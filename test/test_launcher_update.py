"""The in-place update (launcher.update).

Every update here runs on a throwaway install under ``tmp_path`` with its own
``RELEASE_FILES``, and a release zip built the way ``scripts/build_release.py``
builds one. ``uv sync`` and the migrations are replaced by fakes that record
their calls, so nothing is downloaded and the real checkout is never touched.
"""

import hashlib
import io
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from launcher import eject, update  # noqa: E402
from launcher.keeper import paths_for  # noqa: E402

OLD = {
    "app.py": "print('old app')",
    "utils/version.py": 'VERSION = "1.2.0"\n',
    "utils/brand.py": 'PRODUCT_NAME = "FastAlgo"\n',
    "launcher/panel.py": "old panel",
    "frontend/dist/index.html": "<old ui>",
    "strategies/examples/sanity_test.py": "old example",
    "removed_in_new.py": "goes away",
    "db/readme.txt": "shipped readme",
}

#: The client's own files: an update must leave every one exactly as it was.
CLIENT = {
    ".env": "BROKER_API_KEY = 'client-key'\n",
    "db/openalgo.db": "client database",
    "db/sandbox.db": "client sandbox",
    "log/errors.jsonl": "client log",
    "strategies/scripts/my_strategy.py": "client strategy",
    "strategies/state/my_strategy.json": "{}",
    ".venv/Lib/site-packages/marker.txt": "installed package",
}

NEW = {
    "app.py": "print('new app')",
    "utils/version.py": 'VERSION = "1.3.0"\n',
    "utils/brand.py": 'PRODUCT_NAME = "FastAlgo"\n',
    "launcher/panel.py": "new panel",
    "frontend/dist/index.html": "<new ui>",
    "strategies/examples/sanity_test.py": "new example",
    "added_in_new.py": "brand new",
    "db/readme.txt": "shipped readme",
}


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _release_zip(dest: Path, files: dict[str, str], top: str = "FastAlgo-1.3.0") -> Path:
    zip_path = dest / f"{top}.zip"
    shipped = [*files, "RELEASE_FILES"]
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{top}/Install FastAlgo.cmd", "@echo off")
        zf.writestr(f"{top}/install-desktop.ps1", "# new installer")
        for rel, text in files.items():
            zf.writestr(f"{top}/app/{rel}", text)
        zf.writestr(f"{top}/app/RELEASE_FILES", "\n".join(shipped) + "\n")
    return zip_path


class Calls:
    def __init__(self, sync_codes=(0,), migrate=None):
        self.sync_codes = list(sync_codes)
        self.migrate_fn = migrate
        self.syncs = 0
        self.migrations = 0
        self.lines: list[str] = []

    def sync(self, paths, log):
        self.syncs += 1
        return self.sync_codes.pop(0) if self.sync_codes else 0

    def migrate(self, paths, log):
        self.migrations += 1
        return self.migrate_fn(paths) if self.migrate_fn else 0

    def log(self, line):
        self.lines.append(line)


@pytest.fixture
def install(tmp_path, monkeypatch):
    home = tmp_path / "FastAlgo"
    app = home / "app"
    for rel, text in {**OLD, **CLIENT}.items():
        _write(app, rel, text)
    _write(app, "RELEASE_FILES", "\n".join([*OLD, "RELEASE_FILES"]) + "\n")
    _write(home, "install.ok", "1.2.0 2026-11-05T10:00:00")
    _write(home, "install-desktop.ps1", "# old installer")
    # The developer's own server may hold port 5000; the tests decide running or not.
    monkeypatch.setattr(eject, "busy_ports", lambda root: [])
    return paths_for(home)


def _snapshot(app: Path) -> dict[str, str]:
    return {
        p.relative_to(app).as_posix(): p.read_text(encoding="utf-8")
        for p in app.rglob("*")
        if p.is_file()
    }


def _apply(install, zip_path, calls):
    return update.apply(zip_path, install, log=calls.log, sync=calls.sync, migrate=calls.migrate)


# --- a good update ----------------------------------------------------------------


