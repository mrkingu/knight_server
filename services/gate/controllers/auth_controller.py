"""
认证控制器

该模块负责处理用户认证相关的请求，包括登录、注册、Token验证、
密码重置等功能。

主要功能：
- 用户登录和注册
- Token验证和刷新
- 密码重置
- 用户信息管理
"""

import time
from typing import Dict, Any, List, Optional
import hashlib
import secrets

from common.logger import logger
from common.security import generate_tokens, verify_token, JWTAuth
from ..route_manager import route, RouteType
from ..gate_handler import RequestContext
from .base_controller import BaseController, ControllerResponse


class AuthController(BaseController):
    """认证控制器"""
    
    def __init__(self, config, auth_service):
        """
        初始化认证控制器
        
        Args:
            config: 网关配置
            auth_service: 认证服务
        """
        super().__init__(config)
        self.auth_service = auth_service
        
        # 设置匿名方法
        self.add_anonymous_method("handle_protocol_1001")  # 登录
        self.add_anonymous_method("handle_protocol_1002")  # 注册
        self.add_anonymous_method("handle_protocol_1003")  # 忘记密码
        self.add_anonymous_method("handle_protocol_1005")  # 心跳
        
        logger.info("认证控制器初始化完成")
        
    @route(protocol_id=1001, description="用户登录", group_name="auth")
    async def handle_protocol_1001(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理用户登录请求
        
        Args:
            data: 请求数据 {"username": str, "password": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            # 验证参数
            username = data.get("username", "").strip()
            password = data.get("password", "").strip()
            
            if not username or not password:
                return self.validation_error_response("username/password", "用户名或密码不能为空")
                
            # 验证用户凭证
            user_info = await self.auth_service.authenticate_user(username, password)
            if not user_info:
                return self.error_response(401, "用户名或密码错误")
                
            # 检查用户状态
            if not user_info.get("is_active", True):
                return self.error_response(403, "用户账户已被禁用")
                
            # 生成Token
            token_payload = {
                "user_id": user_info["user_id"],
                "username": user_info["username"],
                "permissions": user_info.get("permissions", [])
            }
            
            token_pair = await self.auth_service.generate_user_tokens(token_payload)
            if not token_pair:
                return self.server_error_response("Token生成失败")
                
            # 创建会话
            from ..session_manager import get_session_manager
            session_manager = get_session_manager()
            
            session_info = await session_manager.create_session(
                user_id=user_info["user_id"],
                username=user_info["username"],
                connection_id=context.connection_id,
                client_ip=context.client_ip,
                user_agent=context.user_agent,
                permissions=set(user_info.get("permissions", []))
            )
            
            if not session_info:
                return self.server_error_response("会话创建失败")
                
            # 绑定WebSocket连接
            from ..websocket_manager import get_websocket_manager
            websocket_manager = get_websocket_manager()
            await websocket_manager.bind_user(context.connection_id, user_info["user_id"])
            
            # 记录登录日志
            logger.info("用户登录成功", 
                       user_id=user_info["user_id"],
                       username=user_info["username"],
                       connection_id=context.connection_id,
                       client_ip=context.client_ip)
            
            return self.success_response({
                "user_id": user_info["user_id"],
                "username": user_info["username"],
                "nickname": user_info.get("nickname", ""),
                "email": user_info.get("email", ""),
                "avatar": user_info.get("avatar", ""),
                "permissions": user_info.get("permissions", []),
                "access_token": token_pair["access_token"],
                "refresh_token": token_pair["refresh_token"],
                "session_id": session_info.session_id,
                "expires_in": self.config.auth.token_expire_time
            })
            
        except Exception as e:
            logger.error("登录处理失败", 
                        username=username,
                        error=str(e))
            return self.server_error_response("登录处理失败")
            
    @route(protocol_id=1002, description="用户注册", group_name="auth")
    async def handle_protocol_1002(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理用户注册请求
        
        Args:
            data: 请求数据 {"username": str, "password": str, "email": str, "nickname": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            # 验证参数
            username = data.get("username", "").strip()
            password = data.get("password", "").strip()
            email = data.get("email", "").strip()
            nickname = data.get("nickname", "").strip()
            
            if not username or not password:
                return self.validation_error_response("username/password", "用户名或密码不能为空")
                
            if len(username) < 3 or len(username) > 20:
                return self.validation_error_response("username", "用户名长度必须在3-20个字符之间")
                
            if len(password) < 6:
                return self.validation_error_response("password", "密码长度不能少于6个字符")
                
            # 检查用户名是否已存在
            if await self.auth_service.check_username_exists(username):
                return self.error_response(409, "用户名已存在")
                
            # 检查邮箱是否已存在
            if email and await self.auth_service.check_email_exists(email):
                return self.error_response(409, "邮箱已存在")
                
            # 创建用户
            user_data = {
                "username": username,
                "password": password,
                "email": email,
                "nickname": nickname or username,
                "is_active": True,
                "created_at": time.time(),
                "permissions": ["user:basic"]  # 默认权限
            }
            
            user_info = await self.auth_service.create_user(user_data)
            if not user_info:
                return self.server_error_response("用户创建失败")
                
            # 记录注册日志
            logger.info("用户注册成功", 
                       user_id=user_info["user_id"],
                       username=user_info["username"],
                       client_ip=context.client_ip)
            
            return self.success_response({
                "user_id": user_info["user_id"],
                "username": user_info["username"],
                "nickname": user_info["nickname"],
                "email": user_info["email"],
                "message": "注册成功，请登录"
            })
            
        except Exception as e:
            logger.error("注册处理失败", 
                        username=username,
                        error=str(e))
            return self.server_error_response("注册处理失败")
            
    @route(protocol_id=1003, description="忘记密码", group_name="auth")
    async def handle_protocol_1003(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理忘记密码请求
        
        Args:
            data: 请求数据 {"email": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            email = data.get("email", "").strip()
            
            if not email:
                return self.validation_error_response("email", "邮箱不能为空")
                
            # 检查邮箱是否存在
            user_info = await self.auth_service.get_user_by_email(email)
            if not user_info:
                return self.error_response(404, "邮箱不存在")
                
            # 生成重置令牌
            reset_token = secrets.token_urlsafe(32)
            expire_time = time.time() + 3600  # 1小时有效期
            
            # 保存重置令牌
            await self.auth_service.save_reset_token(user_info["user_id"], reset_token, expire_time)
            
            # 发送重置邮件
            await self.auth_service.send_reset_email(email, reset_token)
            
            logger.info("密码重置请求", 
                       user_id=user_info["user_id"],
                       email=email,
                       client_ip=context.client_ip)
            
            return self.success_response({
                "message": "密码重置链接已发送到您的邮箱"
            })
            
        except Exception as e:
            logger.error("忘记密码处理失败", 
                        email=email,
                        error=str(e))
            return self.server_error_response("忘记密码处理失败")
            
    @route(protocol_id=1004, description="刷新Token", group_name="auth")
    async def handle_protocol_1004(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理Token刷新请求
        
        Args:
            data: 请求数据 {"refresh_token": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            refresh_token = data.get("refresh_token", "").strip()
            
            if not refresh_token:
                return self.validation_error_response("refresh_token", "刷新Token不能为空")
                
            # 验证并刷新Token
            new_token_pair = await self.auth_service.refresh_token(refresh_token)
            if not new_token_pair:
                return self.error_response(401, "刷新Token无效或已过期")
                
            return self.success_response({
                "access_token": new_token_pair["access_token"],
                "refresh_token": new_token_pair["refresh_token"],
                "expires_in": self.config.auth.token_expire_time
            })
            
        except Exception as e:
            logger.error("Token刷新失败", error=str(e))
            return self.server_error_response("Token刷新失败")
            
    @route(protocol_id=1005, description="心跳检测", group_name="auth")
    async def handle_protocol_1005(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理心跳检测请求
        
        Args:
            data: 请求数据 {"timestamp": float}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            client_timestamp = data.get("timestamp", 0)
            server_timestamp = time.time()
            
            # 如果用户已登录，更新会话活动时间
            if context.session_id:
                from ..session_manager import get_session_manager
                session_manager = get_session_manager()
                await session_manager.update_session_activity(context.session_id)
                
            return self.success_response({
                "server_timestamp": server_timestamp,
                "client_timestamp": client_timestamp,
                "latency": server_timestamp - client_timestamp if client_timestamp > 0 else 0
            })
            
        except Exception as e:
            logger.error("心跳处理失败", error=str(e))
            return self.server_error_response("心跳处理失败")
            
    @route(protocol_id=1006, description="用户登出", group_name="auth")
    async def handle_protocol_1006(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理用户登出请求
        
        Args:
            data: 请求数据 {}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 移除会话
            from ..session_manager import get_session_manager
            session_manager = get_session_manager()
            
            if context.session_id:
                await session_manager.remove_session(context.session_id)
                
            # 解绑WebSocket连接
            from ..websocket_manager import get_websocket_manager
            websocket_manager = get_websocket_manager()
            connection_info = websocket_manager.get_connection_info(context.connection_id)
            if connection_info:
                connection_info.user_id = None
                
            logger.info("用户登出成功", 
                       user_id=context.user_id,
                       connection_id=context.connection_id)
            
            return self.success_response({
                "message": "登出成功"
            })
            
        except Exception as e:
            logger.error("登出处理失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("登出处理失败")
            
    @route(protocol_id=1007, description="获取用户信息", group_name="auth")
    async def handle_protocol_1007(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取用户信息请求
        
        Args:
            data: 请求数据 {}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 获取用户信息
            user_info = await self.auth_service.get_user_by_id(context.user_id)
            if not user_info:
                return self.error_response(404, "用户不存在")
                
            # 获取会话信息
            session_info = None
            if context.session_id:
                from ..session_manager import get_session_manager
                session_manager = get_session_manager()
                session_info = await session_manager.get_session(context.session_id)
                
            response_data = {
                "user_id": user_info["user_id"],
                "username": user_info["username"],
                "nickname": user_info.get("nickname", ""),
                "email": user_info.get("email", ""),
                "avatar": user_info.get("avatar", ""),
                "permissions": user_info.get("permissions", []),
                "is_active": user_info.get("is_active", True),
                "created_at": user_info.get("created_at", 0),
                "last_login": user_info.get("last_login", 0)
            }
            
            if session_info:
                response_data["session_info"] = {
                    "session_id": session_info.session_id,
                    "create_time": session_info.create_time,
                    "last_activity": session_info.last_activity,
                    "expire_time": session_info.expire_time
                }
                
            return self.success_response(response_data)
            
        except Exception as e:
            logger.error("获取用户信息失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取用户信息失败")
            
    async def get_supported_protocols(self) -> List[int]:
        """获取支持的协议列表"""
        return [1001, 1002, 1003, 1004, 1005, 1006, 1007]
        
    async def get_controller_info(self) -> Dict[str, Any]:
        """获取控制器信息"""
        return {
            "name": "AuthController",
            "description": "认证控制器",
            "version": "1.0.0",
            "supported_protocols": await self.get_supported_protocols(),
            "anonymous_methods": list(self.anonymous_methods),
            "required_permissions": list(self.required_permissions)
        }