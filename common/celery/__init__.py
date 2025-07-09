"""
Celery任务调度模块

该模块提供了基于Celery的分布式任务调度系统，支持定时任务和延时任务。

主要功能：
- Celery应用初始化：支持Redis/RabbitMQ作为消息队列
- 定时任务：支持cron表达式和interval两种调度方式
- 延时任务：支持指定延迟时间执行任务
- 任务管理：任务注册、取消、查询状态
- 异步支持：与asyncio完美集成
- 任务持久化：任务失败重试机制

使用示例：
```python
from common.celery import periodic_task, delay_task

# 定时任务
@periodic_task(cron="0 0 * * *")  # 每天0点执行
async def daily_reset():
    pass

# 延时任务
@delay_task
async def send_reward(user_id: int, reward_id: int):
    pass

# 调用延时任务
await send_reward.apply_async(args=[1001, 2001], countdown=60)  # 60秒后执行
```
"""

from .celery_app import (
    CeleryApplication, get_celery_app, initialize_celery,
    celery_app_instance
)
from .config import (
    CeleryConfig, RedisConfig, RabbitMQConfig, TaskConfig,
    WorkerConfig, BeatConfig, MonitoringConfig,
    BrokerType, ResultBackendType, SerializerType,
    get_default_celery_config
)
from common.decorator.celery_decorator import (
    delay_task, periodic_task, retry_task, priority_task, task_callback,
    TaskPriority, TaskStatus, TaskInfo, TaskStatistics, TaskRegistry,
    get_task_registry, get_task_info, get_task_statistics, 
    list_running_tasks, list_periodic_tasks, cancel_task
)
from .task_manager import (
    TaskManager, TaskInfo, TaskStatistics, TaskType,
    task_manager
)
from .delay_task import (
    DelayedTaskManager, DelayedTaskInfo, TaskStatus,
    delayed_task_manager, send_reward, send_mail, schedule_maintenance
)
from .beat_schedule import (
    BeatScheduleManager, ScheduleTask, beat_schedule_manager,
    setup_default_scheduled_tasks
)
from .async_task import (
    AsyncTaskManager, AsyncTaskConfig, AsyncTaskMode,
    async_task_manager, async_celery_task,
    async_user_data_sync, async_batch_notification, async_data_export
)

__all__ = [
    # 主要类
    'get_celery_app',
    'initialize_celery',
    'task_manager',
    
    # Celery应用
    'CeleryApplication',
    'celery_app_instance',
    
    # 配置
    'CeleryConfig',
    'RedisConfig',
    'RabbitMQConfig',
    'TaskConfig',
    'WorkerConfig',
    'BeatConfig',
    'MonitoringConfig',
    'BrokerType',
    'ResultBackendType', 
    'SerializerType',
    'get_default_celery_config',
    
    # 装饰器
    'delay_task',
    'periodic_task',
    'retry_task',
    'priority_task',
    'task_callback',
    'TaskPriority',
    'TaskStatus',
    'TaskInfo',
    'TaskStatistics',
    'TaskRegistry',
    'get_task_registry',
    'get_task_info',
    'get_task_statistics',
    'list_running_tasks',
    'list_periodic_tasks',
    'cancel_task',
    
    # 任务管理
    'TaskManager',
    'TaskInfo',
    'TaskStatistics',
    'TaskType',
    
    # 延时任务
    'DelayedTaskManager',
    'DelayedTaskInfo',
    'TaskStatus',
    'delayed_task_manager',
    'send_reward',
    'send_mail',
    'schedule_maintenance',
    
    # 定时任务
    'BeatScheduleManager',
    'ScheduleTask',
    'beat_schedule_manager',
    'setup_default_scheduled_tasks',
    
    # 异步任务
    'AsyncTaskManager',
    'AsyncTaskConfig',
    'AsyncTaskMode',
    'async_task_manager',
    'async_celery_task',
    'async_user_data_sync',
    'async_batch_notification',
    'async_data_export',
]
