"""Update an installation in place from a newer release zip.

Used by the panel's "Update now" and "Update from file" buttons, and usable by
hand:

    python -m launcher.update --home C:\\FastAlgo check
    python -m launcher.update --home C:\\FastAlgo install               # download and apply
    python -m launcher.update --home C:\\FastAlgo apply FastAlgo-1.3.0.zip

**What is replaced and what is kept** comes from ``launcher.state``, the same
list the reset uses. The release's own files (named in ``RELEASE_FILES``) are
replaced; everything else is kept: ``.env``, databases, logs, saved strategies,
``.venv``, the private Python and the download cache. So an update downloads
only the zip and the packages whose version changed in ``uv.lock``.

**Where a release is announced.** ``latest.json``, written by
``scripts/build_release.py`` next to the zip, names the newest version, its
download link, size and SHA-256. The panel reads it from ``MANIFEST_URL``
unless ``panel.json`` sets ``update_url``.

The order is what makes it safe:

1. Refuse unless the zip is a release of this product, newer than what is
   installed, and the keeper and server are stopped.
2. Unpack the release into ``updates\\work-*`` beside the app, never over it.
3. Move every current program file aside into ``updates\\previous-<version>``.
   Renames on one drive are instant, and if any fails (a file in use) every
   file already moved is put back: nothing has changed.
4. Move the new program files into place.
5. Copy the SQLite databases aside, then run ``uv sync`` and the database
   migrations.
6. If any of 3-5 fails, put the previous program, databases and dependencies
   back. The client is left on the version that worked.

Standard library only; see ``launcher/__init__.py``.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

if __package__ in (None, ""):  # run as a file rather than with -m
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher import eject, state
from launcher.branding import display_name, product_name
from launcher.keeper import IS_WINDOWS, InstanceLock, Paths, keeper_running, paths_for

#: Where the newest release is announced. ``panel.json`` ``update_url`` overrides it.
MANIFEST_URL = "https://fastalgo.tinycompute.site/latest.json"

#: How many ``previous-*`` folders to keep. Each is one version's program files.
KEEP_PREVIOUS = 1

WORK_PREFIX = "work-"
PREVIOUS_PREFIX = "previous-"
DATABASES = "_databases"

#: Files the release puts beside ``app`` rather than in it.
INSTALLER_FILES = ("install-desktop.ps1",)

_VERSION = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
_PRODUCT = re.compile(r'^PRODUCT_NAME\s*=\s*"([^"]+)"', re.MULTILINE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

Log = Callable[[str], None]


class UpdateRefused(Exception):
    """The update did not start, or was undone before it changed anything. The message is for the client."""


class UpdateFailed(Exception):
    """The update started and was rolled back; the previous version is in place. The message is for the client."""


@dataclass(frozen=True)
class Manifest:
    version: str
    url: str
    sha256: str
    size: int
    notes: str = ""


@dataclass(frozen=True)
class Result:
    old_version: str
    new_version: str
    previous: Path


# --- versions -------------------------------------------------------------------


def parse_version(text: str) -> tuple[int, ...]:
    """``"1.2.10"`` -> ``(1, 2, 10)``. Raises ValueError for anything else."""
    parts = text.strip().split(".")
    if not parts or not all(p.isdigit() for p in parts):
        raise ValueError(f"not a version: {text!r}")
    return tuple(int(p) for p in parts)


def installed_version(app: Path) -> str:
    try:
        match = _VERSION.search((app / "utils" / "version.py").read_text(encoding="utf-8"))
    except OSError:
        match = None
    return match.group(1) if match else "0"


def is_newer(candidate: str, current: str) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


# --- the announcement -----------------------------------------------------------


def _open(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": "FastAlgo-updater"})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https only, checked below


def parse_manifest(data: dict) -> Manifest:
    """Validate a ``latest.json``. Raises ValueError naming the problem."""
    if not isinstance(data, dict):
        raise ValueError("latest.json is not an object")
    version = str(data.get("version", ""))
    parse_version(version)
    url = str(data.get("url", ""))
    if not url.startswith("https://"):
        raise ValueError("the download link is not https")
    sha = str(data.get("sha256", "")).lower()
    if not _SHA256.match(sha):
        raise ValueError("the checksum is not a SHA-256")
    size = data.get("size")
    if not isinstance(size, int) or size <= 0:
        raise ValueError("the size is missing")
    notes = data.get("notes", "")
    return Manifest(version, url, sha, size, notes if isinstance(notes, str) else "")


def manifest_url(paths: Paths) -> str:
    try:
        settings = json.loads(paths.settings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    url = settings.get("update_url") if isinstance(settings, dict) else None
    return url if isinstance(url, str) and url.startswith("https://") else MANIFEST_URL


def fetch_manifest(url: str, timeout: float = 15.0) -> Manifest:
    """Read ``latest.json``. Raises UpdateRefused with a message for the client."""
    if not url.startswith("https://"):
        raise UpdateRefused("The update address is not secure (https), so it was not used.")
    try:
        with _open(url, timeout) as response:
            raw = response.read(64 * 1024)
        return parse_manifest(json.loads(raw.decode("utf-8")))
    except (OSError, ValueError) as e:
        raise UpdateRefused(
            "Could not check for updates. Check the internet connection and try again."
        ) from e


def check(paths: Paths, timeout: float = 15.0) -> Manifest | None:
    """The announced release when it is newer than this installation, else None."""
    found = fetch_manifest(manifest_url(paths), timeout)
    return found if is_newer(found.version, installed_version(paths.app)) else None


def download(
    manifest: Manifest, dest_dir: Path, progress: Callable[[int, int], None] | None = None
) -> Path:
    """Download the release zip and check its size and SHA-256. Returns the zip's path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = PurePosixPath(urllib.parse.urlsplit(manifest.url).path).name
    if not name.lower().endswith(".zip"):
        name = f"release-{manifest.version}.zip"
    target = dest_dir / name
    partial = target.with_suffix(".zip.partial")
    digest = hashlib.sha256()
    received = 0
    try:
        with _open(manifest.url, 60.0) as response, open(partial, "wb") as out:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if received > manifest.size:
                    break
                if progress:
                    progress(received, manifest.size)
    except OSError as e:
        partial.unlink(missing_ok=True)
        raise UpdateRefused(
            "The download did not finish. Check the internet connection and try again. "
            "Nothing was changed."
        ) from e
    if received != manifest.size or digest.hexdigest() != manifest.sha256:
        partial.unlink(missing_ok=True)
        raise UpdateRefused(
            "The download was damaged, so it was not used. Try again. Nothing was changed."
        )
    os.replace(partial, target)
    return target


