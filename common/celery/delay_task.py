"""
延时任务实现模块

提供延时任务的具体实现和管理功能。
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List, Union, Callable
from dataclasses import dataclass
from enum import Enum
from celery.result import AsyncResult

from common.logger import logger

from .celery_app import get_celery_app
from .decorators import delay_task


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    RETRY = "RETRY"
    REVOKED = "REVOKED"


@dataclass
class DelayedTaskInfo:
    """延时任务信息"""
    task_id: str
    task_name: str
    args: tuple
    kwargs: dict
    countdown: Optional[int] = None
    eta: Optional[datetime] = None
    created_at: datetime = None
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


class DelayedTaskManager:
    """
    延时任务管理器
    
    提供延时任务的创建、监控和管理功能
    """
    
    def __init__(self):
        """初始化延时任务管理器"""
        self.celery_app = get_celery_app()
        self._task_registry: Dict[str, DelayedTaskInfo] = {}
    
    def create_delayed_task(self,
                           task_func: Callable,
                           args: tuple = (),
                           kwargs: dict = None,
                           countdown: int = None,
                           eta: datetime = None,
                           queue: str = 'default',
                           priority: int = 5) -> str:
        """
        创建延时任务
        
        Args:
            task_func: 任务函数
            args: 位置参数
            kwargs: 关键字参数
            countdown: 延时秒数
            eta: 执行时间
            queue: 任务队列
            priority: 任务优先级
            
        Returns:
            str: 任务ID
        """
        if kwargs is None:
            kwargs = {}
        
        try:
            # 获取任务名称
            task_name = getattr(task_func, 'name', task_func.__name__)
            
            # 创建任务
            result = self.celery_app.send_task(
                task_name,
                args=args,
                kwargs=kwargs,
                countdown=countdown,
                eta=eta,
                queue=queue,
                priority=priority
            )
            
            # 保存任务信息
            task_info = DelayedTaskInfo(
                task_id=result.id,
                task_name=task_name,
                args=args,
                kwargs=kwargs,
                countdown=countdown,
                eta=eta
            )
            
            self._task_registry[result.id] = task_info
            
            logger.info(f"创建延时任务: {task_name}[{result.id}]")
            return result.id
            
        except Exception as e:
            logger.error(f"创建延时任务失败: {str(e)}")
            raise
    
    def schedule_task_at(self,
                        task_func: Callable,
                        execute_time: datetime,
                        args: tuple = (),
                        kwargs: dict = None,
                        queue: str = 'default') -> str:
        """
        定时执行任务
        
        Args:
            task_func: 任务函数
            execute_time: 执行时间
            args: 位置参数
            kwargs: 关键字参数
            queue: 任务队列
            
        Returns:
            str: 任务ID
        """
        return self.create_delayed_task(
            task_func=task_func,
            args=args,
            kwargs=kwargs,
            eta=execute_time,
            queue=queue
        )
    
    def schedule_task_after(self,
                           task_func: Callable,
                           delay_seconds: int,
                           args: tuple = (),
                           kwargs: dict = None,
                           queue: str = 'default') -> str:
        """
        延时执行任务
        
        Args:
            task_func: 任务函数
            delay_seconds: 延时秒数
            args: 位置参数
            kwargs: 关键字参数
            queue: 任务队列
            
        Returns:
            str: 任务ID
        """
        return self.create_delayed_task(
            task_func=task_func,
            args=args,
            kwargs=kwargs,
            countdown=delay_seconds,
            queue=queue
        )
    
    def get_task_status(self, task_id: str) -> TaskStatus:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            TaskStatus: 任务状态
        """
        try:
            result = AsyncResult(task_id, app=self.celery_app)
            status_map = {
                'PENDING': TaskStatus.PENDING,
                'STARTED': TaskStatus.STARTED,
                'SUCCESS': TaskStatus.SUCCESS,
                'FAILURE': TaskStatus.FAILURE,
                'RETRY': TaskStatus.RETRY,
                'REVOKED': TaskStatus.REVOKED,
            }
            return status_map.get(result.status, TaskStatus.PENDING)
        except Exception as e:
            logger.error(f"获取任务状态失败: {task_id} - {str(e)}")
            return TaskStatus.PENDING
    
    def get_task_result(self, task_id: str, timeout: float = None) -> Any:
        """
        获取任务结果
        
        Args:
            task_id: 任务ID
            timeout: 超时时间
            
        Returns:
            Any: 任务结果
        """
        try:
            result = AsyncResult(task_id, app=self.celery_app)
            return result.get(timeout=timeout)
        except Exception as e:
            logger.error(f"获取任务结果失败: {task_id} - {str(e)}")
            return None
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否取消成功
        """
        try:
            self.celery_app.control.revoke(task_id, terminate=True)
            
            # 更新任务信息
            if task_id in self._task_registry:
                self._task_registry[task_id].status = TaskStatus.REVOKED
            
            logger.info(f"取消任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"取消任务失败: {task_id} - {str(e)}")
            return False
    
    def get_task_info(self, task_id: str) -> Optional[DelayedTaskInfo]:
        """
        获取任务信息
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[DelayedTaskInfo]: 任务信息
        """
        task_info = self._task_registry.get(task_id)
        if task_info:
            # 更新状态
            task_info.status = self.get_task_status(task_id)
        return task_info
    
    def list_pending_tasks(self) -> List[DelayedTaskInfo]:
        """
        获取待执行任务列表
        
        Returns:
            List[DelayedTaskInfo]: 待执行任务列表
        """
        pending_tasks = []
        for task_info in self._task_registry.values():
            if self.get_task_status(task_info.task_id) == TaskStatus.PENDING:
                pending_tasks.append(task_info)
        return pending_tasks
    
    def list_running_tasks(self) -> List[DelayedTaskInfo]:
        """
        获取运行中任务列表
        
        Returns:
            List[DelayedTaskInfo]: 运行中任务列表
        """
        running_tasks = []
        for task_info in self._task_registry.values():
            status = self.get_task_status(task_info.task_id)
            if status in [TaskStatus.STARTED, TaskStatus.RETRY]:
                running_tasks.append(task_info)
        return running_tasks
    
    def cleanup_completed_tasks(self, keep_hours: int = 24) -> int:
        """
        清理已完成的任务
        
        Args:
            keep_hours: 保留小时数
            
        Returns:
            int: 清理的任务数量
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=keep_hours)
        cleaned_count = 0
        
        task_ids_to_remove = []
        for task_id, task_info in self._task_registry.items():
            if task_info.created_at < cutoff_time:
                status = self.get_task_status(task_id)
                if status in [TaskStatus.SUCCESS, TaskStatus.FAILURE, TaskStatus.REVOKED]:
                    task_ids_to_remove.append(task_id)
        
        for task_id in task_ids_to_remove:
            del self._task_registry[task_id]
            cleaned_count += 1
        
        logger.info(f"清理已完成任务: {cleaned_count} 个")
        return cleaned_count
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        total_tasks = len(self._task_registry)
        status_counts = {}
        
        for task_info in self._task_registry.values():
            status = self.get_task_status(task_info.task_id)
            status_counts[status.value] = status_counts.get(status.value, 0) + 1
        
        return {
            'total_tasks': total_tasks,
            'status_counts': status_counts,
            'pending_tasks': status_counts.get(TaskStatus.PENDING.value, 0),
            'running_tasks': status_counts.get(TaskStatus.STARTED.value, 0),
            'completed_tasks': status_counts.get(TaskStatus.SUCCESS.value, 0),
            'failed_tasks': status_counts.get(TaskStatus.FAILURE.value, 0),
        }


