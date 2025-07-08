"""
Celery任务装饰器模块

该模块提供Celery任务相关的装饰器，简化分布式任务的定义和管理。
支持定时任务、延时任务和重试任务等多种类型。

主要功能：
- @periodic_task: 定时任务装饰器
- @delay_task: 延时任务装饰器
- @retry_task: 带重试的任务装饰器
- 任务状态监控
- 任务执行统计
"""

import asyncio
import functools
import time
import uuid
from typing import Callable, Any, Dict, Optional, Union, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

from common.logger import logger


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"


class TaskPriority(Enum):
    """任务优先级枚举"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_name: str
    task_type: str
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    created_time: float = field(default_factory=time.time)
    started_time: Optional[float] = None
    completed_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CronSchedule:
    """Cron调度配置"""
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"
    
    def to_cron_string(self) -> str:
        """转换为cron字符串"""
        return f"{self.minute} {self.hour} {self.day_of_month} {self.month_of_year} {self.day_of_week}"


@dataclass
class PeriodicTaskConfig:
    """定时任务配置"""
    task_name: str
    cron_schedule: Optional[CronSchedule] = None
    interval: Optional[timedelta] = None
    enabled: bool = True
    max_instances: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskStatistics:
    """任务统计信息"""
    total_executed: int = 0
    total_success: int = 0
    total_failed: int = 0
    total_retries: int = 0
    average_execution_time: float = 0.0
    last_execution_time: float = 0.0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0


class TaskRegistry:
    """任务注册表"""
    
    def __init__(self):
        self._tasks: Dict[str, TaskInfo] = {}
        self._periodic_tasks: Dict[str, PeriodicTaskConfig] = {}
        self._statistics: Dict[str, TaskStatistics] = {}
        self._running_tasks: Dict[str, TaskInfo] = {}
    
    def register_task(self, task_info: TaskInfo):
        """注册任务"""
        self._tasks[task_info.task_id] = task_info
        if task_info.task_name not in self._statistics:
            self._statistics[task_info.task_name] = TaskStatistics()
        logger.info("任务注册成功", task_id=task_info.task_id, task_name=task_info.task_name)
    
    def register_periodic_task(self, config: PeriodicTaskConfig):
        """注册定时任务"""
        self._periodic_tasks[config.task_name] = config
        logger.info("定时任务注册成功", task_name=config.task_name)
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        return self._tasks.get(task_id)
    
    def get_periodic_task(self, task_name: str) -> Optional[PeriodicTaskConfig]:
        """获取定时任务配置"""
        return self._periodic_tasks.get(task_name)
    
    def update_task_status(self, task_id: str, status: TaskStatus, 
                          error_message: Optional[str] = None,
                          result: Any = None):
        """更新任务状态"""
        task = self._tasks.get(task_id)
        if task:
            task.status = status
            if error_message:
                task.error_message = error_message
            if result is not None:
                task.result = result
            
            current_time = time.time()
            if status == TaskStatus.RUNNING:
                task.started_time = current_time
                self._running_tasks[task_id] = task
            elif status in [TaskStatus.SUCCESS, TaskStatus.FAILURE]:
                task.completed_time = current_time
                self._running_tasks.pop(task_id, None)
                self._update_statistics(task)
    
    def _update_statistics(self, task: TaskInfo):
        """更新任务统计信息"""
        stats = self._statistics.get(task.task_name)
        if not stats:
            stats = TaskStatistics()
            self._statistics[task.task_name] = stats
        
        stats.total_executed += 1
        stats.last_execution_time = task.completed_time or time.time()
        
        if task.status == TaskStatus.SUCCESS:
            stats.total_success += 1
            stats.last_success_time = stats.last_execution_time
        elif task.status == TaskStatus.FAILURE:
            stats.total_failed += 1
            stats.last_failure_time = stats.last_execution_time
        
        stats.total_retries += task.retry_count
        
        # 计算平均执行时间
        if task.started_time and task.completed_time:
            execution_time = task.completed_time - task.started_time
            if stats.total_executed == 1:
                stats.average_execution_time = execution_time
            else:
                stats.average_execution_time = (
                    stats.average_execution_time * 0.9 + execution_time * 0.1
                )
    
    def get_statistics(self, task_name: str) -> Optional[TaskStatistics]:
        """获取任务统计信息"""
        return self._statistics.get(task_name)
    
    def list_running_tasks(self) -> List[TaskInfo]:
        """列出正在运行的任务"""
        return list(self._running_tasks.values())
    
    def list_periodic_tasks(self) -> List[PeriodicTaskConfig]:
        """列出所有定时任务"""
        return list(self._periodic_tasks.values())


# 全局任务注册表
_task_registry = TaskRegistry()


def periodic_task(cron: Optional[str] = None,
                 interval: Optional[Union[int, timedelta]] = None,
                 name: Optional[str] = None,
                 enabled: bool = True,
                 max_instances: int = 1,
                 **kwargs) -> Callable:
    """
    定时任务装饰器
    
    Args:
        cron: cron表达式，格式："分 时 日 月 周"
        interval: 间隔时间（秒或timedelta对象）
        name: 任务名称，默认使用函数名
        enabled: 是否启用
        max_instances: 最大并发实例数
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @periodic_task(cron="0 0 * * *")  # 每天0点执行
    async def daily_reset():
        pass
    
    @periodic_task(interval=60)  # 每60秒执行一次
    async def heartbeat_check():
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or func.__name__
        
        # 解析cron表达式
        cron_schedule = None
        if cron:
            parts = cron.split()
            if len(parts) == 5:
                cron_schedule = CronSchedule(
                    minute=parts[0],
                    hour=parts[1],
                    day_of_month=parts[2],
                    month_of_year=parts[3],
                    day_of_week=parts[4]
                )
        
        # 处理间隔时间
        interval_delta = None
        if interval:
            if isinstance(interval, int):
                interval_delta = timedelta(seconds=interval)
            elif isinstance(interval, timedelta):
                interval_delta = interval
        
        # 创建定时任务配置
        config = PeriodicTaskConfig(
            task_name=task_name,
            cron_schedule=cron_schedule,
            interval=interval_delta,
            enabled=enabled,
            max_instances=max_instances,
            metadata=kwargs
        )
        
        # 注册定时任务
        _task_registry.register_periodic_task(config)
        
        # 包装函数
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 创建任务信息
            task_id = str(uuid.uuid4())
            task_info = TaskInfo(
                task_id=task_id,
                task_name=task_name,
                task_type="periodic",
                args=args,
                kwargs=kwargs
            )
            
            # 注册和执行任务
            return await _execute_task(func, task_info, args, kwargs)
        
        # 添加任务信息到函数
        wrapper._periodic_task_config = config
        wrapper.task_name = task_name
        
        logger.info("定时任务装饰完成",
                   task_name=task_name,
                   cron=cron,
                   interval=interval)
        
        return wrapper
    
    return decorator


