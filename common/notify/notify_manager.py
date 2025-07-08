"""
通知管理器模块

该模块实现了通知管理器，负责管理所有通知连接和推送任务。
提供向单个用户、多个用户和全服广播的推送功能。

主要功能：
- 用户连接管理
- 消息推送调度
- 连接状态监控
- 推送失败重试
- 批量推送优化
"""

import asyncio
import time
import weakref
from typing import Dict, List, Optional, Set, Union, Any, Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager
import threading

from common.logger import logger
from .push_service import PushService
from .notify_queue import NotifyQueue, MessagePriority
from .protocol_adapter import ProtocolAdapter


class ConnectionStatus(Enum):
    """连接状态枚举"""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    SUSPENDED = "suspended"


@dataclass
class UserConnection:
    """用户连接信息"""
    user_id: str
    connection_id: str
    websocket: Optional[Any] = None
    last_heartbeat: float = field(default_factory=time.time)
    status: ConnectionStatus = ConnectionStatus.CONNECTED
    retry_count: int = 0
    max_retries: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_alive(self) -> bool:
        """检查连接是否活跃"""
        return self.status == ConnectionStatus.CONNECTED and time.time() - self.last_heartbeat < 30
    
    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = time.time()


@dataclass
class NotifyStatistics:
    """通知统计信息"""
    total_sent: int = 0
    total_failed: int = 0
    total_retried: int = 0
    connections_count: int = 0
    average_latency: float = 0.0
    last_push_time: float = 0.0


