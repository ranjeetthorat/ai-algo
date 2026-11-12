"""Tests for strategies/lib/option_strikes.py.

The rounding must match the Node app's ``getNearestNiftyStrikePrice`` strike for
strike, so the central test runs that function, verbatim, under Node and
compares every result. It is skipped where Node.js is not installed.

Run:
    uv run pytest test/test_option_strikes.py -v
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "strategies" / "lib"))

from option_strikes import (  # noqa: E402
    format_strike,
    nearest_strike,
    option_strike,
    option_symbol,
    strike_step,
)

#: The Node app's function as it is in that codebase. Only appSettings is
#: supplied here, so ATM_OFFSET can be varied.
NODE_FUNCTION = """
export function getNearestNiftyStrikePrice(input: number, opt: 'C' | 'P'): number {
  const atm_set = appSettings.getSettings().ATM_OFFSET
  const offset = opt == 'C' ? 50 * atm_set : 50 * atm_set * -1
  const rounded = Math.floor(input); // handles float input
  const base = Math.floor(rounded / 100) * 100;
  const lastThreeDigits = rounded % 100;
  if (lastThreeDigits >= 75 || lastThreeDigits <= 24) {
    return (lastThreeDigits >= 75 ? base + 100 : base) + offset;
  } else {
    return (base + 50) + offset;
  }
}
"""

NODE_HARNESS = """
let ATM_OFFSET = 0;
const appSettings = { getSettings: () => ({ ATM_OFFSET }) };
%s
const prices: number[] = JSON.parse(process.argv[2]);
const out: Record<string, number[]> = {};
for (const offset of [0, 1, 2, 3]) {
  ATM_OFFSET = offset;
  out[`C${offset}`] = prices.map((p) => getNearestNiftyStrikePrice(p, 'C'));
  out[`P${offset}`] = prices.map((p) => getNearestNiftyStrikePrice(p, 'P'));
}
console.log(JSON.stringify(out));
"""


def _prices() -> list[float]:
    # Every 5 paise across 6,000 points, which visits every remainder within a
    # hundred many times over, plus the exact boundaries.
    grid = [round(20000 + i * 0.05, 2) for i in range(120_000)]
    edges = [24524.99, 24525.0, 24525.01, 24574.99, 24575.0, 24575.01, 24599.99, 24600.0]
    return grid + edges


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_matches_the_node_app_function_exactly(tmp_path):
    script = tmp_path / "strike.ts"
    script.write_text(NODE_HARNESS % NODE_FUNCTION.replace("export ", ""), encoding="utf-8")
    prices = _prices()
    args = tmp_path / "prices.json"
    args.write_text(json.dumps(prices), encoding="utf-8")
    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            "--no-warnings",
            "-e",
            f"process.argv[2]=require('fs').readFileSync({json.dumps(str(args))},'utf8');"
            f"require({json.dumps(str(script))})",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 and "strip-types" in result.stderr:
        pytest.skip("this Node.js cannot run TypeScript directly")
    assert result.returncode == 0, result.stderr
    expected = json.loads(result.stdout)
    for offset in range(4):
        for kind, opt in (("CE", "C"), ("PE", "P")):
            ours = [option_strike(p, kind, offset, 50) for p in prices]
            theirs = expected[f"{opt}{offset}"]
            mismatches = [(p, a, b) for p, a, b in zip(prices, ours, theirs, strict=True) if a != b]
            assert not mismatches, f"{kind} offset {offset}: {mismatches[:5]}"


@pytest.mark.parametrize(
    ("price", "strike"),
    [
        (24510, 24500),
        (24524.99, 24500),
        (24525.0, 24550),  # a midpoint rounds up
        (24536.4, 24550),
        (24574.99, 24550),
        (24575.0, 24600),
        (24599.9, 24600),
        (24600.0, 24600),
    ],
)
def test_nearest_fifty(price, strike):
    assert nearest_strike(price, 50) == strike


def test_offset_moves_out_of_the_money_on_each_side():
    assert option_strike(24536.4, "CE", 0) == option_strike(24536.4, "PE", 0) == 24550
    assert option_strike(24536.4, "CE", 2) == 24650
    assert option_strike(24536.4, "PE", 2) == 24450
    assert option_strike(24536.4, "C", 1) == 24600 and option_strike(24536.4, "P", 1) == 24500


def test_other_steps_use_the_same_rule():
    assert nearest_strike(51249, 100) == 51200
    assert nearest_strike(51250, 100) == 51300
    assert option_strike(80_049.5, "PE", 1, strike_step("SENSEX")) == 79_900
    assert nearest_strike(12_812.4, 25) == 12_800
    assert nearest_strike(12_812.6, 25) == 12_800  # paise are dropped first
    assert nearest_strike(12_813, 25) == 12_825


def test_strike_steps_and_unknown_underlyings():
    assert strike_step("nifty") == 50 and strike_step("BANKNIFTY") == 100
    with pytest.raises(ValueError, match="Pass step="):
        strike_step("RELIANCE")


def test_symbols_are_built_in_the_platform_format():
    assert option_symbol("nifty", "13nov26", 24600, "C") == "NIFTY13NOV2624600CE"
    assert option_symbol("VEDL", "25APR24", 292.5, "CE") == "VEDL25APR24292.5CE"
    assert format_strike(24550.0) == "24550"


@pytest.mark.parametrize(
    "call",
    [
        lambda: nearest_strike(float("nan")),
        lambda: nearest_strike(0),
        lambda: nearest_strike(24500, step=0),
        lambda: option_strike(24500, "XX"),
        lambda: option_strike(24500, "CE", offset=-1),
        lambda: option_strike(24500, "CE", offset=1.5),
    ],
)
def test_bad_inputs_are_refused(call):
    with pytest.raises(ValueError):
        call()
