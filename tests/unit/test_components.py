import asyncio
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from alpaca.common.exceptions import APIError
from cryptography.fernet import Fernet

from atp.brokers.alpaca import AlpacaBroker
from atp.brokers.base import (
    BrokerAuthError,
    BrokerRejected,
    BrokerTransientError,
    DuplicateClientOrderId,
    LiveTradingRefused,
    OrderRequest,
    with_retry,
)
from atp.brokers.paper import PaperExchange
from atp.clock import SimClock
from atp.config import Settings
from atp.crypto import CredentialsError, decrypt_credentials, encrypt_credentials
from atp.db.models import PaperOrder
from atp.marketdata.alpaca import BarAggregator
from atp.marketdata.base import in_regular_session
from atp.marketdata.synthetic import synth_day
from atp.schema.messages import Bar, WakeJob
from atp.worker.ai import build_request, parse_verdict, request_hash
from atp.schema.agent import AIFilter

T0 = datetime(2026, 10, 14, 13, 30, tzinfo=UTC)


def bar(ts: datetime, o: str, h: str, lo: str, c: str, symbol: str = "SPY", tf: str = "5Min") -> Bar:
    return Bar(symbol=symbol, timeframe=tf, ts=ts, open=Decimal(o), high=Decimal(h), low=Decimal(lo),
               close=Decimal(c), volume=Decimal(100))


# --- clock ---

async def test_simclock_as_fast_as_possible() -> None:
    c = SimClock(T0, speed=None)
    started = time.monotonic()
    await c.sleep_until(T0 + timedelta(hours=6))
    assert c.now() == T0 + timedelta(hours=6) and time.monotonic() - started < 0.05


async def test_simclock_speed_paces_wall_time() -> None:
    c = SimClock(T0, speed=600)  # 60 s simulated = 0.1 s wall
    started = time.monotonic()
    await c.sleep_until(T0 + timedelta(seconds=60))
    assert 0.08 < time.monotonic() - started < 0.5


def test_simclock_requires_aware_start() -> None:
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 1, 1))


# --- paper fill model ---

def order(side: str, type_: str, limit: str | None = None, stop: str | None = None) -> PaperOrder:
    return PaperOrder(side=side, type=type_, limit_price=Decimal(limit) if limit else None,
                      stop_price=Decimal(stop) if stop else None)


def test_paper_fill_prices() -> None:
    ex = PaperExchange(factory=None, slippage_bps=Decimal(5))  # type: ignore[arg-type]
    b = bar(T0, "100", "101", "99", "100.5")
    assert ex._fill_price(order("buy", "market"), b) == Decimal("100.0500")
    assert ex._fill_price(order("sell", "market"), b) == Decimal("99.9500")
    assert ex._fill_price(order("buy", "limit", limit="99.5"), b) == Decimal("99.5")
    assert ex._fill_price(order("buy", "limit", limit="98"), b) is None
    assert ex._fill_price(order("sell", "limit", limit="100.8"), b) == Decimal("100.8")
    assert ex._fill_price(order("sell", "stop", stop="99.2"), b) == Decimal("99.2")
    gap = bar(T0, "97", "98", "96", "97.5")  # gapped through the stop: fill at the open
    assert ex._fill_price(order("sell", "stop", stop="99.2"), gap) == Decimal("97")
    assert ex._fill_price(order("sell", "stop", stop="95"), gap) is None


# --- market data ---

def test_session_filter() -> None:
    assert in_regular_session(T0)  # 09:30 NY
    assert not in_regular_session(T0 - timedelta(minutes=1))
    assert not in_regular_session(datetime(2026, 10, 14, 20, 0, tzinfo=UTC))


def test_bar_aggregator_rolls_minutes_into_5min() -> None:
    agg = BarAggregator("5Min")
    out: list[Bar] = []
    prices = ["100", "101", "99", "102", "103"]
    for i, p in enumerate(prices):
        out += agg.add(bar(T0 + timedelta(minutes=i), p, p, p, p, tf="1Min"))
    assert len(out) == 1
    b = out[0]
    assert (b.ts, b.open, b.high, b.low, b.close, b.volume) == (T0, 100, 103, 99, 103, 500)
    # a missing last minute is flushed when the next bucket starts
    agg.add(bar(T0 + timedelta(minutes=5), "1", "1", "1", "1", tf="1Min"))
    flushed = agg.add(bar(T0 + timedelta(minutes=10), "2", "2", "2", "2", tf="1Min"))
    assert [x.ts for x in flushed] == [T0 + timedelta(minutes=5)]


def test_synthetic_is_deterministic_and_in_session() -> None:
    a = synth_day("SPY", T0.date())
    assert a == synth_day("SPY", T0.date())
    assert len(a) == 78 and all(in_regular_session(b.ts) for b in a)
    assert all(b.low <= min(b.open, b.close) and b.high >= max(b.open, b.close) for b in a)


# --- AI filter helpers ---

