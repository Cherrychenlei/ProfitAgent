"""敏感性分析与比价基于持久化 BOM / 报价字段。"""
from decimal import Decimal

import pytest

import app.api.v1.quotation_router as quotation_router


def test_sensitivity_uses_persisted_bom_not_placeholder(client):
    body = {
        "customer_id": 1,
        "product_id": 1,
        "quantity": 100,
        "project_name": "BOM 测试",
        "bom_items": [
            {
                "material_code": "MEM-001",
                "material_name": "DDR5",
                "material_category": "内存",
                "specification": "16G",
                "quantity": "10",
                "unit": "PCS",
            },
            {
                "material_code": "RES-001",
                "material_name": "电阻排",
                "material_category": "被动件",
                "specification": "0402",
                "quantity": "100",
                "unit": "PCS",
            },
        ],
    }
    r = client.post("/api/v1/quotations/", json=body)
    assert r.status_code == 201, r.text
    quote_id = r.json()["quote_id"]
    assert len(r.json()["bom_items"]) == 2

    sens = client.get(f"/api/v1/quotations/{quote_id}/sensitivity-analysis")
    assert sens.status_code == 200, sens.text
    data = sens.json()
    assert data["quote_id"] == quote_id
    assert data["scenarios"]
    scen = data["scenarios"][0]
    assert scen["scenario"] == "三大件涨5%"
    # 内存属于 KEY 类别，10 * max(100,105)=1050 物料小计；5% = 52.5（仅物料行增量，与占位单行 CPU 不同）
    assert scen["cost_delta"] == pytest.approx(52.5)

    # 比价含建议价、成本与 reference_prices
    pc = client.get(f"/api/v1/quotations/{quote_id}/price-comparison")
    assert pc.status_code == 200, pc.text
    rows = pc.json()["comparisons"]
    assert any(r.get("reference_type") == "系统建议价" for r in rows)
    assert any(r.get("reference_type") == "初始成本(料工费+期间)" for r in rows)
    assert any(r.get("reference_type") == "历史报价" for r in rows)


def test_legacy_quote_without_bom_items_falls_back_to_default_cpu(client):
    """无 bom_items 的旧 payload：敏感性仍可用默认单行 BOM。"""
    from datetime import date, datetime

    from app.schemas.quotation_schema import (
        AIAdvice,
        CostBreakdown,
        QuotationResponse,
    )

    repo = quotation_router._REPO
    q = QuotationResponse(
        quote_id=0,
        quote_number="",
        version=1,
        customer_name="X",
        customer_grade="B",
        project_name="legacy",
        product_spec=None,
        quantity=1,
        requested_delivery_days=30,
        bom_items=None,
        cost_breakdown=CostBreakdown(
            material_cost=Decimal("105"),
            labor_cost=Decimal("70"),
            overhead_cost=Decimal("15.75"),
            period_cost=Decimal("15.26"),
            total_cost=Decimal("206.01"),
        ),
        init_cost=Decimal("206.01"),
        coefficients=[],
        total_coefficient=Decimal("1"),
        suggested_price=Decimal("300"),
        margin_rate=Decimal("0.3"),
        reference_prices=[],
        win_rate=Decimal("0.5"),
        win_rate_detail=[],
        ai_advice=AIAdvice(suggestions=[], risk_warnings=[], recommended_actions=[]),
        routing_channel="standard",
        routing_reason="",
        approval_level="L1",
        approval_status="pending",
        valid_until=date.today(),
        price_lock_rule=None,
        price_adjust_trigger=None,
        payment_terms=None,
        status_timeline=[],
        created_at=datetime.utcnow(),
    )
    saved = repo.save_new_quote(q)
    rid = saved.quote_id

    sens = client.get(f"/api/v1/quotations/{rid}/sensitivity-analysis")
    assert sens.status_code == 200
    scen = sens.json()["scenarios"][0]
    # 默认 CPU 单行：subtotal 105，5% = 5.25
    assert scen["cost_delta"] == pytest.approx(5.25)