class NotifyManager:
    """
    通知管理器
    
    管理所有用户连接和消息推送任务，提供高性能的通知推送服务。
    支持单用户推送、多用户推送和全服广播。
    
    Attributes:
        _connections: 用户连接映射表
        _push_service: 推送服务实例
        _notify_queue: 通知队列实例
        _protocol_adapter: 协议适配器实例
        _statistics: 统计信息
        _running: 运行状态
        _cleanup_task: 清理任务
        _heartbeat_task: 心跳检测任务
    """
    
    def __init__(self, 
                 max_connections: int = 10000,
                 heartbeat_interval: int = 30,
                 cleanup_interval: int = 300,
                 retry_delay: float = 1.0,
                 max_retries: int = 3):
        """
        初始化通知管理器
        
        Args:
            max_connections: 最大连接数
            heartbeat_interval: 心跳检测间隔(秒)
            cleanup_interval: 清理间隔(秒)
            retry_delay: 重试延迟(秒)
            max_retries: 最大重试次数
        """
        self._connections: Dict[str, UserConnection] = {}
        self._user_connections: Dict[str, Set[str]] = {}  # user_id -> connection_ids
        self._max_connections = max_connections
        self._heartbeat_interval = heartbeat_interval
        self._cleanup_interval = cleanup_interval
        self._retry_delay = retry_delay
        self._max_retries = max_retries
        
        # 初始化服务组件
        self._push_service = PushService()
        self._notify_queue = NotifyQueue()
        self._protocol_adapter = ProtocolAdapter()
        
        # 统计信息
        self._statistics = NotifyStatistics()
        
        # 运行状态
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._process_task: Optional[asyncio.Task] = None
        
        # 线程安全锁
        self._lock = asyncio.Lock()
        
        # 事件回调
        self._on_connected_callbacks: List[Callable] = []
        self._on_disconnected_callbacks: List[Callable] = []
        self._on_message_sent_callbacks: List[Callable] = []
        
        logger.info("通知管理器初始化完成", 
                   max_connections=max_connections,
                   heartbeat_interval=heartbeat_interval)
    
    async def start(self):
        """启动通知管理器"""
        if self._running:
            logger.warning("通知管理器已经在运行中")
            return
        
        self._running = True
        
        # 启动服务组件
        await self._push_service.start()
        await self._notify_queue.start()
        
        # 启动后台任务
        self._cleanup_task = asyncio.create_task(self._cleanup_connections())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_check())
        self._process_task = asyncio.create_task(self._process_notifications())
        
        logger.info("通知管理器启动成功")
    
    async def stop(self):
        """停止通知管理器"""
        if not self._running:
            return
        
        self._running = False
        
        # 取消后台任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._process_task:
            self._process_task.cancel()
        
        # 等待任务完成
        tasks = [task for task in [self._cleanup_task, self._heartbeat_task, self._process_task] if task]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 关闭所有连接
        await self._close_all_connections()
        
        # 停止服务组件
        await self._push_service.stop()
        await self._notify_queue.stop()
        
        logger.info("通知管理器停止成功")
    
    async def add_connection(self, user_id: str, connection_id: str, websocket: Any, 
                           metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        添加用户连接
        
        Args:
            user_id: 用户ID
            connection_id: 连接ID
            websocket: WebSocket连接对象
            metadata: 连接元数据
            
        Returns:
            bool: 是否添加成功
        """
        async with self._lock:
            if len(self._connections) >= self._max_connections:
                logger.warning("连接数已达上限", 
                             current=len(self._connections), 
                             max_connections=self._max_connections)
                return False
            
            # 创建连接对象
            connection = UserConnection(
                user_id=user_id,
                connection_id=connection_id,
                websocket=websocket,
                metadata=metadata or {}
            )
            
            # 添加到映射表
            self._connections[connection_id] = connection
            
            # 添加到用户连接集合
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(connection_id)
            
            # 更新统计
            self._statistics.connections_count = len(self._connections)
            
            # 触发连接事件
            for callback in self._on_connected_callbacks:
                try:
                    await callback(user_id, connection_id)
                except Exception as e:
                    logger.error("连接事件回调失败", error=str(e))
            
            logger.info("用户连接添加成功", 
                       user_id=user_id, 
                       connection_id=connection_id,
                       total_connections=len(self._connections))
            
            return True
    
    async def remove_connection(self, connection_id: str) -> bool:
        """
        移除用户连接
        
        Args:
            connection_id: 连接ID
            
        Returns:
            bool: 是否移除成功
        """
        async with self._lock:
            if connection_id not in self._connections:
                return False
            
            connection = self._connections[connection_id]
            user_id = connection.user_id
            
            # 从映射表中移除
            del self._connections[connection_id]
            
            # 从用户连接集合中移除
            if user_id in self._user_connections:
                self._user_connections[user_id].discard(connection_id)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]
            
            # 更新统计
            self._statistics.connections_count = len(self._connections)
            
            # 触发断开事件
            for callback in self._on_disconnected_callbacks:
                try:
                    await callback(user_id, connection_id)
                except Exception as e:
                    logger.error("断开事件回调失败", error=str(e))
            
            logger.info("用户连接移除成功", 
                       user_id=user_id, 
                       connection_id=connection_id,
                       total_connections=len(self._connections))
            
            return True
    
    async def push_to_user(self, user_id: str, message: Any, 
                          priority: MessagePriority = MessagePriority.NORMAL,
                          expire_time: Optional[float] = None) -> bool:
        """
        推送消息给指定用户
        
        Args:
            user_id: 用户ID
            message: 消息对象
            priority: 消息优先级
            expire_time: 过期时间(秒)
            
        Returns:
            bool: 是否推送成功
        """
        return await self._notify_queue.enqueue(
            user_ids=[user_id],
            message=message,
            priority=priority,
            expire_time=expire_time
        )
    
    async def push_to_users(self, user_ids: List[str], message: Any,
                           priority: MessagePriority = MessagePriority.NORMAL,
                           expire_time: Optional[float] = None) -> bool:
        """
        推送消息给多个用户
        
        Args:
            user_ids: 用户ID列表
            message: 消息对象
            priority: 消息优先级
            expire_time: 过期时间(秒)
            
        Returns:
            bool: 是否推送成功
        """
        return await self._notify_queue.enqueue(
            user_ids=user_ids,
            message=message,
            priority=priority,
            expire_time=expire_time
        )
    
    async def broadcast(self, message: Any, 
                       priority: MessagePriority = MessagePriority.NORMAL,
                       expire_time: Optional[float] = None) -> bool:
        """
        全服广播消息
        
        Args:
            message: 消息对象
            priority: 消息优先级
            expire_time: 过期时间(秒)
            
        Returns:
            bool: 是否广播成功
        """
        async with self._lock:
            user_ids = list(self._user_connections.keys())
        
        if not user_ids:
            logger.warning("没有用户连接，广播取消")
            return False
        
        return await self._notify_queue.enqueue(
            user_ids=user_ids,
            message=message,
            priority=priority,
            expire_time=expire_time
        )
    
    async def get_user_connections(self, user_id: str) -> List[UserConnection]:
        """
        获取用户的所有连接
        
        Args:
            user_id: 用户ID
            
        Returns:
            List[UserConnection]: 用户连接列表
        """
        async with self._lock:
            if user_id not in self._user_connections:
                return []
            
            connections = []
            for connection_id in self._user_connections[user_id]:
                if connection_id in self._connections:
                    connections.append(self._connections[connection_id])
            
            return connections
    
    async def get_statistics(self) -> NotifyStatistics:
        """获取统计信息"""
        return self._statistics
    
    def add_connected_callback(self, callback: Callable):
        """添加连接事件回调"""
        self._on_connected_callbacks.append(callback)
    
    def add_disconnected_callback(self, callback: Callable):
        """添加断开事件回调"""
        self._on_disconnected_callbacks.append(callback)
    
    def add_message_sent_callback(self, callback: Callable):
        """添加消息发送事件回调"""
        self._on_message_sent_callbacks.append(callback)
    
    async def _process_notifications(self):
        """处理通知队列中的消息"""
        while self._running:
            try:
                message_item = await self._notify_queue.dequeue()
                if message_item:
                    await self._handle_message_item(message_item)
                else:
                    await asyncio.sleep(0.1)  # 短暂休眠避免空轮询
            except Exception as e:
                logger.error("处理通知消息失败", error=str(e))
                await asyncio.sleep(1)
    
    async def _handle_message_item(self, message_item):
        """处理单个消息项"""
        start_time = time.time()
        
        # 编码消息
        encoded_message = await self._protocol_adapter.encode_message(message_item.message)
        
        success_count = 0
        failed_count = 0
        
        # 向每个用户推送消息
        for user_id in message_item.user_ids:
            connections = await self.get_user_connections(user_id)
            
            for connection in connections:
                if connection.is_alive():
                    try:
                        await self._push_service.send_message(
                            connection.websocket,
                            encoded_message
                        )
                        success_count += 1
                        
                        # 触发发送事件
                        for callback in self._on_message_sent_callbacks:
                            try:
                                await callback(user_id, connection.connection_id, message_item.message)
                            except Exception as e:
                                logger.error("消息发送事件回调失败", error=str(e))
                                
                    except Exception as e:
                        logger.error("消息推送失败", 
                                   user_id=user_id, 
                                   connection_id=connection.connection_id,
                                   error=str(e))
                        failed_count += 1
                        
                        # 标记连接为重连状态
                        connection.status = ConnectionStatus.RECONNECTING
                        connection.retry_count += 1
        
        # 更新统计
        self._statistics.total_sent += success_count
        self._statistics.total_failed += failed_count
        self._statistics.last_push_time = time.time()
        
        # 计算平均延迟
        latency = time.time() - start_time
        self._statistics.average_latency = (
            self._statistics.average_latency * 0.9 + latency * 0.1
        )
        
        logger.debug("消息推送完成",
                    success_count=success_count,
                    failed_count=failed_count,
                    latency=latency)
    
    async def _cleanup_connections(self):
        """清理无效连接"""
        while self._running:
            try:
                await asyncio.sleep(self._cleanup_interval)
                
                async with self._lock:
                    expired_connections = []
                    
                    for connection_id, connection in self._connections.items():
                        if not connection.is_alive():
                            expired_connections.append(connection_id)
                    
                    # 移除过期连接
                    for connection_id in expired_connections:
                        await self.remove_connection(connection_id)
                    
                    if expired_connections:
                        logger.info("清理过期连接", count=len(expired_connections))
                        
            except Exception as e:
                logger.error("清理连接失败", error=str(e))
    
    async def _heartbeat_check(self):
        """心跳检测"""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                
                async with self._lock:
                    for connection in self._connections.values():
                        if connection.status == ConnectionStatus.CONNECTED:
                            try:
                                # 发送心跳包
                                await self._push_service.send_heartbeat(connection.websocket)
                                connection.update_heartbeat()
                            except Exception as e:
                                logger.warning("心跳发送失败", 
                                             user_id=connection.user_id,
                                             connection_id=connection.connection_id,
                                             error=str(e))
                                connection.status = ConnectionStatus.DISCONNECTED
                                
            except Exception as e:
                logger.error("心跳检测失败", error=str(e))
    
    async def _close_all_connections(self):
        """关闭所有连接"""
        async with self._lock:
            for connection in self._connections.values():
                try:
                    if connection.websocket:
                        await connection.websocket.close()
                except Exception as e:
                    logger.error("关闭连接失败", 
                               connection_id=connection.connection_id,
                               error=str(e))
            
            self._connections.clear()
            self._user_connections.clear()
            self._statistics.connections_count = 0


# 全局通知管理器实例
_notify_manager: Optional[NotifyManager] = None


async def get_notify_manager() -> NotifyManager:
    """获取全局通知管理器实例"""
    global _notify_manager
    if _notify_manager is None:
        _notify_manager = NotifyManager()
        await _notify_manager.start()
    return _notify_manager


async def initialize_notify_manager(**kwargs) -> NotifyManager:
    """初始化通知管理器"""
    global _notify_manager
    if _notify_manager is not None:
        await _notify_manager.stop()
    
    _notify_manager = NotifyManager(**kwargs)
    await _notify_manager.start()
    return _notify_manager