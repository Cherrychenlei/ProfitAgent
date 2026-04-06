"""决策路由占位。"""
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class _RouteResult:
    channel: str
    reason: str


class DecisionRouterService:
    def route(self, ctx: Dict[str, Any]) -> _RouteResult:
        del ctx
        return _RouteResult(channel="standard", reason="默认路由")
