"""Side-effect-free orchestration for the new signal engine.

The caller owns feed polling, database persistence and Telegram dispatch.
There is deliberately no broker/order-routing integration in this package.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional, Sequence

from .adapter import build_snapshot
from .config import EngineConfig
from .models import DecisionState, SignalDecision
from .pipeline import SignalPipeline
from .risk_gate import RiskContext, RiskLimits, limits_from_legacy_config, validate_daily_risk
from .strategies import default_strategies
from .contracts import ContractPolicy, select_validated_contract
from .signal_builder import build_signal
from engine.chain_quality import chain_quality_issues


def create_engine(strategies: Optional[Sequence] = None,
                  config: Optional[EngineConfig] = None) -> SignalPipeline:
    return SignalPipeline(strategies or default_strategies(), config or EngineConfig())


def evaluate_snapshot(engine: SignalPipeline, snapshot,
                      risk_context: Optional[RiskContext] = None,
                      risk_limits: Optional[RiskLimits] = None) -> list[SignalDecision]:
    decisions = engine.evaluate(snapshot)
    if risk_context is None:
        return decisions
    result = []
    limits = risk_limits or limits_from_legacy_config()
    for decision in decisions:
        if decision.state is DecisionState.REJECTED:
            result.append(decision)
            continue
        allowed, reason = validate_daily_risk(decision.candidate, risk_context, limits)
        if allowed:
            result.append(decision)
        else:
            engine.release(decision)
            result.append(replace(decision, state=DecisionState.REJECTED,
                                  rejected_reasons=(reason,)))
    return result


def evaluate_legacy_candles(engine: SignalPipeline, underlying: str,
                            instrument_kind: str, timeframe: str,
                            candles, live_candle=None,
                            futures_volume_by_timestamp=None,
                            metadata=None, risk_context=None,
                            risk_limits=None) -> list[SignalDecision]:
    snapshot = build_snapshot(
        underlying, instrument_kind, timeframe, candles,
        live_candle=live_candle,
        futures_volume_by_timestamp=futures_volume_by_timestamp,
        metadata=metadata,
    )
    return evaluate_snapshot(engine, snapshot, risk_context, risk_limits)


def build_option_signal(candidate, master, underlying, chain, now,
                        atr_value: float, current_underlying_price: float,
                        provider: str = "", iv_rank=None, fut_price: float = 0.0,
                        policy: Optional[ContractPolicy] = None):
    """Validate chain, select an executable contract and build a Signal record.

    The returned Signal is ready for the existing DB/tracker/outbox layer. The
    caller remains responsible for persistence and Telegram dispatch.
    """
    issues = chain_quality_issues(chain, current_underlying_price, candidate.side.value)
    if issues:
        return None, "chain_quality:" + ",".join(issues)
    selection, reason = select_validated_contract(
        master, underlying, candidate.side.value, chain, now,
        iv_rank=iv_rank, policy=policy,
    )
    if selection is None:
        return None, "contract_selection:" + str(reason)
    return build_signal(
        candidate, selection, chain, now, atr_value,
        current_underlying_price, provider=provider, iv_rank=iv_rank,
        fut_price=fut_price, min_target_rr=1.5,
    )
