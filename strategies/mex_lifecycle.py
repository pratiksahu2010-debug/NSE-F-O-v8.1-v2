"""Persistent Momentum Explosion lifecycle (audit section C).

    IDLE -> CANDIDATE -> CONFIRMED -> EXPIRED / INVALIDATED

* CANDIDATE: an explosion was detected on a closed 5m candle. Its high/low become the breakout levels.
* This persisted lifecycle governs the optional closed-bar continuation filter only.
* Live intrabar alerts are validated independently by engine.live_intrabar and do not wait for this lifecycle.
* INVALIDATED: a close back through the opposite extreme (CANDIDATE) or the detection midpoint (CONFIRMED).
* EXPIRED: no confirmation within MEX_CANDIDATE_MAX_BARS, or CONFIRMED for longer than MEX_CONFIRMED_MAX_BARS.

State is per underlying, advances only on new candles (idempotent within one candle) and is persisted through
the DB key-value store, so a restart does not reset an in-progress explosion.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from config import cfg

log = logging.getLogger("mex")

IDLE, CANDIDATE, CONFIRMED, EXPIRED, INVALIDATED = "IDLE", "CANDIDATE", "CONFIRMED", "EXPIRED", "INVALIDATED"
KV_KEY = "mex_lifecycle_v1"


class MexLifecycle:
    def __init__(self, db=None):
        self.db = db
        self.states: dict = {}
        try:
            raw = db.kv_get(KV_KEY) if db is not None else None
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    self.states = parsed
        except Exception:
            log.exception("mex lifecycle restore failed")

    def _persist(self):
        if self.db is None:
            return
        try:
            self.db.kv_set(KV_KEY, json.dumps(self.states))
        except Exception:
            log.exception("mex lifecycle persist failed")

    def state(self, und: str) -> dict:
        return self.states.get(und, {"state": IDLE, "sgn": 0})

    def confirmed(self, und: str, sgn: int) -> bool:
        s = self.state(und)
        return s.get("state") == CONFIRMED and s.get("sgn") == sgn

    def observe(self, und: str, detected_sgn: Optional[int], bar, detected_score: Optional[float] = None, detected_reason: str = "") -> str:
        """Advance one underlying using its last closed 5m candle `bar` (needs .ts .h .l .c).
        `detected_sgn` is +1/-1 when a Momentum Explosion was detected on this candle, else None."""
        if not cfg.MEX_LIFECYCLE_ENABLED:
            return IDLE if detected_sgn is None else CONFIRMED
        bar_key = bar.ts.isoformat()
        cur = self.state(und)
        st = cur.get("state", IDLE)
        if st in (CANDIDATE, CONFIRMED):
            if cur.get("bar") == bar_key:
                return st                                   # same candle: nothing advances
            # Lifecycle confirmation is valid only on the immediately next 5m
            # candle in the same session; a missing bar must expire the setup.
            try:
                previous_bar = datetime.fromisoformat(str(cur.get("bar", "")))
                current_bar = bar.ts
                contiguous = (previous_bar.date() == current_bar.date()
                              and (current_bar - previous_bar).total_seconds() == 300)
            except (TypeError, ValueError, OverflowError):
                contiguous = False
            if not contiguous:
                cur.update({"state": EXPIRED, "bar": bar_key,
                            "expiry_reason": "candidate lifecycle candle gap or session change"})
                self.states[und] = cur
                self._persist()
                return EXPIRED
            cur = dict(cur, bars=cur.get("bars", 0) + 1, bar=bar_key,
                       setup_bar=cur.get("setup_bar") or cur.get("bar"))
            sgn, hi, lo = cur["sgn"], cur["hi"], cur["lo"]
            mid = (hi + lo) / 2.0
            if st == CANDIDATE:
                if (sgn > 0 and bar.c < lo) or (sgn < 0 and bar.c > hi):
                    st = INVALIDATED
                elif cur["bars"] > cfg.MEX_CANDIDATE_MAX_BARS:
                    # Expire before testing for confirmation: a late breakout must not
                    # revive a candidate after its confirmation window has elapsed.
                    st = EXPIRED
                elif (sgn > 0 and bar.c > hi) or (sgn < 0 and bar.c < lo):
                    st = CONFIRMED
                    cur["bars"] = 0
                    cur["confirmed_bar"] = bar_key
            else:
                if (sgn > 0 and bar.c < mid) or (sgn < 0 and bar.c > mid):
                    st = INVALIDATED
                elif cur["bars"] > cfg.MEX_CONFIRMED_MAX_BARS:
                    st = EXPIRED
            cur["state"] = st
            self.states[und] = cur
            self._persist()
            return st
        # IDLE / EXPIRED / INVALIDATED: a fresh detection starts a new candidate.
        if detected_sgn in (1, -1):
            self.states[und] = {"state": CANDIDATE, "sgn": detected_sgn, "hi": float(bar.h), "lo": float(bar.l),
                                "bars": 0, "bar": bar_key, "setup_bar": bar_key,
                                "score": float(detected_score or 0.0),
                                "reason": str(detected_reason or "Momentum Explosion detected")}
            self._persist()
            return CANDIDATE
        if st != IDLE:
            self.states[und] = {"state": IDLE, "sgn": 0, "bar": bar_key}
            self._persist()
        return IDLE