# --- the zip --------------------------------------------------------------------


@dataclass(frozen=True)
class Release:
    top: str
    version: str
    product: str


def inspect(zip_path: Path) -> Release:
    """Check that ``zip_path`` is a release zip with safe paths. Raises UpdateRefused."""
    not_release = UpdateRefused(
        "That file is not a release zip. Use the zip you were sent, without extracting or renaming its contents."
    )
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            tops = {n.split("/", 1)[0] for n in names}
            if len(tops) != 1:
                raise not_release
            top = tops.pop()
            for n in names:
                pure = PurePosixPath(n)
                if n.startswith("/") or "\\" in n or ".." in pure.parts or ":" in n:
                    raise not_release
            app = f"{top}/app/"
            needed = {f"{app}app.py", f"{app}{state.RELEASE_LIST}", f"{app}utils/version.py"}
            if not needed <= set(names):
                raise not_release
            version_match = _VERSION.search(zf.read(f"{app}utils/version.py").decode("utf-8"))
            brand = f"{app}utils/brand.py"
            product_match = (
                _PRODUCT.search(zf.read(brand).decode("utf-8")) if brand in names else None
            )
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, KeyError) as e:
        raise not_release from e
    if not version_match:
        raise not_release
    return Release(top, version_match.group(1), product_match.group(1) if product_match else "")


def _extract(zip_path: Path, release: Release, work: Path) -> Path:
    """Unpack the release's ``app`` and installer files into ``work``. Returns the new app folder."""
    prefix = f"{release.top}/"
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            rel = info.filename[len(prefix) :]
            if info.is_dir() or not (rel.startswith("app/") or rel in INSTALLER_FILES):
                continue
            target = work / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
    return work / "app"


# --- applying -------------------------------------------------------------------


def _release_list(app: Path) -> set[str]:
    lines = (app / state.RELEASE_LIST).read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip()}


def _is_ours(rel: str) -> bool:
    """Paths an update must never move, whatever a release list says."""
    first = rel.split("/", 1)[0]
    return first in (".venv", ".git") or rel in state.STATE_FILES


