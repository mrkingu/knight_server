"""
认证中间件

该模块负责Token验证和权限检查，确保只有认证用户才能访问受保护的资源。

主要功能：
- Token验证
- 权限检查
- 用户身份验证
- 会话管理
"""

import time
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass

from common.logger import logger
from common.security import verify_token
from ..config import GatewayConfig
from ..gate_handler import RequestContext
from ..session_manager import get_session_manager


@dataclass
class AuthResult:
    """认证结果"""
    success: bool
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    permissions: Set[str] = None
    error_message: str = ""
    
    def __post_init__(self):
        if self.permissions is None:
            self.permissions = set()


class AuthMiddleware:
    """认证中间件"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化认证中间件
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.session_manager = None
        
        # 免认证的协议
        self.anonymous_protocols = {
            1001,  # 登录
            1002,  # 注册
            1003,  # 忘记密码
            1005,  # 心跳
        }
        
        # 权限要求
        self.permission_requirements = {
            # 游戏相关
            2001: {"game:play"},
            2002: {"game:play"},
            2003: {"game:play"},
            2004: {"game:play"},
            2005: {"game:play"},
            2006: {"game:play"},
            2007: {"game:play"},
            2008: {"game:play"},
            
            # 聊天相关
            3001: {"chat:send"},
            3002: {"chat:read"},
            3003: {"chat:manage"},
            3004: {"chat:join"},
            3005: {"chat:leave"},
            3006: {"chat:read"},
            3007: {"chat:send"},
            3008: {"chat:read"},
        }
        
        logger.info("认证中间件初始化完成")
        
    async def process(self, request: Any, context: RequestContext) -> bool:
        """
        处理认证
        
        Args:
            request: 请求数据
            context: 请求上下文
            
        Returns:
            bool: 是否认证通过
        """
        try:
            # 检查是否启用认证
            if not self.config.auth.enabled:
                logger.debug("认证未启用，跳过认证检查")
                return True
                
            # 获取会话管理器
            if not self.session_manager:
                self.session_manager = get_session_manager()
                
            # 检查是否需要认证
            if not self._requires_auth(context.protocol_id):
                logger.debug("协议无需认证", protocol_id=context.protocol_id)
                return True
                
            # 执行认证
            auth_result = await self._authenticate_request(request, context)
            
            if not auth_result.success:
                logger.warning("认证失败", 
                             protocol_id=context.protocol_id,
                             connection_id=context.connection_id,
                             error=auth_result.error_message)
                return False
                
            # 更新上下文
            context.user_id = auth_result.user_id
            context.session_id = auth_result.session_id
            
            # 检查权限
            if not await self._check_permissions(context.protocol_id, auth_result.permissions):
                logger.warning("权限不足", 
                             protocol_id=context.protocol_id,
                             user_id=auth_result.user_id,
                             required_permissions=self.permission_requirements.get(context.protocol_id, set()))
                return False
                
            logger.debug("认证通过", 
                        protocol_id=context.protocol_id,
                        user_id=auth_result.user_id,
                        session_id=auth_result.session_id)
            
            return True
            
        except Exception as e:
            logger.error("认证处理失败", 
                        protocol_id=context.protocol_id,
                        connection_id=context.connection_id,
                        error=str(e))
            return False
            
    def _requires_auth(self, protocol_id: int) -> bool:
        """
        检查协议是否需要认证
        
        Args:
            protocol_id: 协议ID
            
        Returns:
            bool: 是否需要认证
        """
        return protocol_id not in self.anonymous_protocols
        
    async def _authenticate_request(self, request: Any, context: RequestContext) -> AuthResult:
        """
        认证请求
        
        Args:
            request: 请求数据
            context: 请求上下文
            
        Returns:
            AuthResult: 认证结果
        """
        try:
            # 方法1: 通过会话ID认证
            if context.session_id:
                result = await self._authenticate_by_session(context.session_id)
                if result.success:
                    return result
                    
            # 方法2: 通过连接绑定的会话认证
            session_info = await self.session_manager.get_session_by_connection(context.connection_id)
            if session_info and session_info.is_active():
                return AuthResult(
                    success=True,
                    user_id=session_info.user_id,
                    session_id=session_info.session_id,
                    permissions=session_info.permissions
                )
                
            # 方法3: 通过Token认证
            token = self._extract_token_from_request(request)
            if token:
                result = await self._authenticate_by_token(token)
                if result.success:
                    return result
                    
            return AuthResult(
                success=False,
                error_message="未提供有效的认证信息"
            )
            
        except Exception as e:
            logger.error("认证请求失败", error=str(e))
            return AuthResult(
                success=False,
                error_message=f"认证失败: {str(e)}"
            )
            
    async def _authenticate_by_session(self, session_id: str) -> AuthResult:
        """
        通过会话ID认证
        
        Args:
            session_id: 会话ID
            
        Returns:
            AuthResult: 认证结果
        """
        try:
            session_info = await self.session_manager.get_session(session_id)
            if not session_info:
                return AuthResult(
                    success=False,
                    error_message="会话不存在"
                )
                
            if not session_info.is_active():
                return AuthResult(
                    success=False,
                    error_message="会话已过期"
                )
                
            # 更新会话活动时间
            await self.session_manager.update_session_activity(session_id)
            
            return AuthResult(
                success=True,
                user_id=session_info.user_id,
                session_id=session_info.session_id,
                permissions=session_info.permissions
            )
            
        except Exception as e:
            logger.error("会话认证失败", session_id=session_id, error=str(e))
            return AuthResult(
                success=False,
                error_message="会话认证失败"
            )
            
    async def _authenticate_by_token(self, token: str) -> AuthResult:
        """
        通过Token认证
        
        Args:
            token: JWT Token
            
        Returns:
            AuthResult: 认证结果
        """
        try:
            # 验证Token
            session_info = await self.session_manager.verify_token(token)
            if not session_info:
                return AuthResult(
                    success=False,
                    error_message="Token无效"
                )
                
            if not session_info.is_active():
                return AuthResult(
                    success=False,
                    error_message="Token已过期"
                )
                
            return AuthResult(
                success=True,
                user_id=session_info.user_id,
                session_id=session_info.session_id,
                permissions=session_info.permissions
            )
            
        except Exception as e:
            logger.error("Token认证失败", error=str(e))
            return AuthResult(
                success=False,
                error_message="Token认证失败"
            )
            
    def _extract_token_from_request(self, request: Any) -> Optional[str]:
        """
        从请求中提取Token
        
        Args:
            request: 请求数据
            
        Returns:
            Optional[str]: Token
        """
        try:
            # 从请求数据中提取Token
            if isinstance(request, dict):
                # 检查data字段
                if "data" in request and isinstance(request["data"], dict):
                    token = request["data"].get("token")
                    if token:
                        return token
                        
                # 检查根级字段
                token = request.get("token")
                if token:
                    return token
                    
            return None
            
        except Exception as e:
            logger.error("提取Token失败", error=str(e))
            return None
            
    async def _check_permissions(self, protocol_id: int, user_permissions: Set[str]) -> bool:
        """
        检查权限
        
        Args:
            protocol_id: 协议ID
            user_permissions: 用户权限
            
        Returns:
            bool: 是否有权限
        """
        try:
            # 获取协议所需权限
            required_permissions = self.permission_requirements.get(protocol_id, set())
            
            # 如果没有权限要求，直接通过
            if not required_permissions:
                return True
                
            # 检查用户是否有所需权限
            if not user_permissions:
                return False
                
            # 检查是否有管理员权限
            if "admin" in user_permissions:
                return True
                
            # 检查是否有任一所需权限
            return bool(required_permissions.intersection(user_permissions))
            
        except Exception as e:
            logger.error("权限检查失败", 
                        protocol_id=protocol_id,
                        error=str(e))
            return False
            
    def add_anonymous_protocol(self, protocol_id: int):
        """
        添加免认证协议
        
        Args:
            protocol_id: 协议ID
        """
        self.anonymous_protocols.add(protocol_id)
        logger.info("添加免认证协议", protocol_id=protocol_id)
        
    def remove_anonymous_protocol(self, protocol_id: int):
        """
        移除免认证协议
        
        Args:
            protocol_id: 协议ID
        """
        self.anonymous_protocols.discard(protocol_id)
        logger.info("移除免认证协议", protocol_id=protocol_id)
        
    def add_permission_requirement(self, protocol_id: int, permissions: Set[str]):
        """
        添加权限要求
        
        Args:
            protocol_id: 协议ID
            permissions: 权限集合
        """
        self.permission_requirements[protocol_id] = permissions
        logger.info("添加权限要求", 
                   protocol_id=protocol_id,
                   permissions=permissions)
        
    def remove_permission_requirement(self, protocol_id: int):
        """
        移除权限要求
        
        Args:
            protocol_id: 协议ID
        """
        self.permission_requirements.pop(protocol_id, None)
        logger.info("移除权限要求", protocol_id=protocol_id)
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "anonymous_protocols_count": len(self.anonymous_protocols),
            "permission_requirements_count": len(self.permission_requirements),
            "auth_enabled": self.config.auth.enabled,
            "anonymous_protocols": list(self.anonymous_protocols),
            "permission_requirements": {
                k: list(v) for k, v in self.permission_requirements.items()
            }
        }