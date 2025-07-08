"""
用户控制器

该模块实现了用户相关的控制器，继承自BaseController，
负责处理用户登录、登出、信息查询、状态管理等功能。

主要功能：
- 用户登录/登出处理
- 用户信息查询和更新
- 用户状态管理
- 用户权限验证
- 用户会话管理

支持的操作：
- 登录认证
- 安全登出
- 获取用户信息
- 更新用户资料
- 查询用户状态
- 用户在线状态管理
"""

import asyncio
import time
import hashlib
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta

from services.base import BaseController, ControllerConfig
from services.base import ValidationException, AuthorizationException, BusinessException
from common.logger import logger
from common.decorator import handler, controller

# 导入协议定义
try:
    from common.proto import BaseRequest, BaseResponse
    PROTO_AVAILABLE = True
except ImportError:
    logger.warning("协议模块不可用，使用模拟类型")
    PROTO_AVAILABLE = False
    
    @dataclass
    class BaseRequest:
        message_id: int = 0
        user_id: Optional[str] = None
        session_id: Optional[str] = None
        timestamp: float = 0.0
        data: Dict[str, Any] = None
    
    @dataclass
    class BaseResponse:
        message_id: int = 0
        status: str = "success"
        code: int = 200
        message: str = ""
        data: Dict[str, Any] = None
        timestamp: float = 0.0


# 请求和响应协议定义
@dataclass
class LoginRequest(BaseRequest):
    """登录请求"""
    username: str = ""
    password: str = ""
    device_id: Optional[str] = None
    client_version: Optional[str] = None
    login_type: str = "password"  # password, token, guest


@dataclass
class LoginResponse(BaseResponse):
    """登录响应"""
    user_id: str = ""
    username: str = ""
    nickname: str = ""
    avatar_url: str = ""
    level: int = 1
    exp: int = 0
    vip_level: int = 0
    session_token: str = ""
    expires_at: float = 0.0
    is_new_user: bool = False


@dataclass
class LogoutRequest(BaseRequest):
    """登出请求"""
    logout_type: str = "normal"  # normal, force


@dataclass
class LogoutResponse(BaseResponse):
    """登出响应"""
    logout_time: float = 0.0


@dataclass
class GetUserInfoRequest(BaseRequest):
    """获取用户信息请求"""
    target_user_id: Optional[str] = None  # 如果为空则获取自己的信息
    include_private: bool = False  # 是否包含私人信息


@dataclass
class GetUserInfoResponse(BaseResponse):
    """获取用户信息响应"""
    user_info: Dict[str, Any] = None


@dataclass
class UpdateUserInfoRequest(BaseRequest):
    """更新用户信息请求"""
    nickname: Optional[str] = None
    avatar_url: Optional[str] = None
    gender: Optional[int] = None
    birthday: Optional[str] = None
    signature: Optional[str] = None


@dataclass
class UpdateUserInfoResponse(BaseResponse):
    """更新用户信息响应"""
    updated_fields: List[str] = None


@dataclass
class GetUserStatusRequest(BaseRequest):
    """获取用户状态请求"""
    user_ids: List[str] = None


@dataclass
class GetUserStatusResponse(BaseResponse):
    """获取用户状态响应"""
    user_status: Dict[str, Dict[str, Any]] = None


