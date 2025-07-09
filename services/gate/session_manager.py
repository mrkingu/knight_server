"""
会话管理器

该模块负责管理用户会话信息，包括会话创建、验证、刷新、过期处理等。
支持分布式会话存储和会话安全验证。

主要功能：
- 用户会话管理
- 会话与WebSocket连接绑定
- 会话超时处理
- 分布式会话支持(Redis)
- 会话安全验证
"""

import asyncio
import time
import uuid
import json
from typing import Dict, Optional, Any, Set, List
from dataclasses import dataclass, field, asdict
from enum import Enum

from common.logger import logger
from common.db.redis_manager import RedisManager, redis_manager
from common.security import JWTAuth, TokenPayload, verify_token
from common.utils.singleton import Singleton
from .config import GatewayConfig


class SessionStatus(Enum):
    """会话状态枚举"""
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    INVALID = "invalid"


@dataclass
class SessionInfo:
    """会话信息"""
    session_id: str
    user_id: str
    username: str
    connection_id: Optional[str] = None
    client_ip: str = ""
    user_agent: str = ""
    create_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    expire_time: float = field(default_factory=lambda: time.time() + 3600)
    status: SessionStatus = SessionStatus.ACTIVE
    permissions: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """检查会话是否过期"""
        return time.time() > self.expire_time or self.status == SessionStatus.EXPIRED
        
    def is_active(self) -> bool:
        """检查会话是否活跃"""
        return self.status == SessionStatus.ACTIVE and not self.is_expired()
        
    def update_activity(self):
        """更新活动时间"""
        self.last_activity = time.time()
        
    def extend_expire_time(self, seconds: int):
        """延长过期时间"""
        self.expire_time = time.time() + seconds
        
    def add_permission(self, permission: str):
        """添加权限"""
        self.permissions.add(permission)
        
    def remove_permission(self, permission: str):
        """移除权限"""
        self.permissions.discard(permission)
        
    def has_permission(self, permission: str) -> bool:
        """检查是否有权限"""
        return permission in self.permissions
        
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        data['permissions'] = list(self.permissions)
        data['status'] = self.status.value
        return data
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionInfo':
        """从字典创建实例"""
        data = data.copy()
        data['permissions'] = set(data.get('permissions', []))
        data['status'] = SessionStatus(data.get('status', SessionStatus.ACTIVE.value))
        return cls(**data)


