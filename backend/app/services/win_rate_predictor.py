"""赢率预测占位。"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List


@dataclass
class _Score:
    dimension: str
    score: int
    weight: Decimal
    note: str


class WinRatePredictor:
    def predict(self, **kwargs: Any) -> Dict[str, Any]:
        del kwargs
        return {
            "win_rate": Decimal("0.55"),
            "scores": [
                _Score("price", 75, Decimal("0.4"), "价格竞争力中等"),
                _Score("delivery", 80, Decimal("0.3"), "交期"),
                _Score("relation", 70, Decimal("0.3"), "客情"),
            ],
        }
