from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Iterable, Sequence

from .config import EngineConfig
from .models import (Candidate, CandleState, DecisionState, MarketSnapshot,
                     SignalDecision, directional_levels_valid)
from .strategy import Strategy


class SignalPipeline:
    """Collect, validate and select candidates from independent strategies.

    This layer is deliberately side-effect free: it does not place orders,
    fetch data, select option contracts or send alerts.
    """
    def __init__(self, strategies: Sequence[Strategy], config: EngineConfig | None = None):
        self.strategies = tuple(strategies)
        self.config = config or EngineConfig()
        self._emitted: set[str] = set()
        self._lock = RLock()

    def collect(self, snapshot: MarketSnapshot) -> list[Candidate]:
        candidates: list[Candidate] = []
        for strategy in self.strategies:
            try:
                found = strategy.evaluate(snapshot) or ()
                for item in found:
                    if not isinstance(item, Candidate):
                        continue
                    if item.underlying.upper() != snapshot.underlying.upper():
                        continue
                    candidates.append(item)
            except Exception:
                # A broken strategy must not stop other independent strategies.
                continue
        return candidates

    def _reject_reasons(self, c: Candidate, snapshot: MarketSnapshot) -> tuple[str, ...]:
        reasons: list[str] = []
        if not 0 <= c.score <= 100 or c.score < self.config.min_score:
            reasons.append("score_below_minimum")
        if c.age_bars > self.config.max_candidate_age_bars:
            reasons.append("setup_too_old")
        if not directional_levels_valid(c):
            reasons.append("invalid_entry_stop_target_structure")
        if self.config.require_valid_stop and c.risk_reward < self.config.min_risk_reward:
            reasons.append("risk_reward_below_minimum")
        if c.candle_state is CandleState.CLOSED:
            if not snapshot.candle.is_closed:
                reasons.append("closed_candidate_without_closed_snapshot")
            if not self.config.allow_closed_bar_candidates:
                reasons.append("closed_bar_candidates_disabled")
        else:
            if not self.config.allow_intrabar_candidates:
                reasons.append("intrabar_candidates_disabled")
        if self.config.require_closed_htf and c.htf_confirmed and any(not x.is_closed for x in snapshot.htf_candles):
            reasons.append("higher_timeframe_contains_unclosed_candle")
        return tuple(reasons)

    def _rank(self, c: Candidate) -> tuple[float, int, str]:
        # Strategy priority only breaks near-ties; a clearly better setup wins.
        return (c.score, -c.strategy_priority, c.strategy.upper())

    def resolve(self, candidates: Iterable[Candidate], snapshot: MarketSnapshot) -> list[SignalDecision]:
        valid: list[Candidate] = []
        rejected: list[SignalDecision] = []
        for c in candidates:
            reasons = self._reject_reasons(c, snapshot)
            if reasons:
                rejected.append(SignalDecision(c, DecisionState.REJECTED, c.identity, reasons))
            else:
                valid.append(c)

        # One alert per underlying + candle by default. Opposite-side setups
        # compete in the same group and cannot both be published.
        groups: dict[str, list[Candidate]] = defaultdict(list)
        for c in valid:
            key = f"{c.underlying.upper()}|{c.candle_timestamp.isoformat()}"
            groups[key].append(c)

        selected: list[SignalDecision] = []
        for group_key, group in groups.items():
            group.sort(key=self._rank, reverse=True)
            winner = group[0]
            if len(group) > 1:
                runner_up = group[1]
                if winner.side != runner_up.side and winner.score - runner_up.score < self.config.conflict_score_margin:
                    rejected.extend(SignalDecision(x, DecisionState.REJECTED, x.identity,
                                      ("directional_conflict_no_clear_winner",)) for x in group)
                    continue
            state = (DecisionState.CONFIRMED if winner.candle_state is CandleState.CLOSED
                     else DecisionState.EARLY)
            selected.append(SignalDecision(winner, state, group_key))
            rejected.extend(SignalDecision(x, DecisionState.REJECTED, x.identity,
                              ("superseded_by_unified_selector",)) for x in group[1:])

        # Idempotency protects repeated scans of the same candle/setup.
        fresh: list[SignalDecision] = []
        with self._lock:
            for decision in selected:
                dedup_key = decision.decision_key + "|" + decision.state.value
                if dedup_key in self._emitted:
                    continue
                self._emitted.add(dedup_key)
                fresh.append(decision)
        return rejected + fresh

    def evaluate(self, snapshot: MarketSnapshot) -> list[SignalDecision]:
        return self.resolve(self.collect(snapshot), snapshot)
