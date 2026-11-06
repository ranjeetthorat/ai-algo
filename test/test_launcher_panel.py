"""The desktop control panel (launcher.panel) and the network settings it writes.

The window itself is built against a throwaway install and torn down; it is
skipped where Tk cannot open a display. Driving it by hand is in the M3.4 notes
of the Phase 3 plan.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# The panel is a tkinter window; a Python built without Tk cannot import it.
pytest.importorskip("tkinter")

from launcher import envfile, panel  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


# --- which buttons work when -----------------------------------------------------


@pytest.mark.parametrize(
    ("state", "usable"),
    [
        # An update stops a running server itself, so it is offered in every
        # state but stopping and an install with no broker yet.
        ("stopped", {"start", "settings", "maintenance", "update"}),
        ("crashed", {"start", "settings", "maintenance", "update"}),
        ("error", {"start", "settings", "maintenance", "update"}),
        ("starting", {"stop", "restart", "update"}),
        ("running", {"stop", "restart", "open", "update"}),
        ("restarting", {"stop", "restart", "update"}),
        ("stopping", set()),
        # Running with no keeper: Start takes it over; Restart needs a keeper.
        ("unsupervised", {"start", "stop", "update"}),
        # A new install with no .env yet: only setting up a broker is possible.
        ("setup", {"setup"}),
    ],
)
def test_controls_for_each_state(state, usable):
    enabled = panel.controls_for({"state": state})
    assert {name for name, on in enabled.items() if on} == usable


def test_settings_and_reset_are_never_usable_while_running():
    for state in panel.RUNNING_STATES:
        enabled = panel.controls_for({"state": state})
        assert not enabled["settings"] and not enabled["maintenance"], state


def test_lan_address_is_an_address_or_none():
    address = panel.lan_address()
    assert address is None or (address.count(".") == 3 and not address.startswith("127."))


def _sample() -> str:
    text = (REPO / ".sample.env").read_text(encoding="utf-8")
    return envfile.set_value(text, "REDIRECT_URL", "http://127.0.0.1:5000/zerodha/callback")


# --- the window ------------------------------------------------------------------


@pytest.fixture
def install(tmp_path):
    home = tmp_path / "FastAlgo"
    app = home / "app"
    (app / "utils").mkdir(parents=True)
    (app / "utils" / "brand.py").write_text('PRODUCT_NAME = "FastAlgo"\n', encoding="utf-8")
    (app / ".sample.env").write_text(_sample(), encoding="utf-8")
    (app / ".env").write_text(_sample(), encoding="utf-8")
    (app / "RELEASE_FILES").write_text(
        "utils/brand.py\n.sample.env\nRELEASE_FILES\n", encoding="utf-8"
    )
    return panel.paths_for(home)


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for Tk")
    root.withdraw()
    yield root
    root.destroy()


def test_panel_builds_and_shows_a_stopped_server(install, tk_root):
    window = panel.Panel(tk_root, install)
    assert tk_root.title() == "FastAlgo Control Panel"
    assert window.state_label.cget("text") == "Stopped"
    assert window.buttons["start"].instate(["!disabled"])
    assert window.buttons["stop"].instate(["disabled"])
    assert window.port_vars["http"].get() == "5000"
    assert "http://127.0.0.1:5000" in window.address_label.cget("text")


def test_refresh_never_stacks_timers(install, tk_root):
    window = panel.Panel(tk_root, install)
    before = len(tk_root.tk.splitlist(tk_root.tk.call("after", "info")))
    for _ in range(5):
        window.refresh()
    after = len(tk_root.tk.splitlist(tk_root.tk.call("after", "info")))
    assert after == before


def test_white_label_name_is_used(install, tk_root):
    (install.app / "custom_brand").mkdir()
    (install.app / "custom_brand" / "brand.json").write_text(
        '{"displayName": "Acme Trade"}', encoding="utf-8"
    )
    window = panel.Panel(tk_root, install)
    assert tk_root.title() == "Acme Trade Control Panel"
    assert window.buttons["open"].cget("text") == "Open Acme Trade"


def test_save_network_writes_env(install, tk_root):
    window = panel.Panel(tk_root, install)
    window.port_vars["http"].set("5071")
    window.lan_var.set(True)
    window.save_network()
    values = envfile.read_values((install.app / ".env").read_text(encoding="utf-8"))
    assert values["FLASK_PORT"] == "5071" and values["FLASK_HOST_IP"] == "0.0.0.0"
    assert "redirect URL" in window.network_note.cget("text")


def test_switch_broker_dialog_lists_brokers_and_shows_market_fields_for_xts(install, tk_root):
    window = panel.Panel(tk_root, install)
    dialog = panel.SwitchBrokerDialog(window)
    values = dialog.win.nametowidget(dialog.win.winfo_children()[0]).winfo_children()
    combos = [w for w in values if w.winfo_class() == "TCombobox"]
    assert "zerodha" in combos[0].cget("values")
    dialog.vars["broker"].set("zerodha")
    assert not any(w.winfo_manager() for w in dialog.market_widgets)
    dialog.vars["broker"].set("fivepaisaxts")
    assert all(w.winfo_manager() == "grid" for w in dialog.market_widgets)
    assert "will be backed up and removed" in dialog.size_label.cget("text")
    dialog.win.destroy()


# --- first run -------------------------------------------------------------------


def test_a_new_install_without_env_asks_for_a_broker(install, tk_root):
    (install.app / ".env").unlink()
    window = panel.Panel(tk_root, install)
    assert window.state_label.cget("text") == "Not set up yet"
    assert window.buttons["setup"].winfo_manager() == "grid"
    assert window.buttons["start"].instate(["disabled"])


def test_first_setup_writes_an_env_the_app_will_start_with(install, tk_root, monkeypatch):
    (install.app / ".env").unlink()
    monkeypatch.setattr(panel.messagebox, "askyesno", lambda *a, **k: False)
    window = panel.Panel(tk_root, install)
    dialog = panel.SwitchBrokerDialog(window, first_setup=True)
    assert dialog.win.title() == "Set up your broker"
    for key, value in (("broker", "zerodha"), ("key", "abc"), ("secret", "def")):
        dialog.vars[key].set(value)
    dialog.run()

    values = envfile.read_values((install.app / ".env").read_text(encoding="utf-8"))
    assert values["REDIRECT_URL"] == "http://127.0.0.1:5000/zerodha/callback"
    assert (values["BROKER_API_KEY"], values["BROKER_API_SECRET"]) == ("abc", "def")
    assert values["FLASK_HOST_IP"] == "0.0.0.0", "other devices are allowed by default"
    assert len(values["APP_KEY"]) == 64
    assert window.state_label.cget("text") == "Stopped"
    assert window.buttons["setup"].winfo_manager() == ""


# --- updates ---------------------------------------------------------------------

NEWER = panel.update.Manifest("1.3.0", "https://example.test/FastAlgo-1.3.0.zip", "a" * 64, 10)


def _drain_until_idle(window, tk_root, seconds=10.0):
    import time

    deadline = time.monotonic() + seconds
    while window.busy and time.monotonic() < deadline:
        tk_root.update()
        time.sleep(0.05)
    window._drain_events()


def test_update_notice_appears_only_when_a_newer_version_is_found(install, tk_root):
    (install.app / "utils" / "version.py").write_text('VERSION = "1.2.0"\n', encoding="utf-8")
    window = panel.Panel(tk_root, install)
    assert window.update_bar.winfo_manager() == ""
    window.events.put(("check", "available", NEWER))
    window._drain_events()
    window.refresh()
    assert window.update_bar.winfo_manager() == "pack"
    assert "Version 1.3.0 is available (you have 1.2.0)" in window.update_label.cget("text")
    assert window.update_button.instate(["!disabled"])


def test_update_now_applies_the_release_and_reopens_the_panel(install, tk_root, monkeypatch):
    calls = {}
    monkeypatch.setattr(panel.messagebox, "askokcancel", lambda *a, **k: True)
    monkeypatch.setattr(panel.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(panel.control, "stop", lambda paths: calls.setdefault("stop", True))

    def install_latest(paths, log):
        log("Downloading version 1.3.0")
        return panel.update.Result("1.2.0", "1.3.0", paths.home / "updates" / "previous")

    monkeypatch.setattr(panel.update, "install_latest", install_latest)
    window = panel.Panel(tk_root, install)
    monkeypatch.setattr(window, "reopen", lambda: calls.setdefault("reopen", True))
    window.available = NEWER
    window.run_update()
    _drain_until_idle(window, tk_root)
    assert calls == {"reopen": True}, "a stopped server is not stopped or started"
    assert "Downloading version 1.3.0" in window.log_text.get("1.0", "end")


def test_a_refused_update_shows_its_own_message(install, tk_root, monkeypatch):
    shown = []
    monkeypatch.setattr(panel.messagebox, "askokcancel", lambda *a, **k: True)
    monkeypatch.setattr(panel.messagebox, "showerror", lambda title, text, **k: shown.append(text))

    def refuse(paths, log):
        raise panel.update.UpdateRefused("The download was damaged, so it was not used.")

    monkeypatch.setattr(panel.update, "install_latest", refuse)
    window = panel.Panel(tk_root, install)
    window.available = NEWER
    window.run_update()
    _drain_until_idle(window, tk_root)
    assert shown == ["The download was damaged, so it was not used."]