def delay_task(countdown: Optional[int] = None,
              eta: Optional[datetime] = None,
              name: Optional[str] = None,
              priority: TaskPriority = TaskPriority.NORMAL,
              **kwargs) -> Callable:
    """
    延时任务装饰器
    
    Args:
        countdown: 延迟执行时间（秒）
        eta: 指定执行时间
        name: 任务名称，默认使用函数名
        priority: 任务优先级
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @delay_task(countdown=60)  # 延迟60秒执行
    async def send_reward(user_id: str, reward_id: str):
        pass
    
    # 调用方式
    await send_reward.apply_async(args=["user123", "reward456"])
    ```
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or func.__name__
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 创建任务信息
            task_id = str(uuid.uuid4())
            task_info = TaskInfo(
                task_id=task_id,
                task_name=task_name,
                task_type="delay",
                args=args,
                kwargs=kwargs,
                priority=priority
            )
            
            # 计算延迟时间
            delay_seconds = 0
            if countdown:
                delay_seconds = countdown
            elif eta:
                delay_seconds = max(0, (eta - datetime.now()).total_seconds())
            
            # 延迟执行
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
            
            # 执行任务
            return await _execute_task(func, task_info, args, kwargs)
        
        # 添加异步执行方法
        async def apply_async(args=None, kwargs=None, countdown=None, eta=None):
            """异步执行任务"""
            args = args or ()
            kwargs = kwargs or {}
            
            # 创建任务信息
            task_id = str(uuid.uuid4())
            task_info = TaskInfo(
                task_id=task_id,
                task_name=task_name,
                task_type="delay",
                args=args,
                kwargs=kwargs,
                priority=priority
            )
            
            # 计算延迟时间
            delay_seconds = 0
            if countdown:
                delay_seconds = countdown
            elif eta:
                delay_seconds = max(0, (eta - datetime.now()).total_seconds())
            
            # 创建异步任务
            async def delayed_execution():
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                return await _execute_task(func, task_info, args, kwargs)
            
            # 在后台执行
            task = asyncio.create_task(delayed_execution())
            return task_info.task_id, task
        
        wrapper.apply_async = apply_async
        wrapper.task_name = task_name
        
        logger.info("延时任务装饰完成",
                   task_name=task_name,
                   countdown=countdown,
                   priority=priority.name)
        
        return wrapper
    
    return decorator


def retry_task(max_retries: int = 3,
              retry_delay: Union[int, float] = 1.0,
              exponential_backoff: bool = True,
              retry_exceptions: Optional[List[type]] = None,
              name: Optional[str] = None,
              **kwargs) -> Callable:
    """
    带重试的任务装饰器
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 重试延迟时间（秒）
        exponential_backoff: 是否使用指数退避
        retry_exceptions: 需要重试的异常类型列表
        name: 任务名称，默认使用函数名
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @retry_task(max_retries=3, retry_delay=2.0, exponential_backoff=True)
    async def unreliable_task():
        # 可能失败的任务
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or func.__name__
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 创建任务信息
            task_id = str(uuid.uuid4())
            task_info = TaskInfo(
                task_id=task_id,
                task_name=task_name,
                task_type="retry",
                args=args,
                kwargs=kwargs,
                max_retries=max_retries
            )
            
            # 执行任务（带重试）
            return await _execute_task_with_retry(
                func, task_info, args, kwargs,
                max_retries, retry_delay, exponential_backoff, retry_exceptions
            )
        
        wrapper.task_name = task_name
        wrapper.max_retries = max_retries
        
        logger.info("重试任务装饰完成",
                   task_name=task_name,
                   max_retries=max_retries,
                   retry_delay=retry_delay)
        
        return wrapper
    
    return decorator