def test_update_replaces_the_program_and_keeps_client_data(install, tmp_path):
    calls = Calls()
    result = _apply(install, _release_zip(tmp_path, NEW), calls)
    app = install.app

    for rel, text in NEW.items():
        assert (app / rel).read_text(encoding="utf-8") == text, rel
    assert not (app / "removed_in_new.py").exists()
    for rel, text in CLIENT.items():
        assert (app / rel).read_text(encoding="utf-8") == text, rel
    assert update.installed_version(app) == "1.3.0"
    assert (result.old_version, result.new_version) == ("1.2.0", "1.3.0")
    assert calls.syncs == 1 and calls.migrations == 1


def test_previous_program_is_kept_beside_the_app(install, tmp_path):
    result = _apply(install, _release_zip(tmp_path, NEW), Calls())
    assert (result.previous / "app" / "app.py").read_text(encoding="utf-8") == OLD["app.py"]
    assert (result.previous / "app" / "removed_in_new.py").exists()
    assert (result.previous / update.DATABASES / "openalgo.db").exists()
    # The unpacked copy is never left behind.
    assert not list((install.home / "updates").glob(f"{update.WORK_PREFIX}*"))


def test_installer_and_install_marker_follow_the_new_version(install, tmp_path):
    _apply(install, _release_zip(tmp_path, NEW), Calls())
    home = install.home
    assert (home / "install-desktop.ps1").read_text(encoding="utf-8") == "# new installer"
    assert (home / "install.ok").read_text(encoding="ascii").startswith("1.3.0 ")


def test_client_file_where_the_release_now_ships_one_is_kept(install, tmp_path):
    _write(install.app, "added_in_new.py", "the client's own file")
    result = _apply(install, _release_zip(tmp_path, NEW), Calls())
    assert (install.app / "added_in_new.py").read_text(encoding="utf-8") == "brand new"
    kept = result.previous / "app" / "added_in_new.py"
    assert kept.read_text(encoding="utf-8") == "the client's own file"


def test_release_list_can_never_move_env_or_the_venv(install, tmp_path):
    files = {**NEW, ".env": "SHIPPED = 'x'\n", ".venv/Lib/site-packages/marker.txt": "shipped"}
    _apply(install, _release_zip(tmp_path, files), Calls())
    assert (install.app / ".env").read_text(encoding="utf-8") == CLIENT[".env"]
    marker = install.app / ".venv/Lib/site-packages/marker.txt"
    assert marker.read_text(encoding="utf-8") == "installed package"


def test_only_the_newest_previous_folder_is_kept(install, tmp_path):
    updates = install.home / "updates"
    older = updates / f"{update.PREVIOUS_PREFIX}1.10.0-20260101-000000"
    older.mkdir(parents=True)
    past = time.time() - 3600
    os.utime(older, (past, past))
    result = _apply(install, _release_zip(tmp_path, NEW), Calls())
    assert not older.exists()
    assert result.previous.exists()


# --- refusals change nothing ------------------------------------------------------


def _refused(install, zip_path, match):
    before = _snapshot(install.app)
    with pytest.raises(update.UpdateRefused, match=match):
        _apply(install, zip_path, Calls())
    assert _snapshot(install.app) == before
    assert not list((install.home / "updates").glob(f"{update.PREVIOUS_PREFIX}*"))


def test_same_or_older_version_is_refused(install, tmp_path):
    same = {**NEW, "utils/version.py": 'VERSION = "1.2.0"\n'}
    _refused(install, _release_zip(tmp_path, same), "Only a newer version")
    older = {**NEW, "utils/version.py": 'VERSION = "1.1.9"\n'}
    (tmp_path / "FastAlgo-1.3.0.zip").unlink()
    _refused(install, _release_zip(tmp_path, older), "Only a newer version")


def test_another_products_release_is_refused(install, tmp_path):
    other = {**NEW, "utils/brand.py": 'PRODUCT_NAME = "SomethingElse"\n'}
    _refused(install, _release_zip(tmp_path, other), "SomethingElse")


def test_running_server_is_refused(install, tmp_path, monkeypatch):
    monkeypatch.setattr(eject, "busy_ports", lambda root: [5000])
    _refused(install, _release_zip(tmp_path, NEW), "still running")


def test_a_zip_that_is_not_a_release_is_refused(install, tmp_path):
    plain = tmp_path / "notes.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("notes.txt", "hello")
    _refused(install, plain, "not a release zip")
    text = tmp_path / "FastAlgo-1.3.0.zip"
    text.write_text("not a zip", encoding="utf-8")
    _refused(install, text, "not a release zip")


