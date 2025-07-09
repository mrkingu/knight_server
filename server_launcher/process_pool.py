"""
进程池管理模块

该模块提供进程池管理功能，用于优化进程资源的分配和管理。
支持进程创建、监控、回收和复用，提高服务启动器的性能。

主要功能：
- 进程池管理
- 进程资源分配
- 进程监控和回收
- 进程复用优化
- 异常处理和恢复
"""

import os
import time
import signal
import asyncio
import multiprocessing
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from concurrent.futures import ProcessPoolExecutor, Future
from queue import Queue, Empty
from threading import Thread, Lock, Event
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger
from .utils import get_process_info, kill_process_tree, is_process_running


@dataclass
class ProcessInfo:
    """进程信息数据类"""
    pid: int
    name: str
    start_time: float
    status: str
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    restart_count: int = 0
    last_restart_time: float = 0.0
    
    def is_alive(self) -> bool:
        """检查进程是否存活"""
        if not PSUTIL_AVAILABLE:
            return False
        return is_process_running(self.pid)


class ProcessTask:
    """进程任务类"""
    
    def __init__(self, task_id: str, func: Callable, args: Tuple, kwargs: Dict[str, Any]):
        """
        初始化进程任务
        
        Args:
            task_id: 任务ID
            func: 要执行的函数
            args: 函数参数
            kwargs: 函数关键字参数
        """
        self.task_id = task_id
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.submit_time = time.time()
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.result: Any = None
        self.exception: Optional[Exception] = None
        self.status = "pending"  # pending, running, completed, failed
    
    def execute(self) -> Any:
        """执行任务"""
        self.start_time = time.time()
        self.status = "running"
        
        try:
            result = self.func(*self.args, **self.kwargs)
            self.result = result
            self.status = "completed"
            return result
        except Exception as e:
            self.exception = e
            self.status = "failed"
            raise
        finally:
            self.end_time = time.time()
    
    def get_duration(self) -> float:
        """获取任务执行时间"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0


class ProcessPool:
    """
    进程池管理器
    
    优化进程资源的分配和管理，提供进程创建、监控、回收和复用功能
    """
    
    def __init__(self, max_workers: int = None, 
                 process_timeout: int = 300,
                 monitor_interval: int = 5):
        """
        初始化进程池
        
        Args:
            max_workers: 最大工作进程数
            process_timeout: 进程超时时间（秒）
            monitor_interval: 监控间隔（秒）
        """
        self.max_workers = max_workers or multiprocessing.cpu_count()
        self.process_timeout = process_timeout
        self.monitor_interval = monitor_interval
        
        # 进程池执行器
        self.executor: Optional[ProcessPoolExecutor] = None
        
        # 进程信息管理
        self.processes: Dict[int, ProcessInfo] = {}
        self.process_lock = Lock()
        
        # 任务管理
        self.tasks: Dict[str, ProcessTask] = {}
        self.task_futures: Dict[str, Future] = {}
        self.task_lock = Lock()
        
        # 监控相关
        self.monitor_thread: Optional[Thread] = None
        self.stop_event = Event()
        
        # 统计信息
        self.stats = {
            'total_tasks': 0,
            'completed_tasks': 0,
            'failed_tasks': 0,
            'active_processes': 0,
            'peak_processes': 0,
            'total_process_time': 0.0,
            'average_task_time': 0.0
        }
        
        logger.info(f"进程池已创建，最大工作进程数: {self.max_workers}")
    
    def start(self) -> None:
        """启动进程池"""
        if self.executor is not None:
            logger.warning("进程池已经启动")
            return
        
        try:
            self.executor = ProcessPoolExecutor(max_workers=self.max_workers)
            self.stop_event.clear()
            
            # 启动监控线程
            self.monitor_thread = Thread(target=self._monitor_processes)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            logger.info("进程池启动成功")
            
        except Exception as e:
            logger.error(f"进程池启动失败: {e}")
            raise
    
    def stop(self, wait: bool = True) -> None:
        """
        停止进程池
        
        Args:
            wait: 是否等待任务完成
        """
        if self.executor is None:
            logger.warning("进程池未启动")
            return
        
        try:
            # 停止监控线程
            self.stop_event.set()
            if self.monitor_thread:
                self.monitor_thread.join(timeout=5)
            
            # 关闭进程池
            self.executor.shutdown(wait=wait)
            self.executor = None
            
            # 清理进程信息
            with self.process_lock:
                self.processes.clear()
            
            with self.task_lock:
                self.tasks.clear()
                self.task_futures.clear()
            
            logger.info("进程池已停止")
            
        except Exception as e:
            logger.error(f"进程池停止失败: {e}")
            raise
    
    def submit(self, func: Callable, *args, task_id: Optional[str] = None, **kwargs) -> str:
        """
        提交任务到进程池
        
        Args:
            func: 要执行的函数
            *args: 函数参数
            task_id: 任务ID，如果为None则自动生成
            **kwargs: 函数关键字参数
            
        Returns:
            str: 任务ID
        """
        if self.executor is None:
            raise RuntimeError("进程池未启动")
        
        # 生成任务ID
        if task_id is None:
            task_id = f"task_{int(time.time() * 1000)}_{len(self.tasks)}"
        
        # 创建任务
        task = ProcessTask(task_id, func, args, kwargs)
        
        with self.task_lock:
            if task_id in self.tasks:
                raise ValueError(f"任务ID {task_id} 已存在")
            
            self.tasks[task_id] = task
            
            # 提交任务到进程池
            future = self.executor.submit(task.execute)
            self.task_futures[task_id] = future
            
            # 更新统计信息
            self.stats['total_tasks'] += 1
        
        logger.debug(f"任务已提交: {task_id}")
        return task_id
    
    def get_task_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """
        获取任务结果
        
        Args:
            task_id: 任务ID
            timeout: 超时时间
            
        Returns:
            Any: 任务结果
        """
        with self.task_lock:
            if task_id not in self.task_futures:
                raise ValueError(f"任务ID {task_id} 不存在")
            
            future = self.task_futures[task_id]
        
        try:
            result = future.result(timeout=timeout)
            
            # 更新统计信息
            with self.task_lock:
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    if task.status == "completed":
                        self.stats['completed_tasks'] += 1
                        self.stats['total_process_time'] += task.get_duration()
                        self.stats['average_task_time'] = (
                            self.stats['total_process_time'] / self.stats['completed_tasks']
                        )
                    elif task.status == "failed":
                        self.stats['failed_tasks'] += 1
            
            return result
            
        except Exception as e:
            logger.error(f"获取任务结果失败 ({task_id}): {e}")
            raise
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消任务
        
        Args:
            task_id: 任务ID
            
        Returns:
            bool: 是否成功取消
        """
        with self.task_lock:
            if task_id not in self.task_futures:
                return False
            
            future = self.task_futures[task_id]
            cancelled = future.cancel()
            
            if cancelled:
                del self.task_futures[task_id]
                if task_id in self.tasks:
                    self.tasks[task_id].status = "cancelled"
            
            return cancelled
    
    def get_task_status(self, task_id: str) -> Optional[str]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[str]: 任务状态
        """
        with self.task_lock:
            if task_id in self.tasks:
                return self.tasks[task_id].status
            return None
    
    def get_active_processes(self) -> List[ProcessInfo]:
        """
        获取活跃进程列表
        
        Returns:
            List[ProcessInfo]: 活跃进程信息列表
        """
        with self.process_lock:
            return [info for info in self.processes.values() if info.is_alive()]
    
    def get_process_info(self, pid: int) -> Optional[ProcessInfo]:
        """
        获取进程信息
        
        Args:
            pid: 进程ID
            
        Returns:
            Optional[ProcessInfo]: 进程信息
        """
        with self.process_lock:
            return self.processes.get(pid)
    
    def kill_process(self, pid: int, timeout: int = 10) -> bool:
        """
        终止进程
        
        Args:
            pid: 进程ID
            timeout: 超时时间
            
        Returns:
            bool: 是否成功终止
        """
        try:
            success = kill_process_tree(pid, timeout)
            
            if success:
                with self.process_lock:
                    if pid in self.processes:
                        del self.processes[pid]
                
                logger.info(f"进程已终止: {pid}")
            
            return success
            
        except Exception as e:
            logger.error(f"终止进程失败 ({pid}): {e}")
            return False
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        with self.process_lock:
            active_processes = len([p for p in self.processes.values() if p.is_alive()])
            self.stats['active_processes'] = active_processes
            
            if active_processes > self.stats['peak_processes']:
                self.stats['peak_processes'] = active_processes
        
        return self.stats.copy()
    
    def _monitor_processes(self) -> None:
        """监控进程状态"""
        logger.info("进程监控线程已启动")
        
        while not self.stop_event.is_set():
            try:
                self._update_process_info()
                self._cleanup_dead_processes()
                time.sleep(self.monitor_interval)
                
            except Exception as e:
                logger.error(f"进程监控异常: {e}")
                time.sleep(self.monitor_interval)
        
        logger.info("进程监控线程已停止")
    
    def _update_process_info(self) -> None:
        """更新进程信息"""
        with self.process_lock:
            for pid, process_info in self.processes.items():
                try:
                    if not process_info.is_alive():
                        continue
                    
                    # 获取进程详细信息
                    detail_info = get_process_info(pid)
                    if detail_info:
                        process_info.cpu_percent = detail_info.get('cpu_percent', 0.0)
                        process_info.memory_percent = detail_info.get('memory_percent', 0.0)
                        process_info.status = detail_info.get('status', 'unknown')
                
                except Exception as e:
                    logger.warning(f"更新进程信息失败 ({pid}): {e}")
    
    def _cleanup_dead_processes(self) -> None:
        """清理死亡进程"""
        with self.process_lock:
            dead_pids = [pid for pid, info in self.processes.items() if not info.is_alive()]
            
            for pid in dead_pids:
                logger.info(f"清理死亡进程: {pid}")
                del self.processes[pid]
    
    def _register_process(self, pid: int, name: str) -> None:
        """
        注册进程
        
        Args:
            pid: 进程ID
            name: 进程名称
        """
        if not PSUTIL_AVAILABLE:
            logger.warning("psutil 不可用，进程注册功能受限")
            return
            
        with self.process_lock:
            self.processes[pid] = ProcessInfo(
                pid=pid,
                name=name,
                start_time=time.time(),
                status="running"
            )
            
            logger.debug(f"进程已注册: {pid} ({name})")
    
    def shutdown(self, wait: bool = True) -> None:
        """
        关闭进程池（别名方法）
        
        Args:
            wait: 是否等待任务完成
        """
        self.stop(wait=wait)
    
    def __enter__(self):
        """进入上下文管理器"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文管理器"""
        self.stop()
        return False
    
    def __del__(self):
        """析构函数"""
        try:
            self.stop(wait=False)
        except:
            pass