def test_verdict_parsing() -> None:
    assert parse_verdict("TAKE: looks fine") == "TAKE"
    assert parse_verdict("skip - too risky") == "SKIP"
    assert parse_verdict("I would TAKE this") == "TAKE"
    assert parse_verdict("TAKE or SKIP? unsure") is None
    assert parse_verdict("") is None


def test_request_hash_stable_and_secret_free() -> None:
    job = WakeJob(instance_id=uuid.uuid4(), agent_id="a", version=1, symbol="SPY",
                  bar=bar(T0, "1", "1", "1", "1"), indicators={"rsi": 25.123456}, recent_closes=["1"],
                  trigger="entry")
    cfg = AIFilter(model="m", prompt="decide")
    r1 = build_request(cfg, job, "m")
    job2 = job.model_copy(update={"instance_id": uuid.uuid4()})
    assert request_hash(r1) == request_hash(build_request(cfg, job2, "m"))  # instance-independent
    blob = str(r1)
    assert "instance" not in blob and "account" not in blob and "key" not in blob.lower()


# --- broker retry and Alpaca adapter ---

async def test_with_retry_recovers_then_gives_up() -> None:
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise BrokerTransientError("503")
        return "ok"

    assert await with_retry(flaky, base_delay=0.001) == "ok" and calls["n"] == 3

    async def down() -> str:
        raise BrokerTransientError("503")

    with pytest.raises(BrokerTransientError):
        await with_retry(down, attempts=2, base_delay=0.001)


def test_alpaca_live_requires_flag_and_live_row() -> None:
    fake = SimpleNamespace()
    with pytest.raises(LiveTradingRefused):
        AlpacaBroker("k", "s", live=True, allow_live_trading=False, account_is_live=True, client=fake)  # type: ignore[arg-type]
    with pytest.raises(LiveTradingRefused):
        AlpacaBroker("k", "s", live=True, allow_live_trading=True, account_is_live=False, client=fake)  # type: ignore[arg-type]
    with pytest.raises(LiveTradingRefused):
        AlpacaBroker("k", "s", live=False, allow_live_trading=True, account_is_live=True, client=fake)  # type: ignore[arg-type]
    b = AlpacaBroker("k", "s", live=True, allow_live_trading=True, account_is_live=True, client=fake)  # type: ignore[arg-type]
    assert b.name == "alpaca_live"


def _api_error(code: int, msg: str = "boom") -> APIError:
    return APIError(f'{{"message": "{msg}"}}', SimpleNamespace(response=SimpleNamespace(status_code=code)))


@pytest.mark.parametrize(
    ("code", "msg", "exc"),
    [(500, "x", BrokerTransientError), (503, "x", BrokerTransientError), (429, "x", BrokerTransientError),
     (401, "x", BrokerAuthError), (403, "x", BrokerAuthError),
     (422, "client_order_id must be unique", DuplicateClientOrderId), (422, "qty", BrokerRejected)],
)
async def test_alpaca_error_mapping(code: int, msg: str, exc: type[Exception]) -> None:
    def submit(_: Any) -> None:
        raise _api_error(code, msg)

    b = AlpacaBroker("k", "s", live=False, allow_live_trading=False, account_is_live=False,
                     client=SimpleNamespace(submit_order=submit))  # type: ignore[arg-type]
    with pytest.raises(exc):
        await b.submit_order(OrderRequest(client_order_id="c", symbol="SPY", side="buy", notional=Decimal(10)))


async def test_alpaca_timeout_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(_: Any) -> None:
        time.sleep(0.3)

    b = AlpacaBroker("k", "s", live=False, allow_live_trading=False, account_is_live=False,
                     client=SimpleNamespace(submit_order=slow))  # type: ignore[arg-type]
    real_wait_for = asyncio.wait_for
    monkeypatch.setattr(asyncio, "wait_for", lambda aw, timeout: real_wait_for(aw, 0.05))
    with pytest.raises(BrokerTransientError):
        await b.submit_order(OrderRequest(client_order_id="c", symbol="SPY", side="buy", notional=Decimal(10)))


def test_order_request_needs_exactly_one_size() -> None:
    with pytest.raises(ValueError):
        OrderRequest(client_order_id="c", symbol="SPY", side="buy")
    with pytest.raises(ValueError):
        OrderRequest(client_order_id="c", symbol="SPY", side="buy", qty=Decimal(1), notional=Decimal(1))


# --- credentials ---

def test_local_credential_roundtrip() -> None:
    s = Settings(local_encryption_key=Fernet.generate_key().decode())  # type: ignore[arg-type]
    blob = encrypt_credentials({"api_key_id": "AK", "api_secret_key": "SK"}, s)
    assert b"SK" not in blob and blob.startswith(b"local:")
    assert decrypt_credentials(blob, s) == {"api_key_id": "AK", "api_secret_key": "SK"}
    with pytest.raises(CredentialsError):
        decrypt_credentials(b"plain", s)
    with pytest.raises(CredentialsError):
        encrypt_credentials({}, Settings(local_encryption_key=""))  # type: ignore[arg-type]
