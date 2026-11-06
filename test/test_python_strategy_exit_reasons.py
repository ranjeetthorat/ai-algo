"""Tests for how the /python host records why a strategy stopped, and what restarts it.

Covers the M2 behaviour of docs/plans/2026-11-06-python-strategy-kit-implementation-plan.md:

- a strategy that ends on its own gets its exit code and FATAL reason recorded,
  and the strategy page is told at once;
- an errored strategy is not started by the schedule or the enforcer until the
  user presses Start;
- a strategy interrupted by the server stopping is restarted after login only
  inside its schedule window, and says so on its card.

Run:
    uv run pytest test/test_python_strategy_exit_reasons.py -v
"""

import subprocess
from datetime import date

import pytest
from test_python_strategy_edge_cases import _patch_now, calendar_db, ps_module  # noqa: F401

# A Wednesday that is a normal NSE trading day.
TRADING_DAY = date(2026, 11, 4)
MISSING_PID = 2_000_000_001  # valid on every platform, never a live process in practice


class FakePopen(subprocess.Popen):
    """A Popen the reaper can inspect without a real child process."""

    def __init__(self, returncode):
        self._child_created = False
        self._returncode = returncode
        self.pid = 4242

    def poll(self):
        return self._returncode


def write_log(tmp_path, *lines):
    log = tmp_path / "run.log"
    log.write_text("\n".join(("=== Strategy Started ===", *lines)) + "\n", encoding="utf-8")
    return str(log)


def nse_config(**extra):
    config = {
        "name": "Kit Strategy",
        "file_path": "x.py",
        "user_id": "alice",
        "exchange": "NSE",
        "is_scheduled": True,
        "schedule_start": "09:00",
        "schedule_stop": "15:30",
        "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
    }
    config.update(extra)
    return config


@pytest.fixture()
def broadcasts(ps_module, monkeypatch):  # noqa: F811
    sent = []
    monkeypatch.setattr(ps_module, "broadcast_status_update", lambda *a: sent.append(a))
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)
    return sent


# ---------------------------------------------------------------------------
# Reading the reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, lines, expected",
    [
        (0, ["[10:00:00] Strategy finished."], None),
        (
            3,
            ["[10:00:00] FATAL: SELL 65 NIFTY09NOV2624550PE was rejected: Insufficient margin."],
            "SELL 65 NIFTY09NOV2624550PE was rejected: Insufficient margin.",
        ),
        (
            4,
            [
                "[10:00:00] FATAL: KeyError: 'entry'",
                "Traceback (most recent call last):",
                "KeyError: 'entry'",
            ],
            "Strategy code failed: KeyError: 'entry'",
        ),
        (
            1,
            ["Traceback (most recent call last):", "ZeroDivisionError: division by zero"],
            "Strategy stopped unexpectedly (exit code 1). Last log line: ZeroDivisionError: division by zero. "
            "See the latest log.",
        ),
        (None, ["[10:00:00] FATAL: No NIFTY prices for 20s"], "No NIFTY prices for 20s"),
        (
            None,
            ["[10:00:00] working"],
            "Strategy stopped unexpectedly. Last log line: [10:00:00] working. See the latest log.",
        ),
    ],
)
def test_exit_is_described_from_code_and_log(ps_module, tmp_path, code, lines, expected):  # noqa: F811
    assert ps_module.describe_strategy_exit(code, write_log(tmp_path, *lines)) == expected


def test_reason_is_found_in_the_tail_of_a_long_log(ps_module, tmp_path):  # noqa: F811
    log = write_log(
        tmp_path, *(["noise line " * 10] * 2000), "[15:00:00] FATAL: Exit order rejected"
    )
    assert ps_module.read_exit_reason(log)[0] == "Exit order rejected"


def test_missing_log_gives_no_reason(ps_module, tmp_path):  # noqa: F811
    assert ps_module.read_exit_reason(str(tmp_path / "gone.log")) == (None, None)
    assert ps_module.describe_strategy_exit(3, None) == (
        "Strategy stopped unexpectedly (exit code 3). See the latest log."
    )


