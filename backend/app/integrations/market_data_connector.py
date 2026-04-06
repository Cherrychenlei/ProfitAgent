"""行情连接器协议/占位实现。"""
from typing import Protocol


class MarketDataConnector(Protocol):
    def get_latest_price(self, material_code: str) -> dict:
        ...
