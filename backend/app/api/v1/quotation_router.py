"""报价单 API 路由"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.repositories.quotation_repository import QuotationRepository
from app.services.approval_engine_service import ApprovalEngineService
from app.services.coefficient_engine import CoefficientEngine
from app.services.cost_engine_service import BOMItem, CostEngineService
from app.services.decision_router_service import DecisionRouterService
from app.services.win_rate_predictor import WinRatePredictor
from app.schemas.quotation_schema import (
    BOMItemInput,
    QuotationCreateRequest,
    QuotationResponse,
    QuotationListItem,
    NegotiationRequest,
    ApprovalRequest,
    QuotationListQueryParams,
    NegotiationLogQueryParams,
    NegotiationLogListResponse,
    NegotiateResponse,
    ApproveResponse,
    SendToCustomerResponse,
    PriceComparisonResponse,
    SensitivityAnalysisResponse,
)

router = APIRouter(prefix="/quotations", tags=["报价管理"])
_REPO = QuotationRepository()


class _ERPStub:
    def get_material_price(self, material_code: str):
        return {"price": 100}


class _MarketStub:
    def get_latest_price(self, material_code: str):
        return {"price": 105}


def _quote_bom_to_engine_items(quote: QuotationResponse) -> List[BOMItem]:
    """payload 中无 bom_items 的旧报价沿用创建接口默认单行 BOM；显式空列表则按空 BOM 计算。"""
    if quote.bom_items is not None:
        return [
            BOMItem(
                material_code=m.material_code,
                material_name=m.material_name or m.material_code,
                material_category=m.material_category or "其他",
                specification=m.specification or "",
                quantity=m.quantity,
                unit=m.unit or "PCS",
            )
            for m in quote.bom_items
        ]
    return [
        BOMItem(
            material_code="CPU-001",
            material_name="CPU",
            material_category="CPU",
            specification="default",
            quantity=Decimal("1"),
        )
    ]


def _price_comparison_from_quote(quote: QuotationResponse) -> List[Dict[str, Any]]:
    """基于报价单已持久化字段生成比价行（建议价、成本、参考价等）。"""
    rows: List[Dict[str, Any]] = [
        {
            "reference_type": "系统建议价",
            "price": quote.suggested_price,
            "quantity": quote.quantity,
            "margin_rate": quote.margin_rate,
            "project_name": quote.project_name,
            "customer_name": quote.customer_name,
            "quote_number": quote.quote_number,
            "quote_id": quote.quote_id,
            "source": "quotation",
        },
        {
            "reference_type": "初始成本(料工费+期间)",
            "price": quote.init_cost,
            "material_cost": quote.cost_breakdown.material_cost,
            "labor_cost": quote.cost_breakdown.labor_cost,
            "overhead_cost": quote.cost_breakdown.overhead_cost,
            "period_cost": quote.cost_breakdown.period_cost,
            "total_cost": quote.cost_breakdown.total_cost,
            "source": "cost_breakdown",
        },
    ]
    for rp in quote.reference_prices:
        rows.append(rp.model_dump(mode="json"))
    return rows


def _to_list_item(quote: QuotationResponse) -> QuotationListItem:
    return QuotationListItem(
        quote_id=quote.quote_id,
        quote_number=quote.quote_number,
        customer_name=quote.customer_name,
        customer_grade=quote.customer_grade,
        project_name=quote.project_name,
        quantity=quote.quantity,
        suggested_price=quote.suggested_price,
        final_price=None,
        margin_rate=quote.margin_rate,
        win_rate=quote.win_rate,
        routing_channel=quote.routing_channel,
        approval_status=quote.approval_status,
        created_at=quote.created_at,
    )


@router.post("/", response_model=QuotationResponse, status_code=status.HTTP_201_CREATED)
async def create_quotation(request: QuotationCreateRequest):
    """创建报价单 - 核心流程"""
    bom_items = request.bom_items or [
        BOMItem(material_code="CPU-001", material_name="CPU", material_category="CPU", specification="default", quantity=Decimal("1"))
    ]
    normalized_bom = [
        item if isinstance(item, BOMItem) else BOMItem(
            material_code=item.material_code,
            material_name=item.material_name or item.material_code,
            material_category=item.material_category or "其他",
            specification=item.specification or "",
            quantity=item.quantity,
            unit=item.unit,
        )
        for item in bom_items
    ]

    cost_engine = CostEngineService(_ERPStub(), _MarketStub())
    cost_result = cost_engine.calculate_realtime_cost(normalized_bom)
    init_cost = cost_result.total_cost.quantize(Decimal("0.01"))

    coeff_engine = CoefficientEngine()
    coeff_context = {
        "grade": "B",
        "industry": "通信设备",
        "region": "华南",
        "product_type": "多层板",
        "quantity": request.quantity,
        "requested_delivery_days": request.requested_delivery_days,
        "standard_lead_days": 30,
    }
    pricing = coeff_engine.calculate_suggested_price(init_cost, coeff_context)
    total_coefficient = pricing["total_coefficient"]
    suggested_price = pricing["suggested_price"]
    margin_rate = ((suggested_price - init_cost) / suggested_price).quantize(Decimal("0.0001"))

    predictor = WinRatePredictor()
    win = predictor.predict(
        our_price=suggested_price,
        market_avg_price=(suggested_price * Decimal("0.98")).quantize(Decimal("0.01")),
        competitor_price=(suggested_price * Decimal("1.01")).quantize(Decimal("0.01")),
        customer_grade="B",
        cooperation_years=2,
        customer_satisfaction=0.8,
        requested_delivery_days=request.requested_delivery_days or 30,
        standard_lead_days=30,
        product_type="多层板",
        our_capabilities=["多层板", "双面板"],
        payment_terms_days=30,
    )

    discount_rate = Decimal("0.03")
    router_service = DecisionRouterService()
    routing = router_service.route(
        {
            "category": "标品",
            "product_level": "中端",
            "order_scale": "小订单",
            "discount_rate": discount_rate,
            "grade": "B",
            "is_strategic": False,
            "calculated_margin_rate": margin_rate,
            "is_must_win": request.is_must_win,
            "has_red_alert_materials": False,
        }
    )
    target_price = (suggested_price * (Decimal("1") - discount_rate)).quantize(Decimal("0.01"))
    approval = ApprovalEngineService().evaluate(suggested_price=suggested_price, target_price=target_price, init_cost=init_cost)

    coeff_list = [
        {
            "dimension": c.dimension,
            "display_name": c.display_name,
            "value": c.value,
            "adjustment_pct": c.adjustment_pct,
            "label": c.label,
        }
        for c in pricing["coefficients"]
    ]
    win_details = [
        {
            "dimension": s.dimension,
            "score": s.score,
            "weight": s.weight,
            "note": s.note,
        }
        for s in win["scores"]
    ]
    quote = QuotationResponse(
        quote_id=0,
        quote_number="",
        version=1,
        customer_name="Demo Customer",
        customer_grade="B",
        project_name=request.project_name,
        product_spec=request.product_spec,
        quantity=request.quantity,
        requested_delivery_days=request.requested_delivery_days,
        bom_items=[
            BOMItemInput(
                material_code=item.material_code,
                material_name=item.material_name,
                material_category=item.material_category,
                specification=item.specification,
                quantity=item.quantity,
                unit=item.unit,
            )
            for item in normalized_bom
        ],
        cost_breakdown={
            "material_cost": cost_result.material_cost,
            "labor_cost": cost_result.labor_cost,
            "overhead_cost": cost_result.overhead_cost,
            "period_cost": cost_result.period_cost,
            "total_cost": init_cost,
        },
        init_cost=init_cost,
        coefficients=coeff_list,
        total_coefficient=total_coefficient,
        suggested_price=suggested_price,
        margin_rate=margin_rate,
        reference_prices=[
            {
                "reference_type": "历史报价",
                "price": (suggested_price * Decimal("1.01")).quantize(Decimal("0.01")),
                "diff_pct": Decimal("1.00"),
                "source": "history",
            }
        ],
        win_rate=win["win_rate"],
        win_rate_detail=win_details,
        ai_advice={
            "suggestions": ["建议按系统价格发首轮报价，并保留2%-3%议价空间"],
            "risk_warnings": cost_result.warnings or ["暂无重大风险预警"],
            "recommended_actions": ["设置报价有效期7天", "关键物料每日复核行情"],
        },
        routing_channel=routing.channel,
        routing_reason=routing.reason,
        approval_level=approval.level,
        approval_status="pending" if not approval.auto_approved else "approved",
        valid_until=date.today(),
        price_lock_rule="默认锁价规则",
        price_adjust_trigger="关键物料涨幅>=5%",
        payment_terms="月结30天",
        status_timeline=[],
        created_at=datetime.utcnow(),
    )
    try:
        return _REPO.save_new_quote(quote)
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Failed to generate unique quote number, please retry")


@router.post("/upload-config", response_model=QuotationResponse)
async def create_quotation_from_config(
    customer_id: int,
    product_id: int,
    quantity: int,
    file: UploadFile = File(...),
):
    """通过上传客户配置单创建报价单"""
    return await create_quotation(
        QuotationCreateRequest(
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
            project_name=f"上传配置单:{file.filename}",
        )
    )


@router.get("/{quote_id}/negotiations", response_model=NegotiationLogListResponse)
async def get_negotiations(
    quote_id: int,
    query: NegotiationLogQueryParams = Depends(),
):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")
    records = _REPO.list_negotiations(
        quote_id=quote_id,
        action_type=query.action_type,
        start_at=query.start_at,
        end_at=query.end_at,
        page=query.page,
        page_size=query.page_size,
    )
    return NegotiationLogListResponse(
        quote_id=quote_id,
        records=[r.to_dict() for r in records],
        page=query.page,
        page_size=query.page_size,
    )


@router.get("/", response_model=List[QuotationListItem])
async def list_quotations(
    query: QuotationListQueryParams = Depends(),
):
    quotes = _REPO.list(
        approval_status=query.approval_status,
        routing_channel=query.routing_channel,
        created_from=query.date_from,
        created_to=query.date_to,
        page=query.page,
        page_size=query.page_size,
    )
    return [_to_list_item(q) for q in quotes]


@router.get("/{quote_id}", response_model=QuotationResponse)
async def get_quotation(quote_id: int):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")
    return quote


@router.post("/{quote_id}/negotiate", response_model=NegotiateResponse)
async def negotiate(quote_id: int, request: NegotiationRequest):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")

    if request.customer_action == "accept":
        quote.approval_status = "accepted"
    elif request.customer_action == "counter":
        quote.approval_status = "negotiating"
    elif request.customer_action == "reject":
        quote.approval_status = "lost"
    else:
        raise HTTPException(status_code=400, detail="customer_action must be accept/counter/reject")

    now = datetime.utcnow().isoformat()
    quote.status_timeline.append({"status": quote.approval_status, "time": now})
    _REPO.save(quote)
    _REPO.log_negotiation(
        quote_id=quote_id,
        action_type="negotiate",
        payload={
            "customer_action": request.customer_action,
            "customer_target_price": str(request.customer_target_price) if request.customer_target_price is not None else None,
            "customer_reason": request.customer_reason,
            "status": quote.approval_status,
        },
        created_at=now,
    )
    return NegotiateResponse(quote_id=quote_id, status=quote.approval_status, message="negotiate accepted")


@router.post("/{quote_id}/approve", response_model=ApproveResponse)
async def approve(quote_id: int, request: ApprovalRequest):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")

    if request.decision not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="decision must be approve/reject")

    quote.approval_status = "approved" if request.decision == "approve" else "rejected"
    now = datetime.utcnow().isoformat()
    quote.status_timeline.append({"status": quote.approval_status, "time": now, "reason": request.reason})
    _REPO.save(quote)
    _REPO.log_negotiation(
        quote_id=quote_id,
        action_type="approve",
        payload={
            "decision": request.decision,
            "reason": request.reason,
            "status": quote.approval_status,
        },
        created_at=now,
    )
    return ApproveResponse(quote_id=quote_id, decision=request.decision, status=quote.approval_status)


@router.post("/{quote_id}/send-to-customer", response_model=SendToCustomerResponse)
async def send_to_customer(quote_id: int):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")
    quote.approval_status = "sent"
    now = datetime.utcnow().isoformat()
    quote.status_timeline.append({"status": "sent", "time": now})
    _REPO.save(quote)
    _REPO.log_negotiation(
        quote_id=quote_id,
        action_type="send",
        payload={"status": "sent"},
        created_at=now,
    )
    return SendToCustomerResponse(quote_id=quote_id, status="sent")


@router.get("/{quote_id}/price-comparison", response_model=PriceComparisonResponse)
async def get_price_comparison(quote_id: int):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")
    return PriceComparisonResponse(quote_id=quote_id, comparisons=_price_comparison_from_quote(quote))


@router.get("/{quote_id}/sensitivity-analysis", response_model=SensitivityAnalysisResponse)
async def get_sensitivity_analysis(quote_id: int):
    quote = _REPO.get(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail=f"quote_id={quote_id} not found")
    bom = _quote_bom_to_engine_items(quote)
    cost_engine = CostEngineService(_ERPStub(), _MarketStub())
    cost_result = cost_engine.calculate_realtime_cost(bom)
    scenarios = cost_engine.calculate_cost_sensitivity(cost_result)
    return SensitivityAnalysisResponse(quote_id=quote_id, scenarios=scenarios)
