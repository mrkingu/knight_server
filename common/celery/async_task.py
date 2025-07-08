"""
异步任务支持模块

提供与asyncio集成的异步任务支持。
"""

import asyncio
import functools
import threading
from typing import Callable, Any, Dict, Optional, List, Coroutine, Union
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

from common.logger import logger

from .celery_app import get_celery_app
from .decorators import async_task


class AsyncTaskMode(Enum):
    """异步任务模式"""
    THREAD_POOL = "thread_pool"      # 线程池模式
    NEW_LOOP = "new_loop"           # 新事件循环模式
    CURRENT_LOOP = "current_loop"   # 当前事件循环模式


@dataclass
class AsyncTaskConfig:
    """异步任务配置"""
    mode: AsyncTaskMode = AsyncTaskMode.THREAD_POOL
    thread_pool_size: int = 4
    loop_timeout: Optional[float] = None


class AsyncTaskRunner:
    """
    异步任务运行器
    
    提供在Celery任务中运行异步函数的支持
    """
    
    def __init__(self, config: Optional[AsyncTaskConfig] = None):
        """
        初始化异步任务运行器
        
        Args:
            config: 异步任务配置
        """
        self.config = config or AsyncTaskConfig()
        self.celery_app = get_celery_app()
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._loop_cache: Dict[int, asyncio.AbstractEventLoop] = {}
        
        if self.config.mode == AsyncTaskMode.THREAD_POOL:
            self._thread_pool = ThreadPoolExecutor(
                max_workers=self.config.thread_pool_size,
                thread_name_prefix="AsyncTask"
            )
    
    def run_async_task(self, coro: Coroutine) -> Any:
        """
        运行异步任务
        
        Args:
            coro: 协程对象
            
        Returns:
            Any: 任务结果
        """
        if self.config.mode == AsyncTaskMode.THREAD_POOL:
            return self._run_in_thread_pool(coro)
        elif self.config.mode == AsyncTaskMode.NEW_LOOP:
            return self._run_in_new_loop(coro)
        elif self.config.mode == AsyncTaskMode.CURRENT_LOOP:
            return self._run_in_current_loop(coro)
        else:
            raise ValueError(f"不支持的异步任务模式: {self.config.mode}")
    
    def _run_in_thread_pool(self, coro: Coroutine) -> Any:
        """
        在线程池中运行异步任务
        
        Args:
            coro: 协程对象
            
        Returns:
            Any: 任务结果
        """
        if self._thread_pool is None:
            raise RuntimeError("线程池未初始化")
        
        def run_coroutine():
            """在新线程中运行协程"""
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        
        future = self._thread_pool.submit(run_coroutine)
        return future.result(timeout=self.config.loop_timeout)
    
    def _run_in_new_loop(self, coro: Coroutine) -> Any:
        """
        在新事件循环中运行异步任务
        
        Args:
            coro: 协程对象
            
        Returns:
            Any: 任务结果
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    def _run_in_current_loop(self, coro: Coroutine) -> Any:
        """
        在当前事件循环中运行异步任务
        
        Args:
            coro: 协程对象
            
        Returns:
            Any: 任务结果
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果循环正在运行，创建任务
                task = loop.create_task(coro)
                return task
            else:
                # 如果循环未运行，直接运行
                return loop.run_until_complete(coro)
        except RuntimeError:
            # 没有事件循环，创建新的
            return self._run_in_new_loop(coro)
    
    def shutdown(self):
        """关闭异步任务运行器"""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)
            self._thread_pool = None
        
        # 关闭缓存的事件循环
        for loop in self._loop_cache.values():
            if not loop.is_closed():
                loop.close()
        self._loop_cache.clear()


