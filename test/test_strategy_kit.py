"""Tests for strategies/lib/strategy_kit.py, the plumbing shared by Python strategies.

The kit runs inside strategy processes, so these tests drive it with a fake
SDK client and a temporary state folder; no server is involved.

Run:
    uv run pytest test/test_strategy_kit.py -v
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "strategies" / "lib"))

import strategy_kit as kit  # noqa: E402
from strategy_kit import Strategy, StrategyStop, check_params_schema, validate_params  # noqa: E402

PARAMS = {
    "lots": {"type": "int", "default": 1, "min": 1, "max": 5, "label": "Lots"},
    "exit_pct": {"type": "float", "default": 70, "min": 50, "max": 80},
    "expiry": {"type": "str", "default": "09NOV26"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"]},
    "trail": {"type": "bool", "default": False},
}


class FakeClient:
    """The slice of the openalgo client the kit uses, with scripted answers."""

    def __init__(self):
        self.positions = []  # positionbook rows
        self.analyze = False
        self.place_response = None  # None: success with a new order id
        self.outcome = {"order_status": "complete", "average_price": 101.5}
        self.push_updates = True  # deliver the outcome on the order stream
        self.placed = []
        self.read_failures = []  # responses returned before success by positionbook
        self.authenticated = True
        self.timings_data = []
        self.state_seen_at_place = None
        self.state_path = None
        self._order_cb = None
        self._next_id = 1000

    # feed
    def connect(self):
        return True

    def disconnect(self):
        pass

    def subscribe_orders(self, on_order_update=None):
        self._order_cb = on_order_update
        return True

    def subscribe_ltp(self, instruments, on_data_received=None):
        self.ltp_cb = on_data_received
        return True

    # reads
    def positionbook(self):
        if self.read_failures:
            return self.read_failures.pop(0)
        return {"status": "success", "data": self.positions}

    def analyzerstatus(self):
        return {"status": "success", "data": {"analyze_mode": self.analyze}}

    def timings(self, date=None):
        return {"status": "success", "data": self.timings_data}

    def orderstatus(self, order_id, strategy=None):
        return {"status": "success", "data": dict(self.outcome, orderid=order_id)}

    # orders
    def placeorder(self, **kwargs):
        if self.state_path is not None and self.state_path.exists():
            self.state_seen_at_place = json.loads(self.state_path.read_text())
        self.placed.append(kwargs)
        if self.place_response is not None:
            return self.place_response
        self._next_id += 1
        order_id = str(self._next_id)
        if self.push_updates and self._order_cb:
            self._order_cb(
                dict(
                    self.outcome,
                    type="order_update",
                    orderid=order_id,
                    filled_quantity=kwargs["quantity"]
                    if self.outcome["order_status"] == "complete"
                    else 0,
                )
            )
        return {"status": "success", "orderid": order_id}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OPENALGO_STRATEGY_PARAMS", "OPENALGO_API_KEY", "STRATEGY_ID", "STRATEGY_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(kit, "_READ_RETRY_DELAYS", (0, 0))


@pytest.fixture()
def client():
    return FakeClient()


def make(client, tmp_path, schema=PARAMS):
    s = Strategy(schema, client=client, strategy_id="kit_test", name="Kit Test", state_dir=tmp_path)
    s._setup()
    client.state_path = s.state_path
    return s


def run_exit(s, main, capsys):
    with pytest.raises(SystemExit) as exc:
        s.run(main)
    return exc.value.code, capsys.readouterr().out


def write_state(tmp_path, date, fills=None, pending=None, mode=None, extra=None):
    kit_area = {"date": date, "fills": fills or [], "pending": pending or {}}
    if mode:
        kit_area["mode"] = mode
    data = dict(extra or {}, _kit=kit_area)
    (tmp_path / "kit_test.json").write_text(json.dumps(data))


def fill(symbol, action, qty, product="MIS"):
    return {
        "order_id": "1",
        "symbol": symbol,
        "exchange": "NFO",
        "action": action,
        "quantity": qty,
        "average_price": 100.0,
        "product": product,
    }


def pos(symbol, qty, product="MIS"):
    return {"symbol": symbol, "exchange": "NFO", "product": product, "quantity": str(qty)}


TODAY = kit._today()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_params_merge_saved_values_over_defaults():
    params, errors = validate_params(
        PARAMS, {"lots": "3", "exit_pct": 65, "trail": "true", "gone": 1}
    )
    assert errors == []
    assert params == {
        "lots": 3,
        "exit_pct": 65.0,
        "expiry": "09NOV26",
        "product": "MIS",
        "trail": True,
    }


@pytest.mark.parametrize(
    "values, message",
    [
        ({"lots": 9}, "Lots must be at most 5"),
        ({"lots": 0}, "Lots must be at least 1"),
        ({"lots": 1.5}, "Lots must be a whole number"),
        ({"exit_pct": "abc"}, "exit_pct must be a number"),
        ({"product": "CNC"}, "product must be one of: MIS, NRML"),
        ({"trail": "yes"}, "trail must be on or off"),
    ],
)
def test_params_reject_bad_values(values, message):
    _, errors = validate_params(PARAMS, values)
    assert errors == [message]


def test_schema_problems_are_reported():
    problems = check_params_schema(
        {
            "a": {"type": "int"},
            "b": {"type": "weird", "default": 1},
            "c": {"type": "choice", "default": "x"},
            "d": {"type": "int", "default": 1, "colour": "red"},
            "e": {"type": "int", "default": "many"},
        }
    )
    assert any("'a' needs a default" in p for p in problems)
    assert any("'b' needs a type" in p for p in problems)
    assert any("'c' is a choice" in p for p in problems)
    assert any("unknown keys: colour" in p for p in problems)
    assert any("Default for e must be a whole number" in p for p in problems)
    assert check_params_schema(PARAMS) == []
    assert check_params_schema(None) == []


def test_invalid_saved_setting_stops_with_exit_3(client, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENALGO_STRATEGY_PARAMS", json.dumps({"lots": 50}))
    s = Strategy(PARAMS, client=client, strategy_id="kit_test", state_dir=tmp_path)
    code, out = run_exit(s, lambda s: None, capsys)
    assert code == kit.EXIT_CODE_STOPPED
    assert "FATAL: Invalid setting: Lots must be at most 5" in out


def test_saved_settings_reach_the_strategy(client, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OPENALGO_STRATEGY_PARAMS", json.dumps({"lots": 2, "product": "NRML"}))
    seen = {}
    s = Strategy(PARAMS, client=client, strategy_id="kit_test", state_dir=tmp_path)
    code, _ = run_exit(s, lambda s: seen.update(s.params), capsys)
    assert code == kit.EXIT_CODE_OK
    assert seen["lots"] == 2 and seen["product"] == "NRML" and seen["exit_pct"] == 70.0


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_normal_return_exits_0(client, tmp_path, capsys):
    code, out = run_exit(
        Strategy(PARAMS, client=client, state_dir=tmp_path), lambda s: None, capsys
    )
    assert code == kit.EXIT_CODE_OK
    assert "FATAL" not in out


def test_stop_exits_3_with_reason(client, tmp_path, capsys):
    code, out = run_exit(
        Strategy(PARAMS, client=client, state_dir=tmp_path),
        lambda s: s.stop("Exit order rejected"),
        capsys,
    )
    assert code == kit.EXIT_CODE_STOPPED
    assert "FATAL: Exit order rejected" in out


def test_code_error_exits_4_with_reason(client, tmp_path, capsys):
    def main(s):
        return {}["missing"]

    code, out = run_exit(Strategy(PARAMS, client=client, state_dir=tmp_path), main, capsys)
    assert code == kit.EXIT_CODE_ERROR
    assert "FATAL: KeyError: 'missing'" in out


def test_missing_api_key_stops_in_a_real_process(tmp_path):
    """The exit code and FATAL line survive a real interpreter, as the host sees them."""
    env = {k: v for k, v in os.environ.items() if k != "OPENALGO_API_KEY"}
    env["PYTHONPATH"] = str(ROOT / "strategies" / "lib")
    env["OPENALGO_STRATEGY_STATE_DIR"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from strategy_kit import Strategy; Strategy({}).run(lambda s: None)",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == kit.EXIT_CODE_STOPPED
    assert "FATAL: No API key was given to this strategy" in result.stdout


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def test_filled_order_is_recorded(client, tmp_path):
    s = make(client, tmp_path)
    result = s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65)
    assert result.quantity == 65 and result.average_price == 101.5
    saved = json.loads(s.state_path.read_text())["_kit"]
    assert saved["pending"] == {}
    assert saved["fills"][0]["symbol"] == "NIFTY09NOV2624550CE"
    assert saved["mode"] == "live"
    assert s.open_positions() == {"NFO:NIFTY09NOV2624550CE:MIS": -65}


def test_pending_record_is_saved_before_the_order_is_sent(client, tmp_path):
    s = make(client, tmp_path)
    s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65)
    pending = client.state_seen_at_place["_kit"]["pending"]
    assert [p["symbol"] for p in pending.values()] == ["NIFTY09NOV2624550CE"]


def test_rejected_order_stops_with_reason(client, tmp_path):
    client.outcome = {
        "order_status": "rejected",
        "average_price": 0,
        "rejection_reason": "Insufficient margin",
    }
    s = make(client, tmp_path)
    with pytest.raises(
        StrategyStop, match="SELL 65 NIFTY09NOV2624550PE was rejected: Insufficient margin"
    ):
        s.order("NIFTY09NOV2624550PE", "NFO", "SELL", 65)
    saved = json.loads(s.state_path.read_text())["_kit"]
    assert saved["pending"] == {} and saved["fills"] == []


def test_refused_order_clears_pending(client, tmp_path):
    client.place_response = {
        "status": "error",
        "message": "Quantity must be a multiple of 65",
        "code": 400,
        "error_type": "api_error",
    }
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="was refused: Quantity must be a multiple of 65"):
        s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 10)
    assert json.loads(s.state_path.read_text())["_kit"]["pending"] == {}


@pytest.mark.parametrize(
    "response",
    [
        {"status": "error", "message": "Request timed out.", "error_type": "timeout_error"},
        {"status": "error", "message": "Failed to connect", "error_type": "connection_error"},
        {
            "status": "error",
            "message": "HTTP 500: broker timeout",
            "code": 500,
            "error_type": "http_error",
        },
    ],
)
def test_unclear_order_keeps_pending_and_stops(client, tmp_path, response):
    client.place_response = response
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="Could not confirm whether SELL 65"):
        s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65)
    assert len(json.loads(s.state_path.read_text())["_kit"]["pending"]) == 1
    assert len(client.placed) == 1, "an unclear order must never be retried"


def test_order_outcome_falls_back_to_polling(client, tmp_path):
    client.push_updates = False
    s = make(client, tmp_path)
    started = time.monotonic()
    result = s.order("NIFTY09NOV2624550CE", "NFO", "BUY", 65)
    assert result.quantity == 65
    assert time.monotonic() - started < 5


def test_order_without_final_status_stops(client, tmp_path):
    client.push_updates = False
    client.outcome = {"order_status": "open", "average_price": 0}
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="had no final status after 1s"):
        s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65, price_type="LIMIT", price=100, timeout=1)


def test_mode_switch_during_run_blocks_orders(client, tmp_path):
    s = make(client, tmp_path)
    s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65)
    client.analyze = True
    with pytest.raises(StrategyStop, match="switched from live to analyze"):
        s.order("NIFTY09NOV2624550CE", "NFO", "BUY", 65)
    assert len(client.placed) == 1


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def test_resume_fresh_without_state(client, tmp_path):
    s = make(client, tmp_path)
    assert s.resume() == "fresh"
    assert json.loads(s.state_path.read_text())["_kit"]["date"] == TODAY


def test_resume_continues_when_state_matches_broker(client, tmp_path):
    write_state(
        tmp_path,
        TODAY,
        fills=[fill("CE1", "SELL", 65), fill("PE1", "SELL", 65)],
        mode="live",
        extra={"legs": ["CE1", "PE1"]},
    )
    client.positions = [pos("CE1", -65), pos("PE1", -65)]
    s = make(client, tmp_path)
    assert s.resume() == "continue"
    assert s.state["legs"] == ["CE1", "PE1"]
    assert s.open_positions() == {"NFO:CE1:MIS": -65, "NFO:PE1:MIS": -65}


def test_resume_continues_flat_after_todays_exit(client, tmp_path):
    write_state(tmp_path, TODAY, fills=[fill("CE1", "SELL", 65), fill("CE1", "BUY", 65)])
    s = make(client, tmp_path)
    assert s.resume() == "continue"
    assert s.open_positions() == {}


def test_resume_stops_on_quantity_mismatch(client, tmp_path):
    write_state(tmp_path, TODAY, fills=[fill("CE1", "SELL", 65)])
    client.positions = [pos("CE1", -130)]
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="NFO:CE1:MIS: saved -65, broker -130"):
        s.resume()


def test_resume_stops_when_broker_is_flat_but_state_is_not(client, tmp_path):
    write_state(tmp_path, TODAY, fills=[fill("CE1", "SELL", 65)])
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="saved -65, broker 0"):
        s.resume()


def test_resume_stops_on_pending_order(client, tmp_path):
    write_state(tmp_path, TODAY, pending={"x": {"symbol": "CE1"}})
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="An order for CE1 was in flight"):
        s.resume()


def test_resume_stops_on_mode_change(client, tmp_path):
    write_state(tmp_path, TODAY, fills=[fill("CE1", "SELL", 65)], mode="live")
    client.positions = [pos("CE1", -65)]
    client.analyze = True
    s = make(client, tmp_path)
    with pytest.raises(
        StrategyStop, match="placed in live mode but the platform is now in analyze"
    ):
        s.resume()


def test_resume_archives_old_state_when_flat(client, tmp_path):
    write_state(tmp_path, "2026-11-04", fills=[fill("CE1", "SELL", 65)], extra={"legs": ["CE1"]})
    s = make(client, tmp_path)
    assert s.resume() == "fresh"
    assert (tmp_path / "kit_test.2026-11-04.json").exists()
    assert "legs" not in s.state


def test_resume_stops_on_old_state_with_open_position(client, tmp_path):
    write_state(tmp_path, "2026-11-04", fills=[fill("CE1", "SELL", 65, product="NRML")])
    client.positions = [pos("CE1", -65, product="NRML")]
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="earlier day but the broker still holds NFO:CE1:NRML"):
        s.resume()


def test_damaged_state_file_stops(client, tmp_path, monkeypatch, capsys):
    (tmp_path / "kit_test.json").write_text("{not json")
    s = Strategy(PARAMS, client=client, strategy_id="kit_test", state_dir=tmp_path)
    code, out = run_exit(s, lambda s: None, capsys)
    assert code == kit.EXIT_CODE_STOPPED
    assert "saved state file kit_test.json is damaged" in out


# ---------------------------------------------------------------------------
# State, reads, feed watch
# ---------------------------------------------------------------------------


def test_failed_save_leaves_previous_state_intact(client, tmp_path, monkeypatch):
    s = make(client, tmp_path)
    s.state["value"] = 1
    s.save_state()

    def broken_dump(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(kit.json, "dump", broken_dump)
    s.state["value"] = 2
    with pytest.raises(OSError):
        s.save_state()
    assert json.loads(s.state_path.read_text())["value"] == 1
    assert [p.name for p in tmp_path.iterdir()] == ["kit_test.json"], (
        "no temporary file left behind"
    )


def test_read_retries_network_errors(client, tmp_path):
    client.read_failures = [
        {"status": "error", "message": "x", "error_type": "connection_error"},
        {"status": "error", "message": "x", "error_type": "timeout_error"},
    ]
    s = make(client, tmp_path)
    assert s.positions() == {}


def test_read_stops_after_repeated_network_errors(client, tmp_path):
    client.read_failures = [
        {"status": "error", "message": "Failed to connect", "error_type": "connection_error"}
    ] * 3
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="Could not get the position book: Failed to connect"):
        s.positions()


def test_read_does_not_retry_server_errors(client, tmp_path):
    client.read_failures = [
        {
            "status": "error",
            "message": "Invalid openalgo apikey",
            "error_type": "http_error",
            "code": 403,
        }
    ]
    s = make(client, tmp_path)
    with pytest.raises(StrategyStop, match="Invalid openalgo apikey"):
        s.positions()


def _session(client, start_offset_s, end_offset_s):
    now_ms = time.time() * 1000
    client.timings_data = [
        {
            "exchange": "NSE",
            "start_time": now_ms + start_offset_s * 1000,
            "end_time": now_ms + end_offset_s * 1000,
        }
    ]


def test_feed_watch_stops_on_silent_heartbeat_in_session(client, tmp_path):
    _session(client, -3600, 3600)
    s = make(client, tmp_path)
    s.watch_feed(max_silence=20)
    s._watch["since"] = time.monotonic() - 60
    with pytest.raises(StrategyStop, match="No NIFTY prices for 60s during market hours"):
        s.sleep(1.2)


def test_feed_watch_is_quiet_with_fresh_ticks(client, tmp_path):
    _session(client, -3600, 3600)
    s = make(client, tmp_path)
    s.watch_feed(max_silence=20)
    client.ltp_cb({"exchange": "NSE_INDEX", "symbol": "NIFTY", "data": {"ltp": 24500.0}})
    assert s.sleep(1.2) is True
    assert s.ltp("NSE_INDEX", "NIFTY") == 24500.0
    assert s.ltp_age("NSE_INDEX", "NIFTY") < 5


def test_feed_watch_is_quiet_outside_the_session(client, tmp_path):
    _session(client, 3600, 7200)
    s = make(client, tmp_path)
    s.watch_feed(max_silence=1)
    s._watch["since"] = time.monotonic() - 600
    assert s.sleep(1.2) is True


def test_feed_watch_is_quiet_on_a_holiday(client, tmp_path):
    client.timings_data = []
    s = make(client, tmp_path)
    s.watch_feed(max_silence=1)
    s._watch["since"] = time.monotonic() - 600
    assert s.sleep(1.2) is True


def test_feed_watch_stops_when_platform_link_stays_down(client, tmp_path):
    _session(client, -3600, 3600)
    s = make(client, tmp_path)
    s.watch_feed(max_link_down=30)
    client.authenticated = False
    s._link_down_since = time.monotonic() - 45
    with pytest.raises(
        StrategyStop, match="Lost the connection to the platform's market feed for 45s"
    ):
        s.sleep(1.2)


def test_sleep_returns_false_once_stop_requested(client, tmp_path):
    s = make(client, tmp_path)
    s._stop_requested.set()
    assert s.sleep(5) is False


def test_log_lines_carry_ist_time(client, tmp_path, capsys):
    s = make(client, tmp_path)
    capsys.readouterr()
    s.log("hello")
    out = capsys.readouterr().out.strip()
    assert out.endswith("hello")
    datetime.strptime(out[1:9], "%H:%M:%S")
