"""
认证装饰器模块

该模块提供认证和授权相关的装饰器，用于保护API端点和方法。
支持用户认证、权限检查和访问频率限制。

主要功能：
- @require_auth: 需要认证的方法
- @require_permission: 需要特定权限
- @rate_limit: 访问频率限制
- 用户会话管理
- 权限缓存机制
"""

import asyncio
import functools
import time
import hashlib
from typing import Callable, Any, Dict, Optional, List, Union, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from common.logger import logger


class AuthStatus(Enum):
    """认证状态枚举"""
    AUTHENTICATED = "authenticated"
    UNAUTHENTICATED = "unauthenticated"
    EXPIRED = "expired"
    INVALID = "invalid"


class PermissionLevel(Enum):
    """权限级别枚举"""
    GUEST = 0
    USER = 1
    MODERATOR = 2
    ADMIN = 3
    SUPERUSER = 4


@dataclass
class UserInfo:
    """用户信息"""
    user_id: str
    username: str
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    permission_level: PermissionLevel = PermissionLevel.USER
    login_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def has_permission(self, permission: str) -> bool:
        """检查是否拥有指定权限"""
        return permission in self.permissions
    
    def has_role(self, role: str) -> bool:
        """检查是否拥有指定角色"""
        return role in self.roles
    
    def update_activity(self):
        """更新最后活动时间"""
        self.last_activity = time.time()
    
    def is_session_valid(self, session_timeout: int = 3600) -> bool:
        """检查会话是否有效"""
        return time.time() - self.last_activity < session_timeout


@dataclass
class RateLimitInfo:
    """频率限制信息"""
    key: str
    max_calls: int
    period: int  # 时间窗口（秒）
    calls: deque = field(default_factory=deque)
    
    def is_rate_limited(self) -> bool:
        """检查是否达到频率限制"""
        current_time = time.time()
        
        # 清理过期的调用记录
        while self.calls and current_time - self.calls[0] > self.period:
            self.calls.popleft()
        
        # 检查是否超过限制
        return len(self.calls) >= self.max_calls
    
    def add_call(self):
        """添加调用记录"""
        self.calls.append(time.time())


@dataclass
class AuthStatistics:
    """认证统计信息"""
    total_auth_attempts: int = 0
    successful_auth: int = 0
    failed_auth: int = 0
    total_permission_checks: int = 0
    permission_denied: int = 0
    rate_limited_requests: int = 0
    active_sessions: int = 0