# 全局延时任务管理器实例
delayed_task_manager = DelayedTaskManager()


# 便捷函数

def send_reward(user_id: int, reward_id: int, amount: int = 1) -> str:
    """
    发送奖励任务
    
    Args:
        user_id: 用户ID
        reward_id: 奖励ID
        amount: 奖励数量
        
    Returns:
        str: 任务ID
    """
    @delay_task(name="send_reward")
    def _send_reward_task(self, user_id: int, reward_id: int, amount: int):
        """发送奖励的具体实现"""
        try:
            logger.info(f"发送奖励: 用户{user_id} 获得奖励{reward_id} x{amount}")
            # 这里应该调用实际的奖励发送逻辑
            return {"success": True, "user_id": user_id, "reward_id": reward_id, "amount": amount}
        except Exception as e:
            logger.error(f"发送奖励失败: {str(e)}")
            raise
    
    return delayed_task_manager.create_delayed_task(
        _send_reward_task,
        args=(user_id, reward_id, amount)
    )


def send_mail(user_id: int, title: str, content: str, attachments: List[Dict] = None) -> str:
    """
    发送邮件任务
    
    Args:
        user_id: 用户ID
        title: 邮件标题
        content: 邮件内容
        attachments: 附件列表
        
    Returns:
        str: 任务ID
    """
    @delay_task(name="send_mail")
    def _send_mail_task(self, user_id: int, title: str, content: str, attachments: List[Dict]):
        """发送邮件的具体实现"""
        try:
            logger.info(f"发送邮件: 用户{user_id} - {title}")
            # 这里应该调用实际的邮件发送逻辑
            return {"success": True, "user_id": user_id, "title": title}
        except Exception as e:
            logger.error(f"发送邮件失败: {str(e)}")
            raise
    
    return delayed_task_manager.create_delayed_task(
        _send_mail_task,
        args=(user_id, title, content, attachments or [])
    )


def schedule_maintenance(maintenance_time: datetime, duration_minutes: int = 60) -> str:
    """
    调度维护任务
    
    Args:
        maintenance_time: 维护时间
        duration_minutes: 维护时长（分钟）
        
    Returns:
        str: 任务ID
    """
    @delay_task(name="schedule_maintenance")
    def _maintenance_task(self, duration_minutes: int):
        """维护任务的具体实现"""
        try:
            logger.info(f"开始维护，预计时长: {duration_minutes} 分钟")
            # 这里应该调用实际的维护逻辑
            time.sleep(1)  # 模拟维护过程
            logger.info("维护完成")
            return {"success": True, "duration": duration_minutes}
        except Exception as e:
            logger.error(f"维护任务失败: {str(e)}")
            raise
    
    return delayed_task_manager.schedule_task_at(
        _maintenance_task,
        execute_time=maintenance_time,
        args=(duration_minutes,)
    )