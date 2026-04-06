from fastapi import FastAPI

from app.api.v1.quotation_router import router as quotation_router

app = FastAPI(title="智能盈利管理系统 API")
app.include_router(quotation_router, prefix="/api/v1")
