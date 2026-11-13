#!/usr/bin/env python3
"""Clear a deployment's broker-specific and trading-history data, keeping the login and the client's own work.

This is the data half of a broker switch (see ``install/change-broker.sh``,
which also rewrites ``.env`` and restarts the service). Run it with the server
**stopped**, from the project root, in the deployment's own virtualenv:

    python scripts/reset_broker_data.py --dry-run     # show what would be cleared
    python scripts/reset_broker_data.py --yes         # clear it

**What it keeps** (the client is the same person, switching broker, not a new
customer): the login (``users``), the OpenAlgo API key (``api_keys``), settings,
and every piece of work the client authored - Flow workflows, strategy-module
configs, strategy portfolios, Chartink strategies, watchlists, chart
preferences, and the Telegram, WhatsApp and agent configuration. Strategy
scripts and chart indicators live as files, not rows, so they are untouched too.

**What it clears**: the old broker's session (``auth``), the old broker's symbol
master (``symtoken`` and ``master_contract_status``, so the new broker
re-downloads its own contracts on first login), and the live trading history
left behind by the old broker - API order logs, order latency, strategy-book
positions and pending fills, action-centre pending orders, analyzer logs,
scalping state, strategy-module run history, Flow execution history, and the
whole sandbox book (orders, trades, positions, holdings, funds, daily PnL, GTT).
The sandbox *configuration* (capital, settings) is kept.

It wipes a table by name wherever that table is found across the deployment's
SQLite databases, so it never needs to know which file holds which table, and a
kept table can never be touched because its name is not in the clear list. It is
idempotent: clearing an already-empty table is a no-op, so it is safe to re-run.
The historical market-data store (``historify.duckdb``) is broker-agnostic OHLC
and is never opened here.
"""

import argparse
import os
import sys

from sqlalchemy import create_engine, inspect, text

# Set UTF-8 output for Windows consoles, matching the upgrade scripts.
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Wait the same 15s for a write lock the running app does, not sqlite3's default
# 5s, in case the operator runs this without fully stopping the service.
try:
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "upgrade"))
    import _pragmas  # noqa: F401
except Exception:
    pass

# The SQLite databases that can hold broker or trading-history rows. The
# historical DuckDB store and health.db hold nothing we clear, so they are not
# listed. Each entry is (label, env var, default URL).
DATABASES = [
    ("Main", "DATABASE_URL", "sqlite:///db/openalgo.db"),
    ("Logs", "LOGS_DATABASE_URL", "sqlite:///db/logs.db"),
    ("Latency", "LATENCY_DATABASE_URL", "sqlite:///db/latency.db"),
    ("Sandbox", "SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db"),
]

# Tables cleared on a broker switch. A table is cleared wherever it is found, so
# the database it lives in does not matter here - only that the name is correct.
WIPE_TABLES = frozenset(
    {
        # The old broker's session and symbol master.
        "auth",
        "symtoken",
        "master_contract_status",
        # Trading history and live run state left by the old broker.
        "order_logs",
        "order_latency",
        "strategy_positions",
        "strategy_pending_fills",
        "strategy_order_tags",
        "pending_orders",
        "analyzer_logs",
        "scalping_sl_state",
        "scalping_tracked_symbol",
        "sm_strategy_run",
        "sm_strategy_order",
        "sm_strategy_checkpoint",
        "sm_webhook_event",
        "sm_strategy_event",
        "flow_workflow_executions",
        "sandbox_orders",
        "sandbox_trades",
        "sandbox_positions",
        "sandbox_holdings",
        "sandbox_funds",
        "sandbox_daily_pnl",
        "sandbox_gtt",
        "sandbox_gtt_legs",
    }
)

# A last line of defence: these hold the login and the client's own work and
# must survive the reset, so the script refuses to clear them even if one were
# listed above by mistake.
NEVER_WIPE = frozenset(
    {
        "users",
        "api_keys",
        "settings",
        "flow_workflows",
        "sm_strategy",
        "strategy_portfolio",
        "chartink_strategies",
        "chartink_symbol_mappings",
        "chart_preferences",
        "watchlists",
        "watchlist_items",
        "sandbox_config",
    }
)

assert WIPE_TABLES.isdisjoint(NEVER_WIPE), "A kept table is listed for clearing."


def resolve_sqlite_url(url: str) -> str:
    """Make a relative ``sqlite:///db/x.db`` absolute against the project root, as the app does."""
    if url and url.startswith("sqlite:///"):
        path = url[len("sqlite:///") :]
        if not os.path.isabs(path):
            path = os.path.join(PROJECT_ROOT, path)
        return f"sqlite:///{path}"
    return url


def sqlite_file(url: str) -> str | None:
    """The filesystem path behind a sqlite URL, or None if it is not sqlite."""
    if url and url.startswith("sqlite:///"):
        return url[len("sqlite:///") :]
    return None


def process_database(label: str, url: str, dry_run: bool) -> tuple[list[tuple[str, int]], int]:
    """Clear (or count) the wipe-tables present in one database. Returns (per-table rows, total)."""
    resolved = resolve_sqlite_url(url)
    path = sqlite_file(resolved)
    # A database that was never created has nothing to clear. Do not connect,
    # which would create an empty file (and, run as root, a wrongly-owned one).
    if path is not None and not os.path.exists(path):
        print(f"  {label}: not present, skipped")
        return [], 0

    engine = create_engine(resolved)
    results: list[tuple[str, int]] = []
    total = 0
    try:
        present = set(inspect(engine).get_table_names())
        targets = sorted(present & WIPE_TABLES)
        if not targets:
            print(f"  {label}: no broker or history tables")
            return [], 0
        with engine.begin() as conn:
            for table in targets:
                if table in NEVER_WIPE:  # unreachable given the assert; kept as a guard
                    continue
                count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar() or 0
                if not dry_run and count:
                    conn.execute(text(f'DELETE FROM "{table}"'))
                results.append((table, count))
                total += count
        verb = "would clear" if dry_run else "cleared"
        for table, count in results:
            print(f"  {label}: {verb} {count} row(s) from {table}")
    finally:
        engine.dispose()
    return results, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reset_broker_data.py",
        description="Clear broker session and trading history, keeping login and client work.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would be cleared, change nothing"
    )
    parser.add_argument(
        "--yes", action="store_true", help="clear without the confirmation prompt"
    )
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

    print("=" * 60)
    print("Broker data reset" + (" (dry run)" if args.dry_run else ""))
    print("=" * 60)
    print("Keeps: login, API key, settings, and all client-authored work.")
    print("Clears: broker session, symbol master, and trading history.")
    print()

    if not args.dry_run and not args.yes:
        try:
            answer = input('Type RESET to clear broker data, anything else to cancel: ').strip()
        except EOFError:
            answer = ""
        if answer != "RESET":
            print("Cancelled. Nothing was changed.")
            return 1
        print()

    grand_total = 0
    for label, env_var, default in DATABASES:
        url = os.getenv(env_var, default)
        _results, total = process_database(label, url, args.dry_run)
        grand_total += total

    print()
    if args.dry_run:
        print(f"Dry run: {grand_total} row(s) would be cleared. Nothing was changed.")
    else:
        print(f"Done: {grand_total} row(s) cleared.")
        print("The new broker re-downloads its symbol master on first login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
