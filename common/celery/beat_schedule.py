"""
Beat调度任务管理模块

提供Celery Beat调度器的管理功能，支持动态添加和管理定时任务。
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass, asdict
from celery.schedules import crontab, schedule
from celery.beat import ScheduleEntry

from common.logger import logger

from .celery_app import get_celery_app


@dataclass
class ScheduleTask:
    """调度任务信息"""
    name: str
    task: str
    schedule: Union[str, int, float, timedelta]
    args: tuple = ()
    kwargs: dict = None
    enabled: bool = True
    description: str = ""
    created_at: datetime = None
    updated_at: datetime = None
    
    def __post_init__(self):
        if self.kwargs is None:
            self.kwargs = {}
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.updated_at is None:
            self.updated_at = datetime.utcnow()


class BeatScheduleManager:
    """
    Beat调度管理器
    
    提供定时任务的动态添加、删除和管理功能
    """
    
    def __init__(self):
        """初始化Beat调度管理器"""
        self.celery_app = get_celery_app()
        self._schedule_tasks: Dict[str, ScheduleTask] = {}
        self._load_existing_schedule()
    
    def _load_existing_schedule(self) -> None:
        """加载现有的调度任务"""
        try:
            beat_schedule = getattr(self.celery_app.conf, 'beat_schedule', {})
            for name, config in beat_schedule.items():
                task_info = ScheduleTask(
                    name=name,
                    task=config.get('task', ''),
                    schedule=config.get('schedule', 60),
                    args=config.get('args', ()),
                    kwargs=config.get('kwargs', {}),
                    enabled=config.get('enabled', True),
                    description=config.get('description', '')
                )
                self._schedule_tasks[name] = task_info
            
            logger.info(f"加载现有调度任务: {len(self._schedule_tasks)} 个")
        except Exception as e:
            logger.error(f"加载现有调度任务失败: {str(e)}")
    
    def add_cron_task(self,
                      name: str,
                      task: str,
                      cron_expr: str,
                      args: tuple = (),
                      kwargs: dict = None,
                      description: str = "",
                      enabled: bool = True) -> bool:
        """
        添加cron调度任务
        
        Args:
            name: 任务名称
            task: 任务路径
            cron_expr: cron表达式 (例如: "0 0 * * *")
            args: 位置参数
            kwargs: 关键字参数
            description: 任务描述
            enabled: 是否启用
            
        Returns:
            bool: 是否添加成功
        """
        try:
            # 解析cron表达式
            cron_schedule = self._parse_cron_expression(cron_expr)
            
            # 创建任务信息
            task_info = ScheduleTask(
                name=name,
                task=task,
                schedule=cron_expr,
                args=args,
                kwargs=kwargs or {},
                enabled=enabled,
                description=description
            )
            
            # 添加到调度表
            self._add_to_beat_schedule(name, {
                'task': task,
                'schedule': cron_schedule,
                'args': args,
                'kwargs': kwargs or {},
                'enabled': enabled,
                'description': description
            })
            
            self._schedule_tasks[name] = task_info
            
            logger.info(f"添加cron调度任务: {name} - {cron_expr}")
            return True
            
        except Exception as e:
            logger.error(f"添加cron调度任务失败: {name} - {str(e)}")
            return False
    
    def add_interval_task(self,
                         name: str,
                         task: str,
                         interval_seconds: int,
                         args: tuple = (),
                         kwargs: dict = None,
                         description: str = "",
                         enabled: bool = True) -> bool:
        """
        添加间隔调度任务
        
        Args:
            name: 任务名称
            task: 任务路径
            interval_seconds: 间隔秒数
            args: 位置参数
            kwargs: 关键字参数
            description: 任务描述
            enabled: 是否启用
            
        Returns:
            bool: 是否添加成功
        """
        try:
            # 创建任务信息
            task_info = ScheduleTask(
                name=name,
                task=task,
                schedule=interval_seconds,
                args=args,
                kwargs=kwargs or {},
                enabled=enabled,
                description=description
            )
            
            # 添加到调度表
            self._add_to_beat_schedule(name, {
                'task': task,
                'schedule': interval_seconds,
                'args': args,
                'kwargs': kwargs or {},
                'enabled': enabled,
                'description': description
            })
            
            self._schedule_tasks[name] = task_info
            
            logger.info(f"添加间隔调度任务: {name} - {interval_seconds}秒")
            return True
            
        except Exception as e:
            logger.error(f"添加间隔调度任务失败: {name} - {str(e)}")
            return False
    
    def remove_task(self, name: str) -> bool:
        """
        移除调度任务
        
        Args:
            name: 任务名称
            
        Returns:
            bool: 是否移除成功
        """
        try:
            # 从调度表移除
            beat_schedule = getattr(self.celery_app.conf, 'beat_schedule', {})
            if name in beat_schedule:
                del beat_schedule[name]
                self.celery_app.conf.beat_schedule = beat_schedule
            
            # 从任务列表移除
            if name in self._schedule_tasks:
                del self._schedule_tasks[name]
            
            logger.info(f"移除调度任务: {name}")
            return True
            
        except Exception as e:
            logger.error(f"移除调度任务失败: {name} - {str(e)}")
            return False
    
    def enable_task(self, name: str) -> bool:
        """
        启用调度任务
        
        Args:
            name: 任务名称
            
        Returns:
            bool: 是否成功
        """
        return self._update_task_enabled(name, True)
    
    def disable_task(self, name: str) -> bool:
        """
        禁用调度任务
        
        Args:
            name: 任务名称
            
        Returns:
            bool: 是否成功
        """
        return self._update_task_enabled(name, False)
    
    def _update_task_enabled(self, name: str, enabled: bool) -> bool:
        """
        更新任务启用状态
        
        Args:
            name: 任务名称
            enabled: 是否启用
            
        Returns:
            bool: 是否成功
        """
        try:
            if name not in self._schedule_tasks:
                logger.warning(f"调度任务不存在: {name}")
                return False
            
            # 更新任务信息
            self._schedule_tasks[name].enabled = enabled
            self._schedule_tasks[name].updated_at = datetime.utcnow()
            
            # 更新调度表
            beat_schedule = getattr(self.celery_app.conf, 'beat_schedule', {})
            if name in beat_schedule:
                beat_schedule[name]['enabled'] = enabled
                self.celery_app.conf.beat_schedule = beat_schedule
            
            action = "启用" if enabled else "禁用"
            logger.info(f"{action}调度任务: {name}")
            return True
            
        except Exception as e:
            logger.error(f"更新调度任务状态失败: {name} - {str(e)}")
            return False
    
    def update_task_schedule(self, name: str, new_schedule: Union[str, int]) -> bool:
        """
        更新任务调度时间
        
        Args:
            name: 任务名称
            new_schedule: 新的调度时间
            
        Returns:
            bool: 是否成功
        """
        try:
            if name not in self._schedule_tasks:
                logger.warning(f"调度任务不存在: {name}")
                return False
            
            # 解析新的调度时间
            if isinstance(new_schedule, str):
                # cron表达式
                parsed_schedule = self._parse_cron_expression(new_schedule)
            else:
                # 间隔秒数
                parsed_schedule = new_schedule
            
            # 更新任务信息
            self._schedule_tasks[name].schedule = new_schedule
            self._schedule_tasks[name].updated_at = datetime.utcnow()
            
            # 更新调度表
            beat_schedule = getattr(self.celery_app.conf, 'beat_schedule', {})
            if name in beat_schedule:
                beat_schedule[name]['schedule'] = parsed_schedule
                self.celery_app.conf.beat_schedule = beat_schedule
            
            logger.info(f"更新调度任务时间: {name} - {new_schedule}")
            return True
            
        except Exception as e:
            logger.error(f"更新调度任务时间失败: {name} - {str(e)}")
            return False
    
    def get_task(self, name: str) -> Optional[ScheduleTask]:
        """
        获取调度任务信息
        
        Args:
            name: 任务名称
            
        Returns:
            Optional[ScheduleTask]: 任务信息
        """
        return self._schedule_tasks.get(name)
    
    def list_tasks(self, enabled_only: bool = False) -> List[ScheduleTask]:
        """
        获取调度任务列表
        
        Args:
            enabled_only: 是否只返回启用的任务
            
        Returns:
            List[ScheduleTask]: 任务列表
        """
        tasks = list(self._schedule_tasks.values())
        if enabled_only:
            tasks = [task for task in tasks if task.enabled]
        return tasks
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        total_tasks = len(self._schedule_tasks)
        enabled_tasks = len([task for task in self._schedule_tasks.values() if task.enabled])
        disabled_tasks = total_tasks - enabled_tasks
        
        # 按任务类型统计
        cron_tasks = 0
        interval_tasks = 0
        
        for task in self._schedule_tasks.values():
            if isinstance(task.schedule, str):
                cron_tasks += 1
            else:
                interval_tasks += 1
        
        return {
            'total_tasks': total_tasks,
            'enabled_tasks': enabled_tasks,
            'disabled_tasks': disabled_tasks,
            'cron_tasks': cron_tasks,
            'interval_tasks': interval_tasks
        }
    
    def export_schedule(self) -> Dict[str, Any]:
        """
        导出调度配置
        
        Returns:
            Dict[str, Any]: 调度配置
        """
        schedule_config = {}
        for name, task in self._schedule_tasks.items():
            schedule_config[name] = {
                'task': task.task,
                'schedule': task.schedule,
                'args': task.args,
                'kwargs': task.kwargs,
                'enabled': task.enabled,
                'description': task.description
            }
        return schedule_config
    
    def import_schedule(self, schedule_config: Dict[str, Any]) -> int:
        """
        导入调度配置
        
        Args:
            schedule_config: 调度配置
            
        Returns:
            int: 导入的任务数量
        """
        imported_count = 0
        
        for name, config in schedule_config.items():
            try:
                schedule_value = config.get('schedule')
                
                if isinstance(schedule_value, str):
                    # cron任务
                    success = self.add_cron_task(
                        name=name,
                        task=config.get('task', ''),
                        cron_expr=schedule_value,
                        args=config.get('args', ()),
                        kwargs=config.get('kwargs', {}),
                        description=config.get('description', ''),
                        enabled=config.get('enabled', True)
                    )
                else:
                    # 间隔任务
                    success = self.add_interval_task(
                        name=name,
                        task=config.get('task', ''),
                        interval_seconds=schedule_value,
                        args=config.get('args', ()),
                        kwargs=config.get('kwargs', {}),
                        description=config.get('description', ''),
                        enabled=config.get('enabled', True)
                    )
                
                if success:
                    imported_count += 1
                    
            except Exception as e:
                logger.error(f"导入调度任务失败: {name} - {str(e)}")
        
        logger.info(f"导入调度配置完成: {imported_count} 个任务")
        return imported_count
    
    def _parse_cron_expression(self, cron_expr: str) -> crontab:
        """
        解析cron表达式
        
        Args:
            cron_expr: cron表达式
            
        Returns:
            crontab: cron调度对象
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"无效的cron表达式: {cron_expr}")
        
        minute, hour, day, month, day_of_week = parts
        
        return crontab(
            minute=minute,
            hour=hour,
            day_of_month=day,
            month_of_year=month,
            day_of_week=day_of_week
        )
    
    def _add_to_beat_schedule(self, name: str, config: Dict[str, Any]) -> None:
        """
        添加到Beat调度表
        
        Args:
            name: 任务名称
            config: 任务配置
        """
        beat_schedule = getattr(self.celery_app.conf, 'beat_schedule', {})
        beat_schedule[name] = config
        self.celery_app.conf.beat_schedule = beat_schedule


# 全局Beat调度管理器实例
beat_schedule_manager = BeatScheduleManager()


# 预定义的调度任务

def setup_default_scheduled_tasks() -> None:
    """设置默认的调度任务"""
    
    # 每日重置任务（每天0点执行）
    beat_schedule_manager.add_cron_task(
        name="daily_reset",
        task="common.celery.tasks.daily_reset",
        cron_expr="0 0 * * *",
        description="每日重置任务"
    )
    
    # 每小时清理任务（每小时0分执行）
    beat_schedule_manager.add_cron_task(
        name="hourly_cleanup",
        task="common.celery.tasks.hourly_cleanup",
        cron_expr="0 * * * *",
        description="每小时清理任务"
    )
    
    # 每5分钟健康检查
    beat_schedule_manager.add_interval_task(
        name="health_check",
        task="common.celery.tasks.health_check",
        interval_seconds=300,
        description="系统健康检查"
    )
    
    # 每周备份任务（每周日2点执行）
    beat_schedule_manager.add_cron_task(
        name="weekly_backup",
        task="common.celery.tasks.weekly_backup",
        cron_expr="0 2 * * 0",
        description="每周备份任务"
    )
    
    logger.info("默认调度任务设置完成")