class AuthManager:
    """认证管理器"""
    
    def __init__(self, session_timeout: int = 3600, rate_limit_cleanup_interval: int = 300):
        """
        初始化认证管理器
        
        Args:
            session_timeout: 会话超时时间（秒）
            rate_limit_cleanup_interval: 频率限制清理间隔（秒）
        """
        self._users: Dict[str, UserInfo] = {}
        self._sessions: Dict[str, str] = {}  # session_id -> user_id
        self._rate_limits: Dict[str, RateLimitInfo] = {}
        self._permission_cache: Dict[str, Dict[str, bool]] = defaultdict(dict)
        
        self._session_timeout = session_timeout
        self._rate_limit_cleanup_interval = rate_limit_cleanup_interval
        self._statistics = AuthStatistics()
        
        # 启动清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """启动认证管理器"""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_data())
        logger.info("认证管理器启动成功")
    
    async def stop(self):
        """停止认证管理器"""
        if not self._running:
            return
        
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.info("认证管理器停止成功")
    
    async def authenticate_user(self, user_id: str, username: str, 
                              roles: Optional[List[str]] = None,
                              permissions: Optional[List[str]] = None,
                              permission_level: PermissionLevel = PermissionLevel.USER,
                              session_id: Optional[str] = None) -> UserInfo:
        """认证用户"""
        user_info = UserInfo(
            user_id=user_id,
            username=username,
            roles=roles or [],
            permissions=permissions or [],
            permission_level=permission_level,
            session_id=session_id
        )
        
        self._users[user_id] = user_info
        if session_id:
            self._sessions[session_id] = user_id
        
        self._statistics.total_auth_attempts += 1
        self._statistics.successful_auth += 1
        self._statistics.active_sessions = len(self._sessions)
        
        logger.info("用户认证成功", user_id=user_id, username=username)
        return user_info
    
    async def get_user(self, user_id: str) -> Optional[UserInfo]:
        """获取用户信息"""
        user = self._users.get(user_id)
        if user and user.is_session_valid(self._session_timeout):
            user.update_activity()
            return user
        elif user:
            # 会话过期，移除用户
            await self.logout_user(user_id)
        return None
    
    async def get_user_by_session(self, session_id: str) -> Optional[UserInfo]:
        """根据会话ID获取用户信息"""
        user_id = self._sessions.get(session_id)
        if user_id:
            return await self.get_user(user_id)
        return None
    
    async def logout_user(self, user_id: str):
        """用户登出"""
        user = self._users.pop(user_id, None)
        if user and user.session_id:
            self._sessions.pop(user.session_id, None)
        
        self._statistics.active_sessions = len(self._sessions)
        logger.info("用户登出", user_id=user_id)
    
    async def check_permission(self, user_id: str, permission: str) -> bool:
        """检查用户权限"""
        self._statistics.total_permission_checks += 1
        
        # 检查缓存
        cache_key = f"{user_id}:{permission}"
        if cache_key in self._permission_cache[user_id]:
            return self._permission_cache[user_id][cache_key]
        
        user = await self.get_user(user_id)
        if not user:
            self._statistics.permission_denied += 1
            return False
        
        has_permission = user.has_permission(permission)
        
        # 缓存结果
        self._permission_cache[user_id][cache_key] = has_permission
        
        if not has_permission:
            self._statistics.permission_denied += 1
        
        return has_permission
    
    async def check_rate_limit(self, key: str, max_calls: int, period: int) -> bool:
        """检查频率限制"""
        if key not in self._rate_limits:
            self._rate_limits[key] = RateLimitInfo(
                key=key,
                max_calls=max_calls,
                period=period
            )
        
        rate_limit = self._rate_limits[key]
        
        if rate_limit.is_rate_limited():
            self._statistics.rate_limited_requests += 1
            return False
        
        rate_limit.add_call()
        return True
    
    def get_statistics(self) -> AuthStatistics:
        """获取认证统计信息"""
        return self._statistics
    
    async def _cleanup_expired_data(self):
        """清理过期数据"""
        while self._running:
            try:
                await asyncio.sleep(self._rate_limit_cleanup_interval)
                
                current_time = time.time()
                
                # 清理过期会话
                expired_users = []
                for user_id, user in self._users.items():
                    if not user.is_session_valid(self._session_timeout):
                        expired_users.append(user_id)
                
                for user_id in expired_users:
                    await self.logout_user(user_id)
                
                # 清理过期的频率限制记录
                expired_rate_limits = []
                for key, rate_limit in self._rate_limits.items():
                    # 清理过期的调用记录
                    while rate_limit.calls and current_time - rate_limit.calls[0] > rate_limit.period:
                        rate_limit.calls.popleft()
                    
                    # 如果没有调用记录，标记为过期
                    if not rate_limit.calls:
                        expired_rate_limits.append(key)
                
                for key in expired_rate_limits:
                    del self._rate_limits[key]
                
                # 清理权限缓存
                self._permission_cache.clear()
                
                if expired_users or expired_rate_limits:
                    logger.debug("清理过期数据",
                               expired_users=len(expired_users),
                               expired_rate_limits=len(expired_rate_limits))
                
            except Exception as e:
                logger.error("清理过期数据失败", error=str(e))


# 全局认证管理器
_auth_manager = AuthManager()