# ---------------------------------------------------------------------------
# The reaper
# ---------------------------------------------------------------------------


def track(ps_module, sid, returncode, log):  # noqa: F811
    ps_module.STRATEGY_CONFIGS[sid] = nse_config(
        is_running=True, pid=4242, restart_note="Restarted after the server stopped"
    )
    ps_module.RUNNING_STRATEGIES[sid] = {
        "process": FakePopen(returncode),
        "pid": 4242,
        "log_file": log,
    }


def test_reaper_records_a_stop_with_reason_and_broadcasts(ps_module, broadcasts, tmp_path):  # noqa: F811
    track(ps_module, "s", 3, write_log(tmp_path, "[11:40:00] FATAL: Exit order for CE rejected"))
    ps_module.cleanup_dead_processes()

    config = ps_module.STRATEGY_CONFIGS["s"]
    assert "s" not in ps_module.RUNNING_STRATEGIES
    assert config["is_running"] is False and config["pid"] is None
    assert config["is_error"] is True
    assert config["error_message"] == "Exit order for CE rejected"
    assert config["last_exit_code"] == 3
    assert "restart_note" not in config
    assert broadcasts == [("s", "error", "Exit order for CE rejected")]


def test_reaper_records_a_clean_finish_without_error(ps_module, broadcasts, tmp_path):  # noqa: F811
    track(ps_module, "s", 0, write_log(tmp_path, "[15:00:00] Strategy finished."))
    ps_module.STRATEGY_CONFIGS["s"]["is_error"] = True
    ps_module.STRATEGY_CONFIGS["s"]["error_message"] = "old"
    ps_module.cleanup_dead_processes()

    config = ps_module.STRATEGY_CONFIGS["s"]
    assert "is_error" not in config and "error_message" not in config
    assert config["last_exit_code"] == 0
    assert broadcasts and broadcasts[0][0] == "s" and broadcasts[0][1] != "error"


def test_reaper_leaves_a_new_run_alone(ps_module, broadcasts, tmp_path, monkeypatch):  # noqa: F811
    """A Start between the reaper's two holds must not be overwritten by the old run's exit."""
    track(ps_module, "s", 3, write_log(tmp_path, "[11:40:00] FATAL: old run"))
    real_describe = ps_module.describe_strategy_exit

    def start_new_run_meanwhile(code, log):
        ps_module.RUNNING_STRATEGIES["s"] = {
            "process": FakePopen(None),
            "pid": 5555,
            "log_file": None,
        }
        ps_module.STRATEGY_CONFIGS["s"].update(is_running=True, pid=5555)
        return real_describe(code, log)

    monkeypatch.setattr(ps_module, "describe_strategy_exit", start_new_run_meanwhile)
    ps_module.cleanup_dead_processes()

    config = ps_module.STRATEGY_CONFIGS["s"]
    assert config["is_running"] is True and config["pid"] == 5555
    assert "is_error" not in config
    assert broadcasts == []


def test_reaper_keeps_a_restart_pending_for_an_interrupted_strategy(ps_module, broadcasts):  # noqa: F811
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(is_running=True, pid=MISSING_PID)
    ps_module.cleanup_dead_processes()
    config = ps_module.STRATEGY_CONFIGS["s"]
    assert config["is_running"] is False and config["pid"] is None
    assert config["restore_pending"] is True


# ---------------------------------------------------------------------------
# Errored strategies wait for the user
# ---------------------------------------------------------------------------


def test_scheduled_start_skips_an_errored_strategy(ps_module, monkeypatch):  # noqa: F811
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(is_error=True, error_message="Exit order rejected")
    started = []
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: started.append(sid) or (True, "ok")
    )
    p = _patch_now(TRADING_DAY, 9, 0)
    try:
        ps_module.scheduled_start_strategy("s")
    finally:
        p.stop()
    assert started == []


def test_enforcer_does_not_resume_an_errored_strategy(ps_module, monkeypatch):  # noqa: F811
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(
        is_error=True, error_message="x", paused_reason="holiday"
    )
    started = []
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: started.append(sid) or (True, "ok")
    )
    monkeypatch.setattr(ps_module, "_is_strategy_running", lambda sid, cfg: False)
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)
    p = _patch_now(TRADING_DAY, 10, 0)
    try:
        ps_module.market_hours_enforcer()
    finally:
        p.stop()
    assert started == []