class AsyncTaskManager:
    """
    异步任务管理器
    
    提供异步任务的管理和调度功能
    """
    
    def __init__(self, config: Optional[AsyncTaskConfig] = None):
        """
        初始化异步任务管理器
        
        Args:
            config: 异步任务配置
        """
        self.config = config or AsyncTaskConfig()
        self.celery_app = get_celery_app()
        self.runner = AsyncTaskRunner(config)
        self._registered_tasks: Dict[str, Callable] = {}
    
    def register_async_task(self, name: str, async_func: Callable) -> Callable:
        """
        注册异步任务
        
        Args:
            name: 任务名称
            async_func: 异步函数
            
        Returns:
            Callable: 包装后的Celery任务
        """
        if not asyncio.iscoroutinefunction(async_func):
            raise ValueError("函数必须是异步函数")
        
        @functools.wraps(async_func)
        def wrapper(*args, **kwargs):
            """同步包装器"""
            coro = async_func(*args, **kwargs)
            return self.runner.run_async_task(coro)
        
        # 创建Celery任务
        celery_task = self.celery_app.task(name=name, bind=True)(wrapper)
        
        # 添加异步调用方法
        async def async_apply(*args, **kwargs):
            """异步调用方法"""
            return await async_func(*args, **kwargs)
        
        def async_apply_delay(*args, **kwargs):
            """异步延时调用方法"""
            return celery_task.delay(*args, **kwargs)
        
        def async_apply_async(*args, **kwargs):
            """异步apply_async方法"""
            return celery_task.apply_async(args=args, kwargs=kwargs)
        
        # 添加自定义方法
        celery_task.async_apply = async_apply
        celery_task.async_apply_delay = async_apply_delay
        celery_task.async_apply_async = async_apply_async
        
        self._registered_tasks[name] = celery_task
        
        logger.info(f"注册异步任务: {name}")
        return celery_task
    
    def get_async_task(self, name: str) -> Optional[Callable]:
        """
        获取异步任务
        
        Args:
            name: 任务名称
            
        Returns:
            Optional[Callable]: 异步任务
        """
        return self._registered_tasks.get(name)
    
    def list_async_tasks(self) -> List[str]:
        """
        获取异步任务列表
        
        Returns:
            List[str]: 任务名称列表
        """
        return list(self._registered_tasks.keys())
    
    async def run_multiple_tasks(self, tasks: List[tuple], concurrent: bool = True) -> List[Any]:
        """
        运行多个异步任务
        
        Args:
            tasks: 任务列表，每个元素为(task_name, args, kwargs)
            concurrent: 是否并发运行
            
        Returns:
            List[Any]: 任务结果列表
        """
        if not tasks:
            return []
        
        coroutines = []
        for task_name, args, kwargs in tasks:
            task = self.get_async_task(task_name)
            if task and hasattr(task, 'async_apply'):
                coroutines.append(task.async_apply(*args, **kwargs))
            else:
                logger.warning(f"异步任务不存在: {task_name}")
        
        if not coroutines:
            return []
        
        if concurrent:
            # 并发运行
            results = await asyncio.gather(*coroutines, return_exceptions=True)
        else:
            # 顺序运行
            results = []
            for coro in coroutines:
                try:
                    result = await coro
                    results.append(result)
                except Exception as e:
                    results.append(e)
        
        return results
    
    def shutdown(self):
        """关闭异步任务管理器"""
        self.runner.shutdown()


# 全局异步任务管理器实例
async_task_manager = AsyncTaskManager()


# 装饰器函数

def async_celery_task(name: Optional[str] = None, **kwargs):
    """
    异步Celery任务装饰器
    
    Args:
        name: 任务名称
        **kwargs: 任务选项
        
    Returns:
        Callable: 装饰器
    """
    def decorator(func: Callable) -> Callable:
        if not asyncio.iscoroutinefunction(func):
            raise ValueError("async_celery_task装饰器只能用于异步函数")
        
        task_name = name or f"{func.__module__}.{func.__name__}"
        return async_task_manager.register_async_task(task_name, func)
    
    return decorator


# 示例异步任务

