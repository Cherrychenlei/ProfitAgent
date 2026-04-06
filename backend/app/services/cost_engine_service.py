"""
成本计算引擎
核心逻辑: 实时成本 = Σ(物料i × max(ERP价i, 行情价i)) + 人工 + 制造费用 + 期间费用
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Dict, List, Optional

from app.integrations.erp_connector import ERPConnector
from app.integrations.market_data_connector import MarketDataConnector

logger = logging.getLogger(__name__)


@dataclass
class BOMItem:
    material_code: str
    material_name: str
    material_category: str
    specification: str
    quantity: Decimal
    unit: str = "PCS"


@dataclass
class CostItem:
    material_code: str
    material_name: str
    material_category: str
    quantity: Decimal
    erp_price: Decimal
    market_price: Decimal
    effective_price: Decimal
    subtotal: Decimal
    price_source: str
    is_key_component: bool


@dataclass
class CostResult:
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    period_cost: Decimal
    total_cost: Decimal
    cost_items: List[CostItem]
    warnings: List[str]


class CostEngineService:
    KEY_COMPONENT_CATEGORIES = {"CPU", "内存", "存储", "芯片"}

    def __init__(self, erp_connector: ERPConnector, market_connector: MarketDataConnector):
        self.erp = erp_connector
        self.market = market_connector

    def calculate_realtime_cost(
        self,
        bom_items: List[BOMItem],
        product_complexity_factor: Decimal = Decimal("1.0"),
        labor_rate_per_hour: Decimal = Decimal("35.00"),
        overhead_rate: Decimal = Decimal("0.15"),
        period_cost_rate: Decimal = Decimal("0.08"),
    ) -> CostResult:
        cost_items: List[CostItem] = []
        warnings: List[str] = []
        total_material_cost = Decimal("0")
        for item in bom_items:
            erp_price = self._get_erp_price(item.material_code)
            market_price = self._get_market_price(item.material_code)
            effective_price = max(erp_price, market_price)
            subtotal = effective_price * item.quantity
            if erp_price > 0 and market_price > 0:
                price_diff_pct = abs(market_price - erp_price) / erp_price
                if price_diff_pct > Decimal("0.10"):
                    warnings.append(
                        f"⚠️ {item.material_name}({item.material_code}): ERP价{erp_price} vs 行情价{market_price}, 差异{price_diff_pct:.1%}"
                    )
            if market_price == 0 and erp_price == 0:
                warnings.append(f"🔴 {item.material_name}({item.material_code}): ERP和行情均无报价, 请人工确认")
            cost_items.append(
                CostItem(
                    material_code=item.material_code,
                    material_name=item.material_name,
                    material_category=item.material_category,
                    quantity=item.quantity,
                    erp_price=erp_price,
                    market_price=market_price,
                    effective_price=effective_price,
                    subtotal=subtotal,
                    price_source="market" if market_price > erp_price else "erp",
                    is_key_component=item.material_category in self.KEY_COMPONENT_CATEGORIES,
                )
            )
            total_material_cost += subtotal

        standard_hours = self._estimate_labor_hours(bom_items)
        labor_cost = (standard_hours * labor_rate_per_hour * product_complexity_factor).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        overhead_cost = (total_material_cost * overhead_rate * product_complexity_factor).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
        subtotal_before_period = total_material_cost + labor_cost + overhead_cost
        period_cost = (subtotal_before_period * period_cost_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_cost = total_material_cost + labor_cost + overhead_cost + period_cost

        return CostResult(total_material_cost, labor_cost, overhead_cost, period_cost, total_cost, cost_items, warnings)

    def _get_erp_price(self, material_code: str) -> Decimal:
        try:
            result = self.erp.get_material_price(material_code)
            return Decimal(str(result.get("price", 0)))
        except Exception as e:
            logger.warning("ERP取价失败 %s: %s", material_code, e)
            return Decimal("0")

    def _get_market_price(self, material_code: str) -> Decimal:
        try:
            result = self.market.get_latest_price(material_code)
            return Decimal(str(result.get("price", 0)))
        except Exception as e:
            logger.warning("行情取价失败 %s: %s", material_code, e)
            return Decimal("0")

    def _estimate_labor_hours(self, bom_items: List[BOMItem]) -> Decimal:
        base_hours = Decimal("2.0")
        for item in bom_items:
            if item.material_category in ("CPU", "芯片"):
                base_hours += Decimal("0.5")
            elif item.material_category == "PCB原材料":
                base_hours += Decimal("0.3")
        return base_hours

    def calculate_cost_sensitivity(self, cost_result: CostResult, scenarios: Optional[List[Dict]] = None) -> List[Dict]:
        scenarios = scenarios or [{"name": "三大件涨5%", "categories": list(self.KEY_COMPONENT_CATEGORIES), "change_pct": 0.05}]
        results = []
        for s in scenarios:
            delta = Decimal("0")
            for item in cost_result.cost_items:
                if item.material_category in s["categories"]:
                    delta += item.subtotal * Decimal(str(s["change_pct"]))
            results.append(
                {
                    "scenario": s["name"],
                    "cost_delta": float(delta),
                    "new_total_cost": float(cost_result.total_cost + delta),
                    "cost_change_pct": float(delta / cost_result.total_cost) if cost_result.total_cost else 0,
                }
            )
        return results
