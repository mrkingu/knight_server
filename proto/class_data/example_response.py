"""
示例响应类
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from common.proto.base_proto import BaseResponse


@dataclass
class LoginResponse(BaseResponse):
    """登录响应"""
    user_id: Optional[int] = None
    token: Optional[str] = None
    expires_at: Optional[str] = None


@dataclass
class GetUserInfoResponse(BaseResponse):
    """获取用户信息响应"""
    user_id: Optional[int] = None
    username: Optional[str] = None
    email: Optional[str] = None
    profile: Optional[Dict[str, Any]] = None
    permissions: Optional[List[str]] = None