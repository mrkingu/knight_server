"""
任务装饰器模块

提供用于定义Celery任务的装饰器。
"""

import functools
import asyncio
from typing import Callable, Any, Dict, Optional, List, Union
from datetime import datetime, timedelta
from celery import Task
from celery.schedules import crontab
from celery.result import AsyncResult

from common.logger import logger

from .celery_app import get_celery_app


class TaskDecorator:
    """
    任务装饰器基类
    
    提供任务装饰器的基础功能
    """
    
    def __init__(self, name: Optional[str] = None, **kwargs):
        """
        初始化任务装饰器
        
        Args:
            name: 任务名称
            **kwargs: 任务选项
        """
        self.name = name
        self.options = kwargs
        self.celery_app = get_celery_app()
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器调用
        
        Args:
            func: 被装饰的函数
            
        Returns:
            Callable: 装饰后的函数
        """
        raise NotImplementedError("子类必须实现__call__方法")


class DelayTaskDecorator(TaskDecorator):
    """
    延时任务装饰器
    
    用于创建可以延时执行的任务
    """
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器调用
        
        Args:
            func: 被装饰的函数
            
        Returns:
            Callable: 装饰后的函数
        """
        # 设置默认选项
        default_options = {
            'bind': True,
            'autoretry_for': (Exception,),
            'retry_kwargs': {'max_retries': 3, 'countdown': 60},
            'retry_backoff': True,
        }
        
        # 合并选项
        options = {**default_options, **self.options}
        
        # 创建Celery任务
        task_name = self.name or f"{func.__module__}.{func.__name__}"
        celery_task = self.celery_app.task(name=task_name, **options)(func)
        
        # 添加自定义方法
        def apply_async_with_delay(args=None, kwargs=None, countdown=None, eta=None, **options):
            """
            异步执行任务（支持延时）
            
            Args:
                args: 位置参数
                kwargs: 关键字参数
                countdown: 延时秒数
                eta: 执行时间
                **options: 其他选项
                
            Returns:
                AsyncResult: 异步结果
            """
            return celery_task.apply_async(
                args=args, 
                kwargs=kwargs, 
                countdown=countdown, 
                eta=eta, 
                **options
            )
        
        def delay_execution(countdown: int, *args, **kwargs):
            """
            延时执行任务
            
            Args:
                countdown: 延时秒数
                *args: 位置参数
                **kwargs: 关键字参数
                
            Returns:
                AsyncResult: 异步结果
            """
            return apply_async_with_delay(
                args=args, 
                kwargs=kwargs, 
                countdown=countdown
            )
        
        def schedule_at(eta: datetime, *args, **kwargs):
            """
            定时执行任务
            
            Args:
                eta: 执行时间
                *args: 位置参数
                **kwargs: 关键字参数
                
            Returns:
                AsyncResult: 异步结果
            """
            return apply_async_with_delay(
                args=args, 
                kwargs=kwargs, 
                eta=eta
            )
        
        # 添加自定义方法到任务对象
        celery_task.apply_async_with_delay = apply_async_with_delay
        celery_task.delay_execution = delay_execution
        celery_task.schedule_at = schedule_at
        
        return celery_task


class PeriodicTaskDecorator(TaskDecorator):
    """
    周期性任务装饰器
    
    用于创建定时执行的任务
    """
    
    def __init__(self, 
                 cron: Optional[str] = None,
                 interval: Optional[Union[int, timedelta]] = None,
                 **kwargs):
        """
        初始化周期性任务装饰器
        
        Args:
            cron: cron表达式
            interval: 间隔时间
            **kwargs: 其他选项
        """
        super().__init__(**kwargs)
        self.cron = cron
        self.interval = interval
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器调用
        
        Args:
            func: 被装饰的函数
            
        Returns:
            Callable: 装饰后的函数
        """
        # 设置默认选项
        default_options = {
            'bind': True,
        }
        
        # 合并选项
        options = {**default_options, **self.options}
        
        # 创建Celery任务
        task_name = self.name or f"{func.__module__}.{func.__name__}"
        celery_task = self.celery_app.task(name=task_name, **options)(func)
        
        # 注册到Beat调度器
        self._register_periodic_task(celery_task)
        
        return celery_task
    
    def _register_periodic_task(self, task: Task) -> None:
        """
        注册周期性任务到Beat调度器
        
        Args:
            task: Celery任务
        """
        schedule = None
        
        if self.cron:
            # 解析cron表达式
            schedule = self._parse_cron(self.cron)
        elif self.interval:
            # 设置间隔时间
            if isinstance(self.interval, int):
                schedule = self.interval
            else:
                schedule = self.interval.total_seconds()
        
        if schedule:
            # 添加到Beat调度表
            self.celery_app.conf.beat_schedule = getattr(
                self.celery_app.conf, 'beat_schedule', {}
            )
            
            self.celery_app.conf.beat_schedule[task.name] = {
                'task': task.name,
                'schedule': schedule,
            }
            
            logger.info(f"注册周期性任务: {task.name}")
    
    def _parse_cron(self, cron_str: str) -> crontab:
        """
        解析cron表达式
        
        Args:
            cron_str: cron表达式字符串
            
        Returns:
            crontab: cron调度对象
        """
        parts = cron_str.split()
        if len(parts) == 5:
            minute, hour, day, month, day_of_week = parts
            return crontab(
                minute=minute,
                hour=hour,
                day_of_month=day,
                month_of_year=month,
                day_of_week=day_of_week
            )
        else:
            raise ValueError(f"无效的cron表达式: {cron_str}")


class RetryTaskDecorator(TaskDecorator):
    """
    重试任务装饰器
    
    用于创建支持自动重试的任务
    """
    
    def __init__(self, 
                 max_retries: int = 3,
                 countdown: int = 60,
                 autoretry_for: tuple = (Exception,),
                 **kwargs):
        """
        初始化重试任务装饰器
        
        Args:
            max_retries: 最大重试次数
            countdown: 重试间隔
            autoretry_for: 自动重试的异常类型
            **kwargs: 其他选项
        """
        super().__init__(**kwargs)
        self.max_retries = max_retries
        self.countdown = countdown
        self.autoretry_for = autoretry_for
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器调用
        
        Args:
            func: 被装饰的函数
            
        Returns:
            Callable: 装饰后的函数
        """
        # 设置重试选项
        options = {
            'bind': True,
            'autoretry_for': self.autoretry_for,
            'retry_kwargs': {
                'max_retries': self.max_retries,
                'countdown': self.countdown
            },
            'retry_backoff': True,
            **self.options
        }
        
        # 创建Celery任务
        task_name = self.name or f"{func.__module__}.{func.__name__}"
        celery_task = self.celery_app.task(name=task_name, **options)(func)
        
        return celery_task


