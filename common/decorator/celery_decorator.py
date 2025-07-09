"""
Celery装饰器模块
提供定时任务和延时任务的装饰器
"""
from functools import wraps
from typing import Callable, Any, Optional, Union
from datetime import timedelta
from celery import shared_task, current_app
from celery.schedules import crontab, schedule

from common.logger import logger


def periodic_task(
    schedule_expr: Union[str, int, timedelta, crontab], 
    name: Optional[str] = None,
    queue: Optional[str] = None,
    **kwargs
):
    """
    定时任务装饰器
    
    Args:
        schedule_expr: 调度表达式，支持：
            - cron字符串: "*/5 * * * *" (每5分钟)
            - 秒数: 300 (每300秒)
            - timedelta对象: timedelta(minutes=5)
            - crontab对象: crontab(minute='*/5')
        name: 任务名称，默认使用函数名
        queue: 指定队列名称
        **kwargs: 其他Celery任务参数
        
    Example:
        # 每5分钟执行一次
        @periodic_task('*/5 * * * *')
        def sync_data():
            pass
            
        # 每小时执行一次
        @periodic_task(3600)
        def hourly_task():
            pass
    """
    def decorator(func: Callable) -> Callable:
        # 解析调度表达式
        if isinstance(schedule_expr, str):
            # Cron表达式
            parts = schedule_expr.split()
            if len(parts) == 5:
                schedule_obj = crontab(
                    minute=parts[0],
                    hour=parts[1], 
                    day_of_month=parts[2],
                    month_of_year=parts[3],
                    day_of_week=parts[4]
                )
            else:
                raise ValueError(f"无效的cron表达式: {schedule_expr}")
        elif isinstance(schedule_expr, (int, float)):
            # 秒数
            schedule_obj = schedule(run_every=schedule_expr)
        elif isinstance(schedule_expr, timedelta):
            # timedelta对象
            schedule_obj = schedule(run_every=schedule_expr.total_seconds())
        elif isinstance(schedule_expr, crontab):
            # 已经是crontab对象
            schedule_obj = schedule_expr
        else:
            raise ValueError(f"不支持的调度类型: {type(schedule_expr)}")
        
        # 任务名称
        task_name = name or f"{func.__module__}.{func.__name__}"
        
        # 创建任务
        task_kwargs = kwargs.copy()
        if queue:
            task_kwargs['queue'] = queue
            
        @shared_task(name=task_name, **task_kwargs)
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger.info(f"[定时任务] 开始执行: {task_name}")
            try:
                result = func(*args, **kwargs)
                logger.info(f"[定时任务] 执行成功: {task_name}")
                return result
            except Exception as e:
                logger.error(f"[定时任务] 执行失败 {task_name}: {e}", exc_info=True)
                raise
        
        # 保存调度信息
        wrapper.schedule = schedule_obj
        wrapper.task_name = task_name
        
        # 注册到Celery beat
        current_app.conf.beat_schedule[task_name] = {
            'task': task_name,
            'schedule': schedule_obj,
            'options': {'queue': queue} if queue else {}
        }
        
        return wrapper
    return decorator


def delay_task(
    name: Optional[str] = None,
    queue: Optional[str] = None,
    max_retries: int = 3,
    default_retry_delay: int = 60,
    **kwargs
):
    """
    延时任务装饰器
    
    Args:
        name: 任务名称
        queue: 指定队列名称
        max_retries: 最大重试次数
        default_retry_delay: 默认重试延迟(秒)
        **kwargs: 其他Celery任务参数
        
    Example:
        @delay_task(queue='email')
        def send_email(user_id: int, content: str):
            pass
            
        # 延迟60秒执行
        send_email.apply_async(args=[123, 'Hello'], countdown=60)
        
        # 在指定时间执行
        send_email.apply_async(args=[123, 'Hello'], eta=datetime.now() + timedelta(hours=1))
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or f"{func.__module__}.{func.__name__}"
        
        task_kwargs = kwargs.copy()
        task_kwargs.update({
            'name': task_name,
            'bind': True,  # 绑定self参数以访问重试信息
            'max_retries': max_retries,
            'default_retry_delay': default_retry_delay
        })
        if queue:
            task_kwargs['queue'] = queue
            
        @shared_task(**task_kwargs)
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            logger.info(f"[延时任务] 开始执行: {task_name} (重试次数: {self.request.retries})")
            try:
                # 注入task实例，方便在函数内部使用
                kwargs['_task'] = self
                result = func(*args, **kwargs)
                logger.info(f"[延时任务] 执行成功: {task_name}")
                return result
            except Exception as e:
                logger.error(f"[延时任务] 执行失败 {task_name}: {e}", exc_info=True)
                
                # 自动重试
                if self.request.retries < max_retries:
                    logger.warning(
                        f"[延时任务] {task_name} 将在 {default_retry_delay} 秒后重试 "
                        f"({self.request.retries + 1}/{max_retries})"
                    )
                    raise self.retry(exc=e, countdown=default_retry_delay)
                else:
                    logger.error(f"[延时任务] {task_name} 重试次数已达上限，任务失败")
                    raise
                    
        # 添加便捷方法
        wrapper.delay_execute = lambda *args, delay_seconds=0, **kwargs: \
            wrapper.apply_async(args=args, kwargs=kwargs, countdown=delay_seconds)
            
        return wrapper
    return decorator


def task_callback(
    on_success: Optional[Callable] = None,
    on_failure: Optional[Callable] = None,
    on_retry: Optional[Callable] = None
):
    """
    任务回调装饰器
    
    Args:
        on_success: 成功时的回调函数
        on_failure: 失败时的回调函数
        on_retry: 重试时的回调函数
        
    Example:
        def success_handler(result):
            logger.info(f"任务成功: {result}")
            
        def failure_handler(exc, task_id):
            logger.error(f"任务失败: {task_id}, {exc}")
            
        @task_callback(on_success=success_handler, on_failure=failure_handler)
        @delay_task()
        def process_data(data):
            return data * 2
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                if on_success:
                    on_success(result)
                return result
            except Exception as e:
                if on_failure:
                    from celery import current_task
                    on_failure(e, current_task.request.id)
                raise
                
        return wrapper
    return decorator


