"""
示例文档模型
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from common.db.base_document import BaseDocument


@dataclass
class UserDocument(BaseDocument):
    """用户文档模型"""
    username: str
    email: str
    password_hash: str
    profile: Dict[str, Any] = field(default_factory=dict)
    permissions: List[str] = field(default_factory=list)
    last_login: Optional[datetime] = None
    is_active: bool = True
    
    @classmethod
    def get_collection_name(cls) -> str:
        return "users"


@dataclass
class OrderDocument(BaseDocument):
    """订单文档模型"""
    order_id: str
    user_id: str
    total_amount: float
    status: str = "pending"
    items: List[Dict[str, Any]] = field(default_factory=list)
    shipping_address: Optional[Dict[str, str]] = None
    
    @classmethod
    def get_collection_name(cls) -> str:
        return "orders"