"""
WebSocket连接管理器

该模块负责管理所有客户端WebSocket连接，提供连接池管理、心跳检测、
断线重连支持、连接状态监控等功能。支持高并发连接管理。

主要功能：
- WebSocket连接池管理
- 心跳检测机制
- 连接状态监控
- 广播和单播消息支持
- 连接统计和监控
"""

import asyncio
import time
import weakref
from typing import Dict, List, Optional, Set, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import json

from common.logger import logger
from common.utils.singleton import Singleton
from .config import GatewayConfig


class ConnectionStatus(Enum):
    """连接状态枚举"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTING = "disconnecting"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class ConnectionInfo:
    """连接信息"""
    connection_id: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    websocket: Any = None
    client_ip: str = ""
    user_agent: str = ""
    connect_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    status: ConnectionStatus = ConnectionStatus.CONNECTING
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_count: int = 0
    error_count: int = 0
    
    def update_activity(self):
        """更新活动时间"""
        self.last_activity = time.time()
        
    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = time.time()
        self.update_activity()
        
    def is_alive(self, timeout: int = 60) -> bool:
        """检查连接是否存活"""
        if self.status != ConnectionStatus.CONNECTED:
            return False
        return time.time() - self.last_heartbeat < timeout
        
    def get_connection_duration(self) -> float:
        """获取连接持续时间"""
        return time.time() - self.connect_time


class WebSocketManager(Singleton):
    """WebSocket连接管理器"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化WebSocket管理器
        
        Args:
            config: 网关配置
        """
        self.config = config
        self._connections: Dict[str, ConnectionInfo] = {}
        self._user_connections: Dict[str, Set[str]] = {}  # user_id -> connection_ids
        self._session_connections: Dict[str, str] = {}  # session_id -> connection_id
        self._connection_lock = asyncio.Lock()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats_task: Optional[asyncio.Task] = None
        self._running = False
        self._event_callbacks: Dict[str, List[Callable]] = {}
        self._thread_pool = ThreadPoolExecutor(max_workers=4)
        
        # 统计信息
        self._total_connections = 0
        self._peak_connections = 0
        self._total_messages = 0
        self._total_errors = 0
        
        logger.info("WebSocket管理器初始化完成", 
                   max_connections=config.websocket.max_connections)
        
    async def start(self):
        """启动WebSocket管理器"""
        if self._running:
            return
            
        self._running = True
        
        # 启动心跳检测任务
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        # 启动连接清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # 启动统计任务
        self._stats_task = asyncio.create_task(self._stats_loop())
        
        logger.info("WebSocket管理器启动完成")
        
    async def stop(self):
        """停止WebSocket管理器"""
        if not self._running:
            return
            
        self._running = False
        
        # 取消所有任务
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._stats_task:
            self._stats_task.cancel()
            
        # 关闭所有连接
        await self._close_all_connections()
        
        # 关闭线程池
        self._thread_pool.shutdown(wait=True)
        
        logger.info("WebSocket管理器停止完成")
        
    async def add_connection(self, connection_id: str, websocket: Any, 
                           client_ip: str = "", user_agent: str = "") -> bool:
        """
        添加新连接
        
        Args:
            connection_id: 连接ID
            websocket: WebSocket对象
            client_ip: 客户端IP
            user_agent: 用户代理
            
        Returns:
            bool: 是否添加成功
        """
        async with self._connection_lock:
            # 检查连接数限制
            if len(self._connections) >= self.config.websocket.max_connections:
                logger.warning("连接数已达上限", 
                             current=len(self._connections),
                             max=self.config.websocket.max_connections)
                return False
                
            # 检查连接是否已存在
            if connection_id in self._connections:
                logger.warning("连接ID已存在", connection_id=connection_id)
                return False
                
            # 创建连接信息
            connection_info = ConnectionInfo(
                connection_id=connection_id,
                websocket=websocket,
                client_ip=client_ip,
                user_agent=user_agent,
                status=ConnectionStatus.CONNECTED
            )
            
            self._connections[connection_id] = connection_info
            self._total_connections += 1
            
            # 更新峰值连接数
            current_count = len(self._connections)
            if current_count > self._peak_connections:
                self._peak_connections = current_count
                
            logger.info("新连接添加成功", 
                       connection_id=connection_id,
                       client_ip=client_ip,
                       total_connections=current_count)
            
            # 触发连接事件
            await self._trigger_event("connection_added", connection_info)
            
            return True
            
    async def remove_connection(self, connection_id: str) -> bool:
        """
        移除连接
        
        Args:
            connection_id: 连接ID
            
        Returns:
            bool: 是否移除成功
        """
        async with self._connection_lock:
            if connection_id not in self._connections:
                return False
                
            connection_info = self._connections[connection_id]
            
            # 从用户连接映射中移除
            if connection_info.user_id:
                user_connections = self._user_connections.get(connection_info.user_id, set())
                user_connections.discard(connection_id)
                if not user_connections:
                    del self._user_connections[connection_info.user_id]
                    
            # 从会话连接映射中移除
            if connection_info.session_id:
                self._session_connections.pop(connection_info.session_id, None)
                
            # 更新状态为断开
            connection_info.status = ConnectionStatus.DISCONNECTED
            
            # 关闭WebSocket连接
            if connection_info.websocket:
                try:
                    await connection_info.websocket.close()
                except Exception as e:
                    logger.error("关闭WebSocket连接失败", 
                               connection_id=connection_id, 
                               error=str(e))
                    
            # 移除连接
            del self._connections[connection_id]
            
            logger.info("连接移除成功", 
                       connection_id=connection_id,
                       user_id=connection_info.user_id,
                       duration=connection_info.get_connection_duration(),
                       total_connections=len(self._connections))
            
            # 触发断开事件
            await self._trigger_event("connection_removed", connection_info)
            
            return True
            
    async def bind_user(self, connection_id: str, user_id: str) -> bool:
        """
        绑定用户到连接
        
        Args:
            connection_id: 连接ID
            user_id: 用户ID
            
        Returns:
            bool: 是否绑定成功
        """
        async with self._connection_lock:
            if connection_id not in self._connections:
                return False
                
            connection_info = self._connections[connection_id]
            old_user_id = connection_info.user_id
            
            # 从旧用户映射中移除
            if old_user_id:
                old_user_connections = self._user_connections.get(old_user_id, set())
                old_user_connections.discard(connection_id)
                if not old_user_connections:
                    del self._user_connections[old_user_id]
                    
            # 绑定新用户
            connection_info.user_id = user_id
            
            # 添加到新用户映射
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(connection_id)
            
            logger.info("用户绑定成功", 
                       connection_id=connection_id,
                       old_user_id=old_user_id,
                       new_user_id=user_id)
            
            return True
            
    async def bind_session(self, connection_id: str, session_id: str) -> bool:
        """
        绑定会话到连接
        
        Args:
            connection_id: 连接ID
            session_id: 会话ID
            
        Returns:
            bool: 是否绑定成功
        """
        async with self._connection_lock:
            if connection_id not in self._connections:
                return False
                
            connection_info = self._connections[connection_id]
            old_session_id = connection_info.session_id
            
            # 移除旧会话映射
            if old_session_id:
                self._session_connections.pop(old_session_id, None)
                
            # 绑定新会话
            connection_info.session_id = session_id
            self._session_connections[session_id] = connection_id
            
            logger.info("会话绑定成功", 
                       connection_id=connection_id,
                       old_session_id=old_session_id,
                       new_session_id=session_id)
            
            return True
            
    async def send_message(self, connection_id: str, message: Any) -> bool:
        """
        发送消息到指定连接
        
        Args:
            connection_id: 连接ID
            message: 消息内容
            
        Returns:
            bool: 是否发送成功
        """
        if connection_id not in self._connections:
            return False
            
        connection_info = self._connections[connection_id]
        
        if connection_info.status != ConnectionStatus.CONNECTED:
            return False
            
        try:
            # 序列化消息
            if isinstance(message, (dict, list)):
                message_data = json.dumps(message)
            elif isinstance(message, str):
                message_data = message
            else:
                message_data = str(message)
                
            # 发送消息
            await connection_info.websocket.send(message_data)
            
            # 更新统计
            connection_info.message_count += 1
            connection_info.update_activity()
            self._total_messages += 1
            
            return True
            
        except Exception as e:
            logger.error("发送消息失败", 
                        connection_id=connection_id,
                        error=str(e))
            connection_info.error_count += 1
            self._total_errors += 1
            
            # 标记连接为错误状态
            connection_info.status = ConnectionStatus.ERROR
            
            return False
            
    async def send_to_user(self, user_id: str, message: Any) -> int:
        """
        发送消息到用户的所有连接
        
        Args:
            user_id: 用户ID
            message: 消息内容
            
        Returns:
            int: 成功发送的连接数
        """
        if user_id not in self._user_connections:
            return 0
            
        connection_ids = self._user_connections[user_id].copy()
        success_count = 0
        
        for connection_id in connection_ids:
            if await self.send_message(connection_id, message):
                success_count += 1
                
        return success_count
        
    async def broadcast_message(self, message: Any, exclude_connections: Optional[Set[str]] = None) -> int:
        """
        广播消息到所有连接
        
        Args:
            message: 消息内容
            exclude_connections: 排除的连接ID集合
            
        Returns:
            int: 成功发送的连接数
        """
        if exclude_connections is None:
            exclude_connections = set()
            
        success_count = 0
        connection_ids = list(self._connections.keys())
        
        for connection_id in connection_ids:
            if connection_id not in exclude_connections:
                if await self.send_message(connection_id, message):
                    success_count += 1
                    
        return success_count
        
    async def send_heartbeat(self, connection_id: str) -> bool:
        """
        发送心跳包
        
        Args:
            connection_id: 连接ID
            
        Returns:
            bool: 是否发送成功
        """
        heartbeat_message = {
            "type": "heartbeat",
            "timestamp": time.time()
        }
        
        if await self.send_message(connection_id, heartbeat_message):
            if connection_id in self._connections:
                self._connections[connection_id].update_heartbeat()
            return True
            
        return False
        
    def get_connection_info(self, connection_id: str) -> Optional[ConnectionInfo]:
        """获取连接信息"""
        return self._connections.get(connection_id)
        
    def get_user_connections(self, user_id: str) -> Set[str]:
        """获取用户的所有连接"""
        return self._user_connections.get(user_id, set()).copy()
        
    def get_connection_by_session(self, session_id: str) -> Optional[str]:
        """通过会话ID获取连接ID"""
        return self._session_connections.get(session_id)
        
    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self._connections)
        
    def get_user_count(self) -> int:
        """获取当前用户数"""
        return len(self._user_connections)
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "current_connections": len(self._connections),
            "current_users": len(self._user_connections),
            "peak_connections": self._peak_connections,
            "total_connections": self._total_connections,
            "total_messages": self._total_messages,
            "total_errors": self._total_errors,
            "running": self._running
        }
        
    def add_event_callback(self, event_name: str, callback: Callable):
        """添加事件回调"""
        if event_name not in self._event_callbacks:
            self._event_callbacks[event_name] = []
        self._event_callbacks[event_name].append(callback)
        
    async def _trigger_event(self, event_name: str, *args, **kwargs):
        """触发事件"""
        callbacks = self._event_callbacks.get(event_name, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(*args, **kwargs)
                else:
                    callback(*args, **kwargs)
            except Exception as e:
                logger.error("事件回调执行失败", 
                           event_name=event_name,
                           error=str(e))
                
    async def _heartbeat_loop(self):
        """心跳循环"""
        while self._running:
            try:
                await asyncio.sleep(self.config.websocket.heartbeat_interval)
                
                # 批量发送心跳
                connection_ids = list(self._connections.keys())
                for connection_id in connection_ids:
                    if not await self.send_heartbeat(connection_id):
                        # 心跳失败，标记连接为错误状态
                        if connection_id in self._connections:
                            self._connections[connection_id].status = ConnectionStatus.ERROR
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("心跳循环异常", error=str(e))
                
    async def _cleanup_loop(self):
        """清理循环"""
        while self._running:
            try:
                await asyncio.sleep(60)  # 每分钟清理一次
                
                # 查找需要清理的连接
                dead_connections = []
                
                for connection_id, connection_info in self._connections.items():
                    if not connection_info.is_alive(self.config.websocket.connection_timeout):
                        dead_connections.append(connection_id)
                        
                # 清理死连接
                for connection_id in dead_connections:
                    await self.remove_connection(connection_id)
                    
                if dead_connections:
                    logger.info("清理死连接", count=len(dead_connections))
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("清理循环异常", error=str(e))
                
    async def _stats_loop(self):
        """统计循环"""
        while self._running:
            try:
                await asyncio.sleep(300)  # 每5分钟输出一次统计
                
                stats = self.get_statistics()
                logger.info("WebSocket连接统计", **stats)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("统计循环异常", error=str(e))
                
    async def _close_all_connections(self):
        """关闭所有连接"""
        connection_ids = list(self._connections.keys())
        for connection_id in connection_ids:
            await self.remove_connection(connection_id)
            
        logger.info("所有连接已关闭")


# 全局WebSocket管理器实例
_websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> Optional[WebSocketManager]:
    """获取WebSocket管理器实例"""
    return _websocket_manager


def create_websocket_manager(config: GatewayConfig) -> WebSocketManager:
    """创建WebSocket管理器"""
    global _websocket_manager
    _websocket_manager = WebSocketManager(config)
    return _websocket_manager