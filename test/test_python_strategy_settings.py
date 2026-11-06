"""Tests for per-strategy settings (PARAMS) and saved-state handling in the /python host.

Covers M3 of docs/plans/2026-11-06-python-strategy-kit-implementation-plan.md:
reading PARAMS without running the strategy, the settings routes, clearing
saved state, and passing saved settings to the strategy process.

Run:
    uv run pytest test/test_python_strategy_settings.py -v
"""

import json
from pathlib import Path

import pytest
from flask import Flask, session
from test_python_strategy_edge_cases import calendar_db, ps_module  # noqa: F401

PARAMS_SOURCE = """
from strategy_kit import Strategy

PARAMS = {
    "lots": {"type": "int", "default": 1, "min": 1, "max": 5, "label": "Lots per leg"},
    "expiry": {"type": "str", "default": "09NOV26"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"]},
    "trail": {"type": "bool", "default": False},
}

Strategy(PARAMS).run(lambda s: None)
"""


@pytest.fixture()
def host(ps_module, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(ps_module, "STATE_DIR", tmp_path / "state")
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(ps_module, "save_configs", lambda: None)
    return ps_module


def add_strategy(host, tmp_path, source=PARAMS_SOURCE, **extra):
    script = tmp_path / "kit_strategy.py"
    script.write_text(source, encoding="utf-8")
    config = {
        "name": "Kit Strategy",
        "file_path": str(script),
        "user_id": "alice",
        "exchange": "NFO",
    }
    config.update(extra)
    host.STRATEGY_CONFIGS["k"] = config
    return config


def call(view, user="alice", json_body=None, method="GET"):
    """Call a route's undecorated function inside a request with a logged-in session."""
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context(method=method, json=json_body):
        session["user"] = user
        result = view.__wrapped__("k")
    response, status = result if isinstance(result, tuple) else (result, 200)
    return response.get_json(), status


def write_state(host, data):
    (host.STATE_DIR / "k.json").write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Reading PARAMS without running the strategy
# ---------------------------------------------------------------------------


def test_params_are_read_in_declaration_order(host):
    schema, error = host.extract_params_schema(PARAMS_SOURCE)
    assert error is None
    assert list(schema) == ["lots", "expiry", "product", "trail"]


def test_no_params_is_not_an_error(host):
    assert host.extract_params_schema("print('hi')\n") == (None, None)


def test_annotated_and_repeated_params(host):
    source = 'PARAMS: dict = {"a": {"type": "int", "default": 1}}\nPARAMS = {"b": {"type": "int", "default": 2}}\n'
    schema, error = host.extract_params_schema(source)
    assert error is None and list(schema) == ["b"]


@pytest.mark.parametrize(
    "source, fragment",
    [
        ("PARAMS = {\n", "syntax error on line"),
        (
            "N = 3\nPARAMS = {'lots': {'type': 'int', 'default': N}}\n",
            "plain dictionary of fixed values",
        ),
        ("PARAMS = {'lots': {'default': 1}}\n", "'lots' needs a type"),
        ("PARAMS = [1, 2]\n", "PARAMS must be a dictionary"),
    ],
)
def test_bad_params_explain_themselves(host, source, fragment):
    schema, error = host.extract_params_schema(source)
    assert schema is None
    assert fragment in error


def test_reading_params_never_runs_the_strategy(host, tmp_path):
    marker = tmp_path / "ran.txt"
    source = (
        f"open(r'{marker}', 'w').write('x')\nPARAMS = {{'a': {{'type': 'int', 'default': 1}}}}\n"
    )
    schema, error = host.extract_params_schema(source)
    assert error is None and schema
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Settings payload and routes
# ---------------------------------------------------------------------------


def test_payload_merges_saved_values_and_flags_stale_ones(host, tmp_path):
    config = add_strategy(host, tmp_path, params={"lots": 9, "product": "NRML", "gone": 1})
    payload = host.strategy_settings_payload("k", config)
    values = {f["name"]: f["value"] for f in payload["fields"]}
    assert [f["name"] for f in payload["fields"]] == ["lots", "expiry", "product", "trail"]
    assert values == {"lots": 1, "expiry": "09NOV26", "product": "NRML", "trail": False}
    assert payload["problems"] == ["Saved value no longer valid: Lots per leg must be at most 5"]
    assert payload["error"] is None and payload["saved_state"] is None


def test_payload_reports_an_unreadable_file(host, tmp_path):
    config = add_strategy(host, tmp_path)
    Path(config["file_path"]).unlink()
    assert (
        host.strategy_settings_payload("k", config)["error"]
        == "The strategy file could not be read."
    )


def test_get_route_returns_the_form(host, tmp_path):
    add_strategy(host, tmp_path)
    body, status = call(host.api_get_strategy_params)
    assert status == 200 and body["status"] == "success"
    assert body["data"]["fields"][0]["label"] == "Lots per leg"


def test_get_route_refuses_another_user(host, tmp_path):
    add_strategy(host, tmp_path)
    _, status = call(host.api_get_strategy_params, user="mallory")
    assert status == 403


def test_save_route_stores_validated_values(host, tmp_path):
    config = add_strategy(host, tmp_path)
    body, status = call(
        host.api_save_strategy_params,
        method="POST",
        json_body={"values": {"lots": "3", "product": "NRML", "trail": True, "extra": 1}},
    )
    assert status == 200, body
    assert config["params"] == {"lots": 3, "expiry": "09NOV26", "product": "NRML", "trail": True}
    assert body["message"] == "Settings saved."


def test_save_route_refuses_invalid_values(host, tmp_path):
    config = add_strategy(host, tmp_path)
    body, status = call(
        host.api_save_strategy_params,
        method="POST",
        json_body={"values": {"lots": 50, "product": "CNC"}},
    )
    assert status == 400
    assert body["message"] == "Lots per leg must be at most 5; product must be one of: MIS, NRML"
    assert "params" not in config


def test_save_route_while_running_says_when_it_applies(host, tmp_path):
    add_strategy(host, tmp_path, is_running=True)
    body, status = call(
        host.api_save_strategy_params, method="POST", json_body={"values": {"lots": 2}}
    )
    assert status == 200
    assert body["message"] == "Settings saved. They apply the next time the strategy starts."


@pytest.mark.parametrize(
    "source, json_body, message",
    [
        ("print('hi')\n", {"values": {}}, "This strategy declares no settings."),
        ("PARAMS = {\n", {"values": {}}, "syntax error on line"),
        (PARAMS_SOURCE, {}, "No settings were sent."),
    ],
)
def test_save_route_refusals(host, tmp_path, source, json_body, message):
    add_strategy(host, tmp_path, source=source)
    body, status = call(host.api_save_strategy_params, method="POST", json_body=json_body)
    assert status == 400 and message in body["message"]


# ---------------------------------------------------------------------------
# Saved state
# ---------------------------------------------------------------------------


def fill(symbol, action, qty):
    return {
        "symbol": symbol,
        "exchange": "NFO",
        "product": "MIS",
        "action": action,
        "quantity": qty,
    }


def test_saved_state_summary(host, tmp_path):
    add_strategy(host, tmp_path)
    write_state(
        host,
        {
            "_kit": {
                "date": "2026-11-06",
                "fills": [fill("CE", "SELL", 65), fill("PE", "SELL", 65), fill("PE", "BUY", 65)],
                "pending": {"x": {"symbol": "CE"}},
            }
        },
    )
    assert host.describe_saved_state("k") == {
        "date": "2026-11-06",
        "open_positions": 1,
        "pending_orders": 1,
        "damaged": False,
    }


def test_damaged_saved_state_is_reported(host, tmp_path):
    (host.STATE_DIR / "k.json").write_text("{nope", encoding="utf-8")
    assert host.describe_saved_state("k")["damaged"] is True


def test_clear_route_archives_the_state(host, tmp_path):
    add_strategy(host, tmp_path)
    write_state(host, {"_kit": {"date": "2026-11-06", "fills": [], "pending": {}}})
    body, status = call(host.api_clear_strategy_state, method="POST")
    assert status == 200
    assert body["message"] == "Saved state cleared. The next start will be a fresh start."
    names = [p.name for p in host.STATE_DIR.iterdir()]
    assert "k.json" not in names
    assert len(names) == 1 and names[0].startswith("k.cleared-")


def test_clear_route_with_nothing_saved(host, tmp_path):
    add_strategy(host, tmp_path)
    body, status = call(host.api_clear_strategy_state, method="POST")
    assert status == 200 and body["message"] == "There was no saved state to clear."


def test_clear_route_refuses_while_running(host, tmp_path):
    add_strategy(host, tmp_path, is_running=True)
    write_state(host, {"_kit": {}})
    body, status = call(host.api_clear_strategy_state, method="POST")
    assert status == 400 and "Stop the strategy" in body["message"]
    assert (host.STATE_DIR / "k.json").exists()


def test_deleted_strategy_state_is_archived_not_lost(host):
    write_state(host, {"_kit": {}})
    assert host.archive_saved_state("k", label="deleted") is True
    assert [p.name.split("-")[0] for p in host.STATE_DIR.iterdir()] == ["k.deleted"]


# ---------------------------------------------------------------------------
# Settings reach the strategy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("saved, expected", [({"lots": 3}, {"lots": 3}), (None, {})])
def test_saved_settings_are_passed_to_the_process(host, tmp_path, monkeypatch, saved, expected):
    config = add_strategy(host, tmp_path)
    if saved is not None:
        config["params"] = saved
    monkeypatch.setenv("OPENALGO_STRATEGY_PARAMS", '{"leaked": true}')
    captured = {}

    class FakeProc:
        def __init__(self, *a, **kw):
            captured.update(kw.get("env") or {})
            self.pid = 9001

        def poll(self):
            return None

    monkeypatch.setattr(host.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(host, "check_master_contract_ready", lambda: (True, "ok"))
    monkeypatch.setattr(host, "broadcast_status_update", lambda *a, **kw: None)
    monkeypatch.setattr(host, "LOGS_DIR", tmp_path)

    success, message = host.start_strategy_process("k")
    assert success, message
    assert json.loads(captured["OPENALGO_STRATEGY_PARAMS"]) == expected
