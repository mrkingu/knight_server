"""
消息对象池模块

该模块实现了 MessagePool 消息对象池类，用于减少GC压力和提高性能。
支持异步对象获取/释放、自动扩容和对象状态重置。
"""

import asyncio
import time
import weakref
from typing import Type, TypeVar, Optional, Dict, Any, AsyncContextManager, TYPE_CHECKING, List, Callable
from contextlib import asynccontextmanager

if TYPE_CHECKING:
    from typing import Generic
else:
    try:
        from typing import Generic
    except ImportError:
        Generic = object

from .base_proto import BaseMessage
from .exceptions import PoolException, ValidationException, handle_async_proto_exception

T = TypeVar('T', bound=BaseMessage)


class PooledMessage:
    """
    池化消息包装类
    
    支持 with 语句自动归还对象到池中，防止忘记释放对象。
    
    Attributes:
        _message: 被包装的消息对象
        _pool: 所属的对象池
        _acquired: 是否已被获取
    """
    
    __slots__ = ('_message', '_pool', '_acquired', '_acquire_time')
    
    def __init__(self, message: T, pool: 'MessagePool'):
        """
        初始化池化消息
        
        Args:
            message: 被包装的消息对象
            pool: 所属的对象池
        """
        self._message = message
        self._pool = pool
        self._acquired = True
        self._acquire_time = time.time()
    
    @property
    def message(self) -> T:
        """获取消息对象"""
        if not self._acquired:
            raise PoolException("消息对象已被释放", pool_type=type(self._pool).__name__)
        return self._message
    
    @property
    def is_acquired(self) -> bool:
        """检查是否已被获取"""
        return self._acquired
    
    @property
    def acquire_time(self) -> float:
        """获取对象的时间"""
        return self._acquire_time
    
    @property 
    def usage_duration(self) -> float:
        """获取使用时长（秒）"""
        return time.time() - self._acquire_time
    
    async def release(self) -> None:
        """释放对象回池中"""
        if not self._acquired:
            return  # 已经释放过了
        
        self._acquired = False
        await self._pool.release(self._message)
        self._message = None  # 清除引用
        self._pool = None
    
    async def __aenter__(self) -> T:
        """异步上下文管理器入口"""
        return self.message
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """异步上下文管理器出口"""
        await self.release()
    
    def __getattr__(self, name: str) -> Any:
        """代理访问消息对象的属性"""
        if name.startswith('_'):
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")
        return getattr(self.message, name)
    
    def __str__(self) -> str:
        """返回可读的字符串表示"""
        status = "acquired" if self._acquired else "released"
        return f"PooledMessage({status}, duration={self.usage_duration:.3f}s)"
    
    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        return (f"PooledMessage("
                f"message={repr(self._message) if self._acquired else 'None'}, "
                f"acquired={self._acquired}, "
                f"acquire_time={self._acquire_time})")


