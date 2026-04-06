"""报价单 API Schema"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


class BOMItemInput(BaseModel):
    material_code: str
    material_name: Optional[str] = None
    material_category: Optional[str] = None
    specification: Optional[str] = None
    quantity: Decimal = Field(gt=0)
    unit: str = "PCS"


class QuotationCreateRequest(BaseModel):
    customer_id: int
    product_id: int
    project_name: Optional[str] = None
    product_spec: Optional[str] = None
    quantity: int = Field(gt=0, description="订单数量")
    requested_delivery_days: Optional[int] = Field(None, gt=0, description="客户要求交期(天)")
    bom_items: Optional[List[BOMItemInput]] = None
    config_file_url: Optional[str] = None
    is_must_win: bool = False
    notes: Optional[str] = None


class NegotiationRequest(BaseModel):
    quote_id: int
    customer_action: str = Field(..., description="accept/counter/reject")
    customer_target_price: Optional[Decimal] = None
    customer_reason: Optional[str] = None


class ApprovalRequest(BaseModel):
    quote_id: int
    negotiation_id: int
    decision: str = Field(..., description="approve/reject")
    reason: str = Field(..., min_length=10, description="决策理由(必填, ≥10字)")


class CostBreakdown(BaseModel):
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    period_cost: Decimal
    total_cost: Decimal


class CoefficientDetail(BaseModel):
    dimension: str
    display_name: str
    value: Decimal
    adjustment_pct: str
    label: str


class ReferencePrice(BaseModel):
    reference_type: str
    price: Decimal
    diff_pct: Decimal
    source: Optional[str] = None


class WinRateDetail(BaseModel):
    dimension: str
    score: int
    weight: Decimal
    note: Optional[str] = None


class AIAdvice(BaseModel):
    suggestions: List[str]
    risk_warnings: List[str]
    recommended_actions: List[str]


class QuotationResponse(BaseModel):
    quote_id: int
    quote_number: str
    version: int
    customer_name: str
    customer_grade: str
    project_name: Optional[str]
    product_spec: Optional[str]
    quantity: int
    requested_delivery_days: Optional[int]
    bom_items: Optional[List[BOMItemInput]] = Field(
        default=None,
        description="创建报价时使用的 BOM 行，用于后续比价/敏感性分析；历史数据可能为空",
    )
    cost_breakdown: CostBreakdown
    init_cost: Decimal
    coefficients: List[CoefficientDetail]
    total_coefficient: Decimal
    suggested_price: Decimal
    margin_rate: Decimal
    reference_prices: List[ReferencePrice]
    win_rate: Decimal
    win_rate_detail: List[WinRateDetail]
    ai_advice: AIAdvice
    routing_channel: str
    routing_reason: str
    approval_level: Optional[str]
    approval_status: str
    valid_until: Optional[date]
    price_lock_rule: Optional[str]
    price_adjust_trigger: Optional[str]
    payment_terms: Optional[str]
    status_timeline: List[Dict[str, Any]]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuotationListItem(BaseModel):
    quote_id: int
    quote_number: str
    customer_name: str
    customer_grade: str
    project_name: Optional[str]
    quantity: int
    suggested_price: Decimal
    final_price: Optional[Decimal]
    margin_rate: Optional[Decimal]
    win_rate: Optional[Decimal]
    routing_channel: str
    approval_status: str
    created_at: datetime


class QuotationListQueryParams(BaseModel):
    customer_id: Optional[int] = None
    approval_status: Optional[str] = None
    routing_channel: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class NegotiationLogQueryParams(BaseModel):
    action_type: Optional[Literal["negotiate", "approve", "send"]] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class NegotiationLogRecord(BaseModel):
    negotiation_id: int
    action_type: Literal["negotiate", "approve", "send"]
    payload: Dict[str, Any]
    created_at: datetime


class NegotiationLogListResponse(BaseModel):
    quote_id: int
    records: List[NegotiationLogRecord]
    page: int
    page_size: int


class NegotiateResponse(BaseModel):
    quote_id: int
    status: str
    message: str


class ApproveResponse(BaseModel):
    quote_id: int
    decision: str
    status: str


class SendToCustomerResponse(BaseModel):
    quote_id: int
    status: str


class PriceComparisonResponse(BaseModel):
    quote_id: int
    comparisons: List[Dict[str, Any]] = Field(default_factory=list)


class SensitivityScenario(BaseModel):
    scenario: str
    cost_delta: float
    new_total_cost: float
    cost_change_pct: float


class SensitivityAnalysisResponse(BaseModel):
    quote_id: int
    scenarios: List[SensitivityScenario]
