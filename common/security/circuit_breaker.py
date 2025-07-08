"""
熔断器模块

该模块提供熔断器功能，包括：
- 三态熔断器（关闭、开启、半开）
- 基于失败率和响应时间的熔断策略
- 自动恢复机制
- 熔断事件通知
- 分布式熔断状态同步
- 熔断降级处理
"""

import time
import asyncio
from typing import Dict, Any, Optional, List, Callable, Union
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod
import json
import statistics

from common.logger import logger


class CircuitState(Enum):
    """熔断器状态枚举"""
    CLOSED = "closed"        # 关闭状态（正常）
    OPEN = "open"           # 开启状态（熔断）
    HALF_OPEN = "half_open" # 半开状态（探测）


class CircuitBreakerStrategy(Enum):
    """熔断策略枚举"""
    FAILURE_RATE = "failure_rate"                # 失败率策略
    RESPONSE_TIME = "response_time"              # 响应时间策略
    FAILURE_COUNT = "failure_count"              # 失败次数策略
    CONSECUTIVE_FAILURES = "consecutive_failures" # 连续失败策略
    COMPOSITE = "composite"                      # 组合策略


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    failure_threshold: float = 0.5              # 失败率阈值
    response_time_threshold: float = 5.0        # 响应时间阈值（秒）
    failure_count_threshold: int = 10           # 失败次数阈值
    consecutive_failure_threshold: int = 5      # 连续失败阈值
    min_request_count: int = 10                 # 最小请求数（用于计算失败率）
    timeout_duration: int = 60                  # 熔断超时时间（秒）
    half_open_max_calls: int = 3                # 半开状态最大调用次数
    sliding_window_size: int = 100              # 滑动窗口大小
    strategy: CircuitBreakerStrategy = CircuitBreakerStrategy.FAILURE_RATE
    enable_auto_recovery: bool = True           # 启用自动恢复
    enable_distributed_state: bool = True      # 启用分布式状态
    state_sync_interval: int = 5                # 状态同步间隔（秒）
    enable_metrics: bool = True                 # 启用指标收集
    enable_notifications: bool = True           # 启用事件通知


