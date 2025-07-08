"""
通知队列模块

该模块实现了通知队列，用于实现高效的消息缓冲和批量发送。
支持消息优先级、过期时间和批量处理功能。

主要功能：
- 消息优先级队列
- 消息过期处理
- 批量消息处理
- 队列统计监控
- 背压控制机制
"""

import asyncio
import time
import heapq
from typing import List, Optional, Any, Dict, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict, deque

from common.logger import logger


class MessagePriority(Enum):
    """消息优先级枚举"""
    URGENT = 1      # 紧急消息
    HIGH = 2        # 高优先级
    NORMAL = 3      # 普通优先级
    LOW = 4         # 低优先级


@dataclass
class MessageItem:
    """消息项"""
    message_id: str
    user_ids: List[str]
    message: Any
    priority: MessagePriority
    created_time: float
    expire_time: Optional[float] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __lt__(self, other):
        """用于优先级队列排序"""
        if self.priority.value != other.priority.value:
            return self.priority.value < other.priority.value
        return self.created_time < other.created_time
    
    def is_expired(self) -> bool:
        """检查消息是否过期"""
        if self.expire_time is None:
            return False
        return time.time() > self.expire_time
    
    def get_age(self) -> float:
        """获取消息存活时间"""
        return time.time() - self.created_time


@dataclass
class QueueStatistics:
    """队列统计信息"""
    total_enqueued: int = 0
    total_dequeued: int = 0
    total_expired: int = 0
    total_dropped: int = 0
    current_size: int = 0
    max_size_reached: int = 0
    average_wait_time: float = 0.0
    priority_distribution: Dict[MessagePriority, int] = field(default_factory=lambda: defaultdict(int))


