"""Tests for strategies/examples/short_straddle_window.py.

The cycle logic (``Straddle.step``) is driven one tick at a time with a fake
SDK client, a fake clock and prices pushed through the kit's own tick handler,
so no server, market or real waiting is involved.

Run:
    uv run pytest test/test_short_straddle_window.py -v
"""

import ast
import importlib.util
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "strategies" / "lib"))

import strategy_kit as kit  # noqa: E402
from strategy_kit import IST, Strategy, StrategyStop  # noqa: E402

SCRIPT = ROOT / "strategies" / "examples" / "short_straddle_window.py"
_spec = importlib.util.spec_from_file_location("short_straddle_window", SCRIPT)
sw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sw)

TODAY = date(2026, 11, 9)


def at(hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 11, 9, hour, minute, tzinfo=IST)


class Broker:
    """The slice of the openalgo client the strategy and kit use, with a scripted ATM strike."""

    def __init__(self):
        self.spot = 24536.4  # NIFTY; the nearest 50 strike is 24550
        self.unlisted = set()  # option symbols the contract lookup does not know
        self.fill_prices = []  # average price for each next order; 100.0 when empty
        self.placed = []
        self.positions = []
        self.expiries = ["13-NOV-26", "06-NOV-26", "20-NOV-26", "25-NOV-26"]
        self._order_cb = None
        self._next = 1000
        self.authenticated = True

    def connect(self):
        return True

    def disconnect(self):
        pass

    def subscribe_orders(self, on_order_update=None):
        self._order_cb = on_order_update
        return True

    def subscribe_ltp(self, instruments, on_data_received=None):
        return True

    def positionbook(self):
        return {"status": "success", "data": self.positions}

    def analyzerstatus(self):
        return {"status": "success", "data": {"analyze_mode": True}}

    def timings(self, date=None):
        return {"status": "success", "data": [{"exchange": "NFO", "start_time": 0, "end_time": 1}]}

    def expiry(self, symbol, exchange, instrumenttype):
        return {"status": "success", "data": self.expiries}

    def quotes(self, symbol, exchange):
        return {"status": "success", "data": {"ltp": self.spot}}

    def symbol(self, symbol, exchange):
        if symbol in self.unlisted:
            return {"status": "error", "message": f"Symbol {symbol} not found"}
        return {"status": "success", "data": {"symbol": symbol, "lotsize": 65}}

    def orderstatus(self, order_id, strategy=None):
        raise AssertionError("fills arrive on the order stream in these tests")

    def placeorder(self, **kwargs):
        self.placed.append(kwargs)
        self._next += 1
        order_id = str(self._next)
        price = self.fill_prices.pop(0) if self.fill_prices else 100.0
        self._order_cb(
            {
                "type": "order_update",
                "orderid": order_id,
                "order_status": "complete",
                "average_price": price,
                "filled_quantity": kwargs["quantity"],
            }
        )
        return {"status": "success", "orderid": order_id}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OPENALGO_STRATEGY_PARAMS", "OPENALGO_API_KEY", "STRATEGY_ID", "STRATEGY_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(kit, "_READ_RETRY_DELAYS", (0, 0))


def make(tmp_path, monkeypatch, broker=None, **params):
    if params:
        monkeypatch.setenv("OPENALGO_STRATEGY_PARAMS", json.dumps(params))
    broker = broker or Broker()
    s = Strategy(sw.PARAMS, client=broker, strategy_id="window", name="Window", state_dir=tmp_path)
    s._setup()
    s.state = {}
    s._kit()
    tick(s, "NIFTY", broker.spot, "NSE_INDEX")
    return s, broker


def tick(s, symbol, price, exchange="NFO"):
    s._on_tick({"exchange": exchange, "symbol": symbol, "data": {"ltp": price}})


def orders(broker):
    return [(o["action"], o["symbol"], o["quantity"]) for o in broker.placed]


CE = "NIFTY13NOV2624550CE"
PE = "NIFTY13NOV2624550PE"


# --- settings ---------------------------------------------------------------------