def test_a_path_escaping_the_release_folder_is_refused(install, tmp_path):
    zip_path = _release_zip(tmp_path, NEW)
    with zipfile.ZipFile(zip_path, "a") as zf:
        zf.writestr("FastAlgo-1.3.0/app/../../evil.py", "escape")
    _refused(install, zip_path, "not a release zip")
    assert not (install.home / "evil.py").exists()


def test_a_file_in_use_puts_everything_back(install, tmp_path, monkeypatch):
    real_rename = os.rename

    def rename(src, dst):
        if Path(src).name == "panel.py":
            raise PermissionError("in use")
        return real_rename(src, dst)

    monkeypatch.setattr(update.os, "rename", rename)
    _refused(install, _release_zip(tmp_path, NEW), "in use")


# --- failures roll back -----------------------------------------------------------


def test_failed_dependency_install_puts_the_previous_version_back(install, tmp_path):
    before = _snapshot(install.app)
    calls = Calls(sync_codes=(1, 0))
    with pytest.raises(update.UpdateFailed, match="1.2.0 was put back"):
        _apply(install, _release_zip(tmp_path, NEW), calls)
    assert _snapshot(install.app) == before
    # Once for the new version, once to reinstall the previous one.
    assert calls.syncs == 2 and calls.migrations == 0


def test_failed_migration_puts_program_and_databases_back(install, tmp_path):
    before = _snapshot(install.app)

    def migrate(paths):
        (paths.app / "db/openalgo.db").write_text("half converted", encoding="utf-8")
        (paths.app / "db/openalgo.db-journal").write_text("journal", encoding="utf-8")
        return 1

    calls = Calls(migrate=migrate)
    with pytest.raises(update.UpdateFailed, match="your data were put back"):
        _apply(install, _release_zip(tmp_path, NEW), calls)
    assert _snapshot(install.app) == before


def test_unexpected_error_still_rolls_back(install, tmp_path):
    before = _snapshot(install.app)

    def migrate(paths):
        raise RuntimeError("boom")

    with pytest.raises(update.UpdateFailed, match="unexpected problem"):
        _apply(install, _release_zip(tmp_path, NEW), Calls(migrate=migrate))
    assert _snapshot(install.app) == before


# --- the announcement and the download --------------------------------------------


def _manifest(**over):
    data = {
        "version": "1.3.0",
        "url": "https://example.test/FastAlgo-1.3.0.zip",
        "sha256": "a" * 64,
        "size": 10,
        "notes": "New things.",
    }
    data.update(over)
    return data