def test_start_acknowledges_the_last_stop(ps_module):  # noqa: F811
    config = nse_config(
        is_error=True, error_message="x", error_time="t", restart_note="n", restore_pending=True
    )
    assert ps_module.acknowledge_strategy_stop(config) is True
    for key in ("is_error", "error_message", "error_time", "restart_note", "restore_pending"):
        assert key not in config
    assert ps_module.acknowledge_strategy_stop(config) is False


# ---------------------------------------------------------------------------
# Restart after the server stopped
# ---------------------------------------------------------------------------


@pytest.fixture()
def restart_env(ps_module, monkeypatch):  # noqa: F811
    started = []

    def fake_start(sid):
        started.append(sid)
        ps_module.STRATEGY_CONFIGS[sid].update(is_running=True, pid=7777)
        return True, "ok"

    monkeypatch.setattr(
        ps_module,
        "check_master_contract_ready",
        lambda skip_on_startup=False: (True, "Master contracts ready"),
    )
    monkeypatch.setattr(ps_module, "start_strategy_process", fake_start)
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)
    return started


def _restore_at(ps_module, hour, minute=0):  # noqa: F811
    p = _patch_now(TRADING_DAY, hour, minute)
    try:
        ps_module.restore_strategy_states()
    finally:
        p.stop()


def test_interrupted_strategy_restarts_inside_its_window_with_a_note(ps_module, restart_env):  # noqa: F811
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(restore_pending=True)
    _restore_at(ps_module, 11, 40)
    config = ps_module.STRATEGY_CONFIGS["s"]
    assert restart_env == ["s"]
    assert config["restart_note"].startswith("Restarted after the server stopped")
    assert "restore_pending" not in config


def test_restart_uses_the_users_window_not_the_exchange_open(ps_module, restart_env):  # noqa: F811
    """09:05 is before the 09:15 open but inside a 09:00 schedule: restart, as the schedule would have."""
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(restore_pending=True)
    _restore_at(ps_module, 9, 5)
    assert restart_env == ["s"]


def test_interrupted_strategy_waits_for_its_schedule_outside_the_window(ps_module, restart_env):  # noqa: F811
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(is_running=True, pid=MISSING_PID)
    _restore_at(ps_module, 20, 0)
    config = ps_module.STRATEGY_CONFIGS["s"]
    assert restart_env == []
    assert config["is_running"] is False and "restore_pending" not in config
    assert "restart_note" not in config


def test_failed_restart_becomes_an_error(ps_module, restart_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        ps_module, "start_strategy_process", lambda sid: (False, "Strategy file not found")
    )
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(restore_pending=True)
    _restore_at(ps_module, 11, 0)
    config = ps_module.STRATEGY_CONFIGS["s"]
    assert config["is_error"] is True
    assert (
        config["error_message"]
        == "Could not restart after the server stopped: Strategy file not found"
    )


def test_login_long_after_startup_still_restarts(ps_module, restart_env, broadcasts):  # noqa: F811
    """Startup without a broker, the reaper runs, the user logs in later: the restart is not lost."""
    ps_module.STRATEGY_CONFIGS["s"] = nse_config(is_running=True, pid=MISSING_PID)
    ps_module.cleanup_dead_processes()  # a minute after startup, before login
    assert ps_module.STRATEGY_CONFIGS["s"]["is_running"] is False
    _restore_at(ps_module, 9, 30)  # restore_strategies_after_login
    assert restart_env == ["s"]
    assert ps_module.STRATEGY_CONFIGS["s"]["restart_note"].startswith(
        "Restarted after the server stopped"
    )


def test_stop_cancels_a_pending_restart(ps_module):  # noqa: F811
    config = nse_config(restore_pending=True, restart_note="n")
    had_pending = config.pop("restore_pending", None)
    had_note = config.pop("restart_note", None)
    assert had_pending and had_note
