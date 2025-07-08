"""
基础通知服务类模块

该模块提供了向客户端推送消息的基础功能，支持消息队列管理、
批量推送、重试机制、推送目标管理等功能。

主要功能：
- 向客户端推送消息的基础功能
- 消息队列管理
- 批量推送支持
- 推送失败重试机制
- 推送目标管理（单播、组播、广播）
- 与gateway的通信接口
- 消息优先级
- 推送统计

使用示例：
```python
from services.base.base_notify import BaseNotify, NotifyMessage, NotifyTarget

class GameNotify(BaseNotify):
    def __init__(self):
        super().__init__()
    
    async def notify_user_login(self, user_id: str, login_data: dict):
        message = NotifyMessage(
            message_type="user_login",
            data=login_data,
            priority=1
        )
        await self.send_to_user(user_id, message)
    
    async def notify_room_message(self, room_id: str, message_data: dict):
        message = NotifyMessage(
            message_type="room_message",
            data=message_data,
            priority=2
        )
        await self.send_to_room(room_id, message)

# 使用
notify = GameNotify()
await notify.notify_user_login("user123", {"timestamp": time.time()})
await notify.notify_room_message("room456", {"content": "Hello world!"})
```
"""

import asyncio
import time
import json
import uuid
from typing import Dict, List, Optional, Any, Set, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

from common.logger import logger
from common.notify.notify_manager import NotifyManager
try:
    from common.proto import ProtoCodec, encode_message
except ImportError:
    # Mock proto classes if not available
    class ProtoCodec:
        def __init__(self):
            pass
    
    def encode_message(data, codec):
        return b"mock_encoded"
from common.grpc.grpc_client import GrpcClient
try:
    from common.monitor import MonitorManager, record_notify_metrics
except ImportError:
    class MonitorManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
    
    async def record_notify_metrics(*args, **kwargs):
        pass


class NotifyType(Enum):
    """通知类型枚举"""
    UNICAST = "unicast"      # 单播
    MULTICAST = "multicast"  # 组播
    BROADCAST = "broadcast"  # 广播