def priority_task(priority: TaskPriority = TaskPriority.NORMAL,
                 name: Optional[str] = None,
                 **kwargs) -> Callable:
    """
    优先级任务装饰器
    
    Args:
        priority: 任务优先级
        name: 任务名称，默认使用函数名
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @priority_task(priority=TaskPriority.HIGH)
    async def important_task():
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or func.__name__
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 创建任务信息
            task_id = str(uuid.uuid4())
            task_info = TaskInfo(
                task_id=task_id,
                task_name=task_name,
                task_type="priority",
                args=args,
                kwargs=kwargs,
                priority=priority
            )
            
            # 执行任务
            return await _execute_task(func, task_info, args, kwargs)
        
        wrapper.task_name = task_name
        wrapper.priority = priority
        
        logger.info("优先级任务装饰完成",
                   task_name=task_name,
                   priority=priority.name)
        
        return wrapper
    
    return decorator


async def _execute_task(func: Callable, task_info: TaskInfo, 
                       args: tuple, kwargs: dict) -> Any:
    """执行任务"""
    # 注册任务
    _task_registry.register_task(task_info)
    
    # 更新状态为运行中
    _task_registry.update_task_status(task_info.task_id, TaskStatus.RUNNING)
    
    try:
        # 执行任务函数
        result = await func(*args, **kwargs)
        
        # 更新状态为成功
        _task_registry.update_task_status(
            task_info.task_id, TaskStatus.SUCCESS, result=result
        )
        
        logger.debug("任务执行成功",
                   task_id=task_info.task_id,
                   task_name=task_info.task_name)
        
        return result
        
    except Exception as e:
        # 更新状态为失败
        _task_registry.update_task_status(
            task_info.task_id, TaskStatus.FAILURE, error_message=str(e)
        )
        
        logger.error("任务执行失败",
                   task_id=task_info.task_id,
                   task_name=task_info.task_name,
                   error=str(e))
        
        raise


async def _execute_task_with_retry(func: Callable, task_info: TaskInfo,
                                 args: tuple, kwargs: dict,
                                 max_retries: int, retry_delay: float,
                                 exponential_backoff: bool,
                                 retry_exceptions: Optional[List[type]]) -> Any:
    """带重试的任务执行"""
    # 注册任务
    _task_registry.register_task(task_info)
    
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            # 更新状态
            if attempt == 0:
                _task_registry.update_task_status(task_info.task_id, TaskStatus.RUNNING)
            else:
                _task_registry.update_task_status(task_info.task_id, TaskStatus.RETRY)
                task_info.retry_count = attempt
            
            # 执行任务函数
            result = await func(*args, **kwargs)
            
            # 更新状态为成功
            _task_registry.update_task_status(
                task_info.task_id, TaskStatus.SUCCESS, result=result
            )
            
            logger.debug("任务执行成功",
                       task_id=task_info.task_id,
                       task_name=task_info.task_name,
                       attempt=attempt + 1)
            
            return result
            
        except Exception as e:
            last_exception = e
            
            # 检查是否需要重试
            should_retry = attempt < max_retries
            if retry_exceptions:
                should_retry = should_retry and any(isinstance(e, exc_type) for exc_type in retry_exceptions)
            
            if should_retry:
                # 计算重试延迟
                delay = retry_delay
                if exponential_backoff:
                    delay = retry_delay * (2 ** attempt)
                
                logger.warning("任务执行失败，准备重试",
                             task_id=task_info.task_id,
                             task_name=task_info.task_name,
                             attempt=attempt + 1,
                             error=str(e),
                             retry_delay=delay)
                
                await asyncio.sleep(delay)
            else:
                # 更新状态为失败
                _task_registry.update_task_status(
                    task_info.task_id, TaskStatus.FAILURE, error_message=str(e)
                )
                
                logger.error("任务最终执行失败",
                           task_id=task_info.task_id,
                           task_name=task_info.task_name,
                           total_attempts=attempt + 1,
                           error=str(e))
                
                break
    
    # 抛出最后一个异常
    if last_exception:
        raise last_exception


def get_task_registry() -> TaskRegistry:
    """获取任务注册表"""
    return _task_registry


def get_task_info(task_id: str) -> Optional[TaskInfo]:
    """获取任务信息"""
    return _task_registry.get_task(task_id)


def get_task_statistics(task_name: str) -> Optional[TaskStatistics]:
    """获取任务统计信息"""
    return _task_registry.get_statistics(task_name)


def list_running_tasks() -> List[TaskInfo]:
    """列出正在运行的任务"""
    return _task_registry.list_running_tasks()


def list_periodic_tasks() -> List[PeriodicTaskConfig]:
    """列出所有定时任务"""
    return _task_registry.list_periodic_tasks()


async def cancel_task(task_id: str) -> bool:
    """取消任务"""
    task = _task_registry.get_task(task_id)
    if task and task.status == TaskStatus.RUNNING:
        _task_registry.update_task_status(task_id, TaskStatus.REVOKED)
        logger.info("任务已取消", task_id=task_id, task_name=task.task_name)
        return True
    return False