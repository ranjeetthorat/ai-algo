"""Build the Windows desktop release zip.

    uv run python scripts/build_release.py              # from a clean tree
    uv run python scripts/build_release.py --allow-dirty

Writes ``release/<Product>-<version>.zip`` and a ``.sha256`` beside it, plus
``latest.json``, the announcement installed panels read to offer the update
(``launcher.update``). The same ``latest.json`` is copied into ``static/``, and
the download link and note in ``static/site-config.js`` are filled in, so
publishing is: upload the zip, then upload ``static/``. The zip
holds one folder:

    <Product>-<version>/
      Install <Product>.cmd     what the client double-clicks
      install-desktop.ps1       the installer it runs
      app/                      the source tree, with no Git information
        RELEASE_FILES           every file shipped, read by the reset (launcher.state)

The source is every file Git tracks plus new files not ignored, as they are in
the working tree, so the built ``frontend/dist`` goes in as it is: build it
first. Nothing from ``.git`` and nothing gitignored is included, which keeps
``.env``, databases and logs out.

See M3.5 in ``docs/plans/2026-11-05-desktop-panel-and-reset-plan.md``.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher.branding import product_name  # noqa: E402
from launcher.state import RELEASE_LIST  # noqa: E402

INSTALLER_DIR = REPO / "install" / "desktop"
STATIC = REPO / "static"
SITE_CONFIG = STATIC / "site-config.js"

_DOWNLOAD_URL = re.compile(r"(downloadUrl:\s*')([^']*)(')")
_DOWNLOAD_NOTE = re.compile(r"(downloadNote:\s*')([^']*)(')")


def version() -> str:
    match = re.search(
        r'^VERSION\s*=\s*"([^"]+)"',
        (REPO / "utils" / "version.py").read_text(encoding="utf-8"),
        re.M,
    )
    if not match:
        raise SystemExit("utils/version.py has no VERSION")
    return match.group(1)


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, check=True, timeout=120
    ).stdout


def source_files() -> list[str]:
    listed = (
        git("ls-files", "-z", "--cached", "--others", "--exclude-standard")
        .decode("utf-8")
        .split("\0")
    )
    # A tracked file deleted in the working tree is not shipped.
    return sorted(p for p in set(listed) if p and (REPO / p).is_file())


def checks(allow_dirty: bool) -> None:
    if not allow_dirty and git("status", "--porcelain").strip():
        raise SystemExit(
            "The working tree has uncommitted changes. Commit them, or pass --allow-dirty for a test build."
        )
    if not (REPO / "frontend" / "dist" / "index.html").is_file():
        raise SystemExit(
            "frontend/dist is missing. Build the frontend first (cd frontend && npm run build)."
        )
    node = shutil.which("node")
    if node:
        result = subprocess.run(
            [node, "scripts/brand-check.mjs"], cwd=REPO, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            print(result.stdout[-2000:])
            raise SystemExit(
                "brand-check found upstream branding that would reach a user. Fix it before releasing."
            )
    else:
        print("Warning: Node.js not found, so scripts/brand-check.mjs was not run.")


def crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def build(out_dir: Path, allow_dirty: bool) -> Path:
    checks(allow_dirty)
    name, ver = product_name(REPO), version()
    top = f"{name}-{ver}"
    # An output folder inside the checkout must not ship its own earlier zips.
    inside = out_dir.is_relative_to(REPO)
    skip = f"{out_dir.relative_to(REPO).as_posix()}/" if inside else None
    files = [f for f in source_files() if not (skip and f.startswith(skip))]
    shipped = files + [RELEASE_LIST]

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{top}.zip"
    partial = target.with_suffix(".zip.partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(f"{top}/Install {name}.cmd", crlf((INSTALLER_DIR / "Install.cmd").read_bytes()))
        zf.writestr(
            f"{top}/install-desktop.ps1", crlf((INSTALLER_DIR / "install-desktop.ps1").read_bytes())
        )
        for rel in files:
            zf.write(REPO / rel, f"{top}/app/{rel}")
        zf.writestr(f"{top}/app/{RELEASE_LIST}", "\n".join(shipped) + "\n")
    partial.replace(target)

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(
        f"{digest}  {target.name}\n", encoding="utf-8"
    )
    print(f"{target}  ({target.stat().st_size / 1_048_576:.1f} MB, {len(files)} files)")
    print(f"sha256 {digest}")
    return target


def release_summary(ver: str) -> str:
    """The one-line summary of ``docs/releases/version-<ver>-released.md``, or "" without one.

    That is the first bold line after the date, the line the release notes open
    with for a reader.
    """
    notes = REPO / "docs" / "releases" / f"version-{ver}-released.md"
    if not notes.is_file():
        return ""
    for line in notes.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("**") and line.endswith("**") and not line.startswith("**Date"):
            return line.strip("*").strip()
    return ""


def url_base(explicit: str | None) -> str:
    """Where the zip will be downloaded from: ``--url-base``, else the folder of the current site link."""
    if explicit:
        return explicit.rstrip("/")
    match = _DOWNLOAD_URL.search(SITE_CONFIG.read_text(encoding="utf-8"))
    if not match or "/" not in match.group(2):
        raise SystemExit(
            "No download address is known. Pass --url-base with the folder the zip is uploaded to."
        )
    return match.group(2).rsplit("/", 1)[0]


def announce(target: Path, base: str, ver: str) -> dict:
    """Write ``latest.json`` beside the zip and into ``static/``, and point the site at the zip."""
    data = target.read_bytes()
    url = f"{base}/{target.name}"
    if not url.startswith("https://"):
        raise SystemExit(f"The download address must be https: {url}")
    manifest = {
        "version": ver,
        "url": url,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "released": time.strftime("%Y-%m-%d"),
        "notes": release_summary(ver),
    }
    text = json.dumps(manifest, indent=2) + "\n"
    (target.parent / "latest.json").write_text(text, encoding="utf-8")
    (STATIC / "latest.json").write_text(text, encoding="utf-8", newline="\n")

    name = product_name(REPO)
    note = (
        f"Version {ver} for Windows 10 and 11 (64-bit), {len(data) / 1_048_576:.1f} MB. "
        f"Extract the zip and double-click Install {name}.cmd."
    )
    config = SITE_CONFIG.read_text(encoding="utf-8")
    config = _DOWNLOAD_URL.sub(lambda m: m.group(1) + url + m.group(3), config, count=1)
    config = _DOWNLOAD_NOTE.sub(lambda m: m.group(1) + note + m.group(3), config, count=1)
    SITE_CONFIG.write_text(config, encoding="utf-8", newline="\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows desktop release zip.")
    parser.add_argument(
        "--out", type=Path, default=REPO / "release", help="output folder (default: release/)"
    )
    parser.add_argument(
        "--allow-dirty", action="store_true", help="build with uncommitted changes (test builds)"
    )
    parser.add_argument(
        "--url-base",
        help="the https folder the zip is uploaded to (default: the folder of the current site link)",
    )
    parser.add_argument(
        "--no-announce",
        action="store_true",
        help="build the zip only; do not write latest.json or touch static/",
    )
    args = parser.parse_args(argv)
    out = args.out.resolve()
    target = build(out, args.allow_dirty)
    if not args.no_announce:
        manifest = announce(target, url_base(args.url_base), version())
        print(f"latest.json  {manifest['url']}")
        print()
        print("To publish, in this order:")
        print(f"  1. Upload {target.name} so it is reachable at {manifest['url']}")
        print("  2. Commit static/latest.json and static/site-config.js")
        print("  3. Upload the static/ folder to the public site")
        print("Installed panels offer the update once step 3 is live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