@dataclass
class CallResult:
    """调用结果"""
    success: bool
    response_time: float
    error: Optional[Exception] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class CircuitBreakerMetrics:
    """熔断器指标"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    circuit_opened_count: int = 0
    circuit_closed_count: int = 0
    circuit_half_opened_count: int = 0
    avg_response_time: float = 0.0
    failure_rate: float = 0.0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0


@dataclass
class CircuitBreakerEvent:
    """熔断器事件"""
    event_type: str  # state_change, call_success, call_failure
    circuit_name: str
    old_state: Optional[CircuitState] = None
    new_state: Optional[CircuitState] = None
    call_result: Optional[CallResult] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class CircuitBreakerError(Exception):
    """熔断器相关异常基类"""
    pass


class CircuitOpenError(CircuitBreakerError):
    """熔断器开启异常"""
    pass


class CircuitHalfOpenError(CircuitBreakerError):
    """熔断器半开异常"""
    pass


class CircuitBreakerStrategy:
    """熔断器策略接口"""
    
    @abstractmethod
    def should_open(self, metrics: CircuitBreakerMetrics, 
                   call_results: List[CallResult]) -> bool:
        """判断是否应该开启熔断"""
        pass
    
    @abstractmethod
    def should_close(self, metrics: CircuitBreakerMetrics, 
                    call_results: List[CallResult]) -> bool:
        """判断是否应该关闭熔断"""
        pass


class FailureRateStrategy(CircuitBreakerStrategy):
    """失败率策略"""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
    
    def should_open(self, metrics: CircuitBreakerMetrics, 
                   call_results: List[CallResult]) -> bool:
        """基于失败率判断是否开启熔断"""
        if metrics.total_calls < self.config.min_request_count:
            return False
        
        return metrics.failure_rate >= self.config.failure_threshold
    
    def should_close(self, metrics: CircuitBreakerMetrics, 
                    call_results: List[CallResult]) -> bool:
        """基于失败率判断是否关闭熔断"""
        if not call_results:
            return False
        
        # 检查最近的调用是否都成功
        recent_calls = call_results[-self.config.half_open_max_calls:]
        return all(result.success for result in recent_calls)


class ResponseTimeStrategy(CircuitBreakerStrategy):
    """响应时间策略"""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
    
    def should_open(self, metrics: CircuitBreakerMetrics, 
                   call_results: List[CallResult]) -> bool:
        """基于响应时间判断是否开启熔断"""
        if metrics.total_calls < self.config.min_request_count:
            return False
        
        return metrics.avg_response_time >= self.config.response_time_threshold
    
    def should_close(self, metrics: CircuitBreakerMetrics, 
                    call_results: List[CallResult]) -> bool:
        """基于响应时间判断是否关闭熔断"""
        if not call_results:
            return False
        
        # 检查最近调用的平均响应时间
        recent_calls = call_results[-self.config.half_open_max_calls:]
        if not recent_calls:
            return False
        
        avg_response_time = statistics.mean(r.response_time for r in recent_calls)
        return avg_response_time < self.config.response_time_threshold


class FailureCountStrategy(CircuitBreakerStrategy):
    """失败次数策略"""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
    
    def should_open(self, metrics: CircuitBreakerMetrics, 
                   call_results: List[CallResult]) -> bool:
        """基于失败次数判断是否开启熔断"""
        return metrics.failed_calls >= self.config.failure_count_threshold
    
    def should_close(self, metrics: CircuitBreakerMetrics, 
                    call_results: List[CallResult]) -> bool:
        """基于失败次数判断是否关闭熔断"""
        if not call_results:
            return False
        
        # 检查最近的调用是否都成功
        recent_calls = call_results[-self.config.half_open_max_calls:]
        return all(result.success for result in recent_calls)


class ConsecutiveFailuresStrategy(CircuitBreakerStrategy):
    """连续失败策略"""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
    
    def should_open(self, metrics: CircuitBreakerMetrics, 
                   call_results: List[CallResult]) -> bool:
        """基于连续失败判断是否开启熔断"""
        if len(call_results) < self.config.consecutive_failure_threshold:
            return False
        
        # 检查最近的调用是否连续失败
        recent_calls = call_results[-self.config.consecutive_failure_threshold:]
        return all(not result.success for result in recent_calls)
    
    def should_close(self, metrics: CircuitBreakerMetrics, 
                    call_results: List[CallResult]) -> bool:
        """基于连续失败判断是否关闭熔断"""
        if not call_results:
            return False
        
        # 检查最近的调用是否都成功
        recent_calls = call_results[-self.config.half_open_max_calls:]
        return all(result.success for result in recent_calls)


class CircuitBreaker:
    """熔断器主类"""
    
    def __init__(self, name: str, config: CircuitBreakerConfig, 
                 redis_manager=None):
        """
        初始化熔断器
        
        Args:
            name: 熔断器名称
            config: 熔断器配置
            redis_manager: Redis管理器（用于分布式状态同步）
        """
        self.name = name
        self.config = config
        self.redis_manager = redis_manager
        
        # 状态管理
        self.state = CircuitState.CLOSED
        self.last_state_change = time.time()
        self.half_open_calls = 0
        
        # 指标收集
        self.metrics = CircuitBreakerMetrics()
        self.call_results: List[CallResult] = []
        
        # 策略
        self.strategy = self._create_strategy()
        
        # 事件通知
        self.event_handlers: List[Callable[[CircuitBreakerEvent], None]] = []
        
        # 分布式状态同步
        self._sync_task = None
        if self.config.enable_distributed_state and self.redis_manager:
            self._start_state_sync()
    
    def _create_strategy(self) -> CircuitBreakerStrategy:
        """创建熔断策略"""
        if self.config.strategy == CircuitBreakerStrategy.FAILURE_RATE:
            return FailureRateStrategy(self.config)
        elif self.config.strategy == CircuitBreakerStrategy.RESPONSE_TIME:
            return ResponseTimeStrategy(self.config)
        elif self.config.strategy == CircuitBreakerStrategy.FAILURE_COUNT:
            return FailureCountStrategy(self.config)
        elif self.config.strategy == CircuitBreakerStrategy.CONSECUTIVE_FAILURES:
            return ConsecutiveFailuresStrategy(self.config)
        else:
            return FailureRateStrategy(self.config)
    
    def _start_state_sync(self):
        """启动状态同步任务"""
        if self._sync_task is None:
            self._sync_task = asyncio.create_task(self._sync_state_loop())
    
    async def _sync_state_loop(self):
        """状态同步循环"""
        while True:
            try:
                await self._sync_state_with_redis()
                await asyncio.sleep(self.config.state_sync_interval)
            except Exception as e:
                logger.error(f"状态同步失败: {e}")
                await asyncio.sleep(self.config.state_sync_interval)
    
    async def _sync_state_with_redis(self):
        """与Redis同步状态"""
        if not self.redis_manager:
            return
        
        try:
            state_key = f"circuit_breaker:{self.name}:state"
            
            # 获取当前分布式状态
            distributed_state_data = await self.redis_manager.get(state_key)
            
            if distributed_state_data:
                distributed_state = json.loads(distributed_state_data)
                distributed_circuit_state = CircuitState(distributed_state['state'])
                
                # 如果分布式状态比本地状态更新，更新本地状态
                if distributed_state['timestamp'] > self.last_state_change:
                    if distributed_circuit_state != self.state:
                        old_state = self.state
                        self.state = distributed_circuit_state
                        self.last_state_change = distributed_state['timestamp']
                        
                        # 发送状态变更事件
                        self._emit_event(CircuitBreakerEvent(
                            event_type="state_change",
                            circuit_name=self.name,
                            old_state=old_state,
                            new_state=self.state
                        ))
            
            # 更新Redis中的状态
            local_state_data = {
                'state': self.state.value,
                'timestamp': self.last_state_change,
                'metrics': {
                    'total_calls': self.metrics.total_calls,
                    'successful_calls': self.metrics.successful_calls,
                    'failed_calls': self.metrics.failed_calls,
                    'failure_rate': self.metrics.failure_rate,
                    'avg_response_time': self.metrics.avg_response_time
                }
            }
            
            await self.redis_manager.setex(
                state_key,
                self.config.timeout_duration * 2,
                json.dumps(local_state_data)
            )
            
        except Exception as e:
            logger.error(f"Redis状态同步失败: {e}")
    
    def add_event_handler(self, handler: Callable[[CircuitBreakerEvent], None]):
        """添加事件处理器"""
        self.event_handlers.append(handler)
    
    def remove_event_handler(self, handler: Callable[[CircuitBreakerEvent], None]):
        """移除事件处理器"""
        if handler in self.event_handlers:
            self.event_handlers.remove(handler)
    
    def _emit_event(self, event: CircuitBreakerEvent):
        """发送事件"""
        if self.config.enable_notifications:
            for handler in self.event_handlers:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"事件处理器执行失败: {e}")
    
    def _update_metrics(self, call_result: CallResult):
        """更新指标"""
        self.metrics.total_calls += 1
        
        if call_result.success:
            self.metrics.successful_calls += 1
            self.metrics.last_success_time = call_result.timestamp
        else:
            self.metrics.failed_calls += 1
            self.metrics.last_failure_time = call_result.timestamp
        
        # 计算失败率
        if self.metrics.total_calls > 0:
            self.metrics.failure_rate = self.metrics.failed_calls / self.metrics.total_calls
        
        # 更新调用结果历史
        self.call_results.append(call_result)
        
        # 限制历史记录大小
        if len(self.call_results) > self.config.sliding_window_size:
            self.call_results = self.call_results[-self.config.sliding_window_size:]
        
        # 计算平均响应时间
        if self.call_results:
            self.metrics.avg_response_time = statistics.mean(
                r.response_time for r in self.call_results
            )
    
    def _should_allow_call(self) -> bool:
        """判断是否应该允许调用"""
        current_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # 检查是否应该进入半开状态
            if (current_time - self.last_state_change) >= self.config.timeout_duration:
                self._change_state(CircuitState.HALF_OPEN)
                return True
            return False
        elif self.state == CircuitState.HALF_OPEN:
            # 限制半开状态的调用次数
            return self.half_open_calls < self.config.half_open_max_calls
        
        return False
    
    def _change_state(self, new_state: CircuitState):
        """改变熔断器状态"""
        if new_state == self.state:
            return
        
        old_state = self.state
        self.state = new_state
        self.last_state_change = time.time()
        
        # 重置半开调用计数
        if new_state == CircuitState.HALF_OPEN:
            self.half_open_calls = 0
        
        # 更新指标
        if new_state == CircuitState.OPEN:
            self.metrics.circuit_opened_count += 1
        elif new_state == CircuitState.CLOSED:
            self.metrics.circuit_closed_count += 1
        elif new_state == CircuitState.HALF_OPEN:
            self.metrics.circuit_half_opened_count += 1
        
        # 发送状态变更事件
        self._emit_event(CircuitBreakerEvent(
            event_type="state_change",
            circuit_name=self.name,
            old_state=old_state,
            new_state=new_state
        ))
        
        logger.info(f"熔断器 {self.name} 状态变更: {old_state.value} -> {new_state.value}")
    
    def _evaluate_state(self, call_result: CallResult):
        """评估状态变更"""
        if self.state == CircuitState.CLOSED:
            # 检查是否应该开启熔断
            if self.strategy.should_open(self.metrics, self.call_results):
                self._change_state(CircuitState.OPEN)
        elif self.state == CircuitState.HALF_OPEN:
            if call_result.success:
                # 检查是否应该关闭熔断
                if self.strategy.should_close(self.metrics, self.call_results):
                    self._change_state(CircuitState.CLOSED)
            else:
                # 失败则重新开启熔断
                self._change_state(CircuitState.OPEN)
    
    async def call(self, func: Callable, *args, **kwargs):
        """
        通过熔断器调用函数
        
        Args:
            func: 要调用的函数
            *args: 函数参数
            **kwargs: 函数关键字参数
            
        Returns:
            函数返回值
            
        Raises:
            CircuitOpenError: 熔断器开启
            CircuitHalfOpenError: 熔断器半开且超过调用限制
        """
        if not self._should_allow_call():
            if self.state == CircuitState.OPEN:
                raise CircuitOpenError(f"熔断器 {self.name} 处于开启状态")
            elif self.state == CircuitState.HALF_OPEN:
                raise CircuitHalfOpenError(f"熔断器 {self.name} 处于半开状态，超过调用限制")
        
        # 记录半开状态的调用次数
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_calls += 1
        
        # 执行调用
        start_time = time.time()
        call_result = None
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # 记录成功调用
            call_result = CallResult(
                success=True,
                response_time=time.time() - start_time
            )
            
            self._update_metrics(call_result)
            self._evaluate_state(call_result)
            
            # 发送调用成功事件
            self._emit_event(CircuitBreakerEvent(
                event_type="call_success",
                circuit_name=self.name,
                call_result=call_result
            ))
            
            return result
            
        except Exception as e:
            # 记录失败调用
            call_result = CallResult(
                success=False,
                response_time=time.time() - start_time,
                error=e
            )
            
            self._update_metrics(call_result)
            self._evaluate_state(call_result)
            
            # 发送调用失败事件
            self._emit_event(CircuitBreakerEvent(
                event_type="call_failure",
                circuit_name=self.name,
                call_result=call_result
            ))
            
            raise e
    
    def get_state(self) -> CircuitState:
        """获取当前状态"""
        return self.state
    
    def get_metrics(self) -> CircuitBreakerMetrics:
        """获取指标"""
        return self.metrics
    
    def reset(self):
        """重置熔断器"""
        self.state = CircuitState.CLOSED
        self.last_state_change = time.time()
        self.half_open_calls = 0
        self.metrics = CircuitBreakerMetrics()
        self.call_results.clear()
        
        # 发送状态变更事件
        self._emit_event(CircuitBreakerEvent(
            event_type="state_change",
            circuit_name=self.name,
            old_state=CircuitState.OPEN,
            new_state=CircuitState.CLOSED
        ))
        
        logger.info(f"熔断器 {self.name} 已重置")
    
    def force_open(self):
        """强制开启熔断"""
        self._change_state(CircuitState.OPEN)
    
    def force_close(self):
        """强制关闭熔断"""
        self._change_state(CircuitState.CLOSED)
    
    def force_half_open(self):
        """强制半开熔断"""
        self._change_state(CircuitState.HALF_OPEN)
    
    async def close(self):
        """关闭熔断器"""
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass


class CircuitBreakerManager:
    """熔断器管理器"""
    
    def __init__(self, redis_manager=None):
        self.redis_manager = redis_manager
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
    
    def create_circuit_breaker(self, name: str, config: CircuitBreakerConfig) -> CircuitBreaker:
        """
        创建熔断器
        
        Args:
            name: 熔断器名称
            config: 熔断器配置
            
        Returns:
            CircuitBreaker: 熔断器实例
        """
        if name in self.circuit_breakers:
            logger.warning(f"熔断器 {name} 已存在")
            return self.circuit_breakers[name]
        
        circuit_breaker = CircuitBreaker(name, config, self.redis_manager)
        self.circuit_breakers[name] = circuit_breaker
        
        logger.info(f"已创建熔断器: {name}")
        return circuit_breaker
    
    def get_circuit_breaker(self, name: str) -> Optional[CircuitBreaker]:
        """
        获取熔断器
        
        Args:
            name: 熔断器名称
            
        Returns:
            Optional[CircuitBreaker]: 熔断器实例
        """
        return self.circuit_breakers.get(name)
    
    def remove_circuit_breaker(self, name: str):
        """
        移除熔断器
        
        Args:
            name: 熔断器名称
        """
        if name in self.circuit_breakers:
            circuit_breaker = self.circuit_breakers[name]
            asyncio.create_task(circuit_breaker.close())
            del self.circuit_breakers[name]
            logger.info(f"已移除熔断器: {name}")
    
    def list_circuit_breakers(self) -> List[str]:
        """
        列出所有熔断器名称
        
        Returns:
            List[str]: 熔断器名称列表
        """
        return list(self.circuit_breakers.keys())
    
    def get_all_metrics(self) -> Dict[str, CircuitBreakerMetrics]:
        """
        获取所有熔断器的指标
        
        Returns:
            Dict[str, CircuitBreakerMetrics]: 熔断器指标字典
        """
        return {
            name: cb.get_metrics() 
            for name, cb in self.circuit_breakers.items()
        }
    
    def reset_all(self):
        """重置所有熔断器"""
        for circuit_breaker in self.circuit_breakers.values():
            circuit_breaker.reset()
    
    async def close_all(self):
        """关闭所有熔断器"""
        tasks = []
        for circuit_breaker in self.circuit_breakers.values():
            tasks.append(circuit_breaker.close())
        
        if tasks:
            await asyncio.gather(*tasks)
        
        self.circuit_breakers.clear()


# 默认配置实例
default_config = CircuitBreakerConfig()

# 默认熔断器管理器实例
_default_manager = None


def get_circuit_breaker_manager(redis_manager=None) -> CircuitBreakerManager:
    """
    获取熔断器管理器实例
    
    Args:
        redis_manager: Redis管理器
        
    Returns:
        CircuitBreakerManager: 熔断器管理器实例
    """
    global _default_manager
    
    if _default_manager is None:
        _default_manager = CircuitBreakerManager(redis_manager)
    
    return _default_manager


# 便捷函数
def create_circuit_breaker(name: str, config: CircuitBreakerConfig = None) -> CircuitBreaker:
    """创建熔断器的便捷函数"""
    if config is None:
        config = default_config
    
    manager = get_circuit_breaker_manager()
    return manager.create_circuit_breaker(name, config)


def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    """获取熔断器的便捷函数"""
    manager = get_circuit_breaker_manager()
    return manager.get_circuit_breaker(name)


async def circuit_breaker_call(name: str, func: Callable, *args, **kwargs):
    """通过熔断器调用函数的便捷函数"""
    circuit_breaker = get_circuit_breaker(name)
    if circuit_breaker is None:
        raise CircuitBreakerError(f"熔断器 {name} 不存在")
    
    return await circuit_breaker.call(func, *args, **kwargs)


def circuit_breaker_decorator(name: str, config: CircuitBreakerConfig = None):
    """熔断器装饰器"""
    def decorator(func):
        # 创建熔断器
        circuit_breaker = create_circuit_breaker(name, config)
        
        async def async_wrapper(*args, **kwargs):
            return await circuit_breaker.call(func, *args, **kwargs)
        
        def sync_wrapper(*args, **kwargs):
            return asyncio.run(circuit_breaker.call(func, *args, **kwargs))
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator