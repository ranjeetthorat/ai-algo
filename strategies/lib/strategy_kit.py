"""
FastAlgo strategy kit: the plumbing every Python strategy needs.

A strategy imports it and writes only its trading logic:

    from strategy_kit import Strategy

    PARAMS = {
        "lots": {"type": "int", "default": 1, "min": 1, "label": "Lots per leg"},
    }

    def main(s):
        if s.resume() == "fresh":
            s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65 * s.params["lots"])
        while s.sleep(1):
            ...

    Strategy(PARAMS).run(main)

The /python host puts this folder on PYTHONPATH when it starts a strategy.

What the kit gives a strategy:

- s.params        settings from the strategy card merged over PARAMS defaults
- s.state         the strategy's own dict, saved with s.save_state()
- s.resume()      "fresh" or "continue", from the strategy's Start mode
                  setting: New sets saved state aside, Old continues it as is
- s.order(...)    places an order, waits for its outcome, records it, and stops
                  the run if it is rejected or its outcome cannot be confirmed
- s.read(...)     a read-only SDK call with short retries on network errors
- s.subscribe()   live prices from the shared feed; s.ltp(), s.ltp_age()
- s.watch_feed()  stops the run if the market feed goes silent in session
- s.sleep(n)      waits, runs the feed watch, False once a stop is requested
- s.stop(reason)  ends the run cleanly with a reason
- s.run(main)     turns every outcome into an exit code the host understands

Exit codes (the host reads them):

    0  main returned, or the host asked the strategy to stop
    3  the strategy stopped itself with a reason (s.stop, an order failure,
       a failed read, the feed watch, an invalid setting)
    4  the strategy's own code raised an exception

Codes 3 and 4 print one line starting with "FATAL: " carrying the reason; the
host shows that line on the strategy card.

Public names in this module are a contract with installed strategies: later
versions add to it and never rename or change meaning.

This file runs inside strategy processes, never inside the server, so it
writes to stdout (the run log) rather than the platform logger.
"""

import json
import os
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

__all__ = [
    "EXIT_CODE_ERROR",
    "EXIT_CODE_OK",
    "EXIT_CODE_STOPPED",
    "Fill",
    "Strategy",
    "StrategyStop",
    "check_params_schema",
    "coerce_param",
    "net_positions",
    "validate_params",
]

KIT_VERSION = "1.0.0"

EXIT_CODE_OK = 0
EXIT_CODE_STOPPED = 3
EXIT_CODE_ERROR = 4

IST = timezone(timedelta(hours=5, minutes=30))

PARAM_TYPES = ("int", "float", "str", "bool", "choice")
_PARAM_KEYS = {"type", "default", "min", "max", "options", "label", "help"}

_TERMINAL_STATUSES = {"complete", "rejected", "cancelled"}
_RETRYABLE_ERRORS = {"connection_error", "timeout_error"}
_READ_RETRY_DELAYS = (1.5, 3.0)


