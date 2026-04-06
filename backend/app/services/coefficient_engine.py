"""系数与建议价（最小实现，供创建报价流程使用）。"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List


@dataclass
class _CoeffRow:
    dimension: str
    display_name: str
    value: Decimal
    adjustment_pct: str
    label: str


class CoefficientEngine:
    def calculate_suggested_price(self, init_cost: Decimal, context: Dict[str, Any]) -> Dict[str, Any]:
        del context  # 预留扩展
        total_coefficient = Decimal("1.25")
        suggested_price = (init_cost * total_coefficient).quantize(Decimal("0.01"))
        coefficients: List[_CoeffRow] = [
            _CoeffRow("base", "基础系数", Decimal("1.0"), "0%", "基准"),
            _CoeffRow("margin", "毛利调节", total_coefficient, "25%", "综合"),
        ]
        return {
            "total_coefficient": total_coefficient,
            "suggested_price": suggested_price,
            "coefficients": coefficients,
        }
