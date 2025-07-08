"""
任务管理器模块

提供Celery任务的统一管理功能，包括任务监控、统计和控制。
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from celery.result import AsyncResult
from celery import states

from common.logger import logger

from .celery_app import get_celery_app, celery_app_instance
from .beat_schedule import beat_schedule_manager
from .delay_task import delayed_task_manager
from .async_task import async_task_manager


class TaskType(Enum):
    """任务类型枚举"""
    DELAYED = "delayed"      # 延时任务
    PERIODIC = "periodic"    # 周期性任务
    ASYNC = "async"         # 异步任务
    NORMAL = "normal"       # 普通任务


@dataclass
class TaskStatistics:
    """任务统计信息"""
    total_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    retried_tasks: int = 0
    revoked_tasks: int = 0
    
    # 按类型统计
    delayed_tasks: int = 0
    periodic_tasks: int = 0
    async_tasks: int = 0
    normal_tasks: int = 0
    
    # 性能统计
    average_runtime: float = 0.0
    max_runtime: float = 0.0
    min_runtime: float = 0.0
    
    # 时间统计
    last_hour_tasks: int = 0
    last_day_tasks: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total_tasks': self.total_tasks,
            'pending_tasks': self.pending_tasks,
            'running_tasks': self.running_tasks,
            'successful_tasks': self.successful_tasks,
            'failed_tasks': self.failed_tasks,
            'retried_tasks': self.retried_tasks,
            'revoked_tasks': self.revoked_tasks,
            'delayed_tasks': self.delayed_tasks,
            'periodic_tasks': self.periodic_tasks,
            'async_tasks': self.async_tasks,
            'normal_tasks': self.normal_tasks,
            'average_runtime': self.average_runtime,
            'max_runtime': self.max_runtime,
            'min_runtime': self.min_runtime,
            'last_hour_tasks': self.last_hour_tasks,
            'last_day_tasks': self.last_day_tasks
        }


@dataclass
class TaskInfo:
    """任务信息"""
    task_id: str
    task_name: str
    task_type: TaskType
    state: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    runtime: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    worker: Optional[str] = None
    queue: Optional[str] = None
    retries: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'task_id': self.task_id,
            'task_name': self.task_name,
            'task_type': self.task_type.value,
            'state': self.state,
            'args': self.args,
            'kwargs': self.kwargs,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'runtime': self.runtime,
            'result': self.result,
            'error': self.error,
            'worker': self.worker,
            'queue': self.queue,
            'retries': self.retries
        }


class TaskManager:
    """
    任务管理器
    
    提供Celery任务的统一管理、监控和控制功能
    """
    
    def __init__(self):
        """初始化任务管理器"""
        self.celery_app = get_celery_app()
        self._task_history: Dict[str, TaskInfo] = {}
        self._max_history_size = 10000
        self._cleanup_interval = 3600  # 1小时
        self._last_cleanup = time.time()
    
    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """
        获取任务信息
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[TaskInfo]: 任务信息
        """
        try:
            # 从历史记录获取
            if task_id in self._task_history:
                return self._task_history[task_id]
            
            # 从Celery获取
            result = AsyncResult(task_id, app=self.celery_app)
            
            task_info = TaskInfo(
                task_id=task_id,
                task_name=result.name or "unknown",
                task_type=self._detect_task_type(result.name),
                state=result.state,
                result=result.result if result.state == states.SUCCESS else None,
                error=str(result.info) if result.state == states.FAILURE else None
            )
            
            # 缓存到历史记录
            self._task_history[task_id] = task_info
            
            return task_info
            
        except Exception as e:
            logger.error(f"获取任务信息失败: {task_id} - {str(e)}")
            return None
    
    def get_active_tasks(self) -> List[TaskInfo]:
        """
        获取活跃任务列表
        
        Returns:
            List[TaskInfo]: 活跃任务列表
        """
        try:
            inspect = self.celery_app.control.inspect()
            active_tasks = inspect.active()
            
            if not active_tasks:
                return []
            
            task_list = []
            for worker_name, tasks in active_tasks.items():
                for task_data in tasks:
                    task_info = TaskInfo(
                        task_id=task_data.get('id', ''),
                        task_name=task_data.get('name', ''),
                        task_type=self._detect_task_type(task_data.get('name', '')),
                        state=states.STARTED,
                        args=task_data.get('args', ()),
                        kwargs=task_data.get('kwargs', {}),
                        worker=worker_name,
                        started_at=datetime.utcnow()
                    )
                    task_list.append(task_info)
            
            return task_list
            
        except Exception as e:
            logger.error(f"获取活跃任务失败: {str(e)}")
            return []
    
    def get_scheduled_tasks(self) -> List[TaskInfo]:
        """
        获取计划任务列表
        
        Returns:
            List[TaskInfo]: 计划任务列表
        """
        try:
            inspect = self.celery_app.control.inspect()
            scheduled_tasks = inspect.scheduled()
            
            if not scheduled_tasks:
                return []
            
            task_list = []
            for worker_name, tasks in scheduled_tasks.items():
                for task_data in tasks:
                    eta = task_data.get('eta')
                    eta_datetime = datetime.fromisoformat(eta) if eta else None
                    
                    task_info = TaskInfo(
                        task_id=task_data.get('request', {}).get('id', ''),
                        task_name=task_data.get('request', {}).get('task', ''),
                        task_type=TaskType.DELAYED,
                        state=states.PENDING,
                        args=task_data.get('request', {}).get('args', ()),
                        kwargs=task_data.get('request', {}).get('kwargs', {}),
                        worker=worker_name,
                        created_at=eta_datetime
                    )
                    task_list.append(task_info)
            
            return task_list
            
        except Exception as e:
            logger.error(f"获取计划任务失败: {str(e)}")
            return []
    
    def cancel_task(self, task_id: str, terminate: bool = False) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            terminate: 是否强制终止
            
        Returns:
            bool: 是否取消成功
        """
        try:
            self.celery_app.control.revoke(task_id, terminate=terminate)
            
            # 更新历史记录
            if task_id in self._task_history:
                self._task_history[task_id].state = states.REVOKED
                self._task_history[task_id].completed_at = datetime.utcnow()
            
            action = "强制终止" if terminate else "取消"
            logger.info(f"{action}任务: {task_id}")
            return True
            
        except Exception as e:
            logger.error(f"取消任务失败: {task_id} - {str(e)}")
            return False
    
    def retry_task(self, task_id: str, countdown: int = None) -> bool:
        """
        重试任务
        
        Args:
            task_id: 任务ID
            countdown: 延时秒数
            
        Returns:
            bool: 是否重试成功
        """
        try:
            result = AsyncResult(task_id, app=self.celery_app)
            
            if result.state not in [states.FAILURE, states.REVOKED]:
                logger.warning(f"任务状态不允许重试: {task_id} - {result.state}")
                return False
            
            # 获取原始任务信息
            task_info = self.get_task_info(task_id)
            if not task_info:
                logger.error(f"无法获取任务信息: {task_id}")
                return False
            
            # 重新发送任务
            new_result = self.celery_app.send_task(
                task_info.task_name,
                args=task_info.args,
                kwargs=task_info.kwargs,
                countdown=countdown
            )
            
            logger.info(f"重试任务: {task_id} -> {new_result.id}")
            return True
            
        except Exception as e:
            logger.error(f"重试任务失败: {task_id} - {str(e)}")
            return False
    
    def get_statistics(self) -> TaskStatistics:
        """
        获取任务统计信息
        
        Returns:
            TaskStatistics: 统计信息
        """
        stats = TaskStatistics()
        
        try:
            # 统计历史任务
            for task_info in self._task_history.values():
                stats.total_tasks += 1
                
                # 按状态统计
                if task_info.state == states.PENDING:
                    stats.pending_tasks += 1
                elif task_info.state == states.STARTED:
                    stats.running_tasks += 1
                elif task_info.state == states.SUCCESS:
                    stats.successful_tasks += 1
                elif task_info.state == states.FAILURE:
                    stats.failed_tasks += 1
                elif task_info.state == states.RETRY:
                    stats.retried_tasks += 1
                elif task_info.state == states.REVOKED:
                    stats.revoked_tasks += 1
                
                # 按类型统计
                if task_info.task_type == TaskType.DELAYED:
                    stats.delayed_tasks += 1
                elif task_info.task_type == TaskType.PERIODIC:
                    stats.periodic_tasks += 1
                elif task_info.task_type == TaskType.ASYNC:
                    stats.async_tasks += 1
                else:
                    stats.normal_tasks += 1
                
                # 时间统计
                if task_info.created_at:
                    now = datetime.utcnow()
                    if now - task_info.created_at <= timedelta(hours=1):
                        stats.last_hour_tasks += 1
                    if now - task_info.created_at <= timedelta(days=1):
                        stats.last_day_tasks += 1
                
                # 运行时间统计
                if task_info.runtime:
                    if stats.max_runtime == 0:
                        stats.max_runtime = task_info.runtime
                        stats.min_runtime = task_info.runtime
                    else:
                        stats.max_runtime = max(stats.max_runtime, task_info.runtime)
                        stats.min_runtime = min(stats.min_runtime, task_info.runtime)
            
            # 计算平均运行时间
            runtimes = [task.runtime for task in self._task_history.values() if task.runtime]
            if runtimes:
                stats.average_runtime = sum(runtimes) / len(runtimes)
            
            # 获取当前活跃任务
            active_tasks = self.get_active_tasks()
            stats.running_tasks += len(active_tasks)
            
            # 获取计划任务
            scheduled_tasks = self.get_scheduled_tasks()
            stats.pending_tasks += len(scheduled_tasks)
            
        except Exception as e:
            logger.error(f"获取任务统计失败: {str(e)}")
        
        return stats
    
    def get_worker_statistics(self) -> Dict[str, Any]:
        """
        获取Worker统计信息
        
        Returns:
            Dict[str, Any]: Worker统计信息
        """
        try:
            inspect = self.celery_app.control.inspect()
            
            # 获取各种状态信息
            stats = inspect.stats()
            ping_result = inspect.ping()
            registered_tasks = inspect.registered()
            active_queues = inspect.active_queues()
            
            return {
                'worker_stats': stats,
                'worker_ping': ping_result,
                'registered_tasks': registered_tasks,
                'active_queues': active_queues,
                'total_workers': len(ping_result) if ping_result else 0
            }
            
        except Exception as e:
            logger.error(f"获取Worker统计失败: {str(e)}")
            return {}
    
    def purge_queue(self, queue_name: str) -> int:
        """
        清空队列
        
        Args:
            queue_name: 队列名称
            
        Returns:
            int: 清空的消息数量
        """
        try:
            with self.celery_app.connection() as conn:
                queue = conn.default_channel.queue_declare(queue_name, passive=True)
                message_count = queue.message_count
                
                # 清空队列
                conn.default_channel.queue_purge(queue_name)
                
                logger.info(f"清空队列: {queue_name} - {message_count} 条消息")
                return message_count
                
        except Exception as e:
            logger.error(f"清空队列失败: {queue_name} - {str(e)}")
            return 0
    
    def cleanup_history(self, max_age_hours: int = 24) -> int:
        """
        清理历史记录
        
        Args:
            max_age_hours: 最大保留小时数
            
        Returns:
            int: 清理的记录数量
        """
        if time.time() - self._last_cleanup < self._cleanup_interval:
            return 0
        
        cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        cleaned_count = 0
        
        task_ids_to_remove = []
        for task_id, task_info in self._task_history.items():
            if (task_info.completed_at and task_info.completed_at < cutoff_time) or \
               (task_info.created_at and task_info.created_at < cutoff_time):
                task_ids_to_remove.append(task_id)
        
        for task_id in task_ids_to_remove:
            del self._task_history[task_id]
            cleaned_count += 1
        
        # 如果历史记录太多，删除最旧的
        if len(self._task_history) > self._max_history_size:
            sorted_tasks = sorted(
                self._task_history.items(),
                key=lambda x: x[1].created_at or datetime.min
            )
            
            excess_count = len(self._task_history) - self._max_history_size
            for i in range(excess_count):
                task_id = sorted_tasks[i][0]
                del self._task_history[task_id]
                cleaned_count += 1
        
        self._last_cleanup = time.time()
        
        if cleaned_count > 0:
            logger.info(f"清理任务历史记录: {cleaned_count} 条")
        
        return cleaned_count
    
    def _detect_task_type(self, task_name: str) -> TaskType:
        """
        检测任务类型
        
        Args:
            task_name: 任务名称
            
        Returns:
            TaskType: 任务类型
        """
        if not task_name:
            return TaskType.NORMAL
        
        # 检查是否为延时任务
        if task_name in delayed_task_manager._task_registry:
            return TaskType.DELAYED
        
        # 检查是否为周期性任务
        if task_name in [task.task for task in beat_schedule_manager.list_tasks()]:
            return TaskType.PERIODIC
        
        # 检查是否为异步任务
        if task_name in async_task_manager.list_async_tasks():
            return TaskType.ASYNC
        
        # 检查任务名称模式
        if 'async' in task_name.lower():
            return TaskType.ASYNC
        elif 'schedule' in task_name.lower() or 'periodic' in task_name.lower():
            return TaskType.PERIODIC
        elif 'delay' in task_name.lower():
            return TaskType.DELAYED
        
        return TaskType.NORMAL
    
    def get_task_history(self, limit: int = 100) -> List[TaskInfo]:
        """
        获取任务历史记录
        
        Args:
            limit: 限制数量
            
        Returns:
            List[TaskInfo]: 任务历史列表
        """
        sorted_tasks = sorted(
            self._task_history.values(),
            key=lambda x: x.created_at or datetime.min,
            reverse=True
        )
        
        return sorted_tasks[:limit]
    
    def export_statistics(self) -> Dict[str, Any]:
        """
        导出完整统计信息
        
        Returns:
            Dict[str, Any]: 完整统计信息
        """
        return {
            'task_statistics': self.get_statistics().to_dict(),
            'worker_statistics': self.get_worker_statistics(),
            'delayed_task_statistics': delayed_task_manager.get_statistics(),
            'beat_schedule_statistics': beat_schedule_manager.get_statistics(),
            'celery_app_statistics': celery_app_instance.get_stats() if celery_app_instance.app else {}
        }


# 全局任务管理器实例
task_manager = TaskManager()