class StrategyStop(Exception):
    """A deliberate, clean stop. The message is shown to the user as the reason."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = str(reason)


@dataclass(frozen=True)
class Fill:
    """The outcome of a filled order."""

    order_id: str
    symbol: str
    exchange: str
    action: str
    quantity: int
    average_price: float
    product: str


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def check_params_schema(schema):
    """Return a list of problems with a PARAMS declaration; empty when valid."""
    if schema is None:
        return []
    if not isinstance(schema, dict):
        return ["PARAMS must be a dictionary"]
    problems = []
    for name, spec in schema.items():
        if not isinstance(name, str) or not name.isidentifier():
            problems.append(f"Setting name {name!r} must be a plain word")
            continue
        if not isinstance(spec, dict):
            problems.append(f"Setting {name!r} must be a dictionary")
            continue
        unknown = set(spec) - _PARAM_KEYS
        if unknown:
            problems.append(f"Setting {name!r} has unknown keys: {', '.join(sorted(unknown))}")
        kind = spec.get("type")
        if kind not in PARAM_TYPES:
            problems.append(f"Setting {name!r} needs a type: one of {', '.join(PARAM_TYPES)}")
            continue
        if kind == "choice":
            options = spec.get("options")
            if not isinstance(options, list) or not options:
                problems.append(f"Setting {name!r} is a choice and needs a list of options")
                continue
        if "default" not in spec:
            problems.append(f"Setting {name!r} needs a default")
            continue
        _, error = _coerce(name, spec, spec["default"])
        if error:
            problems.append(f"Default for {error}")
    return problems


def _coerce(name, spec, value):
    """Convert one value to its declared type. Returns (value, error)."""
    kind = spec["type"]
    label = spec.get("label") or name
    try:
        if kind == "bool":
            if isinstance(value, bool):
                result = value
            elif isinstance(value, str) and value.strip().lower() in ("true", "false"):
                result = value.strip().lower() == "true"
            else:
                return None, f"{label} must be on or off"
        elif kind == "int":
            if isinstance(value, bool):
                raise ValueError
            number = float(value)
            if number != int(number):
                raise ValueError
            result = int(number)
        elif kind == "float":
            if isinstance(value, bool):
                raise ValueError
            result = float(value)
        elif kind == "choice":
            if value not in spec["options"]:
                return None, f"{label} must be one of: {', '.join(map(str, spec['options']))}"
            result = value
        else:
            if not isinstance(value, str):
                raise ValueError
            result = value.strip()
    except (TypeError, ValueError):
        return (
            None,
            f"{label} must be {'a whole number' if kind == 'int' else 'a number' if kind == 'float' else 'text'}",
        )
    if kind in ("int", "float"):
        if spec.get("min") is not None and result < spec["min"]:
            return None, f"{label} must be at least {spec['min']}"
        if spec.get("max") is not None and result > spec["max"]:
            return None, f"{label} must be at most {spec['max']}"
    return result, None


def coerce_param(name, spec, value):
    """Convert one setting value to its declared type. Returns (value, error)."""
    return _coerce(name, spec, value)


def validate_params(schema, values):
    """Merge saved values over the declared defaults.

    Returns (params, errors). Values for names the schema no longer declares
    are ignored, so renaming a setting in the script never breaks a start.
    """
    schema = schema or {}
    values = values or {}
    params, errors = {}, []
    for name, spec in schema.items():
        raw = values.get(name, spec.get("default"))
        value, error = _coerce(name, spec, raw)
        if error:
            errors.append(error)
        else:
            params[name] = value
    return params, errors


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _ok(response):
    return isinstance(response, dict) and response.get("status") == "success"


def _message(response):
    if isinstance(response, dict):
        return str(response.get("message") or response.get("error") or "no details given")
    return "no answer"


def _qty(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _key(symbol, exchange, product):
    return f"{exchange.upper()}:{symbol.upper()}:{product.upper()}"


def _today():
    return datetime.now(IST).date().isoformat()


def net_positions(fills):
    """Net signed quantity per "EXCHANGE:SYMBOL:PRODUCT" from recorded fills (BUY positive)."""
    net = {}
    for fill in fills:
        key = _key(fill["symbol"], fill["exchange"], fill["product"])
        signed = fill["quantity"] if fill["action"] == "BUY" else -fill["quantity"]
        net[key] = net.get(key, 0) + signed
    return net


# ---------------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------------


class Strategy:
    """One run of a strategy. Create it with the script's PARAMS, then call run(main)."""

    def __init__(
        self,
        params_schema=None,
        *,
        client=None,
        strategy_id=None,
        name=None,
        state_dir=None,
        product="MIS",
        order_timeout=15.0,
    ):
        self.schema = params_schema or {}
        self.strategy_id = (
            strategy_id or os.getenv("STRATEGY_ID") or Path(sys.argv[0]).stem or "strategy"
        )
        self.name = name or os.getenv("STRATEGY_NAME") or self.strategy_id
        self.default_product = product
        self.order_timeout = order_timeout
        self.params = {}
        self.state = {}
        self.client = client
        self._state_dir = Path(
            state_dir or os.getenv("OPENALGO_STRATEGY_STATE_DIR") or Path("strategies") / "state"
        )
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._prices = {}  # "EXCHANGE:SYMBOL" -> (ltp, monotonic arrival)
        self._order_updates = {}  # order id -> latest order_update message
        self._feed_connected = False
        self._orders_subscribed = False
        self._user_tick = None
        self._watch = None
        self._link_down_since = None
        self._last_watch_check = 0.0
        self._session = None  # (start_ms, end_ms) or None when closed

    # -- lifecycle ----------------------------------------------------------

    def run(self, main):
        """Run main(self) and exit the process with the matching code."""
        code = EXIT_CODE_OK
        try:
            if threading.current_thread() is threading.main_thread():
                signal.signal(signal.SIGTERM, lambda *_: self._stop_requested.set())
            self._setup()
            main(self)
        except StrategyStop as stop:
            self.log(f"FATAL: {stop.reason}")
            code = EXIT_CODE_STOPPED
        except KeyboardInterrupt:
            code = EXIT_CODE_OK
        except SystemExit:
            self._shutdown()
            raise
        except Exception as exc:
            self.log(f"FATAL: {type(exc).__name__}: {exc}")
            sys.__excepthook__(*sys.exc_info())
            code = EXIT_CODE_ERROR
        self._shutdown()
        if code == EXIT_CODE_OK:
            self.log("Strategy finished.")
        sys.stdout.flush()
        sys.exit(code)

    def _setup(self):
        problems = check_params_schema(self.schema)
        if problems:
            raise StrategyStop(
                "The strategy's PARAMS declaration is invalid: " + "; ".join(problems)
            )
        params, errors = validate_params(self.schema, self._saved_values())
        if errors:
            raise StrategyStop(
                "Invalid setting: " + "; ".join(errors) + ". Fix it in the strategy settings."
            )
        self.params = params

        if self.client is None:
            api_key = os.getenv("OPENALGO_API_KEY", "")
            if not api_key:
                raise StrategyStop(
                    "No API key was given to this strategy. Generate one on the API Key page, "
                    "then start the strategy from the Python Strategies page."
                )
            from openalgo import api

            host = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
            ws_url = os.getenv("WEBSOCKET_URL") or (
                f"ws://{os.getenv('WEBSOCKET_HOST', '127.0.0.1')}:{os.getenv('WEBSOCKET_PORT', '8765')}"
            )
            self.client = api(api_key=api_key, host=host, ws_url=ws_url)

        self.state = self._load_state()
        self.log(f"{self.name} starting (kit {KIT_VERSION})")
        if self.params:
            self.log("Settings: " + ", ".join(f"{k}={v}" for k, v in self.params.items()))

    def _saved_values(self):
        raw = os.getenv("OPENALGO_STRATEGY_PARAMS", "")
        if not raw:
            return {}
        try:
            values = json.loads(raw)
        except json.JSONDecodeError:
            raise StrategyStop(
                "The saved strategy settings could not be read. Save them again."
            ) from None
        return values if isinstance(values, dict) else {}

    def _shutdown(self):
        if self._feed_connected and self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
            self._feed_connected = False

    def stop(self, reason):
        """End the run cleanly. The reason is shown on the strategy card."""
        raise StrategyStop(reason)

    @property
    def stop_requested(self):
        """True once the host has asked the strategy to stop."""
        return self._stop_requested.is_set()

    def sleep(self, seconds):
        """Wait, watching the feed. Returns False once a stop has been requested."""
        deadline = time.monotonic() + max(0.0, seconds)
        while not self._stop_requested.is_set():
            self._check_feed()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._stop_requested.wait(min(0.2, remaining))
        return not self._stop_requested.is_set()

    def log(self, message):
        print(f"[{datetime.now(IST):%H:%M:%S}] {message}", flush=True)

    # -- reads --------------------------------------------------------------

    def read(self, method, *args, what=None, **kwargs):
        """Call a read-only SDK method, retrying network errors briefly.

        Returns the successful response. Stops the run when the server answers
        with an error, or when every try fails to reach it. Never use this for
        orders: an order that timed out may still have reached the broker.
        """
        label = what or getattr(method, "__name__", "request")
        response = None
        for attempt in range(len(_READ_RETRY_DELAYS) + 1):
            response = method(*args, **kwargs)
            if _ok(response):
                return response
            if (
                not isinstance(response, dict)
                or response.get("error_type") not in _RETRYABLE_ERRORS
            ):
                break
            if attempt < len(_READ_RETRY_DELAYS):
                time.sleep(_READ_RETRY_DELAYS[attempt])
        raise StrategyStop(f"Could not get {label}: {_message(response)}")

    def positions(self):
        """Net quantity per "EXCHANGE:SYMBOL:PRODUCT" from the broker's position book."""
        response = self.read(self.client.positionbook, what="the position book")
        book = {}
        for row in response.get("data") or []:
            symbol, exchange, product = row.get("symbol"), row.get("exchange"), row.get("product")
            if symbol and exchange and product:
                key = _key(symbol, exchange, product)
                book[key] = book.get(key, 0) + _qty(row.get("quantity"))
        return book

    # -- saved state --------------------------------------------------------

    @property
    def state_path(self):
        return self._state_dir / f"{self.strategy_id}.json"

    def _load_state(self):
        path = self.state_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise StrategyStop(
                f"The saved state file {path.name} is damaged. Check the positions at the broker, "
                "then clear saved state in the strategy settings."
            ) from None
        return data if isinstance(data, dict) else {}

    def save_state(self):
        """Write s.state to disk atomically, so a power cut never leaves half a file."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_path
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _kit(self):
        kit = self.state.setdefault("_kit", {})
        kit.setdefault("pending", {})
        kit.setdefault("fills", [])
        kit["date"] = _today()  # the last day the strategy used this state
        return kit

    def open_positions(self):
        """Net quantity per "EXCHANGE:SYMBOL:PRODUCT" implied by the recorded fills (non-zero only).

        Fills are kept until a New start sets the state aside, so positions
        carried over to another day with Old are still known.
        """
        kit = self.state.get("_kit") or {}
        net = self._net(kit.get("fills") or [])
        return {k: v for k, v in net.items() if v}

    @staticmethod
    def _net(fills):
        return net_positions(fills)

    def resume(self, mode=None):
        """Start fresh or continue the saved state, as the user chose.

        ``mode`` is "new" or "old"; without it, the strategy's ``start_mode``
        setting decides, and "new" when it has none.

        "new"  Any saved state is set aside (renamed, never deleted) and the run
               starts empty. Returns "fresh".
        "old"  The saved state is continued exactly as it is. Nothing is checked
               against the broker: the user is responsible for the saved state
               matching their positions. Returns "continue", or "fresh" when
               there is no saved state to continue.
        """
        mode = str(mode or self.params.get("start_mode") or "new").lower()
        if mode not in ("new", "old"):
            raise StrategyStop(f"Start mode must be new or old, not {mode}.")
        saved = bool(self.state)

        if mode == "new":
            set_aside = (
                self._archive_state(f"set-aside-{datetime.now(IST):%Y%m%d-%H%M%S}")
                if saved
                else None
            )
            self.state = {}
            self._kit()
            self.save_state()
            self.log(
                "Starting in NEW mode: fresh start"
                + (
                    f". The previous saved state was set aside as {set_aside}."
                    if set_aside
                    else ", no saved state."
                )
            )
            return "fresh"

        if not saved:
            self.state = {}
            self._kit()
            self.save_state()
            self.log("Starting in OLD mode, but there is no saved state: fresh start.")
            return "fresh"

        kit = self.state.get("_kit") or {}
        last_used = kit.get("date") or "an unknown day"
        for record in (kit.get("pending") or {}).values():
            self.log(
                f"WARNING: an order for {record.get('symbol', '?')} was in flight when the last run "
                "ended, so its outcome is unknown. It is treated as not filled; check the order book."
            )
        if kit.get("pending"):
            kit["pending"] = {}
        recorded = kit.get("mode")
        current = self._mode()
        if recorded and recorded != current:
            self.log(
                f"WARNING: the saved orders were placed in {recorded} mode, and the platform is now "
                f"in {current} mode."
            )
            # From here on, a switch during this run still stops it (see order()).
            kit["mode"] = current
        held = self.open_positions()
        self._kit()
        self.save_state()
        self.log(
            f"Starting in OLD mode: continuing the saved state last used on {last_used}. "
            + (
                "Open: " + ", ".join(f"{k} {v}" for k, v in held.items())
                if held
                else "No open positions."
            )
        )
        return "continue"

    def _archive_state(self, label):
        """Rename the saved state aside. Returns the new file name, or None."""
        path = self.state_path
        if path.exists():
            target = path.with_name(f"{self.strategy_id}.{label}.json")
            try:
                os.replace(path, target)
                return target.name
            except OSError:
                pass
        return None

    # -- orders -------------------------------------------------------------

    def _mode(self):
        response = self.read(self.client.analyzerstatus, what="the trading mode")
        return "analyze" if (response.get("data") or {}).get("analyze_mode") else "live"

    def order(
        self,
        symbol,
        exchange,
        action,
        quantity,
        price_type="MARKET",
        price=None,
        trigger_price=None,
        product=None,
        timeout=None,
    ):
        """Place an order and wait until it is filled.

        Returns a Fill. Stops the run when the order is refused, rejected or
        cancelled, when it is still open after the timeout, or when the result
        of placing it is unclear. A pending record is saved before the order is
        sent, so a crash in between is caught by the next resume().
        """
        action = action.upper()
        product = (product or self.default_product).upper()
        quantity = int(quantity)
        if action not in ("BUY", "SELL"):
            raise StrategyStop(f"Order action must be BUY or SELL, not {action}")
        if quantity <= 0:
            raise StrategyStop(f"Order quantity for {symbol} must be positive, not {quantity}")

        kit = self._kit()
        mode = self._mode()
        if kit.get("mode") and kit["mode"] != mode:
            raise StrategyStop(
                f"The platform switched from {kit['mode']} to {mode} mode during this run. "
                f"No order was placed for {symbol}."
            )
        kit["mode"] = mode
        self._ensure_order_stream()

        ref = uuid.uuid4().hex
        kit["pending"][ref] = {
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "product": product,
            "sent_at": datetime.now(IST).isoformat(),
        }
        self.save_state()

        extra = {}
        if price is not None:
            extra["price"] = price
        if trigger_price is not None:
            extra["trigger_price"] = trigger_price
        response = self.client.placeorder(
            strategy=self.name,
            symbol=symbol,
            action=action,
            exchange=exchange,
            price_type=price_type,
            product=product,
            quantity=quantity,
            **extra,
        )
        if not _ok(response):
            if self._definitely_refused(response):
                kit["pending"].pop(ref, None)
                self.save_state()
                raise StrategyStop(
                    f"{action} {quantity} {symbol} was refused: {_message(response)}"
                )
            raise StrategyStop(
                f"Could not confirm whether {action} {quantity} {symbol} reached the broker "
                f"({_message(response)}). Check the order book before starting again."
            )

        order_id = str(response.get("orderid"))
        kit["pending"][ref]["order_id"] = order_id
        self.save_state()
        self.log(f"Order sent: {action} {quantity} {symbol} {product} {price_type} -> {order_id}")

        status, filled, avg, reason = self._wait_for_outcome(
            order_id, quantity, timeout or self.order_timeout
        )
        if status is None:
            raise StrategyStop(
                f"Order {order_id} ({action} {quantity} {symbol}) had no final status after "
                f"{timeout or self.order_timeout:.0f}s. Check the order book before starting again."
            )

        kit["pending"].pop(ref, None)
        fill = None
        if filled > 0:
            kit["fills"].append(
                {
                    "order_id": order_id,
                    "symbol": symbol,
                    "exchange": exchange,
                    "action": action,
                    "quantity": filled,
                    "average_price": avg,
                    "product": product,
                    "time": datetime.now(IST).isoformat(),
                }
            )
            fill = Fill(order_id, symbol, exchange, action, filled, avg, product)
        self.save_state()

        if status != "complete":
            done = f" after {filled} of {quantity} filled" if filled else ""
            raise StrategyStop(
                f"{action} {quantity} {symbol} was {status}{done}"
                + (f": {reason}" if reason else "")
                + "."
            )
        self.log(f"Filled: {action} {filled} {symbol} @ {avg}")
        return fill

    @staticmethod
    def _definitely_refused(response):
        """True when the server answered and said no, so the order never reached the broker.

        A network error, a timeout or a server-side failure (5xx) leaves the
        outcome unknown: the order may have been sent before the error.
        """
        if not isinstance(response, dict):
            return False
        if response.get("error_type") == "api_error":
            return True
        return (
            response.get("error_type") == "http_error" and 400 <= _qty(response.get("code")) < 500
        )

    def _wait_for_outcome(self, order_id, quantity, timeout):
        """Return (status, filled, average_price, reason); status None on timeout."""
        deadline = time.monotonic() + timeout
        next_poll = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with self._lock:
                update = self._order_updates.get(order_id)
            if update and str(update.get("order_status", "")).lower() in _TERMINAL_STATUSES:
                status = str(update["order_status"]).lower()
                filled = _qty(update.get("filled_quantity"))
                if status == "complete" and not filled:
                    filled = quantity
                return (
                    status,
                    filled,
                    float(update.get("average_price") or 0),
                    update.get("rejection_reason") or "",
                )
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + 1.0
                response = self.client.orderstatus(order_id=order_id, strategy=self.name)
                if _ok(response):
                    data = response.get("data") or {}
                    status = str(data.get("order_status", "")).lower()
                    if status in _TERMINAL_STATUSES:
                        filled = _qty(data.get("filled_quantity")) or (
                            quantity if status == "complete" else 0
                        )
                        reason = data.get("rejection_reason") or data.get("rejectreason") or ""
                        return status, filled, float(data.get("average_price") or 0), reason
            time.sleep(0.1)
        return None, 0, 0.0, ""

    # -- live prices --------------------------------------------------------

    def _ensure_connected(self):
        if self._feed_connected:
            return
        if not self.client.connect():
            raise StrategyStop("Could not connect to the platform's market feed.")
        self._feed_connected = True

    def _ensure_order_stream(self):
        if self._orders_subscribed:
            return
        try:
            self._ensure_connected()
            self._orders_subscribed = bool(
                self.client.subscribe_orders(on_order_update=self._on_order)
            )
        except StrategyStop:
            # Order outcomes are still confirmed by polling order status.
            self.log("Order update stream unavailable; confirming orders by polling")

    def _on_order(self, message):
        order_id = message.get("orderid")
        if order_id:
            with self._lock:
                self._order_updates[str(order_id)] = message

    def _on_tick(self, message):
        try:
            key = f"{message['exchange']}:{message['symbol']}"
            ltp = float(message["data"]["ltp"])
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            self._prices[key] = (ltp, time.monotonic())
        if self._user_tick is not None:
            self._user_tick(message)

    def subscribe(self, instruments, on_tick=None):
        """Subscribe to live prices, as [{"exchange": "NFO", "symbol": "..."}] or ("NFO", "...") pairs.

        on_tick, if given, runs on the feed thread for every tick: keep it short.
        """
        items = [
            i if isinstance(i, dict) else {"exchange": i[0], "symbol": i[1]} for i in instruments
        ]
        if on_tick is not None:
            self._user_tick = on_tick
        self._ensure_connected()
        if not self.client.subscribe_ltp(items, on_data_received=self._on_tick):
            raise StrategyStop(
                "Could not subscribe to prices for "
                + ", ".join(f"{i['exchange']}:{i['symbol']}" for i in items)
            )

    def ltp(self, exchange, symbol):
        """Latest price received for a symbol, or None if none has arrived yet."""
        with self._lock:
            entry = self._prices.get(f"{exchange}:{symbol}")
        return entry[0] if entry else None

    def ltp_age(self, exchange, symbol):
        """Seconds since the latest price arrived, or None if none has arrived yet."""
        with self._lock:
            entry = self._prices.get(f"{exchange}:{symbol}")
        return time.monotonic() - entry[1] if entry else None

    def watch_feed(
        self,
        heartbeat=("NSE_INDEX", "NIFTY"),
        max_silence=20,
        max_link_down=30,
        session_exchange="NSE",
    ):
        """Stop the run if the market feed fails during the exchange session.

        Trips when the link to the platform has been down for max_link_down
        seconds, or the heartbeat symbol (an index that ticks every second in
        session) has been silent for max_silence seconds. Outside the session,
        and on holidays, it does nothing. Checked from s.sleep().
        """
        self._watch = {
            "heartbeat": heartbeat,
            "max_silence": max_silence,
            "max_link_down": max_link_down,
            "since": time.monotonic(),
        }
        self._session = self._session_window(session_exchange)
        self.subscribe([heartbeat])

    def _session_window(self, exchange):
        response = self.read(self.client.timings, date=_today(), what="today's market timings")
        for row in response.get("data") or []:
            if str(row.get("exchange", "")).upper() == exchange.upper():
                return int(row["start_time"]), int(row["end_time"])
        return None

    def _check_feed(self):
        if self._watch is None or time.monotonic() - self._last_watch_check < 1.0:
            return
        self._last_watch_check = time.monotonic()
        if self._session is None:
            return
        now_ms = time.time() * 1000
        start_ms, end_ms = self._session
        if not (start_ms <= now_ms <= end_ms):
            self._link_down_since = None
            return

        if not getattr(self.client, "authenticated", True):
            self._link_down_since = self._link_down_since or time.monotonic()
            down = time.monotonic() - self._link_down_since
            if down >= self._watch["max_link_down"]:
                raise StrategyStop(
                    f"Lost the connection to the platform's market feed for {down:.0f}s."
                )
            return
        self._link_down_since = None

        exchange, symbol = self._watch["heartbeat"]
        age = self.ltp_age(exchange, symbol)
        session_age = (now_ms - start_ms) / 1000
        silent = (
            age if age is not None else min(time.monotonic() - self._watch["since"], session_age)
        )
        if silent >= self._watch["max_silence"]:
            raise StrategyStop(
                f"No {symbol} prices for {silent:.0f}s during market hours: the broker feed looks down."
            )