@async_celery_task(name="async_user_data_sync")
async def async_user_data_sync(user_id: int) -> Dict[str, Any]:
    """
    异步用户数据同步任务
    
    Args:
        user_id: 用户ID
        
    Returns:
        Dict[str, Any]: 同步结果
    """
    try:
        logger.info(f"开始同步用户数据: {user_id}")
        
        # 模拟异步操作
        await asyncio.sleep(1)
        
        # 这里应该调用实际的数据同步逻辑
        result = {
            "user_id": user_id,
            "sync_time": asyncio.get_event_loop().time(),
            "status": "success"
        }
        
        logger.info(f"用户数据同步完成: {user_id}")
        return result
        
    except Exception as e:
        logger.error(f"用户数据同步失败: {user_id} - {str(e)}")
        raise


@async_celery_task(name="async_batch_notification")
async def async_batch_notification(user_ids: List[int], message: str) -> Dict[str, Any]:
    """
    异步批量通知任务
    
    Args:
        user_ids: 用户ID列表
        message: 通知消息
        
    Returns:
        Dict[str, Any]: 通知结果
    """
    try:
        logger.info(f"开始批量通知: {len(user_ids)} 个用户")
        
        # 并发发送通知
        async def send_notification(user_id: int):
            await asyncio.sleep(0.1)  # 模拟网络延迟
            return {"user_id": user_id, "status": "sent"}
        
        tasks = [send_notification(user_id) for user_id in user_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 统计结果
        success_count = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "sent")
        failed_count = len(results) - success_count
        
        result = {
            "total_users": len(user_ids),
            "success_count": success_count,
            "failed_count": failed_count,
            "message": message
        }
        
        logger.info(f"批量通知完成: 成功{success_count}, 失败{failed_count}")
        return result
        
    except Exception as e:
        logger.error(f"批量通知失败: {str(e)}")
        raise


@async_celery_task(name="async_data_export")
async def async_data_export(export_type: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    异步数据导出任务
    
    Args:
        export_type: 导出类型
        filters: 过滤条件
        
    Returns:
        Dict[str, Any]: 导出结果
    """
    try:
        logger.info(f"开始数据导出: {export_type}")
        
        # 模拟数据导出过程
        total_records = filters.get("limit", 1000)
        batch_size = 100
        
        exported_records = 0
        for i in range(0, total_records, batch_size):
            # 模拟批量处理
            await asyncio.sleep(0.5)
            current_batch = min(batch_size, total_records - i)
            exported_records += current_batch
            
            logger.debug(f"导出进度: {exported_records}/{total_records}")
        
        result = {
            "export_type": export_type,
            "total_records": exported_records,
            "filters": filters,
            "export_time": asyncio.get_event_loop().time(),
            "status": "completed"
        }
        
        logger.info(f"数据导出完成: {export_type} - {exported_records} 条记录")
        return result
        
    except Exception as e:
        logger.error(f"数据导出失败: {export_type} - {str(e)}")
        raise


# 异步任务工具函数

async def run_async_task_chain(task_chain: List[tuple]) -> List[Any]:
    """
    运行异步任务链
    
    Args:
        task_chain: 任务链，每个元素为(task_name, args, kwargs)
        
    Returns:
        List[Any]: 任务结果列表
    """
    results = []
    
    for task_name, args, kwargs in task_chain:
        try:
            task = async_task_manager.get_async_task(task_name)
            if task and hasattr(task, 'async_apply'):
                result = await task.async_apply(*args, **kwargs)
                results.append(result)
            else:
                logger.warning(f"异步任务不存在: {task_name}")
                results.append(None)
        except Exception as e:
            logger.error(f"异步任务执行失败: {task_name} - {str(e)}")
            results.append(e)
    
    return results


def get_async_task_config() -> AsyncTaskConfig:
    """
    获取异步任务配置
    
    Returns:
        AsyncTaskConfig: 当前配置
    """
    return async_task_manager.config


def update_async_task_config(config: AsyncTaskConfig) -> None:
    """
    更新异步任务配置
    
    Args:
        config: 新配置
    """
    async_task_manager.config = config
    async_task_manager.runner = AsyncTaskRunner(config)
    logger.info("异步任务配置已更新")