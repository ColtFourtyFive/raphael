"""Pick the Broker for an instance. This (with Clock and MarketDataSource) is the only
place where replay, paper, and live differ."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp.brokers.alpaca import AlpacaBroker
from atp.brokers.base import Broker
from atp.brokers.paper import PaperBroker
from atp.clock import Clock
from atp.config import get_settings
from atp.crypto import decrypt_credentials
from atp.db.models import BrokerAccount, Instance

PAPER_MODES = frozenset({"replay", "paper"})
_alpaca_cache: dict[str, AlpacaBroker] = {}


def paper_account_ref(instance: Instance) -> str:
    return str(instance.id)


async def broker_for(
    instance: Instance,
    factory: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> Broker:
    if instance.mode in PAPER_MODES:
        return PaperBroker(paper_account_ref(instance), factory, clock)
    key = f"{instance.account_ref}:{instance.mode}"
    if key in _alpaca_cache:
        return _alpaca_cache[key]
    async with factory() as s:
        account = await s.get(BrokerAccount, instance.account_ref)
    if account is None or account.broker != "alpaca":
        raise LookupError(f"instance {instance.id} has no Alpaca account row")
    s_ = get_settings()
    if account.encrypted_credentials:
        creds = decrypt_credentials(account.encrypted_credentials)
        api_key, secret = creds["api_key_id"], creds["api_secret_key"]
    else:
        api_key = s_.alpaca_api_key_id.get_secret_value()
        secret = s_.alpaca_api_secret_key.get_secret_value()
    broker = AlpacaBroker(
        api_key,
        secret,
        live=instance.mode == "alpaca_live",
        allow_live_trading=s_.allow_live_trading,
        account_is_live=account.is_live,
    )
    _alpaca_cache[key] = broker
    return broker
