"""Clocks. Replay, paper, and live differ only by Clock, MarketDataSource, and Broker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep_until(self, when: datetime) -> None: ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep_until(self, when: datetime) -> None:
        delay = (when - self.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)


class SimClock:
    """Simulated time. `speed` is a multiple of real time; `None` means as fast as possible.

    Time only moves forward through `sleep_until` / `advance_to`, so the simulated
    timeline is fully determined by the data being replayed.
    """

    def __init__(self, start: datetime, speed: float | None = None) -> None:
        if start.tzinfo is None:
            raise ValueError("SimClock needs a timezone-aware start")
        if speed is not None and speed <= 0:
            raise ValueError("speed must be positive or None")
        self._now = start
        self.speed = speed
        self._wall_anchor = time.monotonic()
        self._sim_anchor = start

    def now(self) -> datetime:
        return self._now

    def advance_to(self, when: datetime) -> None:
        if when > self._now:
            self._now = when

    async def sleep_until(self, when: datetime) -> None:
        if when <= self._now:
            return
        if self.speed is not None:
            sim_elapsed = (when - self._sim_anchor).total_seconds()
            wall_target = self._wall_anchor + sim_elapsed / self.speed
            delay = wall_target - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
        self._now = when

    def reanchor(self) -> None:
        """Restart pacing from the current sim time (after a pause for pipeline drain)."""
        self._wall_anchor = time.monotonic()
        self._sim_anchor = self._now
