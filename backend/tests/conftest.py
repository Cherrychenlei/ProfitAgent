import pytest
from fastapi.testclient import TestClient

import app.api.v1.quotation_router as quotation_router
from app.main import app
from app.repositories.quotation_repository import QuotationRepository


@pytest.fixture
def client(tmp_path):
    quotation_router._REPO = QuotationRepository(db_path=str(tmp_path / "quotations.db"))
    with TestClient(app) as tc:
        yield tc