def require_auth(user_id_param: str = "user_id",
                session_id_param: str = "session_id",
                auto_update_activity: bool = True,
                **kwargs) -> Callable:
    """
    需要认证的方法装饰器
    
    Args:
        user_id_param: 用户ID参数名
        session_id_param: 会话ID参数名
        auto_update_activity: 是否自动更新活动时间
        **kwargs: 其他选项
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @require_auth(user_id_param="uid")
    async def get_user_profile(uid: str):
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                # 从参数中获取用户ID或会话ID
                user_id = kwargs.get(user_id_param)
                session_id = kwargs.get(session_id_param)
                
                user = None
                if user_id:
                    user = await _auth_manager.get_user(user_id)
                elif session_id:
                    user = await _auth_manager.get_user_by_session(session_id)
                
                if not user:
                    _auth_manager._statistics.failed_auth += 1
                    raise PermissionError("用户未认证或会话已过期")
                
                # 自动更新活动时间
                if auto_update_activity:
                    user.update_activity()
                
                # 将用户信息添加到kwargs中
                kwargs['_current_user'] = user
                
                # 调用原始函数
                result = await func(*args, **kwargs)
                
                latency = time.time() - start_time
                logger.debug("认证检查成功",
                           user_id=user.user_id,
                           function=func.__name__,
                           latency=latency)
                
                return result
                
            except Exception as e:
                latency = time.time() - start_time
                logger.error("认证检查失败",
                           function=func.__name__,
                           error=str(e),
                           latency=latency)
                raise
        
        return wrapper
    
    return decorator


def require_permission(permission: str,
                      user_id_param: str = "user_id",
                      session_id_param: str = "session_id",
                      **kwargs) -> Callable:
    """
    需要特定权限的装饰器
    
    Args:
        permission: 所需权限
        user_id_param: 用户ID参数名
        session_id_param: 会话ID参数名
        **kwargs: 其他选项
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @require_permission("user.edit")
    async def edit_user(user_id: str):
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                # 从参数中获取用户ID或会话ID
                user_id = kwargs.get(user_id_param)
                session_id = kwargs.get(session_id_param)
                
                user = None
                if user_id:
                    user = await _auth_manager.get_user(user_id)
                elif session_id:
                    user = await _auth_manager.get_user_by_session(session_id)
                
                if not user:
                    raise PermissionError("用户未认证")
                
                # 检查权限
                has_permission = await _auth_manager.check_permission(user.user_id, permission)
                if not has_permission:
                    raise PermissionError(f"缺少权限: {permission}")
                
                # 将用户信息添加到kwargs中
                kwargs['_current_user'] = user
                
                # 调用原始函数
                result = await func(*args, **kwargs)
                
                latency = time.time() - start_time
                logger.debug("权限检查成功",
                           user_id=user.user_id,
                           permission=permission,
                           function=func.__name__,
                           latency=latency)
                
                return result
                
            except Exception as e:
                latency = time.time() - start_time
                logger.error("权限检查失败",
                           permission=permission,
                           function=func.__name__,
                           error=str(e),
                           latency=latency)
                raise
        
        return wrapper
    
    return decorator