class _Swap:
    """Move the old program aside and the new one in, and undo either."""

    def __init__(self, app: Path, previous: Path):
        self.app = app
        self.previous = previous
        self.aside: list[str] = []
        self.placed: list[str] = []

    def move_aside(self, rels: list[str]) -> None:
        for rel in rels:
            dest = self.previous / "app" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(self.app / rel, dest)
            self.aside.append(rel)

    def place(self, new_app: Path, rels: list[str]) -> None:
        for rel in rels:
            dest = self.app / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(new_app / rel, dest)
            self.placed.append(rel)

    def undo(self) -> list[str]:
        """Put the old program back. Returns paths that could not be restored."""
        stuck = []
        for rel in reversed(self.placed):
            try:
                (self.app / rel).unlink()
            except FileNotFoundError:
                pass
            except OSError:
                stuck.append(rel)
        for rel in reversed(self.aside):
            try:
                os.replace(self.previous / "app" / rel, self.app / rel)
            except OSError:
                stuck.append(rel)
        self.placed.clear()
        self.aside.clear()
        return stuck


def _sqlite_files(app: Path) -> list[Path]:
    folder = app / "db"
    if not folder.is_dir():
        return []
    suffixes = (".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite", ".sqlite3")
    return [p for p in folder.iterdir() if p.is_file() and p.name.endswith(suffixes)]


def _copy_databases(app: Path, dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in _sqlite_files(app):
        shutil.copy2(path, dest / path.name)
        copied.append(path)
    return copied


def _restore_databases(app: Path, saved: Path, originals: list[Path]) -> None:
    names = {p.name for p in originals}
    # A journal the migration created would be replayed over the restored file.
    for path in _sqlite_files(app):
        if path.name not in names:
            path.unlink(missing_ok=True)
    for name in names:
        shutil.copy2(saved / name, app / "db" / name)


def _stream(command: list[str], cwd: Path, env: dict, log: Log) -> int:
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
        text=True,
        errors="replace",
    )
    for line in process.stdout:
        log(line.rstrip("\n"))
    return process.wait()


def uv_sync_command(paths: Paths) -> tuple[list[str], dict]:
    """``uv sync --frozen --no-dev`` with the install's own Python and download cache.

    The same command ``install-desktop.ps1`` runs. ``--no-dev`` because uv
    installs the ``dev`` group by default, and a client needs no test tools.
    """
    uv = paths.home / ("uv.exe" if IS_WINDOWS else "uv")
    exe = str(uv) if uv.exists() else (shutil.which("uv") or "uv")
    env = dict(os.environ)
    if (paths.home / "python").is_dir():
        env["UV_PYTHON_INSTALL_DIR"] = str(paths.home / "python")
    env["UV_CACHE_DIR"] = str(paths.home / "cache")
    env.setdefault("UV_HTTP_RETRIES", "5")
    env.setdefault("UV_PYTHON_PREFERENCE", "only-managed")
    return [exe, "sync", "--frozen", "--no-dev"], env


def run_sync(paths: Paths, log: Log) -> int:
    command, env = uv_sync_command(paths)
    return _stream(command, paths.app, env, log)


def run_migrations(paths: Paths, log: Log) -> int:
    script = paths.app / "upgrade" / "migrate_all.py"
    if not script.is_file():
        return 0
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return _stream([str(paths.python), str(script)], paths.app, env, log)


def _prune(updates: Path, prefix: str, keep: int) -> None:
    """Delete all but the newest ``keep`` folders named ``prefix*``, by age (names sort 1.10 before 1.9)."""
    folders = sorted(updates.glob(f"{prefix}*"), key=lambda p: p.stat().st_mtime)
    for old in folders[: max(len(folders) - keep, 0)]:
        shutil.rmtree(old, onexc=eject._force_remove)


