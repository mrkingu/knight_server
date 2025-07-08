"""
Celery应用配置模块

提供Celery应用的初始化和配置管理。
"""

import os
from typing import Dict, Any, Optional, List, Callable
from celery import Celery
from celery.signals import task_prerun, task_postrun, task_failure, task_retry
from kombu import Queue

from common.logger import logger

from .config import CeleryConfig, get_default_celery_config


class CeleryApplication:
    """
    Celery应用封装类
    
    提供Celery应用的初始化、配置和生命周期管理
    """
    
    def __init__(self, config: Optional[CeleryConfig] = None):
        """
        初始化Celery应用
        
        Args:
            config: Celery配置，为None时使用默认配置
        """
        self.config = config or get_default_celery_config()
        self.app: Optional[Celery] = None
        self._initialized = False
        self._task_registry: Dict[str, Callable] = {}
        
    def create_app(self) -> Celery:
        """
        创建Celery应用实例
        
        Returns:
            Celery: Celery应用实例
        """
        if self.app is not None:
            return self.app
        
        # 创建Celery应用
        self.app = Celery(self.config.name)
        
        # 更新配置
        self.app.config_from_object(self.config.to_celery_config())
        
        # 注册信号处理器
        self._register_signals()
        
        # 自动发现任务
        self._autodiscover_tasks()
        
        self._initialized = True
        logger.info(f"Celery应用已创建: {self.config.name}")
        
        return self.app
    
    def _register_signals(self) -> None:
        """注册Celery信号处理器"""
        
        @task_prerun.connect
        def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
            """任务开始前的处理"""
            logger.info(f"任务开始: {task.name}[{task_id}]")
        
        @task_postrun.connect
        def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kwds):
            """任务完成后的处理"""
            logger.info(f"任务完成: {task.name}[{task_id}] - 状态: {state}")
        
        @task_failure.connect
        def task_failure_handler(sender=None, task_id=None, exception=None, einfo=None, **kwds):
            """任务失败的处理"""
            logger.error(f"任务失败: {sender.name}[{task_id}] - 异常: {exception}")
        
        @task_retry.connect
        def task_retry_handler(sender=None, task_id=None, reason=None, einfo=None, **kwds):
            """任务重试的处理"""
            logger.warning(f"任务重试: {sender.name}[{task_id}] - 原因: {reason}")
    
    def _autodiscover_tasks(self) -> None:
        """自动发现任务"""
        # 定义需要自动发现的任务模块
        task_modules = [
            'common.celery.tasks',
            'services.logic.tasks',
            'services.chat.tasks',
            'services.fight.tasks',
        ]
        
        # 过滤存在的模块
        existing_modules = []
        for module in task_modules:
            try:
                __import__(module)
                existing_modules.append(module)
            except ImportError:
                logger.debug(f"任务模块不存在: {module}")
        
        if existing_modules:
            self.app.autodiscover_tasks(existing_modules)
            logger.info(f"自动发现任务模块: {existing_modules}")
    
    def register_task(self, name: str, task_func: Callable) -> None:
        """
        注册任务
        
        Args:
            name: 任务名称
            task_func: 任务函数
        """
        if self.app is None:
            raise RuntimeError("Celery应用未创建")
        
        self._task_registry[name] = task_func
        logger.info(f"注册任务: {name}")
    
    def get_task(self, name: str) -> Optional[Callable]:
        """
        获取任务
        
        Args:
            name: 任务名称
            
        Returns:
            Optional[Callable]: 任务函数
        """
        return self._task_registry.get(name)
    
    def list_tasks(self) -> List[str]:
        """
        获取所有任务列表
        
        Returns:
            List[str]: 任务名称列表
        """
        if self.app is None:
            return []
        
        return list(self.app.tasks.keys())
    
    def get_task_info(self, name: str) -> Dict[str, Any]:
        """
        获取任务信息
        
        Args:
            name: 任务名称
            
        Returns:
            Dict[str, Any]: 任务信息
        """
        if self.app is None:
            return {}
        
        task = self.app.tasks.get(name)
        if task is None:
            return {}
        
        return {
            'name': task.name,
            'max_retries': task.max_retries,
            'default_retry_delay': task.default_retry_delay,
            'rate_limit': task.rate_limit,
            'time_limit': task.time_limit,
            'soft_time_limit': task.soft_time_limit,
            'ignore_result': task.ignore_result,
            'store_errors_even_if_ignored': task.store_errors_even_if_ignored,
            'track_started': task.track_started,
            'acks_late': task.acks_late,
        }
    
    def update_config(self, config: CeleryConfig) -> None:
        """
        更新配置
        
        Args:
            config: 新的配置
        """
        self.config = config
        
        if self.app is not None:
            self.app.config_from_object(self.config.to_celery_config())
            logger.info("Celery配置已更新")
    
    def start_worker(self, concurrency: int = None, queues: List[str] = None) -> None:
        """
        启动Worker
        
        Args:
            concurrency: 并发数
            queues: 队列列表
        """
        if self.app is None:
            raise RuntimeError("Celery应用未创建")
        
        argv = ['worker']
        
        if concurrency:
            argv.extend(['--concurrency', str(concurrency)])
        
        if queues:
            argv.extend(['--queues', ','.join(queues)])
        
        # 添加日志级别
        argv.extend(['--loglevel', 'info'])
        
        logger.info(f"启动Celery Worker: {' '.join(argv)}")
        self.app.worker_main(argv)
    
    def start_beat(self) -> None:
        """启动Beat调度器"""
        if self.app is None:
            raise RuntimeError("Celery应用未创建")
        
        argv = ['beat', '--loglevel', 'info']
        
        logger.info("启动Celery Beat调度器")
        self.app.start(argv)
    
    def start_flower(self, port: int = 5555) -> None:
        """
        启动Flower监控
        
        Args:
            port: 端口号
        """
        try:
            from flower.app import Flower
            
            flower = Flower(capp=self.app, port=port)
            logger.info(f"启动Flower监控: http://localhost:{port}")
            flower.start()
            
        except ImportError:
            logger.error("Flower未安装，无法启动监控")
    
    def purge_queue(self, queue_name: str) -> int:
        """
        清空队列
        
        Args:
            queue_name: 队列名称
            
        Returns:
            int: 清空的消息数量
        """
        if self.app is None:
            raise RuntimeError("Celery应用未创建")
        
        with self.app.connection() as conn:
            conn.default_channel.queue_purge(queue_name)
        
        logger.info(f"清空队列: {queue_name}")
        return 0  # 简化实现
    
    def get_queue_length(self, queue_name: str) -> int:
        """
        获取队列长度
        
        Args:
            queue_name: 队列名称
            
        Returns:
            int: 队列长度
        """
        if self.app is None:
            raise RuntimeError("Celery应用未创建")
        
        # 简化实现，实际需要根据不同的代理类型实现
        return 0
    
    def get_active_tasks(self) -> List[Dict[str, Any]]:
        """
        获取活跃任务列表
        
        Returns:
            List[Dict[str, Any]]: 活跃任务列表
        """
        if self.app is None:
            return []
        
        # 获取活跃任务
        inspect = self.app.control.inspect()
        active_tasks = inspect.active()
        
        if active_tasks is None:
            return []
        
        # 合并所有worker的活跃任务
        all_tasks = []
        for worker_name, tasks in active_tasks.items():
            for task in tasks:
                task['worker'] = worker_name
                all_tasks.append(task)
        
        return all_tasks
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否取消成功
        """
        if self.app is None:
            return False
        
        try:
            self.app.control.revoke(task_id, terminate=True)
            logger.info(f"取消任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"取消任务失败: {task_id} - {str(e)}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        if self.app is None:
            return {}
        
        inspect = self.app.control.inspect()
        
        # 获取各种统计信息
        stats = inspect.stats()
        registered_tasks = inspect.registered()
        active_queues = inspect.active_queues()
        
        return {
            'stats': stats,
            'registered_tasks': registered_tasks,
            'active_queues': active_queues,
            'total_tasks': len(self.list_tasks()),
        }
    
    def health_check(self) -> Dict[str, Any]:
        """
        健康检查
        
        Returns:
            Dict[str, Any]: 健康检查结果
        """
        if self.app is None:
            return {'status': 'error', 'message': 'Celery应用未创建'}
        
        try:
            # 检查连接
            with self.app.connection() as conn:
                conn.ensure_connection(max_retries=3)
            
            # 检查worker状态
            inspect = self.app.control.inspect()
            ping_result = inspect.ping()
            
            if ping_result:
                return {
                    'status': 'healthy',
                    'message': 'Celery应用运行正常',
                    'workers': list(ping_result.keys())
                }
            else:
                return {
                    'status': 'warning',
                    'message': '没有活跃的worker'
                }
        
        except Exception as e:
            return {
                'status': 'error',
                'message': f'健康检查失败: {str(e)}'
            }
    
    def shutdown(self) -> None:
        """关闭Celery应用"""
        if self.app is not None:
            # 停止所有worker
            self.app.control.shutdown()
            logger.info("Celery应用已关闭")


# 全局Celery应用实例
celery_app_instance = CeleryApplication()


def get_celery_app() -> Celery:
    """
    获取Celery应用实例
    
    Returns:
        Celery: Celery应用实例
    """
    return celery_app_instance.create_app()


def initialize_celery(config: Optional[CeleryConfig] = None) -> CeleryApplication:
    """
    初始化Celery应用
    
    Args:
        config: Celery配置
        
    Returns:
        CeleryApplication: Celery应用封装实例
    """
    if config:
        celery_app_instance.config = config
    
    celery_app_instance.create_app()
    return celery_app_instance