class ServiceProcess:
    """
    服务进程类
    
    用于管理单个服务进程的生命周期
    """
    
    def __init__(self, service_name: str, command: str, 
                 working_dir: str, env_vars: Dict[str, str]):
        """
        初始化服务进程
        
        Args:
            service_name: 服务名称
            command: 启动命令
            working_dir: 工作目录
            env_vars: 环境变量
        """
        self.service_name = service_name
        self.command = command
        self.working_dir = working_dir
        self.env_vars = env_vars
        
        self.process: Optional[multiprocessing.Process] = None
        self.pid: Optional[int] = None
        self.start_time: Optional[float] = None
        self.restart_count = 0
        self.last_restart_time = 0.0
        
        logger.debug(f"服务进程已创建: {service_name}")
    
    def start(self) -> bool:
        """
        启动服务进程
        
        Returns:
            bool: 是否成功启动
        """
        if self.process and self.process.is_alive():
            logger.warning(f"服务进程已在运行: {self.service_name}")
            return True
        
        try:
            # 创建进程
            self.process = multiprocessing.Process(
                target=self._run_service,
                name=self.service_name
            )
            
            self.process.start()
            self.pid = self.process.pid
            self.start_time = time.time()
            
            logger.info(f"服务进程已启动: {self.service_name} (PID: {self.pid})")
            return True
            
        except Exception as e:
            logger.error(f"启动服务进程失败 ({self.service_name}): {e}")
            return False
    
    def stop(self, timeout: int = 30) -> bool:
        """
        停止服务进程
        
        Args:
            timeout: 超时时间
            
        Returns:
            bool: 是否成功停止
        """
        if not self.process or not self.process.is_alive():
            logger.info(f"服务进程未运行: {self.service_name}")
            return True
        
        try:
            # 优雅关闭
            self.process.terminate()
            self.process.join(timeout=timeout)
            
            # 如果仍在运行，强制终止
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=5)
            
            logger.info(f"服务进程已停止: {self.service_name}")
            return True
            
        except Exception as e:
            logger.error(f"停止服务进程失败 ({self.service_name}): {e}")
            return False
    
    def restart(self) -> bool:
        """
        重启服务进程
        
        Returns:
            bool: 是否成功重启
        """
        logger.info(f"重启服务进程: {self.service_name}")
        
        # 停止进程
        if not self.stop():
            return False
        
        # 等待一段时间
        time.sleep(1)
        
        # 启动进程
        if self.start():
            self.restart_count += 1
            self.last_restart_time = time.time()
            return True
        
        return False
    
    def is_alive(self) -> bool:
        """
        检查进程是否存活
        
        Returns:
            bool: 进程是否存活
        """
        if not self.process:
            return False
        
        return self.process.is_alive()
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取进程信息
        
        Returns:
            Dict[str, Any]: 进程信息
        """
        info = {
            'service_name': self.service_name,
            'pid': self.pid,
            'is_alive': self.is_alive(),
            'start_time': self.start_time,
            'restart_count': self.restart_count,
            'last_restart_time': self.last_restart_time
        }
        
        if self.start_time:
            info['uptime'] = time.time() - self.start_time
        
        return info
    
    def _run_service(self) -> None:
        """运行服务"""
        try:
            # 设置环境变量
            env = os.environ.copy()
            env.update(self.env_vars)
            
            # 切换工作目录
            os.chdir(self.working_dir)
            
            # 执行命令
            os.system(self.command)
            
        except Exception as e:
            logger.error(f"服务进程运行异常 ({self.service_name}): {e}")
            raise