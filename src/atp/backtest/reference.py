"""A deliberately plain reference backtest (pandas), independent of the live pipeline.

Used only by the replay parity test (SPEC §9 #1). It re-implements the same trading
semantics from scratch in one loop: evaluate at each bar's close, fill at the next
bar's open with slippage, guardrails applied in (timestamp, symbol) order. It does not
support the AI filter (parity is checked on the rules-only agent).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

import pandas as pd

from atp.marketdata.base import in_regular_session
from atp.schema.agent import AgentDefinition, Comparison, StopLossPct, TakeProfitPct
from atp.schema.messages import Bar

QTY = Decimal("0.000001")
PX = Decimal("0.0001")


@dataclass
class Trade:
    symbol: str
    side: str
    decided_at: datetime  # bar_ts of the decision
    qty: Decimal
    price: Decimal


def _rsi(closes: pd.Series, period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    d = closes.diff().iloc[1:].to_numpy()
    gain = d.clip(min=0)
    loss = (-d).clip(min=0)
    ag, al = gain[:period].mean(), loss[:period].mean()
    for g, lo in zip(gain[period:], loss[period:], strict=True):
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + lo) / period
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return float(100 - 100 / (1 + ag / al))


def _indicator(kind: str, period: int, closes: pd.Series) -> float | None:
    if kind == "SMA":
        return float(closes.iloc[-period:].mean()) if len(closes) >= period else None
    if kind == "EMA":
        if len(closes) < period:
            return None
        v = float(closes.iloc[:period].mean())
        a = 2 / (period + 1)
        for c in closes.iloc[period:]:
            v = a * float(c) + (1 - a) * v
        return v
    return _rsi(closes, period)


def _cmp(c: Comparison, vals: dict[str, float | None]) -> bool:
    lhs = vals.get(c.lhs) if isinstance(c.lhs, str) else float(c.lhs)
    rhs = vals.get(c.rhs) if isinstance(c.rhs, str) else float(c.rhs)
    if lhs is None or rhs is None:
        return False
    return {
        "<": lhs < rhs,
        "<=": lhs <= rhs,
        ">": lhs > rhs,
        ">=": lhs >= rhs,
        "==": lhs == rhs,
        "!=": lhs != rhs,
    }[c.op]


def run_reference(
    defn: AgentDefinition,
    warmup: list[Bar],
    day: list[Bar],
    slippage_bps: Decimal = Decimal(5),
    starting_cash: Decimal = Decimal(10_000),
    lookback: int = 250,
) -> list[Trade]:
    df = pd.DataFrame(
        [{"symbol": b.symbol, "ts": b.ts, "open": b.open, "close": b.close} for b in [*warmup, *day]]
    ).sort_values(["ts", "symbol"])
    day_ts = {b.ts for b in day}
    slip = slippage_bps / Decimal(10_000)
    step = timedelta(seconds=defn.timeframe_seconds)
    g = defn.guardrails

    cash = starting_cash
    positions: dict[str, tuple[Decimal, Decimal]] = {}  # symbol -> (qty, avg)
    pending: dict[str, tuple[str, datetime]] = {}  # symbol -> (side, decided bar ts)
    realized = Decimal(0)
    trades: list[Trade] = []
    history: dict[str, list[Bar]] = {}
    by_key = {(b.symbol, b.ts): b for b in [*warmup, *day]}

    for _, row in df.iterrows():
        bar = by_key[(row["symbol"], row["ts"])]
        sym = bar.symbol
        history.setdefault(sym, []).append(bar)
        if bar.ts not in day_ts:
            continue
        # fill yesterday's decision at this bar's open
        if sym in pending:
            side, decided = pending.pop(sym)
            if side == "buy":
                price = (bar.open * (1 + slip)).quantize(PX)
                qty = (defn.sizing.usd / price).quantize(QTY, rounding=ROUND_DOWN)
                cash -= qty * price
                positions[sym] = (qty, price)
            else:
                price = (bar.open * (1 - slip)).quantize(PX)
                qty, avg = positions.pop(sym)
                cash += qty * price
                realized += qty * price - qty * avg
            trades.append(Trade(sym, side, decided, qty, price))

        closes = pd.Series([float(b.close) for b in history[sym][-lookback:]])
        vals: dict[str, float | None] = {i.id: _indicator(i.type, i.period, closes) for i in defn.indicators}
        vals.update({"close": float(bar.close), "open": float(bar.open)})
        decide_at = bar.ts + step
        if not in_regular_session(decide_at) or sym in pending:
            continue
        if sym in positions:
            qty, avg = positions[sym]
            chg = (float(bar.close) / float(avg) - 1) * 100
            fire = False
            for c in defn.exit.any:
                if isinstance(c, Comparison):
                    fire |= _cmp(c, vals)
                elif isinstance(c, StopLossPct):
                    fire |= chg <= -c.value
                elif isinstance(c, TakeProfitPct):
                    fire |= chg >= c.value
            if fire:
                pending[sym] = ("sell", bar.ts)
        elif all(_cmp(c, vals) for c in defn.entry.all):
            busy = set(positions) | {s for s, (side, _) in pending.items() if side == "buy"}
            # `realized` covers exactly the one replayed day, matching the daily-loss rule.
            if (
                defn.sizing.usd <= g.max_position_usd
                and len(busy) < g.max_open_positions
                and realized > -g.max_daily_loss_usd
                and defn.sizing.usd <= cash
            ):
                pending[sym] = ("buy", bar.ts)
    return trades