class PriorityTaskDecorator(TaskDecorator):
    """
    优先级任务装饰器
    
    用于创建具有优先级的任务
    """
    
    def __init__(self, priority: int = 5, queue: str = 'default', **kwargs):
        """
        初始化优先级任务装饰器
        
        Args:
            priority: 任务优先级(0-9，9最高)
            queue: 任务队列
            **kwargs: 其他选项
        """
        super().__init__(**kwargs)
        self.priority = priority
        self.queue = queue
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器调用
        
        Args:
            func: 被装饰的函数
            
        Returns:
            Callable: 装饰后的函数
        """
        # 设置优先级选项
        options = {
            'bind': True,
            'queue': self.queue,
            'priority': self.priority,
            **self.options
        }
        
        # 创建Celery任务
        task_name = self.name or f"{func.__module__}.{func.__name__}"
        celery_task = self.celery_app.task(name=task_name, **options)(func)
        
        return celery_task


class AsyncTaskDecorator(TaskDecorator):
    """
    异步任务装饰器
    
    用于创建支持asyncio的任务
    """
    
    def __call__(self, func: Callable) -> Callable:
        """
        装饰器调用
        
        Args:
            func: 被装饰的函数（异步函数）
            
        Returns:
            Callable: 装饰后的函数
        """
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("async_task装饰器只能用于异步函数")
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            """
            异步函数包装器
            
            Args:
                *args: 位置参数
                **kwargs: 关键字参数
                
            Returns:
                Any: 函数返回值
            """
            # 获取或创建事件循环
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 运行异步函数
            return loop.run_until_complete(func(*args, **kwargs))
        
        # 设置默认选项
        options = {
            'bind': True,
            **self.options
        }
        
        # 创建Celery任务
        task_name = self.name or f"{func.__module__}.{func.__name__}"
        celery_task = self.celery_app.task(name=task_name, **options)(wrapper)
        
        return celery_task


# 装饰器工厂函数

def delay_task(name: Optional[str] = None, **kwargs) -> DelayTaskDecorator:
    """
    延时任务装饰器
    
    Args:
        name: 任务名称
        **kwargs: 任务选项
        
    Returns:
        DelayTaskDecorator: 装饰器实例
    """
    return DelayTaskDecorator(name=name, **kwargs)


def periodic_task(cron: Optional[str] = None, 
                  interval: Optional[Union[int, timedelta]] = None,
                  name: Optional[str] = None,
                  **kwargs) -> PeriodicTaskDecorator:
    """
    周期性任务装饰器
    
    Args:
        cron: cron表达式
        interval: 间隔时间
        name: 任务名称
        **kwargs: 任务选项
        
    Returns:
        PeriodicTaskDecorator: 装饰器实例
    """
    return PeriodicTaskDecorator(cron=cron, interval=interval, name=name, **kwargs)


def retry_task(max_retries: int = 3,
               countdown: int = 60,
               autoretry_for: tuple = (Exception,),
               name: Optional[str] = None,
               **kwargs) -> RetryTaskDecorator:
    """
    重试任务装饰器
    
    Args:
        max_retries: 最大重试次数
        countdown: 重试间隔
        autoretry_for: 自动重试的异常类型
        name: 任务名称
        **kwargs: 任务选项
        
    Returns:
        RetryTaskDecorator: 装饰器实例
    """
    return RetryTaskDecorator(
        max_retries=max_retries,
        countdown=countdown,
        autoretry_for=autoretry_for,
        name=name,
        **kwargs
    )


def priority_task(priority: int = 5,
                  queue: str = 'default',
                  name: Optional[str] = None,
                  **kwargs) -> PriorityTaskDecorator:
    """
    优先级任务装饰器
    
    Args:
        priority: 任务优先级
        queue: 任务队列
        name: 任务名称
        **kwargs: 任务选项
        
    Returns:
        PriorityTaskDecorator: 装饰器实例
    """
    return PriorityTaskDecorator(
        priority=priority,
        queue=queue,
        name=name,
        **kwargs
    )


def async_task(name: Optional[str] = None, **kwargs) -> AsyncTaskDecorator:
    """
    异步任务装饰器
    
    Args:
        name: 任务名称
        **kwargs: 任务选项
        
    Returns:
        AsyncTaskDecorator: 装饰器实例
    """
    return AsyncTaskDecorator(name=name, **kwargs)