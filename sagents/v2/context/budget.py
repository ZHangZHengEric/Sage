"""Context budget helpers. Reducer implementations live in plugins/."""

from sagents.v2.context.plugins.token_estimators import JsonHeuristicTokenEstimator
from sagents.v2.context.plugins.window import WindowContextReducer

HeuristicTokenEstimator = JsonHeuristicTokenEstimator

__all__ = ["HeuristicTokenEstimator", "WindowContextReducer"]