def require_role(role: str,
                user_id_param: str = "user_id",
                session_id_param: str = "session_id",
                **kwargs) -> Callable:
    """
    需要特定角色的装饰器
    
    Args:
        role: 所需角色
        user_id_param: 用户ID参数名
        session_id_param: 会话ID参数名
        **kwargs: 其他选项
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @require_role("admin")
    async def admin_operation():
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                # 从参数中获取用户ID或会话ID
                user_id = kwargs.get(user_id_param)
                session_id = kwargs.get(session_id_param)
                
                user = None
                if user_id:
                    user = await _auth_manager.get_user(user_id)
                elif session_id:
                    user = await _auth_manager.get_user_by_session(session_id)
                
                if not user:
                    raise PermissionError("用户未认证")
                
                # 检查角色
                if not user.has_role(role):
                    raise PermissionError(f"缺少角色: {role}")
                
                # 将用户信息添加到kwargs中
                kwargs['_current_user'] = user
                
                # 调用原始函数
                result = await func(*args, **kwargs)
                
                latency = time.time() - start_time
                logger.debug("角色检查成功",
                           user_id=user.user_id,
                           role=role,
                           function=func.__name__,
                           latency=latency)
                
                return result
                
            except Exception as e:
                latency = time.time() - start_time
                logger.error("角色检查失败",
                           role=role,
                           function=func.__name__,
                           error=str(e),
                           latency=latency)
                raise
        
        return wrapper
    
    return decorator


def rate_limit(max_calls: int,
              period: int = 60,
              key_func: Optional[Callable] = None,
              per_user: bool = True,
              **kwargs) -> Callable:
    """
    访问频率限制装饰器
    
    Args:
        max_calls: 最大调用次数
        period: 时间窗口（秒）
        key_func: 自定义键生成函数
        per_user: 是否按用户限制
        **kwargs: 其他选项
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @rate_limit(max_calls=10, period=60)  # 每分钟最多10次调用
    async def api_call():
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                # 生成限制键
                if key_func:
                    rate_limit_key = key_func(*args, **kwargs)
                elif per_user:
                    user_id = kwargs.get("user_id")
                    session_id = kwargs.get("session_id")
                    
                    if user_id:
                        rate_limit_key = f"user:{user_id}:{func.__name__}"
                    elif session_id:
                        user = await _auth_manager.get_user_by_session(session_id)
                        if user:
                            rate_limit_key = f"user:{user.user_id}:{func.__name__}"
                        else:
                            rate_limit_key = f"session:{session_id}:{func.__name__}"
                    else:
                        # 使用IP地址或其他标识符
                        client_ip = kwargs.get("client_ip", "unknown")
                        rate_limit_key = f"ip:{client_ip}:{func.__name__}"
                else:
                    # 全局限制
                    rate_limit_key = f"global:{func.__name__}"
                
                # 检查频率限制
                allowed = await _auth_manager.check_rate_limit(
                    rate_limit_key, max_calls, period
                )
                
                if not allowed:
                    raise Exception(f"访问频率超限: 每{period}秒最多{max_calls}次调用")
                
                # 调用原始函数
                result = await func(*args, **kwargs)
                
                latency = time.time() - start_time
                logger.debug("频率限制检查通过",
                           rate_limit_key=rate_limit_key,
                           function=func.__name__,
                           latency=latency)
                
                return result
                
            except Exception as e:
                latency = time.time() - start_time
                logger.error("频率限制检查失败",
                           function=func.__name__,
                           error=str(e),
                           latency=latency)
                raise
        
        return wrapper
    
    return decorator


def permission_level_required(min_level: PermissionLevel,
                            user_id_param: str = "user_id",
                            session_id_param: str = "session_id",
                            **kwargs) -> Callable:
    """
    需要最低权限级别的装饰器
    
    Args:
        min_level: 最低权限级别
        user_id_param: 用户ID参数名
        session_id_param: 会话ID参数名
        **kwargs: 其他选项
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @permission_level_required(PermissionLevel.ADMIN)
    async def admin_function():
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                # 从参数中获取用户ID或会话ID
                user_id = kwargs.get(user_id_param)
                session_id = kwargs.get(session_id_param)
                
                user = None
                if user_id:
                    user = await _auth_manager.get_user(user_id)
                elif session_id:
                    user = await _auth_manager.get_user_by_session(session_id)
                
                if not user:
                    raise PermissionError("用户未认证")
                
                # 检查权限级别
                if user.permission_level.value < min_level.value:
                    raise PermissionError(f"权限级别不足: 需要{min_level.name}，当前{user.permission_level.name}")
                
                # 将用户信息添加到kwargs中
                kwargs['_current_user'] = user
                
                # 调用原始函数
                return await func(*args, **kwargs)
                
            except Exception as e:
                logger.error("权限级别检查失败",
                           min_level=min_level.name,
                           function=func.__name__,
                           error=str(e))
                raise
        
        return wrapper
    
    return decorator


def get_auth_manager() -> AuthManager:
    """获取认证管理器"""
    return _auth_manager


async def authenticate_user(user_id: str, username: str, **kwargs) -> UserInfo:
    """认证用户的便捷函数"""
    return await _auth_manager.authenticate_user(user_id, username, **kwargs)


async def logout_user(user_id: str):
    """用户登出的便捷函数"""
    await _auth_manager.logout_user(user_id)


async def get_current_user(user_id: Optional[str] = None, 
                          session_id: Optional[str] = None) -> Optional[UserInfo]:
    """获取当前用户的便捷函数"""
    if user_id:
        return await _auth_manager.get_user(user_id)
    elif session_id:
        return await _auth_manager.get_user_by_session(session_id)
    return None


def get_auth_statistics() -> AuthStatistics:
    """获取认证统计信息"""
    return _auth_manager.get_statistics()