class MessagePool:
    """
    消息对象池
    
    高效的消息对象池实现，支持：
    - 异步对象获取和释放
    - 预创建对象池
    - 自动扩容策略  
    - 对象重置机制
    - 池状态监控
    - 超时检测
    
    Attributes:
        _message_class: 消息类型
        _pool: 对象池队列
        _max_size: 最大池大小
        _created_count: 已创建对象计数
        _acquired_count: 已获取对象计数
        _acquire_timeout: 获取超时时间
        _lock: 异步锁
        _statistics: 统计信息
    """
    
    __slots__ = (
        '_message_class', '_pool', '_max_size', '_min_size', '_created_count',
        '_acquired_count', '_acquire_timeout', '_lock', '_statistics',
        '_growth_factor', '_shrink_threshold', '_last_shrink_time'
    )
    
    def __init__(self, message_class: Type[T], size: int = 10, max_size: int = 100,
                 acquire_timeout: float = 5.0, growth_factor: float = 1.5):
        """
        初始化消息对象池
        
        Args:
            message_class: 消息类型
            size: 初始池大小
            max_size: 最大池大小
            acquire_timeout: 获取对象超时时间（秒）
            growth_factor: 扩容因子
            
        Raises:
            ValidationException: 参数验证失败时抛出
        """
        if not issubclass(message_class, BaseMessage):
            raise ValidationException("消息类必须继承自BaseMessage",
                                    field_name="message_class",
                                    field_value=message_class.__name__)
        
        if size <= 0:
            raise ValidationException("池大小必须大于0",
                                    field_name="size",
                                    field_value=size)
        
        if max_size < size:
            raise ValidationException("最大池大小不能小于初始大小",
                                    field_name="max_size",
                                    field_value=max_size)
        
        if acquire_timeout <= 0:
            raise ValidationException("获取超时时间必须大于0",
                                    field_name="acquire_timeout",
                                    field_value=acquire_timeout)
        
        if growth_factor <= 1.0:
            raise ValidationException("扩容因子必须大于1.0",
                                    field_name="growth_factor",
                                    field_value=growth_factor)
        
        self._message_class = message_class
        self._pool = asyncio.Queue(maxsize=max_size)
        self._min_size = size
        self._max_size = max_size
        self._created_count = 0
        self._acquired_count = 0
        self._acquire_timeout = acquire_timeout
        self._lock = asyncio.Lock()
        self._growth_factor = growth_factor
        self._shrink_threshold = 0.3  # 使用率低于30%时考虑缩容
        self._last_shrink_time = 0
        
        # 统计信息
        self._statistics = {
            'total_acquired': 0,
            'total_released': 0,
            'total_created': 0,
            'total_reset': 0,
            'acquire_failures': 0,
            'release_failures': 0,
            'peak_size': 0,
            'peak_acquired': 0
        }
    
    @property
    def message_class(self) -> Type[T]:
        """获取消息类型"""
        return self._message_class
    
    @property
    def size(self) -> int:
        """获取当前池大小"""
        return self._pool.qsize()
    
    @property
    def max_size(self) -> int:
        """获取最大池大小"""
        return self._max_size
    
    @property
    def acquired_count(self) -> int:
        """获取已获取对象数量"""
        return self._acquired_count
    
    @property
    def available_count(self) -> int:
        """获取可用对象数量"""
        return self.size
    
    @property
    def utilization(self) -> float:
        """获取池使用率"""
        if self._created_count == 0:
            return 0.0
        return self._acquired_count / self._created_count
    
    @property
    def is_empty(self) -> bool:
        """检查池是否为空"""
        return self._pool.empty()
    
    @property
    def is_full(self) -> bool:
        """检查池是否已满"""
        return self._pool.full()
    
    async def initialize(self) -> None:
        """
        初始化对象池
        
        预创建指定数量的对象放入池中
        """
        async with self._lock:
            for _ in range(self._min_size):
                try:
                    message = await self._create_message()
                    await self._pool.put(message)
                except Exception as e:
                    raise PoolException(f"初始化对象池失败: {e}",
                                      pool_type=self._message_class.__name__) from e
    
    @handle_async_proto_exception
    async def acquire(self, timeout: Optional[float] = None) -> 'PooledMessage':
        """
        获取对象
        
        Args:
            timeout: 超时时间，如果为None则使用默认超时时间
            
        Returns:
            PooledMessage: 池化消息对象
            
        Raises:
            PoolException: 获取失败时抛出
        """
        if timeout is None:
            timeout = self._acquire_timeout
        
        try:
            # 尝试从池中获取对象
            try:
                message = await asyncio.wait_for(self._pool.get(), timeout=timeout)
            except asyncio.TimeoutError:
                # 超时，尝试创建新对象
                async with self._lock:
                    if self._created_count < self._max_size:
                        message = await self._create_message()
                    else:
                        self._statistics['acquire_failures'] += 1
                        raise PoolException(
                            f"获取对象超时，池已满且无法创建新对象",
                            pool_type=self._message_class.__name__,
                            pool_size=self._created_count
                        )
            
            # 重置对象状态
            await self._reset_message(message)
            
            # 更新统计
            async with self._lock:
                self._acquired_count += 1
                self._statistics['total_acquired'] += 1
                self._statistics['peak_acquired'] = max(
                    self._statistics['peak_acquired'], self._acquired_count)
            
            return PooledMessage(message, self)
            
        except Exception as e:
            self._statistics['acquire_failures'] += 1
            if isinstance(e, PoolException):
                raise
            raise PoolException(f"获取对象失败: {e}",
                              pool_type=self._message_class.__name__) from e
    
    @handle_async_proto_exception
    async def release(self, message: T) -> None:
        """
        释放对象回池中
        
        Args:
            message: 要释放的消息对象
        """
        if not isinstance(message, self._message_class):
            raise ValidationException("对象类型不匹配",
                                    field_name="message",
                                    field_value=type(message).__name__)
        
        try:
            # 重置对象状态
            await self._reset_message(message)
            
            # 尝试放回池中
            try:
                self._pool.put_nowait(message)
            except asyncio.QueueFull:
                # 池满，销毁对象
                async with self._lock:
                    self._created_count -= 1
            
            # 更新统计
            async with self._lock:
                self._acquired_count -= 1
                self._statistics['total_released'] += 1
            
            # 检查是否需要缩容
            await self._shrink_if_needed()
            
        except Exception as e:
            self._statistics['release_failures'] += 1
            if isinstance(e, (PoolException, ValidationException)):
                raise
            raise PoolException(f"释放对象失败: {e}",
                              pool_type=self._message_class.__name__) from e
    
    async def _create_message(self) -> T:
        """
        创建新的消息对象
        
        Returns:
            T: 新创建的消息对象
        """
        try:
            # 这里需要子类提供创建方法或使用反射
            # 简化实现，假设消息类有默认构造函数
            message = self._message_class()
            
            self._created_count += 1
            self._statistics['total_created'] += 1
            self._statistics['peak_size'] = max(
                self._statistics['peak_size'], self._created_count)
            
            return message
            
        except Exception as e:
            raise PoolException(f"创建消息对象失败: {e}",
                              pool_type=self._message_class.__name__) from e
    
    async def _reset_message(self, message: T) -> None:
        """
        重置消息对象状态
        
        Args:
            message: 要重置的消息对象
        """
        try:
            if hasattr(message, 'reset'):
                message.reset()
            
            self._statistics['total_reset'] += 1
            
        except Exception as e:
            raise PoolException(f"重置消息对象失败: {e}",
                              pool_type=self._message_class.__name__) from e
    
    async def _shrink_if_needed(self) -> None:
        """根据使用情况缩容池"""
        current_time = time.time()
        
        # 限制缩容频率（至少间隔60秒）
        if current_time - self._last_shrink_time < 60:
            return
        
        async with self._lock:
            # 检查是否需要缩容
            if (self.utilization < self._shrink_threshold and 
                self._created_count > self._min_size):
                
                # 计算需要缩容的数量
                target_size = max(self._min_size, 
                                int(self._created_count * 0.8))
                shrink_count = self._created_count - target_size
                
                # 执行缩容
                for _ in range(min(shrink_count, self.size)):
                    try:
                        self._pool.get_nowait()
                        self._created_count -= 1
                    except asyncio.QueueEmpty:
                        break
                
                self._last_shrink_time = current_time
    
    @asynccontextmanager
    async def get_message(self, timeout: Optional[float] = None) -> T:
        """
        异步上下文管理器方式获取消息
        
        Args:
            timeout: 超时时间
            
        Yields:
            T: 消息对象
        """
        pooled_message = await self.acquire(timeout)
        try:
            yield pooled_message.message
        finally:
            await pooled_message.release()
    
    async def warm_up(self, count: Optional[int] = None) -> None:
        """
        预热对象池
        
        Args:
            count: 预热对象数量，如果为None则预热到最小大小
        """
        if count is None:
            count = self._min_size
        
        count = min(count, self._max_size)
        
        async with self._lock:
            current_size = self.size + self._acquired_count
            needed = count - current_size
            
            for _ in range(max(0, needed)):
                try:
                    message = await self._create_message()
                    await self._pool.put(message)
                except Exception:
                    break  # 创建失败时停止预热
    
    async def clear(self) -> None:
        """清空对象池"""
        async with self._lock:
            # 清空队列
            while not self._pool.empty():
                try:
                    self._pool.get_nowait()
                except asyncio.QueueEmpty:
                    break
            
            # 重置计数
            self._created_count = self._acquired_count
            
            # 重置统计（保留历史峰值）
            self._statistics.update({
                'total_acquired': 0,
                'total_released': 0,
                'total_created': 0,
                'total_reset': 0,
                'acquire_failures': 0,
                'release_failures': 0
            })
    
    async def shutdown(self) -> None:
        """关闭对象池"""
        await self.clear()
        
        async with self._lock:
            self._created_count = 0
            self._acquired_count = 0
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取池统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        return {
            'message_class': self._message_class.__name__,
            'current_size': self.size,
            'max_size': self._max_size,
            'min_size': self._min_size,
            'created_count': self._created_count,
            'acquired_count': self._acquired_count,
            'available_count': self.available_count,
            'utilization': self.utilization,
            'is_empty': self.is_empty,
            'is_full': self.is_full,
            'acquire_timeout': self._acquire_timeout,
            'growth_factor': self._growth_factor,
            **self._statistics
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        获取池健康状态
        
        Returns:
            Dict[str, Any]: 健康状态信息
        """
        stats = self.get_statistics()
        
        # 计算健康得分
        health_score = 100
        issues = []
        
        # 检查使用率
        if stats['utilization'] > 0.9:
            health_score -= 20
            issues.append("使用率过高")
        elif stats['utilization'] < 0.1 and stats['created_count'] > stats['min_size']:
            health_score -= 10
            issues.append("使用率过低")
        
        # 检查获取失败率
        total_attempts = stats['total_acquired'] + stats['acquire_failures']
        if total_attempts > 0:
            failure_rate = stats['acquire_failures'] / total_attempts
            if failure_rate > 0.1:
                health_score -= 30
                issues.append(f"获取失败率过高: {failure_rate:.1%}")
        
        # 检查池是否为空
        if stats['is_empty'] and stats['acquired_count'] == 0:
            health_score -= 15
            issues.append("池为空且无对象被使用")
        
        # 确定健康状态
        if health_score >= 80:
            status = "healthy"
        elif health_score >= 60:
            status = "warning"
        else:
            status = "critical"
        
        return {
            'status': status,
            'health_score': health_score,
            'issues': issues,
            'recommendations': self._get_recommendations(stats, issues)
        }
    
    def _get_recommendations(self, stats: Dict[str, Any], issues: List[str]) -> List[str]:
        """
        根据统计信息和问题生成建议
        
        Args:
            stats: 统计信息
            issues: 发现的问题
            
        Returns:
            List[str]: 建议列表
        """
        recommendations = []
        
        if "使用率过高" in issues:
            recommendations.append("考虑增加池的最大大小")
            recommendations.append("检查是否有对象未正确释放")
        
        if "使用率过低" in issues:
            recommendations.append("考虑减少池的最小大小")
        
        if "获取失败率过高" in issues:
            recommendations.append("增加获取超时时间")
            recommendations.append("增加池的最大大小")
        
        if "池为空且无对象被使用" in issues:
            recommendations.append("执行预热操作")
        
        if not issues:
            recommendations.append("池运行状况良好")
        
        return recommendations
    
    def __str__(self) -> str:
        """返回可读的字符串表示"""
        return (f"MessagePool("
                f"class={self._message_class.__name__}, "
                f"size={self.size}/{self._max_size}, "
                f"acquired={self._acquired_count}, "
                f"utilization={self.utilization:.1%})")
    
    def __repr__(self) -> str:
        """返回详细的字符串表示"""
        return (f"MessagePool("
                f"message_class={self._message_class.__name__}, "
                f"size={self.size}, "
                f"max_size={self._max_size}, "
                f"created_count={self._created_count}, "
                f"acquired_count={self._acquired_count})")


# 工厂函数和便捷方法

async def create_message_pool(message_class: Type[T], size: int = 10, 
                            max_size: int = 100, **kwargs) -> 'MessagePool':
    """
    创建并初始化消息对象池
    
    Args:
        message_class: 消息类型
        size: 初始池大小
        max_size: 最大池大小
        **kwargs: 其他参数
        
    Returns:
        MessagePool: 初始化后的消息对象池
    """
    pool = MessagePool(message_class, size, max_size, **kwargs)
    await pool.initialize()
    return pool