def test_params_are_a_literal_the_host_can_read():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "PARAMS")
    schema = ast.literal_eval(node.value)
    kit.check_params_schema(schema)
    kit.validate_params(schema, {})


def test_an_unreadable_time_setting_stops_with_its_label(tmp_path, monkeypatch):
    s, _ = make(tmp_path, monkeypatch, squareoff_time="3pm")
    with pytest.raises(StrategyStop, match="Square off at"):
        sw.Straddle(s, today=TODAY)


def test_first_entry_after_square_off_is_refused(tmp_path, monkeypatch):
    s, _ = make(tmp_path, monkeypatch, first_entry="15:20", squareoff_time="15:15")
    with pytest.raises(StrategyStop, match="earlier than the square-off"):
        sw.Straddle(s, today=TODAY)


def test_nearest_expiry_is_the_first_on_or_after_today(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    assert sw.nearest_expiry(s, "NIFTY", "NFO", TODAY) == "13NOV26"
    broker.expiries = ["06-NOV-26"]
    with pytest.raises(StrategyStop, match="No upcoming"):
        sw.nearest_expiry(s, "NIFTY", "NFO", TODAY)


# --- the cycle --------------------------------------------------------------------


def test_nothing_is_sold_before_first_entry(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    straddle = sw.Straddle(s, today=TODAY)
    assert straddle.step(at("09:19"), 1) is True
    assert broker.placed == []


def test_first_entry_sells_the_atm_pair_of_the_nearest_expiry(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch, lots=2)
    broker.fill_prices = [100.0, 90.0]
    straddle = sw.Straddle(s, today=TODAY)
    straddle.step(at("09:20"), 1)
    assert orders(broker) == [("SELL", CE, 130), ("SELL", PE, 130)]
    assert s.state["legs"] == {CE: 100.0, PE: 90.0}
    saved = json.loads(s.state_path.read_text(encoding="utf-8"))
    assert saved["legs"] == {CE: 100.0, PE: 90.0}


def test_only_a_rise_by_the_window_closes_the_cycle(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch, window_percent=20)
    broker.fill_prices = [100.0, 90.0]
    straddle = sw.Straddle(s, today=TODAY)
    straddle.step(at("09:20"), 1)

    tick(s, CE, 119.9)
    tick(s, PE, 40.0)  # a fall, however large, is not the trigger
    straddle.step(at("09:30"), 2)
    assert len(broker.placed) == 2

    tick(s, PE, 108.0)  # 90 * 1.20
    straddle.step(at("09:31"), 3)
    assert orders(broker)[2:] == [("BUY", CE, 65), ("BUY", PE, 65)]
    assert s.state["legs"] == {} and s.state["cycles"] == 1
    assert s.open_positions() == {}


def test_after_a_cycle_a_fresh_pair_is_sold_at_the_new_strike(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    straddle = sw.Straddle(s, today=TODAY)
    straddle.step(at("09:20"), 1)
    tick(s, CE, 500.0)
    straddle.step(at("09:40"), 2)
    tick(s, "NIFTY", 24610.0, "NSE_INDEX")
    straddle.step(at("09:41"), 3)
    new = orders(broker)[4:]
    assert new == [("SELL", "NIFTY13NOV2624600CE", 65), ("SELL", "NIFTY13NOV2624600PE", 65)]


def test_the_cycle_limit_ends_the_day(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch, max_cycles=2)
    straddle = sw.Straddle(s, today=TODAY)
    for minute in range(2):
        straddle.step(at("09:20"), minute * 10 + 1)
        tick(s, CE, 1000.0)
        assert straddle.step(at("09:21"), minute * 10 + 2) is True
    assert straddle.step(at("09:22"), 30) is False
    assert s.state["cycles"] == 2
    assert [o[0] for o in orders(broker)].count("SELL") == 4


def test_square_off_buys_back_open_legs_and_ends(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    straddle = sw.Straddle(s, today=TODAY)
    straddle.step(at("09:20"), 1)
    assert straddle.step(at("15:15"), 2) is False
    assert orders(broker)[2:] == [("BUY", CE, 65), ("BUY", PE, 65)]
    assert s.open_positions() == {}


def test_square_off_with_nothing_open_just_ends(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    straddle = sw.Straddle(s, today=TODAY)
    assert straddle.step(at("15:30"), 1) is False
    assert broker.placed == []


# --- after a restart ---------------------------------------------------------------


def _sold(s, symbol, price):
    s._kit()["fills"].append(
        {
            "order_id": "1",
            "symbol": symbol,
            "exchange": "NFO",
            "action": "SELL",
            "quantity": 65,
            "average_price": price,
            "product": "MIS",
        }
    )


def test_restart_continues_a_full_pair(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    _sold(s, CE, 100.0)
    _sold(s, PE, 90.0)
    s.state.update({"legs": {CE: 100.0, PE: 90.0}, "cycles": 1})
    straddle = sw.Straddle(s, today=TODAY)
    straddle.recover("continue")
    assert s.state["legs"] == {CE: 100.0, PE: 90.0} and broker.placed == []


def test_restart_with_one_leg_sold_buys_it_back(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    _sold(s, CE, 100.0)
    s.state.update({"legs": {CE: 100.0}, "cycles": 0})
    straddle = sw.Straddle(s, today=TODAY)
    straddle.recover("continue")
    assert orders(broker) == [("BUY", CE, 65)]
    assert s.state["legs"] == {} and s.state["cycles"] == 1


def test_restart_adds_a_leg_filled_before_its_price_was_saved(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch)
    _sold(s, CE, 100.0)
    _sold(s, PE, 92.5)
    s.state.update({"legs": {CE: 100.0}, "cycles": 0})
    straddle = sw.Straddle(s, today=TODAY)
    straddle.recover("continue")
    assert s.state["legs"] == {CE: 100.0, PE: 92.5} and broker.placed == []


def test_a_fresh_start_resets_the_day(tmp_path, monkeypatch):
    s, _ = make(tmp_path, monkeypatch)
    s.state.update({"legs": {CE: 1.0}, "cycles": 4})
    straddle = sw.Straddle(s, today=TODAY)
    straddle.recover("fresh")
    assert (s.state["legs"], s.state["cycles"]) == ({}, 0)


# --- strikes and the ATM offset -------------------------------------------------------


def test_atm_offset_sells_out_of_the_money_on_each_side(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch, atm_offset=2)
    sw.Straddle(s, today=TODAY).step(at("09:20"), 1)
    assert orders(broker) == [
        ("SELL", "NIFTY13NOV2624650CE", 65),
        ("SELL", "NIFTY13NOV2624450PE", 65),
    ]


def test_strikes_follow_the_node_app_rounding(tmp_path, monkeypatch):
    broker = Broker()
    broker.spot = 24525.0  # a midpoint: the Node app rounds up, to 24550
    s, broker = make(tmp_path, monkeypatch, broker=broker)
    sw.Straddle(s, today=TODAY).step(at("09:20"), 1)
    assert [o[1] for o in orders(broker)] == [CE, PE]


def test_banknifty_uses_its_hundred_point_strikes(tmp_path, monkeypatch):
    broker = Broker()
    broker.spot = 51249.0
    s, broker = make(tmp_path, monkeypatch, broker=broker, underlying="BANKNIFTY", atm_offset=1)
    tick(s, "BANKNIFTY", 51249.0, "NSE_INDEX")
    sw.Straddle(s, today=TODAY).step(at("09:20"), 1)
    assert [o[1] for o in orders(broker)] == ["BANKNIFTY13NOV2651300CE", "BANKNIFTY13NOV2651100PE"]


def test_an_unlisted_strike_stops_before_any_order(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch, atm_offset=10)
    broker.unlisted.add("NIFTY13NOV2625050CE")
    with pytest.raises(StrategyStop, match="may not be listed"):
        sw.Straddle(s, today=TODAY).step(at("09:20"), 1)
    assert broker.placed == []


# --- whether the day is done ---------------------------------------------------------


def test_raising_the_cycle_limit_continues_the_same_day(tmp_path, monkeypatch):
    s, broker = make(tmp_path, monkeypatch, max_cycles=10)
    s.state["cycles"] = 5  # the day stopped at the old limit of 5
    straddle = sw.Straddle(s, today=TODAY)
    assert straddle.done_for_today(at("13:12")) is None
    straddle.step(at("13:12"), 1)
    assert [o[0] for o in orders(broker)] == ["SELL", "SELL"]


def test_done_for_today_names_the_reason(tmp_path, monkeypatch):
    s, _ = make(tmp_path, monkeypatch, max_cycles=5)
    s.state["cycles"] = 5
    straddle = sw.Straddle(s, today=TODAY)
    assert "5 of 5 cycles" in straddle.done_for_today(at("13:12"))
    s.state["cycles"] = 1
    assert "square-off" in straddle.done_for_today(at("15:20"))


def _main_once(s, monkeypatch, hhmm):
    monkeypatch.setattr(sw, "now_ist", lambda: at(hhmm))
    monkeypatch.setattr(s, "sleep", lambda seconds: False)
    sw.main(s)


def test_a_second_start_after_the_limit_places_nothing(tmp_path, monkeypatch, capsys):
    s, broker = make(tmp_path, monkeypatch, max_cycles=5, start_mode="old")
    s.state["cycles"] = 5
    s.save_state()
    _main_once(s, monkeypatch, "13:12")
    out = capsys.readouterr().out
    assert "Starting in OLD mode" in out and "No open positions." in out
    assert "Today so far: 5 of 5 cycles done." in out
    assert "Raise Cycles per day" in out
    assert broker.placed == []


def test_a_second_start_with_a_raised_limit_runs_on(tmp_path, monkeypatch, capsys):
    s, broker = make(tmp_path, monkeypatch, max_cycles=5, start_mode="old")
    s.state["cycles"] = 5
    s.save_state()
    s.params["max_cycles"] = 6
    _main_once(s, monkeypatch, "13:12")
    out = capsys.readouterr().out
    assert "Today so far: 5 of 6 cycles done." in out and "Raise Cycles" not in out


# --- start mode -------------------------------------------------------------------------


def test_new_mode_starts_a_fresh_day_even_with_legs_saved(tmp_path, monkeypatch, capsys):
    s, broker = make(tmp_path, monkeypatch, start_mode="new")
    _sold(s, CE, 100.0)
    _sold(s, PE, 90.0)
    s.state.update({"legs": {CE: 100.0, PE: 90.0}, "cycles": 3})
    s.save_state()
    _main_once(s, monkeypatch, "13:12")
    out = capsys.readouterr().out
    assert "Starting in NEW mode: fresh start" in out
    assert s.state["cycles"] == 0 and s.state["legs"] == {}
    assert broker.placed == [], "nothing is bought back: New ignores what was saved"


def test_old_mode_continues_saved_legs_the_broker_no_longer_shows(tmp_path, monkeypatch, capsys):
    s, broker = make(tmp_path, monkeypatch, start_mode="old")
    broker.positions = []  # closed by hand at the broker: Old does not ask
    _sold(s, CE, 100.0)
    _sold(s, PE, 90.0)
    s.state.update({"legs": {CE: 100.0, PE: 90.0}, "cycles": 1})
    s.save_state()
    _main_once(s, monkeypatch, "13:12")
    out = capsys.readouterr().out
    assert "Starting in OLD mode" in out and "Continuing cycle 2" in out
    assert s.state["legs"] == {CE: 100.0, PE: 90.0}


def test_old_mode_on_a_new_day_restarts_the_cycle_count(tmp_path, monkeypatch, capsys):
    s, _ = make(tmp_path, monkeypatch, start_mode="old")
    s.state.update({"cycles": 4, "day": "2026-11-08", "legs": {}})
    straddle = sw.Straddle(s, today=TODAY)
    assert s.state["cycles"] == 0 and s.state["day"] == "2026-11-09"
    assert "New trading day" in capsys.readouterr().out
    assert straddle.done_for_today(at("10:00")) is None