# 任务优先级常量
class TaskPriority:
    """任务优先级常量"""
    CRITICAL = 10
    HIGH = 7
    NORMAL = 5
    LOW = 3
    IDLE = 1


def retry_task(
    max_retries: int = 3,
    retry_delay: int = 60,
    autoretry_for: tuple = (Exception,),
    name: Optional[str] = None,
    **kwargs
):
    """
    重试任务装饰器
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 重试延迟时间（秒）
        autoretry_for: 需要重试的异常类型
        name: 任务名称
        **kwargs: 其他Celery任务参数
        
    Example:
        @retry_task(max_retries=3, retry_delay=30)
        def unstable_task():
            # 可能失败的任务
            pass
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or f"{func.__module__}.{func.__name__}"
        
        task_kwargs = kwargs.copy()
        task_kwargs.update({
            'name': task_name,
            'bind': True,
            'max_retries': max_retries,
            'default_retry_delay': retry_delay,
            'autoretry_for': autoretry_for
        })
        
        @shared_task(**task_kwargs)
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            logger.info(f"[重试任务] 开始执行: {task_name} (重试次数: {self.request.retries})")
            try:
                kwargs['_task'] = self
                result = func(*args, **kwargs)
                logger.info(f"[重试任务] 执行成功: {task_name}")
                return result
            except Exception as e:
                logger.error(f"[重试任务] 执行失败 {task_name}: {e}", exc_info=True)
                
                # 检查是否需要重试
                if self.request.retries < max_retries and any(isinstance(e, exc_type) for exc_type in autoretry_for):
                    logger.warning(
                        f"[重试任务] {task_name} 将在 {retry_delay} 秒后重试 "
                        f"({self.request.retries + 1}/{max_retries})"
                    )
                    raise self.retry(exc=e, countdown=retry_delay)
                else:
                    logger.error(f"[重试任务] {task_name} 重试次数已达上限，任务失败")
                    raise
                    
        return wrapper
    return decorator


def priority_task(
    priority: int = TaskPriority.NORMAL,
    queue: str = 'default',
    name: Optional[str] = None,
    **kwargs
):
    """
    优先级任务装饰器
    
    Args:
        priority: 任务优先级
        queue: 任务队列
        name: 任务名称
        **kwargs: 其他Celery任务参数
        
    Example:
        @priority_task(priority=TaskPriority.HIGH, queue='important')
        def important_task():
            pass
    """
    def decorator(func: Callable) -> Callable:
        task_name = name or f"{func.__module__}.{func.__name__}"
        
        task_kwargs = kwargs.copy()
        task_kwargs.update({
            'name': task_name,
            'bind': True,
            'priority': priority,
            'queue': queue
        })
        
        @shared_task(**task_kwargs)
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            logger.info(f"[优先级任务] 开始执行: {task_name} (优先级: {priority})")
            try:
                kwargs['_task'] = self
                result = func(*args, **kwargs)
                logger.info(f"[优先级任务] 执行成功: {task_name}")
                return result
            except Exception as e:
                logger.error(f"[优先级任务] 执行失败 {task_name}: {e}", exc_info=True)
                raise
                
        return wrapper
    return decorator


# 保留原有的类型定义以保证兼容性
from typing import List
from dataclasses import dataclass, field
from enum import Enum
import time

class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"

@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_name: str
    task_type: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: int = TaskPriority.NORMAL
    created_time: float = field(default_factory=time.time)
    started_time: Optional[float] = None
    completed_time: Optional[float] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    result: Any = None
    metadata: dict = field(default_factory=dict)

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
    metadata: dict = field(default_factory=dict)

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
        self._tasks: dict = {}
        self._periodic_tasks: dict = {}
        self._statistics: dict = {}
        self._running_tasks: dict = {}
    
    def register_task(self, task_info: TaskInfo):
        """注册任务"""
        self._tasks[task_info.task_id] = task_info
        if task_info.task_name not in self._statistics:
            self._statistics[task_info.task_name] = TaskStatistics()
        logger.info(f"任务注册成功: {task_info.task_name}")
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务信息"""
        return self._tasks.get(task_id)
    
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

def cancel_task(task_id: str) -> bool:
    """取消任务"""
    task = _task_registry.get_task(task_id)
    if task and task.status == TaskStatus.RUNNING:
        task.status = TaskStatus.REVOKED
        logger.info(f"任务已取消: {task_id}")
        return True
    return False