"""Strike selection for option strategies: the nearest strike, and strikes out of the money.

Shared by every strategy (the host puts ``strategies/lib`` on ``PYTHONPATH``)::

    from option_strikes import option_strike, option_symbol, strike_step

    step = strike_step("NIFTY")                                # 50
    ce = option_strike(24536.4, "CE", offset=1, step=step)     # 24600
    pe = option_strike(24536.4, "PE", offset=1, step=step)     # 24500
    option_symbol("NIFTY", "13NOV26", ce, "CE")                # NIFTY13NOV2624600CE

**The rounding rule** is the one the TinyCompute Node app uses
(``getNearestNiftyStrikePrice``), generalised from 50 to any step:

1. Drop the paise: ``floor(price)``.
2. Within its step, a remainder below half the step rounds down, half or more
   rounds up. For a 50 step: 24,524 -> 24,500 and 24,525 -> 24,550; 24,574 ->
   24,550 and 24,575 -> 24,600.
3. ``offset`` moves out of the money by whole steps: a call up, a put down.
   Offset 0 is the ATM strike for both.

So an exact midpoint (24,525.00) rounds up. The platform's own ``optionsymbol``
picks the lower strike there; use this module where a strategy must match the
Node app strike for strike.

Pure functions, no I/O; tested in ``test/test_option_strikes.py`` against the
original JavaScript.
"""

import math

#: Strike interval of the weekly or nearest-month options per underlying.
#: Exchanges change these; pass ``step=`` to override one.
STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "NIFTYNXT50": 100,
    "SENSEX": 100,
    "BANKEX": 100,
    "SENSEX50": 50,
}


def strike_step(underlying: str) -> float:
    """The strike interval for ``underlying``. Raises ValueError for one not in STRIKE_STEPS."""
    try:
        return STRIKE_STEPS[underlying.upper()]
    except KeyError:
        raise ValueError(
            f"No strike interval is known for {underlying}. Pass step= explicitly."
        ) from None


def nearest_strike(price: float, step: float = 50) -> float:
    """The strike nearest ``price``: paise dropped first, a half step or more rounds up."""
    if step <= 0:
        raise ValueError("step must be positive")
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"not a usable price: {price!r}")
    whole = math.floor(price)
    base = math.floor(whole / step) * step
    remainder = whole - base
    strike = base + step if remainder >= step / 2 else base
    return int(strike) if float(strike).is_integer() else strike


def option_strike(price: float, option_type: str, offset: int = 0, step: float = 50) -> float:
    """The strike to trade: nearest to ``price``, then ``offset`` steps out of the money.

    A call (``"CE"`` or ``"C"``) moves up, a put (``"PE"`` or ``"P"``) moves down.
    """
    kind = option_type.upper()
    if kind not in ("CE", "C", "PE", "P"):
        raise ValueError(f"option_type must be CE or PE, not {option_type!r}")
    if int(offset) != offset or offset < 0:
        raise ValueError("offset must be a whole number of strikes, 0 or more")
    direction = 1 if kind in ("CE", "C") else -1
    strike = nearest_strike(price, step) + direction * int(offset) * step
    return int(strike) if float(strike).is_integer() else strike


def format_strike(strike: float) -> str:
    """24550 -> "24550", 292.5 -> "292.5": the strike as it appears in a symbol."""
    return str(int(strike)) if float(strike).is_integer() else f"{strike:g}"


def option_symbol(underlying: str, expiry: str, strike: float, option_type: str) -> str:
    """The platform's option symbol, ``[Base][DDMMMYY][Strike][CE/PE]``."""
    kind = option_type.upper()
    kind = {"C": "CE", "P": "PE"}.get(kind, kind)
    if kind not in ("CE", "PE"):
        raise ValueError(f"option_type must be CE or PE, not {option_type!r}")
    return f"{underlying.upper()}{expiry.upper()}{format_strike(strike)}{kind}"