class MessagePriority(Enum):
    """消息优先级枚举"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class NotifyStatus(Enum):
    """通知状态枚举"""
    PENDING = "pending"
    SENDING = "sending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


@dataclass
class NotifyMessage:
    """通知消息"""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message_type: str = ""
    data: Any = None
    priority: MessagePriority = MessagePriority.NORMAL
    retry_count: int = 0
    max_retries: int = 3
    timeout: float = 30.0
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotifyTarget:
    """通知目标"""
    target_type: NotifyType
    target_id: str
    user_ids: Set[str] = field(default_factory=set)
    connection_ids: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotifyTask:
    """通知任务"""
    message: NotifyMessage
    target: NotifyTarget
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: NotifyStatus = NotifyStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error_message: Optional[str] = None
    attempts: int = 0


@dataclass
class NotifyStatistics:
    """通知统计信息"""
    total_sent: int = 0
    total_success: int = 0
    total_failed: int = 0
    total_retry: int = 0
    
    avg_latency: float = 0.0
    max_latency: float = 0.0
    min_latency: float = float('inf')
    
    messages_per_second: float = 0.0
    last_reset_time: float = field(default_factory=time.time)


@dataclass
class NotifyConfig:
    """通知配置"""
    # 队列配置
    max_queue_size: int = 10000
    batch_size: int = 100
    batch_timeout: float = 1.0
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0
    retry_backoff: float = 2.0
    
    # 超时配置
    default_timeout: float = 30.0
    
    # 工作线程配置
    worker_count: int = 4
    thread_pool_size: int = 10
    
    # 缓存配置
    enable_message_cache: bool = True
    cache_ttl: int = 300
    
    # 监控配置
    enable_monitoring: bool = True
    enable_statistics: bool = True
    
    # Gateway配置
    gateway_host: str = "localhost"
    gateway_port: int = 50052
    
    # 其他配置
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseNotify:
    """
    基础通知服务类
    
    提供向客户端推送消息的基础功能：
    - 消息队列管理
    - 批量推送
    - 重试机制
    - 目标管理
    - Gateway通信
    - 优先级处理
    - 统计监控
    """
    
    def __init__(self, config: Optional[NotifyConfig] = None):
        """
        初始化基础通知服务
        
        Args:
            config: 通知配置
        """
        self.config = config or NotifyConfig()
        self.logger = logger
        
        # 服务基本信息
        self.service_name = self.__class__.__name__
        
        # 核心组件
        self._notify_manager = NotifyManager()
        self._proto_codec = ProtoCodec()
        self._monitor_manager = MonitorManager() if self.config.enable_monitoring else None
        
        # 消息队列（按优先级分组）
        self._message_queues: Dict[MessagePriority, deque] = {
            priority: deque() for priority in MessagePriority
        }
        
        # 任务管理
        self._pending_tasks: Dict[str, NotifyTask] = {}
        self._processing_tasks: Dict[str, NotifyTask] = {}
        self._completed_tasks: Dict[str, NotifyTask] = {}
        
        # 目标管理
        self._user_connections: Dict[str, Set[str]] = defaultdict(set)
        self._room_members: Dict[str, Set[str]] = defaultdict(set)
        self._connection_users: Dict[str, str] = {}
        
        # Gateway客户端
        self._gateway_client: Optional[GrpcClient] = None
        
        # 工作线程
        self._workers: List[asyncio.Task] = []
        self._running = False
        
        # 线程池
        self._thread_pool = ThreadPoolExecutor(max_workers=self.config.thread_pool_size)
        
        # 统计信息
        self._statistics = NotifyStatistics()
        
        # 中间件
        self._before_send_middlewares: List[Callable] = []
        self._after_send_middlewares: List[Callable] = []
        self._error_middlewares: List[Callable] = []
        
        # 消息缓存
        self._message_cache: Dict[str, NotifyMessage] = {}
        self._cache_timestamps: Dict[str, float] = {}
        
        self.logger.info("基础通知服务初始化完成", service_name=self.service_name)
    
    async def initialize(self):
        """初始化通知服务"""
        try:
            # 初始化通知管理器
            await self._notify_manager.initialize()
            
            # 初始化监控管理器
            if self._monitor_manager:
                await self._monitor_manager.initialize()
            
            # 初始化Gateway客户端
            await self._initialize_gateway_client()
            
            # 启动工作线程
            await self._start_workers()
            
            self.logger.info("通知服务初始化完成", service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("通知服务初始化失败", 
                            service_name=self.service_name,
                            error=str(e))
            raise
    
    async def cleanup(self):
        """清理通知服务资源"""
        try:
            # 停止工作线程
            await self._stop_workers()
            
            # 关闭Gateway客户端
            if self._gateway_client:
                await self._gateway_client.close()
            
            # 清理消息队列
            for queue in self._message_queues.values():
                queue.clear()
            
            # 清理任务
            self._pending_tasks.clear()
            self._processing_tasks.clear()
            self._completed_tasks.clear()
            
            # 清理缓存
            self._message_cache.clear()
            self._cache_timestamps.clear()
            
            # 关闭线程池
            self._thread_pool.shutdown(wait=True)
            
            self.logger.info("通知服务清理完成", service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("通知服务清理失败", 
                            service_name=self.service_name,
                            error=str(e))
    
    async def send_to_user(self, user_id: str, message: NotifyMessage) -> str:
        """
        向单个用户发送消息
        
        Args:
            user_id: 用户ID
            message: 通知消息
            
        Returns:
            str: 任务ID
        """
        target = NotifyTarget(
            target_type=NotifyType.UNICAST,
            target_id=user_id,
            user_ids={user_id}
        )
        
        return await self._enqueue_message(message, target)
    
    async def send_to_users(self, user_ids: List[str], message: NotifyMessage) -> str:
        """
        向多个用户发送消息
        
        Args:
            user_ids: 用户ID列表
            message: 通知消息
            
        Returns:
            str: 任务ID
        """
        target = NotifyTarget(
            target_type=NotifyType.MULTICAST,
            target_id=f"users_{int(time.time() * 1000000)}",
            user_ids=set(user_ids)
        )
        
        return await self._enqueue_message(message, target)
    
    async def send_to_room(self, room_id: str, message: NotifyMessage) -> str:
        """
        向房间发送消息
        
        Args:
            room_id: 房间ID
            message: 通知消息
            
        Returns:
            str: 任务ID
        """
        # 获取房间成员
        user_ids = self._room_members.get(room_id, set())
        
        target = NotifyTarget(
            target_type=NotifyType.MULTICAST,
            target_id=room_id,
            user_ids=user_ids
        )
        
        return await self._enqueue_message(message, target)
    
    async def broadcast(self, message: NotifyMessage) -> str:
        """
        广播消息
        
        Args:
            message: 通知消息
            
        Returns:
            str: 任务ID
        """
        # 获取所有在线用户
        user_ids = set(self._user_connections.keys())
        
        target = NotifyTarget(
            target_type=NotifyType.BROADCAST,
            target_id=f"broadcast_{int(time.time() * 1000000)}",
            user_ids=user_ids
        )
        
        return await self._enqueue_message(message, target)
    
    async def send_to_connection(self, connection_id: str, message: NotifyMessage) -> str:
        """
        向特定连接发送消息
        
        Args:
            connection_id: 连接ID
            message: 通知消息
            
        Returns:
            str: 任务ID
        """
        target = NotifyTarget(
            target_type=NotifyType.UNICAST,
            target_id=connection_id,
            connection_ids={connection_id}
        )
        
        return await self._enqueue_message(message, target)
    
    async def _enqueue_message(self, message: NotifyMessage, target: NotifyTarget) -> str:
        """
        将消息加入队列
        
        Args:
            message: 通知消息
            target: 通知目标
            
        Returns:
            str: 任务ID
        """
        # 创建通知任务
        task = NotifyTask(
            message=message,
            target=target
        )
        
        # 检查消息是否过期
        if message.expires_at and time.time() > message.expires_at:
            self.logger.warning("消息已过期，跳过发送", 
                              message_id=message.message_id,
                              expires_at=message.expires_at)
            return task.task_id
        
        # 检查队列大小
        total_queued = sum(len(queue) for queue in self._message_queues.values())
        if total_queued >= self.config.max_queue_size:
            self.logger.warning("消息队列已满，丢弃消息", 
                              message_id=message.message_id,
                              queue_size=total_queued)
            return task.task_id
        
        # 加入队列
        self._message_queues[message.priority].append(task)
        self._pending_tasks[task.task_id] = task
        
        # 缓存消息
        if self.config.enable_message_cache:
            self._cache_message(message)
        
        self.logger.debug("消息已加入队列", 
                        message_id=message.message_id,
                        task_id=task.task_id,
                        priority=message.priority.name,
                        target_type=target.target_type.name)
        
        return task.task_id
    
    async def _start_workers(self):
        """启动工作线程"""
        self._running = True
        
        for i in range(self.config.worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)
        
        self.logger.info("工作线程启动完成", worker_count=self.config.worker_count)
    
    async def _stop_workers(self):
        """停止工作线程"""
        self._running = False
        
        # 等待所有工作线程完成
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        
        self._workers.clear()
        self.logger.info("工作线程停止完成")
    
    async def _worker_loop(self, worker_id: int):
        """工作线程循环"""
        self.logger.info("工作线程启动", worker_id=worker_id)
        
        while self._running:
            try:
                # 批量处理消息
                tasks = await self._get_batch_tasks()
                
                if tasks:
                    await self._process_batch_tasks(tasks)
                else:
                    # 没有任务时短暂休眠
                    await asyncio.sleep(0.1)
                    
            except Exception as e:
                self.logger.error("工作线程异常", 
                                worker_id=worker_id,
                                error=str(e))
                await asyncio.sleep(1)
        
        self.logger.info("工作线程停止", worker_id=worker_id)
    
    async def _get_batch_tasks(self) -> List[NotifyTask]:
        """获取批量任务"""
        tasks = []
        
        # 按优先级获取任务
        for priority in reversed(MessagePriority):
            queue = self._message_queues[priority]
            
            while queue and len(tasks) < self.config.batch_size:
                task = queue.popleft()
                
                # 检查任务是否过期
                if task.message.expires_at and time.time() > task.message.expires_at:
                    self.logger.warning("任务已过期，跳过处理", 
                                      task_id=task.task_id,
                                      message_id=task.message.message_id)
                    continue
                
                tasks.append(task)
                
                # 更新任务状态
                task.status = NotifyStatus.SENDING
                task.started_at = time.time()
                self._processing_tasks[task.task_id] = task
                
                if task.task_id in self._pending_tasks:
                    del self._pending_tasks[task.task_id]
        
        return tasks
    
    async def _process_batch_tasks(self, tasks: List[NotifyTask]):
        """批量处理任务"""
        try:
            # 执行前置中间件
            for middleware in self._before_send_middlewares:
                await middleware(tasks)
            
            # 并行处理任务
            await asyncio.gather(*[self._process_single_task(task) for task in tasks])
            
            # 执行后置中间件
            for middleware in self._after_send_middlewares:
                await middleware(tasks)
                
        except Exception as e:
            self.logger.error("批量处理任务失败", error=str(e))
            
            # 执行错误中间件
            for middleware in self._error_middlewares:
                await middleware(tasks, e)
    
    async def _process_single_task(self, task: NotifyTask):
        """处理单个任务"""
        start_time = time.time()
        
        try:
            task.attempts += 1
            
            # 根据目标类型处理
            if task.target.target_type == NotifyType.UNICAST:
                await self._send_unicast(task)
            elif task.target.target_type == NotifyType.MULTICAST:
                await self._send_multicast(task)
            elif task.target.target_type == NotifyType.BROADCAST:
                await self._send_broadcast(task)
            
            # 标记任务完成
            task.status = NotifyStatus.SUCCESS
            task.completed_at = time.time()
            
            # 更新统计信息
            self._statistics.total_sent += 1
            self._statistics.total_success += 1
            latency = time.time() - start_time
            self._update_latency_stats(latency)
            
            # 记录监控指标
            if self._monitor_manager:
                await record_notify_metrics(
                    message_type=task.message.message_type,
                    target_type=task.target.target_type.value,
                    latency=latency,
                    success=True
                )
            
            self.logger.debug("任务处理成功", 
                            task_id=task.task_id,
                            message_id=task.message.message_id,
                            latency=latency)
            
        except Exception as e:
            # 处理失败
            task.status = NotifyStatus.FAILED
            task.error_message = str(e)
            task.completed_at = time.time()
            
            self.logger.error("任务处理失败", 
                            task_id=task.task_id,
                            message_id=task.message.message_id,
                            error=str(e))
            
            # 检查是否需要重试
            if task.attempts < task.message.max_retries:
                await self._retry_task(task)
            else:
                # 更新统计信息
                self._statistics.total_failed += 1
                
                # 记录监控指标
                if self._monitor_manager:
                    await record_notify_metrics(
                        message_type=task.message.message_type,
                        target_type=task.target.target_type.value,
                        latency=time.time() - start_time,
                        success=False
                    )
        
        finally:
            # 移动任务到完成队列
            if task.task_id in self._processing_tasks:
                del self._processing_tasks[task.task_id]
            
            self._completed_tasks[task.task_id] = task
    
    async def _send_unicast(self, task: NotifyTask):
        """发送单播消息"""
        target = task.target
        message = task.message
        
        # 编码消息
        encoded_message = encode_message(message.data, self._proto_codec)
        
        # 发送到用户连接
        if target.user_ids:
            user_id = next(iter(target.user_ids))
            connection_ids = self._user_connections.get(user_id, set())
            
            for connection_id in connection_ids:
                await self._send_to_gateway(connection_id, encoded_message)
        
        # 发送到指定连接
        elif target.connection_ids:
            for connection_id in target.connection_ids:
                await self._send_to_gateway(connection_id, encoded_message)
    
    async def _send_multicast(self, task: NotifyTask):
        """发送组播消息"""
        target = task.target
        message = task.message
        
        # 编码消息
        encoded_message = encode_message(message.data, self._proto_codec)
        
        # 收集所有目标连接
        connection_ids = set()
        for user_id in target.user_ids:
            connection_ids.update(self._user_connections.get(user_id, set()))
        
        # 批量发送
        for connection_id in connection_ids:
            await self._send_to_gateway(connection_id, encoded_message)
    
    async def _send_broadcast(self, task: NotifyTask):
        """发送广播消息"""
        target = task.target
        message = task.message
        
        # 编码消息
        encoded_message = encode_message(message.data, self._proto_codec)
        
        # 发送到所有连接
        all_connections = set()
        for connections in self._user_connections.values():
            all_connections.update(connections)
        
        for connection_id in all_connections:
            await self._send_to_gateway(connection_id, encoded_message)
    
    async def _send_to_gateway(self, connection_id: str, message_data: bytes):
        """发送消息到Gateway"""
        try:
            if self._gateway_client:
                await self._gateway_client.send_message(connection_id, message_data)
            else:
                # 直接通过notify_manager发送
                await self._notify_manager.send_message(connection_id, message_data)
                
        except Exception as e:
            self.logger.error("发送消息到Gateway失败", 
                            connection_id=connection_id,
                            error=str(e))
            raise
    
    async def _retry_task(self, task: NotifyTask):
        """重试任务"""
        task.status = NotifyStatus.RETRY
        task.message.retry_count += 1
        
        # 计算重试延迟
        delay = self.config.retry_delay * (self.config.retry_backoff ** task.message.retry_count)
        
        # 延迟后重新加入队列
        await asyncio.sleep(delay)
        
        self._message_queues[task.message.priority].append(task)
        self._pending_tasks[task.task_id] = task
        
        if task.task_id in self._processing_tasks:
            del self._processing_tasks[task.task_id]
        
        self._statistics.total_retry += 1
        
        self.logger.info("任务重试", 
                        task_id=task.task_id,
                        message_id=task.message.message_id,
                        retry_count=task.message.retry_count,
                        delay=delay)
    
    async def _initialize_gateway_client(self):
        """初始化Gateway客户端"""
        try:
            self._gateway_client = GrpcClient(
                service_name="gateway",
                host=self.config.gateway_host,
                port=self.config.gateway_port
            )
            await self._gateway_client.connect()
            
            self.logger.info("Gateway客户端初始化成功")
            
        except Exception as e:
            self.logger.error("Gateway客户端初始化失败", error=str(e))
            # 不抛出异常，可以继续使用notify_manager
    
    def _cache_message(self, message: NotifyMessage):
        """缓存消息"""
        # 检查缓存大小
        if len(self._message_cache) >= 1000:  # 限制缓存大小
            # 清理最老的缓存项
            oldest_key = min(self._cache_timestamps, key=self._cache_timestamps.get)
            del self._message_cache[oldest_key]
            del self._cache_timestamps[oldest_key]
        
        self._message_cache[message.message_id] = message
        self._cache_timestamps[message.message_id] = time.time()
    
    def _update_latency_stats(self, latency: float):
        """更新延迟统计"""
        self._statistics.max_latency = max(self._statistics.max_latency, latency)
        self._statistics.min_latency = min(self._statistics.min_latency, latency)
        
        # 计算平均延迟
        if self._statistics.total_success > 0:
            total_latency = self._statistics.avg_latency * (self._statistics.total_success - 1) + latency
            self._statistics.avg_latency = total_latency / self._statistics.total_success
    
    def register_user_connection(self, user_id: str, connection_id: str):
        """注册用户连接"""
        self._user_connections[user_id].add(connection_id)
        self._connection_users[connection_id] = user_id
        
        self.logger.debug("用户连接注册", 
                        user_id=user_id,
                        connection_id=connection_id)
    
    def unregister_user_connection(self, user_id: str, connection_id: str):
        """注销用户连接"""
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(connection_id)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        
        if connection_id in self._connection_users:
            del self._connection_users[connection_id]
        
        self.logger.debug("用户连接注销", 
                        user_id=user_id,
                        connection_id=connection_id)
    
    def join_room(self, room_id: str, user_id: str):
        """加入房间"""
        self._room_members[room_id].add(user_id)
        
        self.logger.debug("用户加入房间", 
                        room_id=room_id,
                        user_id=user_id)
    
    def leave_room(self, room_id: str, user_id: str):
        """离开房间"""
        if room_id in self._room_members:
            self._room_members[room_id].discard(user_id)
            if not self._room_members[room_id]:
                del self._room_members[room_id]
        
        self.logger.debug("用户离开房间", 
                        room_id=room_id,
                        user_id=user_id)
    
    def get_task_status(self, task_id: str) -> Optional[NotifyTask]:
        """获取任务状态"""
        return (self._pending_tasks.get(task_id) or
                self._processing_tasks.get(task_id) or
                self._completed_tasks.get(task_id))
    
    def get_statistics(self) -> NotifyStatistics:
        """获取统计信息"""
        # 计算QPS
        current_time = time.time()
        time_diff = current_time - self._statistics.last_reset_time
        if time_diff > 0:
            self._statistics.messages_per_second = self._statistics.total_sent / time_diff
        
        return self._statistics
    
    def reset_statistics(self):
        """重置统计信息"""
        self._statistics = NotifyStatistics()
    
    def add_before_send_middleware(self, middleware: Callable):
        """添加发送前中间件"""
        self._before_send_middlewares.append(middleware)
    
    def add_after_send_middleware(self, middleware: Callable):
        """添加发送后中间件"""
        self._after_send_middlewares.append(middleware)
    
    def add_error_middleware(self, middleware: Callable):
        """添加错误中间件"""
        self._error_middlewares.append(middleware)
    
    @property
    def queue_size(self) -> int:
        """获取队列大小"""
        return sum(len(queue) for queue in self._message_queues.values())
    
    @property
    def pending_tasks_count(self) -> int:
        """获取待处理任务数量"""
        return len(self._pending_tasks)
    
    @property
    def processing_tasks_count(self) -> int:
        """获取正在处理的任务数量"""
        return len(self._processing_tasks)
    
    @property
    def completed_tasks_count(self) -> int:
        """获取已完成任务数量"""
        return len(self._completed_tasks)
    
    @property
    def online_users_count(self) -> int:
        """获取在线用户数量"""
        return len(self._user_connections)
    
    @property
    def active_rooms_count(self) -> int:
        """获取活跃房间数量"""
        return len(self._room_members)