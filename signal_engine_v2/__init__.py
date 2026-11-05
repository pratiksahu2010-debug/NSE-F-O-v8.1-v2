"""Balanced hybrid signal engine, introduced alongside the legacy scanner.

The package is intentionally isolated until integration and regression tests pass.
"""
from .config import EngineConfig
from .models import Candidate, Candle, MarketSnapshot, SignalDecision
from .pipeline import SignalPipeline

__all__ = ["EngineConfig", "Candidate", "Candle", "MarketSnapshot", "SignalDecision", "SignalPipeline"]
