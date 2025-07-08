"""
示例请求类
"""
from typing import Optional
from dataclasses import dataclass
from common.proto.base_proto import BaseRequest


@dataclass
class LoginRequest(BaseRequest):
    """登录请求"""
    username: str
    password: str
    platform: Optional[str] = None


@dataclass
class GetUserInfoRequest(BaseRequest):
    """获取用户信息请求"""
    user_id: int
    include_detail: bool = False