class NotifyQueue:
    """
    通知队列
    
    高效的消息队列实现，支持优先级、过期时间和批量处理。
    用于缓冲通知消息，提高推送性能。
    
    Attributes:
        _queue: 优先级队列
        _max_size: 最大队列大小
        _batch_size: 批量处理大小
        _batch_timeout: 批量处理超时时间
        _statistics: 队列统计信息
        _running: 运行状态
        _condition: 条件变量
    """
    
    def __init__(self, 
                 max_size: int = 10000,
                 batch_size: int = 100,
                 batch_timeout: float = 1.0,
                 enable_batching: bool = True,
                 default_expire_time: float = 300.0):
        """
        初始化通知队列
        
        Args:
            max_size: 最大队列大小
            batch_size: 批量处理大小
            batch_timeout: 批量处理超时时间(秒)
            enable_batching: 是否启用批量处理
            default_expire_time: 默认过期时间(秒)
        """
        self._queue: List[MessageItem] = []
        self._max_size = max_size
        self._batch_size = batch_size
        self._batch_timeout = batch_timeout
        self._enable_batching = enable_batching
        self._default_expire_time = default_expire_time
        
        # 统计信息
        self._statistics = QueueStatistics()
        
        # 运行状态
        self._running = False
        
        # 异步同步原语
        self._condition = asyncio.Condition()
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # 消息ID生成器
        self._message_id_counter = 0
        
        # 批量处理缓冲区
        self._batch_buffer: List[MessageItem] = []
        self._last_batch_time = time.time()
        
        logger.info("通知队列初始化完成",
                   max_size=max_size,
                   batch_size=batch_size,
                   batch_timeout=batch_timeout)
    
    async def start(self):
        """启动通知队列"""
        if self._running:
            logger.warning("通知队列已经在运行中")
            return
        
        self._running = True
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_messages())
        
        logger.info("通知队列启动成功")
    
    async def stop(self):
        """停止通知队列"""
        if not self._running:
            return
        
        self._running = False
        
        # 取消清理任务
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # 通知所有等待的协程
        async with self._condition:
            self._condition.notify_all()
        
        logger.info("通知队列停止成功")
    
    async def enqueue(self, user_ids: List[str], message: Any, 
                     priority: MessagePriority = MessagePriority.NORMAL,
                     expire_time: Optional[float] = None,
                     metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        将消息加入队列
        
        Args:
            user_ids: 用户ID列表
            message: 消息对象
            priority: 消息优先级
            expire_time: 过期时间(秒)
            metadata: 元数据
            
        Returns:
            bool: 是否成功加入队列
        """
        if not self._running:
            logger.warning("通知队列未运行，消息入队失败")
            return False
        
        async with self._condition:
            # 检查队列容量
            if len(self._queue) >= self._max_size:
                logger.warning("通知队列已满，消息被丢弃",
                             current_size=len(self._queue),
                             max_size=self._max_size)
                self._statistics.total_dropped += 1
                return False
            
            # 创建消息项
            message_item = MessageItem(
                message_id=self._generate_message_id(),
                user_ids=user_ids.copy(),
                message=message,
                priority=priority,
                created_time=time.time(),
                expire_time=time.time() + (expire_time or self._default_expire_time),
                metadata=metadata or {}
            )
            
            # 加入优先级队列
            heapq.heappush(self._queue, message_item)
            
            # 更新统计
            self._statistics.total_enqueued += 1
            self._statistics.current_size = len(self._queue)
            self._statistics.max_size_reached = max(
                self._statistics.max_size_reached, 
                len(self._queue)
            )
            self._statistics.priority_distribution[priority] += 1
            
            # 通知等待的协程
            self._condition.notify()
            
            logger.debug("消息入队成功",
                        message_id=message_item.message_id,
                        user_count=len(user_ids),
                        priority=priority.name,
                        queue_size=len(self._queue))
            
            return True
    
    async def dequeue(self, timeout: Optional[float] = None) -> Optional[MessageItem]:
        """
        从队列中取出消息
        
        Args:
            timeout: 超时时间(秒)
            
        Returns:
            Optional[MessageItem]: 消息项，如果队列为空则返回None
        """
        if not self._running:
            return None
        
        async with self._condition:
            # 等待消息或超时
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: bool(self._queue) or not self._running),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                return None
            
            # 如果队列已停止，返回None
            if not self._running:
                return None
            
            # 检查是否有消息
            if not self._queue:
                return None
            
            # 取出优先级最高的消息
            message_item = heapq.heappop(self._queue)
            
            # 检查消息是否过期
            if message_item.is_expired():
                logger.debug("消息已过期，丢弃",
                           message_id=message_item.message_id,
                           age=message_item.get_age())
                self._statistics.total_expired += 1
                return await self.dequeue(timeout)  # 递归获取下一个消息
            
            # 更新统计
            self._statistics.total_dequeued += 1
            self._statistics.current_size = len(self._queue)
            
            # 计算等待时间
            wait_time = message_item.get_age()
            self._statistics.average_wait_time = (
                self._statistics.average_wait_time * 0.9 + wait_time * 0.1
            )
            
            logger.debug("消息出队成功",
                        message_id=message_item.message_id,
                        priority=message_item.priority.name,
                        wait_time=wait_time,
                        queue_size=len(self._queue))
            
            return message_item
    
    async def dequeue_batch(self, max_batch_size: Optional[int] = None) -> List[MessageItem]:
        """
        批量取出消息
        
        Args:
            max_batch_size: 最大批量大小
            
        Returns:
            List[MessageItem]: 消息项列表
        """
        if not self._running:
            return []
        
        batch_size = max_batch_size or self._batch_size
        batch = []
        
        async with self._condition:
            # 批量取出消息
            while len(batch) < batch_size and self._queue:
                message_item = heapq.heappop(self._queue)
                
                # 检查消息是否过期
                if message_item.is_expired():
                    logger.debug("批量处理中消息已过期，丢弃",
                               message_id=message_item.message_id)
                    self._statistics.total_expired += 1
                    continue
                
                batch.append(message_item)
                self._statistics.total_dequeued += 1
            
            # 更新统计
            self._statistics.current_size = len(self._queue)
            
            if batch:
                logger.debug("批量出队成功",
                           batch_size=len(batch),
                           queue_size=len(self._queue))
        
        return batch
    
    async def peek(self) -> Optional[MessageItem]:
        """
        查看队列头部消息（不移除）
        
        Returns:
            Optional[MessageItem]: 消息项，如果队列为空则返回None
        """
        async with self._condition:
            if not self._queue:
                return None
            
            return self._queue[0]
    
    async def size(self) -> int:
        """获取队列大小"""
        async with self._condition:
            return len(self._queue)
    
    async def is_empty(self) -> bool:
        """检查队列是否为空"""
        async with self._condition:
            return len(self._queue) == 0
    
    async def clear(self):
        """清空队列"""
        async with self._condition:
            cleared_count = len(self._queue)
            self._queue.clear()
            self._statistics.current_size = 0
            
            logger.info("队列已清空", cleared_count=cleared_count)
    
    async def remove_expired(self) -> int:
        """
        移除过期消息
        
        Returns:
            int: 移除的消息数量
        """
        async with self._condition:
            expired_count = 0
            valid_messages = []
            
            # 检查所有消息
            while self._queue:
                message_item = heapq.heappop(self._queue)
                if message_item.is_expired():
                    expired_count += 1
                    self._statistics.total_expired += 1
                else:
                    valid_messages.append(message_item)
            
            # 重新构建队列
            self._queue = valid_messages
            heapq.heapify(self._queue)
            self._statistics.current_size = len(self._queue)
            
            if expired_count > 0:
                logger.info("移除过期消息", count=expired_count)
            
            return expired_count
    
    def get_statistics(self) -> QueueStatistics:
        """获取队列统计信息"""
        return self._statistics
    
    def reset_statistics(self):
        """重置统计信息"""
        self._statistics = QueueStatistics()
        logger.info("队列统计信息已重置")
    
    async def get_queue_info(self) -> Dict[str, Any]:
        """
        获取队列详细信息
        
        Returns:
            Dict[str, Any]: 队列信息
        """
        async with self._condition:
            return {
                "size": len(self._queue),
                "max_size": self._max_size,
                "running": self._running,
                "batch_size": self._batch_size,
                "batch_timeout": self._batch_timeout,
                "enable_batching": self._enable_batching,
                "statistics": self._statistics
            }
    
    def _generate_message_id(self) -> str:
        """生成消息ID"""
        self._message_id_counter += 1
        return f"msg_{int(time.time() * 1000)}_{self._message_id_counter}"
    
    async def _cleanup_expired_messages(self):
        """清理过期消息的后台任务"""
        while self._running:
            try:
                await asyncio.sleep(60)  # 每60秒清理一次
                await self.remove_expired()
            except Exception as e:
                logger.error("清理过期消息失败", error=str(e))


# 工厂函数
def create_notify_queue(**kwargs) -> NotifyQueue:
    """
    创建通知队列实例
    
    Args:
        **kwargs: 配置参数
        
    Returns:
        NotifyQueue: 通知队列实例
    """
    return NotifyQueue(**kwargs)