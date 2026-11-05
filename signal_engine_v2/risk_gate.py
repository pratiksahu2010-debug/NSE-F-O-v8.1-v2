"""Central daily and portfolio risk gates for signal publication.

The engine is signal-only. This module controls whether a candidate may be
published; it never creates, modifies or submits a broker order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Mapping, Optional

from config import cfg
from .models import Candidate


@dataclass(frozen=True)
class RiskLimits:
    daily_signal_cap: int = 15
    max_daily_losses: int = 4
    max_active_signals: int = 6
    max_per_correlation_group: int = 3
    symbol_cooldown_minutes: int = 0
    block_same_side_after_loss: bool = True


@dataclass(frozen=True)
class RiskContext:
    now: datetime
    daily_signals: int = 0
    daily_losses: int = 0
    active_signals: int = 0
    active_by_group: Mapping[str, int] = field(default_factory=dict)
    last_signal_at: Mapping[str, datetime] = field(default_factory=dict)
    stopped_out_sides: frozenset[tuple[str, str]] = frozenset()


def correlation_group(symbol: str) -> str:
    name = symbol.upper()
    for group, members in cfg.GROUPS.items():
        if name in {str(x).upper() for x in members}:
            return group
    return name


def validate_daily_risk(candidate: Candidate, context: RiskContext,
                        limits: Optional[RiskLimits] = None) -> tuple[bool, str]:
    limits = limits or RiskLimits()
    if context.daily_losses >= limits.max_daily_losses:
        return False, "daily_loss_circuit_breaker"
    if context.daily_signals >= limits.daily_signal_cap:
        return False, "daily_signal_cap_reached"
    if context.active_signals >= limits.max_active_signals:
        return False, "maximum_active_signals_reached"

    group = correlation_group(candidate.underlying)
    if context.active_by_group.get(group, 0) >= limits.max_per_correlation_group:
        return False, "correlation_group_capacity_reached"

    side_key = (candidate.underlying.upper(), candidate.side.value)
    if limits.block_same_side_after_loss and side_key in context.stopped_out_sides:
        return False, "same_side_blocked_after_stop_loss"

    previous = context.last_signal_at.get(candidate.underlying.upper())
    if previous is not None and limits.symbol_cooldown_minutes > 0:
        if context.now - previous < timedelta(minutes=limits.symbol_cooldown_minutes):
            return False, "symbol_cooldown_active"
    return True, ""


def limits_from_legacy_config() -> RiskLimits:
    """Map the audited production configuration into the v2 risk policy."""
    return RiskLimits(
        daily_signal_cap=int(cfg.DAILY_SIGNAL_CAP),
        max_daily_losses=int(cfg.MAX_DAILY_LOSSES),
        max_active_signals=int(cfg.MAX_ACTIVE),
        max_per_correlation_group=int(cfg.MAX_PER_GROUP),
        symbol_cooldown_minutes=int(cfg.SYMBOL_COOLDOWN_MIN),
        block_same_side_after_loss=bool(cfg.BLOCK_SAME_SIDE_AFTER_LOSS),
    )