@controller(name="UserController")
class UserController(BaseController):
    """用户控制器
    
    处理所有用户相关的请求，包括认证、信息管理、状态查询等。
    """
    
    def __init__(self, config: Optional[ControllerConfig] = None):
        """初始化用户控制器"""
        super().__init__(config)
        
        # 用户服务
        self.user_service = None
        
        # 登录限制配置
        self.max_login_attempts = 5
        self.login_attempt_window = 300  # 5分钟
        self.session_timeout = 3600  # 1小时
        
        # 登录尝试记录
        self.login_attempts: Dict[str, List[float]] = {}
        
        # 在线用户会话
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        
        # 用户状态缓存
        self.user_status_cache: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info("用户控制器初始化完成")
    
    async def initialize(self):
        """初始化用户控制器"""
        try:
            await super().initialize()
            
            # 获取用户服务
            self.user_service = self.get_service("user_service")
            if not self.user_service:
                raise ValueError("用户服务未注册")
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_sessions())
            asyncio.create_task(self._cleanup_login_attempts())
            
            self.logger.info("用户控制器初始化完成")
            
        except Exception as e:
            self.logger.error("用户控制器初始化失败", error=str(e))
            raise
    
    @handler(LoginRequest, LoginResponse)
    async def handle_login(self, request: LoginRequest, context=None) -> LoginResponse:
        """
        处理用户登录请求
        
        Args:
            request: 登录请求
            context: 请求上下文
            
        Returns:
            LoginResponse: 登录响应
        """
        try:
            # 参数验证
            if not request.username or not request.password:
                raise ValidationException("用户名和密码不能为空")
            
            # 检查登录尝试次数
            client_ip = context.client_ip if context else "127.0.0.1"
            if await self._check_login_attempts(client_ip):
                raise AuthorizationException("登录尝试次数过多，请稍后再试")
            
            # 记录登录尝试
            await self._record_login_attempt(client_ip)
            
            # 调用用户服务进行认证
            auth_result = await self.user_service.authenticate_user(
                username=request.username,
                password=request.password,
                device_id=request.device_id,
                client_version=request.client_version,
                login_type=request.login_type
            )
            
            if not auth_result["success"]:
                raise AuthorizationException(auth_result["message"])
            
            user_info = auth_result["user_info"]
            
            # 生成会话令牌
            session_token = await self._generate_session_token(user_info["user_id"])
            
            # 创建用户会话
            session_info = {
                "user_id": user_info["user_id"],
                "username": user_info["username"],
                "session_token": session_token,
                "login_time": time.time(),
                "last_active": time.time(),
                "device_id": request.device_id,
                "client_version": request.client_version,
                "client_ip": client_ip,
                "expires_at": time.time() + self.session_timeout
            }
            
            # 保存会话
            self.active_sessions[session_token] = session_info
            await self.user_service.save_user_session(session_info)
            
            # 更新用户在线状态
            await self._update_user_status(user_info["user_id"], "online")
            
            # 清除登录尝试记录
            await self._clear_login_attempts(client_ip)
            
            # 构造响应
            response = LoginResponse(
                message_id=request.message_id,
                user_id=user_info["user_id"],
                username=user_info["username"],
                nickname=user_info.get("nickname", ""),
                avatar_url=user_info.get("avatar_url", ""),
                level=user_info.get("level", 1),
                exp=user_info.get("exp", 0),
                vip_level=user_info.get("vip_level", 0),
                session_token=session_token,
                expires_at=session_info["expires_at"],
                is_new_user=auth_result.get("is_new_user", False),
                timestamp=time.time()
            )
            
            self.logger.info("用户登录成功",
                           user_id=user_info["user_id"],
                           username=user_info["username"],
                           client_ip=client_ip)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("登录参数验证失败", error=str(e))
            raise
        except AuthorizationException as e:
            self.logger.warning("登录认证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("登录处理异常", error=str(e))
            raise BusinessException(f"登录失败: {str(e)}")
    
    @handler(LogoutRequest, LogoutResponse)
    async def handle_logout(self, request: LogoutRequest, context=None) -> LogoutResponse:
        """
        处理用户登出请求
        
        Args:
            request: 登出请求
            context: 请求上下文
            
        Returns:
            LogoutResponse: 登出响应
        """
        try:
            # 参数验证
            if not request.user_id or not request.session_id:
                raise ValidationException("用户ID和会话ID不能为空")
            
            # 验证会话
            session_info = self.active_sessions.get(request.session_id)
            if not session_info or session_info["user_id"] != request.user_id:
                raise AuthorizationException("无效的会话")
            
            # 调用用户服务执行登出
            await self.user_service.logout_user(
                user_id=request.user_id,
                session_id=request.session_id,
                logout_type=request.logout_type
            )
            
            # 清除会话
            if request.session_id in self.active_sessions:
                del self.active_sessions[request.session_id]
            
            # 更新用户状态
            await self._update_user_status(request.user_id, "offline")
            
            logout_time = time.time()
            
            # 构造响应
            response = LogoutResponse(
                message_id=request.message_id,
                logout_time=logout_time,
                timestamp=logout_time
            )
            
            self.logger.info("用户登出成功",
                           user_id=request.user_id,
                           session_id=request.session_id)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("登出参数验证失败", error=str(e))
            raise
        except AuthorizationException as e:
            self.logger.warning("登出认证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("登出处理异常", error=str(e))
            raise BusinessException(f"登出失败: {str(e)}")
    
    @handler(GetUserInfoRequest, GetUserInfoResponse)
    async def handle_get_user_info(self, request: GetUserInfoRequest, context=None) -> GetUserInfoResponse:
        """
        处理获取用户信息请求
        
        Args:
            request: 获取用户信息请求
            context: 请求上下文
            
        Returns:
            GetUserInfoResponse: 用户信息响应
        """
        try:
            # 验证会话
            await self._validate_session(request.user_id, request.session_id)
            
            # 确定目标用户ID
            target_user_id = request.target_user_id or request.user_id
            
            # 检查权限
            if target_user_id != request.user_id and request.include_private:
                raise AuthorizationException("无权查看其他用户的私人信息")
            
            # 调用用户服务获取用户信息
            user_info = await self.user_service.get_user_info(
                user_id=target_user_id,
                include_private=request.include_private and target_user_id == request.user_id
            )
            
            if not user_info:
                raise BusinessException("用户不存在")
            
            # 构造响应
            response = GetUserInfoResponse(
                message_id=request.message_id,
                user_info=user_info,
                timestamp=time.time()
            )
            
            self.logger.info("获取用户信息成功",
                           user_id=request.user_id,
                           target_user_id=target_user_id)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("获取用户信息参数验证失败", error=str(e))
            raise
        except AuthorizationException as e:
            self.logger.warning("获取用户信息认证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取用户信息处理异常", error=str(e))
            raise BusinessException(f"获取用户信息失败: {str(e)}")
    
    @handler(UpdateUserInfoRequest, UpdateUserInfoResponse)
    async def handle_update_user_info(self, request: UpdateUserInfoRequest, context=None) -> UpdateUserInfoResponse:
        """
        处理更新用户信息请求
        
        Args:
            request: 更新用户信息请求
            context: 请求上下文
            
        Returns:
            UpdateUserInfoResponse: 更新用户信息响应
        """
        try:
            # 验证会话
            await self._validate_session(request.user_id, request.session_id)
            
            # 构建更新数据
            update_data = {}
            if request.nickname is not None:
                update_data["nickname"] = request.nickname
            if request.avatar_url is not None:
                update_data["avatar_url"] = request.avatar_url
            if request.gender is not None:
                update_data["gender"] = request.gender
            if request.birthday is not None:
                update_data["birthday"] = request.birthday
            if request.signature is not None:
                update_data["signature"] = request.signature
            
            if not update_data:
                raise ValidationException("没有提供需要更新的字段")
            
            # 调用用户服务更新用户信息
            updated_fields = await self.user_service.update_user_info(
                user_id=request.user_id,
                update_data=update_data
            )
            
            # 构造响应
            response = UpdateUserInfoResponse(
                message_id=request.message_id,
                updated_fields=updated_fields,
                timestamp=time.time()
            )
            
            self.logger.info("更新用户信息成功",
                           user_id=request.user_id,
                           updated_fields=updated_fields)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("更新用户信息参数验证失败", error=str(e))
            raise
        except AuthorizationException as e:
            self.logger.warning("更新用户信息认证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("更新用户信息处理异常", error=str(e))
            raise BusinessException(f"更新用户信息失败: {str(e)}")
    
    @handler(GetUserStatusRequest, GetUserStatusResponse)
    async def handle_get_user_status(self, request: GetUserStatusRequest, context=None) -> GetUserStatusResponse:
        """
        处理获取用户状态请求
        
        Args:
            request: 获取用户状态请求
            context: 请求上下文
            
        Returns:
            GetUserStatusResponse: 用户状态响应
        """
        try:
            # 验证会话
            await self._validate_session(request.user_id, request.session_id)
            
            # 参数验证
            if not request.user_ids:
                raise ValidationException("用户ID列表不能为空")
            
            # 调用用户服务获取用户状态
            user_status = await self.user_service.get_user_status(request.user_ids)
            
            # 构造响应
            response = GetUserStatusResponse(
                message_id=request.message_id,
                user_status=user_status,
                timestamp=time.time()
            )
            
            self.logger.info("获取用户状态成功",
                           user_id=request.user_id,
                           query_count=len(request.user_ids))
            
            return response
            
        except ValidationException as e:
            self.logger.warning("获取用户状态参数验证失败", error=str(e))
            raise
        except AuthorizationException as e:
            self.logger.warning("获取用户状态认证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取用户状态处理异常", error=str(e))
            raise BusinessException(f"获取用户状态失败: {str(e)}")
    
    async def _validate_session(self, user_id: str, session_id: str):
        """验证用户会话"""
        if not user_id or not session_id:
            raise ValidationException("用户ID和会话ID不能为空")
        
        session_info = self.active_sessions.get(session_id)
        if not session_info:
            raise AuthorizationException("会话不存在")
        
        if session_info["user_id"] != user_id:
            raise AuthorizationException("会话用户不匹配")
        
        if session_info["expires_at"] < time.time():
            # 清除过期会话
            del self.active_sessions[session_id]
            raise AuthorizationException("会话已过期")
        
        # 更新最后活跃时间
        session_info["last_active"] = time.time()
    
    async def _check_login_attempts(self, client_ip: str) -> bool:
        """检查登录尝试次数"""
        if client_ip not in self.login_attempts:
            return False
        
        attempts = self.login_attempts[client_ip]
        current_time = time.time()
        
        # 清除过期的尝试记录
        attempts = [t for t in attempts if current_time - t < self.login_attempt_window]
        self.login_attempts[client_ip] = attempts
        
        return len(attempts) >= self.max_login_attempts
    
    async def _record_login_attempt(self, client_ip: str):
        """记录登录尝试"""
        if client_ip not in self.login_attempts:
            self.login_attempts[client_ip] = []
        
        self.login_attempts[client_ip].append(time.time())
    
    async def _clear_login_attempts(self, client_ip: str):
        """清除登录尝试记录"""
        if client_ip in self.login_attempts:
            del self.login_attempts[client_ip]
    
    async def _generate_session_token(self, user_id: str) -> str:
        """生成会话令牌"""
        timestamp = str(time.time())
        token_data = f"{user_id}:{timestamp}:{hash(user_id + timestamp)}"
        return hashlib.sha256(token_data.encode()).hexdigest()
    
    async def _update_user_status(self, user_id: str, status: str):
        """更新用户状态"""
        status_info = {
            "user_id": user_id,
            "status": status,
            "last_update": time.time()
        }
        
        self.user_status_cache[user_id] = status_info
        
        # 通知用户服务更新状态
        await self.user_service.update_user_status(user_id, status)
    
    async def _cleanup_expired_sessions(self):
        """清理过期会话"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                
                current_time = time.time()
                expired_sessions = [
                    session_id for session_id, session_info in self.active_sessions.items()
                    if session_info["expires_at"] < current_time
                ]
                
                for session_id in expired_sessions:
                    session_info = self.active_sessions.pop(session_id)
                    await self._update_user_status(session_info["user_id"], "offline")
                    
                    self.logger.info("清理过期会话",
                                   session_id=session_id,
                                   user_id=session_info["user_id"])
                
            except Exception as e:
                self.logger.error("清理过期会话异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _cleanup_login_attempts(self):
        """清理登录尝试记录"""
        while True:
            try:
                await asyncio.sleep(600)  # 每10分钟清理一次
                
                current_time = time.time()
                for client_ip in list(self.login_attempts.keys()):
                    attempts = self.login_attempts[client_ip]
                    attempts = [t for t in attempts if current_time - t < self.login_attempt_window]
                    
                    if attempts:
                        self.login_attempts[client_ip] = attempts
                    else:
                        del self.login_attempts[client_ip]
                
            except Exception as e:
                self.logger.error("清理登录尝试记录异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            await super().cleanup()
            
            # 清理所有会话
            for session_id, session_info in self.active_sessions.items():
                await self._update_user_status(session_info["user_id"], "offline")
            
            self.active_sessions.clear()
            self.login_attempts.clear()
            self.user_status_cache.clear()
            
            self.logger.info("用户控制器资源清理完成")
            
        except Exception as e:
            self.logger.error("用户控制器资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            "active_sessions": len(self.active_sessions),
            "login_attempts": len(self.login_attempts),
            "user_status_cache": len(self.user_status_cache),
            "controller_name": self.__class__.__name__,
            "max_login_attempts": self.max_login_attempts,
            "session_timeout": self.session_timeout
        }


def create_user_controller(config: Optional[ControllerConfig] = None) -> UserController:
    """
    创建用户控制器实例
    
    Args:
        config: 控制器配置
        
    Returns:
        UserController实例
    """
    try:
        controller = UserController(config)
        logger.info("用户控制器创建成功")
        return controller
        
    except Exception as e:
        logger.error("创建用户控制器失败", error=str(e))
        raise