def test_manifest_is_validated():
    assert update.parse_manifest(_manifest()).version == "1.3.0"
    for bad in (
        {"url": "http://example.test/x.zip"},
        {"sha256": "abc"},
        {"size": 0},
        {"version": "latest"},
    ):
        with pytest.raises(ValueError):
            update.parse_manifest(_manifest(**bad))


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("1.3.0", "1.2.0", True),
        ("1.10.0", "1.9.9", True),
        ("1.2.0", "1.2.0", False),
        ("1.2", "1.2.1", False),
        ("bad", "1.2.0", False),
    ],
)
def test_version_comparison_is_numeric(candidate, current, newer):
    assert update.is_newer(candidate, current) is newer


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def test_download_checks_size_and_checksum(tmp_path, monkeypatch):
    payload = b"release bytes"
    monkeypatch.setattr(update, "_open", lambda url, timeout: _Response(payload))
    good = update.Manifest(
        "1.3.0",
        "https://example.test/FastAlgo-1.3.0.zip",
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )
    seen = []
    path = update.download(good, tmp_path, progress=lambda got, total: seen.append(got))
    assert path.name == "FastAlgo-1.3.0.zip" and path.read_bytes() == payload
    assert seen[-1] == len(payload)

    damaged = update.Manifest("1.3.0", good.url, "0" * 64, len(payload))
    path.unlink()
    with pytest.raises(update.UpdateRefused, match="damaged"):
        update.download(damaged, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_check_reports_only_a_newer_version(install, monkeypatch):
    import json

    for version, expect in (("1.3.0", "1.3.0"), ("1.2.0", None)):
        body = json.dumps(_manifest(version=version)).encode()
        monkeypatch.setattr(update, "_open", lambda url, timeout, b=body: _Response(b))
        found = update.check(install)
        assert (found.version if found else None) == expect


def test_check_without_internet_says_so(install, monkeypatch):
    def offline(url, timeout):
        raise OSError("no route")

    monkeypatch.setattr(update, "_open", offline)
    with pytest.raises(update.UpdateRefused, match="internet connection"):
        update.check(install)


def test_update_url_comes_from_panel_settings(install):
    assert update.manifest_url(install) == update.MANIFEST_URL
    install.settings.write_text('{"update_url": "https://mirror.test/latest.json"}', "utf-8")
    assert update.manifest_url(install) == "https://mirror.test/latest.json"
    install.settings.write_text('{"update_url": "http://insecure.test/latest.json"}', "utf-8")
    assert update.manifest_url(install) == update.MANIFEST_URL


def test_install_latest_downloads_applies_and_cleans_up(install, tmp_path, monkeypatch):
    import json

    zip_bytes = _release_zip(tmp_path, NEW).read_bytes()
    manifest = _manifest(sha256=hashlib.sha256(zip_bytes).hexdigest(), size=len(zip_bytes))

    def opener(url, timeout):
        return _Response(json.dumps(manifest).encode() if url.endswith(".json") else zip_bytes)

    monkeypatch.setattr(update, "_open", opener)
    calls = Calls()
    result = update.install_latest(install, log=calls.log, sync=calls.sync, migrate=calls.migrate)
    assert result.new_version == "1.3.0"
    assert list((install.home / "updates" / "downloads").iterdir()) == []


# --- the release build's announcement ---------------------------------------------


@pytest.fixture
def build_release(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import build_release as module

    static = tmp_path / "static"
    static.mkdir()
    config = static / "site-config.js"
    config.write_text(
        "window.FASTALGO_SITE = {\n"
        "  downloadUrl: 'https://store.test/files/FastAlgo-1.2.0.zip',\n"
        "  downloadNote: 'Version 1.2.0 old note.',\n"
        "  telegramUrl: 'https://t.me/x',\n"
        "}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "STATIC", static)
    monkeypatch.setattr(module, "SITE_CONFIG", config)
    return module


def test_announcement_is_accepted_by_the_updater(build_release, tmp_path):
    zip_path = _release_zip(tmp_path, NEW)
    base = build_release.url_base(None)
    assert base == "https://store.test/files"
    written = build_release.announce(zip_path, base, "1.3.0")

    import json

    for location in (tmp_path / "latest.json", build_release.STATIC / "latest.json"):
        manifest = update.parse_manifest(json.loads(location.read_text(encoding="utf-8")))
        assert manifest.version == "1.3.0"
        assert manifest.url == "https://store.test/files/FastAlgo-1.3.0.zip"
        assert manifest.sha256 == hashlib.sha256(zip_path.read_bytes()).hexdigest()
        assert manifest.size == zip_path.stat().st_size
    assert written["url"].endswith("FastAlgo-1.3.0.zip")

    config = build_release.SITE_CONFIG.read_text(encoding="utf-8")
    assert "downloadUrl: 'https://store.test/files/FastAlgo-1.3.0.zip'" in config
    assert "downloadNote: 'Version 1.3.0 for Windows 10 and 11 (64-bit)," in config
    assert "telegramUrl: 'https://t.me/x'" in config


def test_announcement_refuses_a_plain_http_address(build_release, tmp_path):
    with pytest.raises(SystemExit, match="https"):
        build_release.announce(_release_zip(tmp_path, NEW), "http://store.test", "1.3.0")


def test_release_summary_is_the_bold_opening_line(build_release):
    summary = build_release.release_summary("1.2.0")
    assert summary.startswith("Desktop release:")
    assert build_release.release_summary("0.0.0") == ""


def test_a_missing_manifest_is_not_blamed_on_the_internet(install, monkeypatch):
    import urllib.error

    def not_found(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(update, "_open", not_found)
    with pytest.raises(update.UpdateRefused, match="release information"):
        update.check(install)
    # A 404 must not claim the internet is down.
    try:
        update.check(install)
    except update.UpdateRefused as e:
        assert "internet" not in str(e).lower()
