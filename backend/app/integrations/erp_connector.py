"""ERP 价格连接器协议/占位实现。"""
from typing import Protocol


class ERPConnector(Protocol):
    def get_material_price(self, material_code: str) -> dict:
        ...