class SessionManager(Singleton):
    """会话管理器"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化会话管理器
        
        Args:
            config: 网关配置
        """
        self.config = config
        self._sessions: Dict[str, SessionInfo] = {}
        self._user_sessions: Dict[str, Set[str]] = {}  # user_id -> session_ids
        self._connection_sessions: Dict[str, str] = {}  # connection_id -> session_id
        self._session_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Redis管理器
        self._redis_manager: Optional[RedisManager] = None
        
        # JWT认证
        self._jwt_auth: Optional[JWTAuth] = None
        
        # 统计信息
        self._total_sessions = 0
        self._active_sessions = 0
        self._expired_sessions = 0
        
        logger.info("会话管理器初始化完成")
        
    async def initialize(self):
        """初始化会话管理器"""
        # 初始化Redis管理器
        self._redis_manager = redis_manager
        if not self._redis_manager:
            from common.db.redis_manager import RedisManager
            self._redis_manager = RedisManager()
            
        # 初始化Redis连接
        redis_config = {
            'default': {
                'host': self.config.redis_host,
                'port': self.config.redis_port,
                'password': self.config.redis_password,
                'db': self.config.redis_db,
                'max_connections': self.config.redis_max_connections
            }
        }
        await self._redis_manager.initialize(redis_config)
        
        # 初始化JWT认证
        from common.security import JWTAuth, TokenConfig
        jwt_config = TokenConfig(
            secret_key=self.config.auth.jwt_secret,
            algorithm=self.config.auth.jwt_algorithm,
            access_token_expire_minutes=self.config.auth.token_expire_time // 60,
            refresh_token_expire_days=self.config.auth.refresh_token_expire_time // (60 * 24)
        )
        self._jwt_auth = JWTAuth(jwt_config)
        
        logger.info("会话管理器初始化完成")
        
    async def start(self):
        """启动会话管理器"""
        if self._running:
            return
            
        self._running = True
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # 从Redis恢复会话
        await self._restore_sessions_from_redis()
        
        logger.info("会话管理器启动完成")
        
    async def stop(self):
        """停止会话管理器"""
        if not self._running:
            return
            
        self._running = False
        
        # 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            
        # 保存会话到Redis
        await self._save_sessions_to_redis()
        
        logger.info("会话管理器停止完成")
        
    async def create_session(self, user_id: str, username: str, 
                           connection_id: Optional[str] = None,
                           client_ip: str = "", user_agent: str = "",
                           permissions: Optional[Set[str]] = None,
                           expire_seconds: Optional[int] = None) -> Optional[SessionInfo]:
        """
        创建新会话
        
        Args:
            user_id: 用户ID
            username: 用户名
            connection_id: 连接ID
            client_ip: 客户端IP
            user_agent: 用户代理
            permissions: 权限集合
            expire_seconds: 过期时间(秒)
            
        Returns:
            SessionInfo: 会话信息
        """
        async with self._session_lock:
            # 生成会话ID
            session_id = str(uuid.uuid4())
            
            # 计算过期时间
            if expire_seconds is None:
                expire_seconds = self.config.auth.token_expire_time
            expire_time = time.time() + expire_seconds
            
            # 创建会话信息
            session_info = SessionInfo(
                session_id=session_id,
                user_id=user_id,
                username=username,
                connection_id=connection_id,
                client_ip=client_ip,
                user_agent=user_agent,
                expire_time=expire_time,
                permissions=permissions or set()
            )
            
            # 保存会话
            self._sessions[session_id] = session_info
            
            # 更新用户会话映射
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = set()
            self._user_sessions[user_id].add(session_id)
            
            # 更新连接会话映射
            if connection_id:
                self._connection_sessions[connection_id] = session_id
                
            # 更新统计
            self._total_sessions += 1
            self._active_sessions += 1
            
            # 保存到Redis
            await self._save_session_to_redis(session_info)
            
            logger.info("会话创建成功", 
                       session_id=session_id,
                       user_id=user_id,
                       connection_id=connection_id,
                       expire_time=expire_time)
            
            return session_info
            
    async def get_session(self, session_id: str) -> Optional[SessionInfo]:
        """
        获取会话信息
        
        Args:
            session_id: 会话ID
            
        Returns:
            SessionInfo: 会话信息
        """
        # 首先从内存中获取
        session_info = self._sessions.get(session_id)
        
        # 如果内存中没有，从Redis中获取
        if not session_info:
            session_info = await self._load_session_from_redis(session_id)
            if session_info:
                self._sessions[session_id] = session_info
                
        # 检查会话是否过期
        if session_info and session_info.is_expired():
            await self.remove_session(session_id)
            return None
            
        return session_info
        
    async def validate_session(self, session_id: str) -> bool:
        """
        验证会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 会话是否有效
        """
        session_info = await self.get_session(session_id)
        return session_info is not None and session_info.is_active()
        
    async def update_session_activity(self, session_id: str) -> bool:
        """
        更新会话活动时间
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 是否更新成功
        """
        session_info = await self.get_session(session_id)
        if not session_info:
            return False
            
        session_info.update_activity()
        
        # 更新到Redis
        await self._save_session_to_redis(session_info)
        
        return True
        
    async def extend_session(self, session_id: str, seconds: int) -> bool:
        """
        延长会话时间
        
        Args:
            session_id: 会话ID
            seconds: 延长时间(秒)
            
        Returns:
            bool: 是否延长成功
        """
        session_info = await self.get_session(session_id)
        if not session_info:
            return False
            
        session_info.extend_expire_time(seconds)
        
        # 更新到Redis
        await self._save_session_to_redis(session_info)
        
        logger.info("会话延长成功", 
                   session_id=session_id,
                   new_expire_time=session_info.expire_time)
        
        return True
        
    async def remove_session(self, session_id: str) -> bool:
        """
        移除会话
        
        Args:
            session_id: 会话ID
            
        Returns:
            bool: 是否移除成功
        """
        async with self._session_lock:
            if session_id not in self._sessions:
                return False
                
            session_info = self._sessions[session_id]
            
            # 从用户会话映射中移除
            if session_info.user_id in self._user_sessions:
                self._user_sessions[session_info.user_id].discard(session_id)
                if not self._user_sessions[session_info.user_id]:
                    del self._user_sessions[session_info.user_id]
                    
            # 从连接会话映射中移除
            if session_info.connection_id:
                self._connection_sessions.pop(session_info.connection_id, None)
                
            # 移除会话
            del self._sessions[session_id]
            
            # 更新统计
            self._active_sessions -= 1
            self._expired_sessions += 1
            
            # 从Redis中移除
            await self._remove_session_from_redis(session_id)
            
            logger.info("会话移除成功", 
                       session_id=session_id,
                       user_id=session_info.user_id)
            
            return True
            
    async def get_user_sessions(self, user_id: str) -> List[SessionInfo]:
        """
        获取用户的所有会话
        
        Args:
            user_id: 用户ID
            
        Returns:
            List[SessionInfo]: 会话列表
        """
        if user_id not in self._user_sessions:
            return []
            
        sessions = []
        session_ids = self._user_sessions[user_id].copy()
        
        for session_id in session_ids:
            session_info = await self.get_session(session_id)
            if session_info:
                sessions.append(session_info)
                
        return sessions
        
    async def get_session_by_connection(self, connection_id: str) -> Optional[SessionInfo]:
        """
        通过连接ID获取会话
        
        Args:
            connection_id: 连接ID
            
        Returns:
            SessionInfo: 会话信息
        """
        session_id = self._connection_sessions.get(connection_id)
        if session_id:
            return await self.get_session(session_id)
        return None
        
    async def bind_connection(self, session_id: str, connection_id: str) -> bool:
        """
        绑定连接到会话
        
        Args:
            session_id: 会话ID
            connection_id: 连接ID
            
        Returns:
            bool: 是否绑定成功
        """
        session_info = await self.get_session(session_id)
        if not session_info:
            return False
            
        # 解绑旧连接
        if session_info.connection_id:
            self._connection_sessions.pop(session_info.connection_id, None)
            
        # 绑定新连接
        session_info.connection_id = connection_id
        self._connection_sessions[connection_id] = session_id
        
        # 更新到Redis
        await self._save_session_to_redis(session_info)
        
        logger.info("连接绑定成功", 
                   session_id=session_id,
                   connection_id=connection_id)
        
        return True
        
    async def unbind_connection(self, connection_id: str) -> bool:
        """
        解绑连接
        
        Args:
            connection_id: 连接ID
            
        Returns:
            bool: 是否解绑成功
        """
        session_id = self._connection_sessions.pop(connection_id, None)
        if not session_id:
            return False
            
        session_info = await self.get_session(session_id)
        if session_info:
            session_info.connection_id = None
            await self._save_session_to_redis(session_info)
            
        logger.info("连接解绑成功", 
                   session_id=session_id,
                   connection_id=connection_id)
        
        return True
        
    async def verify_token(self, token: str) -> Optional[SessionInfo]:
        """
        验证JWT Token并获取会话
        
        Args:
            token: JWT Token
            
        Returns:
            SessionInfo: 会话信息
        """
        try:
            # 验证Token
            payload = await verify_token(token, self._jwt_auth)
            if not payload:
                return None
                
            # 获取会话
            session_id = payload.get('session_id')
            if not session_id:
                return None
                
            return await self.get_session(session_id)
            
        except Exception as e:
            logger.error("Token验证失败", error=str(e))
            return None
            
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_sessions": self._total_sessions,
            "active_sessions": self._active_sessions,
            "expired_sessions": self._expired_sessions,
            "current_sessions": len(self._sessions),
            "current_users": len(self._user_sessions),
            "running": self._running
        }
        
    async def _cleanup_loop(self):
        """清理循环"""
        while self._running:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                
                # 查找过期会话
                expired_sessions = []
                
                for session_id, session_info in self._sessions.items():
                    if session_info.is_expired():
                        expired_sessions.append(session_id)
                        
                # 清理过期会话
                for session_id in expired_sessions:
                    await self.remove_session(session_id)
                    
                if expired_sessions:
                    logger.info("清理过期会话", count=len(expired_sessions))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("清理循环异常", error=str(e))
                
    async def _save_session_to_redis(self, session_info: SessionInfo):
        """保存会话到Redis"""
        if not self._redis_manager:
            return
            
        try:
            key = f"session:{session_info.session_id}"
            data = json.dumps(session_info.to_dict())
            expire_seconds = int(session_info.expire_time - time.time())
            
            if expire_seconds > 0:
                await self._redis_manager.set(key, data, expire=expire_seconds)
                
        except Exception as e:
            logger.error("保存会话到Redis失败", 
                        session_id=session_info.session_id,
                        error=str(e))
            
    async def _load_session_from_redis(self, session_id: str) -> Optional[SessionInfo]:
        """从Redis加载会话"""
        if not self._redis_manager:
            return None
            
        try:
            key = f"session:{session_id}"
            data = await self._redis_manager.get(key)
            
            if data:
                session_data = json.loads(data)
                return SessionInfo.from_dict(session_data)
                
        except Exception as e:
            logger.error("从Redis加载会话失败", 
                        session_id=session_id,
                        error=str(e))
            
        return None
        
    async def _remove_session_from_redis(self, session_id: str):
        """从Redis移除会话"""
        if not self._redis_manager:
            return
            
        try:
            key = f"session:{session_id}"
            await self._redis_manager.delete(key)
            
        except Exception as e:
            logger.error("从Redis移除会话失败", 
                        session_id=session_id,
                        error=str(e))
            
    async def _save_sessions_to_redis(self):
        """保存所有会话到Redis"""
        for session_info in self._sessions.values():
            await self._save_session_to_redis(session_info)
            
    async def _restore_sessions_from_redis(self):
        """从Redis恢复会话"""
        # TODO: 实现批量恢复逻辑
        pass


# 全局会话管理器实例
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> Optional[SessionManager]:
    """获取会话管理器实例"""
    return _session_manager


def create_session_manager(config: GatewayConfig) -> SessionManager:
    """创建会话管理器"""
    global _session_manager
    _session_manager = SessionManager(config)
    return _session_manager