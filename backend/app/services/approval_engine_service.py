"""审批引擎占位。"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class _ApprovalOutcome:
    level: str
    auto_approved: bool


class ApprovalEngineService:
    def evaluate(
        self,
        suggested_price: Decimal,
        target_price: Decimal,
        init_cost: Decimal,
    ) -> _ApprovalOutcome:
        del suggested_price, target_price, init_cost
        return _ApprovalOutcome(level="L1", auto_approved=False)