def apply(
    zip_path: Path,
    paths: Paths,
    *,
    log: Log = print,
    sync: Callable[[Paths, Log], int] = run_sync,
    migrate: Callable[[Paths, Log], int] = run_migrations,
) -> Result:
    """Update ``paths.app`` from ``zip_path``. Raises UpdateRefused or UpdateFailed with a client message."""
    app = paths.app
    name = display_name(app)
    release = inspect(zip_path)
    current = installed_version(app)
    if release.product and release.product != product_name(app):
        raise UpdateRefused(f"That zip is a release of {release.product}, not {name}.")
    if not is_newer(release.version, current):
        raise UpdateRefused(
            f"{name} {current} is installed, and that zip is version {release.version}. "
            "Only a newer version can be installed. Nothing was changed."
        )
    if keeper_running(paths) or eject.busy_ports(app):
        raise UpdateRefused(f"{name} is still running. Stop it in the panel, then try again.")
    try:
        old_shipped = state.shipped_files(app)[0]
    except state.NoReleaseList as e:
        raise UpdateRefused(
            "This installation has no list of its program files, so the update cannot tell your "
            "data apart from the program. Nothing was changed. Contact support."
        ) from e

    updates = paths.home / "updates"
    lock = InstanceLock(paths.run / "update.lock")
    if not lock.acquire():
        raise UpdateRefused("An update is already running.")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    work = updates / f"{WORK_PREFIX}{stamp}"
    previous = updates / f"{PREVIOUS_PREFIX}{current}-{stamp}"
    try:
        log(f"Unpacking version {release.version}")
        new_app = _extract(zip_path, release, work)
        new_shipped = _release_list(new_app)
        incoming = sorted(r for r in new_shipped if (new_app / r).is_file() and not _is_ours(r))
        # Every current program file, plus any file of the client's sitting
        # where the new release puts one: both are kept in ``previous``.
        outgoing = sorted(
            r
            for r in old_shipped | set(incoming)
            if not _is_ours(r) and (app / r).is_file() and not (app / r).is_symlink()
        )

        swap = _Swap(app, previous)
        try:
            swap.move_aside(outgoing)
        except OSError as e:
            swap.undo()
            shutil.rmtree(previous, ignore_errors=True)
            raise UpdateRefused(
                f"A program file is in use. Close {name}, any strategy windows and any program "
                "that has a file in the install folder open, then try again. Nothing was changed."
            ) from e
        try:
            swap.place(new_app, incoming)
        except OSError as e:
            swap.undo()
            shutil.rmtree(previous, ignore_errors=True)
            raise UpdateRefused(
                "The new files could not be put in place, so the previous version was kept. "
                "Nothing was changed."
            ) from e

        saved = previous / DATABASES
        originals: list[Path] = []

        def roll_back(message: str) -> UpdateFailed:
            log("Putting the previous version back")
            try:
                _restore_databases(app, saved, originals)
            except OSError:
                log(f"The databases could not be restored by themselves; a copy is in {saved}")
            stuck = swap.undo()
            try:
                if sync(paths, log) != 0:
                    log(
                        "The previous dependencies could not be reinstalled; use Repair dependencies."
                    )
            except OSError:
                log("The previous dependencies could not be reinstalled; use Repair dependencies.")
            if stuck:
                log(f"{len(stuck)} files could not be restored; they are in {previous}")
            return UpdateFailed(message)

        try:
            log("Saving a copy of the databases")
            originals = _copy_databases(app, saved)
            log("Installing dependencies")
            if sync(paths, log) != 0:
                raise roll_back(
                    f"The update could not download what it needs, so {name} {current} was put "
                    "back. Check the internet connection and try again."
                )
            log("Updating the databases")
            if migrate(paths, log) != 0:
                raise roll_back(
                    f"The update could not convert your data, so {name} {current} and your data "
                    "were put back. Contact support with the log below."
                )
        except UpdateFailed:
            raise
        except Exception as e:  # noqa: BLE001 - anything unexpected must still roll back
            log(f"Unexpected problem: {e}")
            raise roll_back(
                f"The update stopped on an unexpected problem, so {name} {current} was put back. "
                "Contact support with the log below."
            ) from e

        for file in INSTALLER_FILES:
            if (work / file).is_file():
                shutil.copy2(work / file, paths.home / file)
        if (paths.home / "install.ok").exists():
            (paths.home / "install.ok").write_text(
                f"{release.version} {time.strftime('%Y-%m-%dT%H:%M:%S')}", encoding="ascii"
            )
        log(f"{name} is now version {release.version}")
        return Result(current, release.version, previous)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _prune(updates, PREVIOUS_PREFIX, KEEP_PREVIOUS)
        lock.release()


def install_latest(paths: Paths, log: Log = print, **kwargs) -> Result | None:
    """Check, download and apply the announced release. None when already up to date."""
    found = check(paths)
    if found is None:
        return None
    log(f"Downloading version {found.version}")
    downloads = paths.home / "updates" / "downloads"
    zip_path = download(found, downloads)
    try:
        return apply(zip_path, paths, log=log, **kwargs)
    finally:
        zip_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m launcher.update")
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--app", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="say whether a newer version is announced")
    sub.add_parser("install", help="download and apply the announced version")
    apply_cmd = sub.add_parser("apply", help="apply a release zip you already have")
    apply_cmd.add_argument("zip", type=Path)
    args = parser.parse_args(argv)
    paths = paths_for(args.home, args.app)
    try:
        if args.command == "check":
            found = check(paths)
            current = installed_version(paths.app)
            print(
                f"Version {found.version} is available." if found else f"{current} is the latest."
            )
        elif args.command == "install":
            if install_latest(paths) is None:
                print("Already up to date.")
        else:
            apply(args.zip.resolve(), paths)
    except (UpdateRefused, UpdateFailed) as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
