"""
服务管理器模块

该模块负责管理所有微服务的生命周期，包括服务注册、启动、停止、
重启、状态查询等功能。处理服务启动顺序和依赖关系。

主要功能：
- 服务注册和管理
- 服务启动顺序控制
- 依赖关系处理
- 服务状态管理
- 服务生命周期管理
"""

import asyncio
import subprocess
import signal
import time
import threading
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
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
from .service_config import ServiceConfig, ServiceConfigManager
from .process_monitor import ProcessMonitor, ProcessMonitorConfig
from .health_checker import HealthChecker, HealthCheckResult
from .process_pool import ProcessPool, ServiceProcess
from .utils import (
    create_pid_file, remove_pid_file, read_pid_file, 
    check_port_available, kill_process_tree, is_process_running
)


class ServiceStatus(Enum):
    """服务状态枚举"""
    STOPPED = "已停止"
    STARTING = "启动中"
    RUNNING = "运行中"
    STOPPING = "停止中"
    FAILED = "失败"
    UNKNOWN = "未知"


@dataclass
class ServiceInstance:
    """服务实例数据类"""
    name: str
    config: ServiceConfig
    status: ServiceStatus = ServiceStatus.STOPPED
    pid: Optional[int] = None
    process: Optional[ServiceProcess] = None
    start_time: Optional[float] = None
    stop_time: Optional[float] = None
    restart_count: int = 0
    last_restart_time: Optional[float] = None
    error_message: Optional[str] = None
    pid_file: Optional[str] = None
    
    def get_uptime(self) -> float:
        """获取运行时间"""
        if self.start_time and self.status == ServiceStatus.RUNNING:
            return time.time() - self.start_time
        return 0.0
    
    def is_healthy(self) -> bool:
        """检查服务是否健康"""
        return (self.status == ServiceStatus.RUNNING and 
                self.pid is not None and 
                is_process_running(self.pid))
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'status': self.status.value,
            'pid': self.pid,
            'start_time': self.start_time,
            'stop_time': self.stop_time,
            'uptime': self.get_uptime(),
            'restart_count': self.restart_count,
            'last_restart_time': self.last_restart_time,
            'error_message': self.error_message,
            'is_healthy': self.is_healthy(),
            'config': {
                'service_type': self.config.service_type.value,
                'port': self.config.port,
                'process_count': self.config.process_count,
                'auto_restart': self.config.auto_restart,
                'dependencies': self.config.dependencies
            }
        }


class ServiceManager:
    """
    服务管理器
    
    负责管理所有微服务的生命周期，包括启动、停止、重启、状态查询等
    """
    
    def __init__(self, config_manager: ServiceConfigManager, 
                 process_monitor: Optional[ProcessMonitor] = None,
                 health_checker: Optional[HealthChecker] = None,
                 process_pool: Optional[ProcessPool] = None):
        """
        初始化服务管理器
        
        Args:
            config_manager: 配置管理器
            process_monitor: 进程监控器
            health_checker: 健康检查器
            process_pool: 进程池
        """
        self.config_manager = config_manager
        self.process_monitor = process_monitor
        self.health_checker = health_checker
        self.process_pool = process_pool
        
        # 服务实例管理
        self.services: Dict[str, ServiceInstance] = {}
        self.service_lock = threading.Lock()
        
        # 启动状态管理
        self.startup_in_progress = False
        self.shutdown_in_progress = False
        
        # 统计信息
        self.stats = {
            'total_services': 0,
            'running_services': 0,
            'failed_services': 0,
            'total_starts': 0,
            'total_stops': 0,
            'total_restarts': 0,
            'last_startup_time': 0.0,
            'last_shutdown_time': 0.0
        }
        
        # 初始化服务实例
        self._initialize_services()
        
        logger.info("服务管理器已初始化")
    
    def _initialize_services(self) -> None:
        """初始化服务实例"""
        with self.service_lock:
            all_configs = self.config_manager.get_all_configs()
            
            for service_name, service_config in all_configs.items():
                if service_config.enabled:
                    instance = ServiceInstance(
                        name=service_name,
                        config=service_config,
                        pid_file=self._get_pid_file_path(service_name)
                    )
                    
                    # 检查是否已有运行的进程
                    existing_pid = self._check_existing_process(instance)
                    if existing_pid:
                        instance.pid = existing_pid
                        instance.status = ServiceStatus.RUNNING
                        instance.start_time = time.time()  # 估计启动时间
                    
                    self.services[service_name] = instance
                    self.stats['total_services'] += 1
                    
                    logger.debug(f"已初始化服务实例: {service_name}")
    
    def _get_pid_file_path(self, service_name: str) -> str:
        """获取PID文件路径"""
        pid_dir = Path(self.config_manager.launcher_config.pid_file_dir)
        return str(pid_dir / f"{service_name}.pid")
    
    def _check_existing_process(self, instance: ServiceInstance) -> Optional[int]:
        """检查是否存在已运行的进程"""
        if not instance.pid_file:
            return None
        
        existing_pid = read_pid_file(instance.pid_file)
        if existing_pid and is_process_running(existing_pid):
            logger.info(f"发现已运行的进程: {instance.name} (PID: {existing_pid})")
            return existing_pid
        
        # 清理无效的PID文件
        if existing_pid:
            remove_pid_file(instance.pid_file)
        
        return None
    
    def register_service(self, service_config: ServiceConfig) -> bool:
        """
        注册服务
        
        Args:
            service_config: 服务配置
            
        Returns:
            bool: 是否成功注册
        """
        try:
            with self.service_lock:
                if service_config.name in self.services:
                    logger.warning(f"服务已存在: {service_config.name}")
                    return False
                
                instance = ServiceInstance(
                    name=service_config.name,
                    config=service_config,
                    pid_file=self._get_pid_file_path(service_config.name)
                )
                
                self.services[service_config.name] = instance
                self.stats['total_services'] += 1
                
                # 注册到健康检查器
                if self.health_checker and service_config.health_check:
                    self.health_checker.register_service(service_config)
                
                logger.info(f"已注册服务: {service_config.name}")
                return True
                
        except Exception as e:
            logger.error(f"注册服务失败 ({service_config.name}): {e}")
            return False
    
    def unregister_service(self, service_name: str) -> bool:
        """
        取消注册服务
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否成功取消注册
        """
        try:
            with self.service_lock:
                if service_name not in self.services:
                    logger.warning(f"服务不存在: {service_name}")
                    return False
                
                instance = self.services[service_name]
                
                # 如果服务正在运行，先停止
                if instance.status == ServiceStatus.RUNNING:
                    self.stop_service(service_name)
                
                del self.services[service_name]
                self.stats['total_services'] -= 1
                
                # 从健康检查器取消注册
                if self.health_checker:
                    self.health_checker.unregister_service(service_name)
                
                logger.info(f"已取消注册服务: {service_name}")
                return True
                
        except Exception as e:
            logger.error(f"取消注册服务失败 ({service_name}): {e}")
            return False
    
    async def start_service(self, service_name: str) -> bool:
        """
        启动服务
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否成功启动
        """
        with self.service_lock:
            if service_name not in self.services:
                logger.error(f"服务不存在: {service_name}")
                return False
            
            instance = self.services[service_name]
            
            if instance.status == ServiceStatus.RUNNING:
                logger.warning(f"服务已在运行: {service_name}")
                return True
            
            if instance.status == ServiceStatus.STARTING:
                logger.warning(f"服务正在启动: {service_name}")
                return False
        
        try:
            # 更新状态
            instance.status = ServiceStatus.STARTING
            instance.error_message = None
            
            logger.info(f"启动服务: {service_name}")
            
            # 检查依赖服务
            if not await self._check_dependencies(instance):
                instance.status = ServiceStatus.FAILED
                instance.error_message = "依赖服务检查失败"
                return False
            
            # 检查端口可用性
            if not check_port_available(instance.config.port):
                instance.status = ServiceStatus.FAILED
                instance.error_message = f"端口 {instance.config.port} 已被占用"
                logger.error(f"端口冲突: {service_name} - 端口 {instance.config.port} 已被占用")
                return False
            
            # 启动进程
            success = await self._start_process(instance)
            
            if success:
                instance.status = ServiceStatus.RUNNING
                instance.start_time = time.time()
                self.stats['total_starts'] += 1
                self.stats['running_services'] += 1
                
                logger.info(f"服务启动成功: {service_name} (PID: {instance.pid})")
                return True
            else:
                instance.status = ServiceStatus.FAILED
                logger.error(f"服务启动失败: {service_name}")
                return False
                
        except Exception as e:
            instance.status = ServiceStatus.FAILED
            instance.error_message = str(e)
            logger.error(f"启动服务异常 ({service_name}): {e}")
            return False
    
    async def stop_service(self, service_name: str) -> bool:
        """
        停止服务
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否成功停止
        """
        with self.service_lock:
            if service_name not in self.services:
                logger.error(f"服务不存在: {service_name}")
                return False
            
            instance = self.services[service_name]
            
            if instance.status == ServiceStatus.STOPPED:
                logger.warning(f"服务已停止: {service_name}")
                return True
            
            if instance.status == ServiceStatus.STOPPING:
                logger.warning(f"服务正在停止: {service_name}")
                return False
        
        try:
            # 更新状态
            instance.status = ServiceStatus.STOPPING
            
            logger.info(f"停止服务: {service_name}")
            
            # 停止进程
            success = await self._stop_process(instance)
            
            if success:
                instance.status = ServiceStatus.STOPPED
                instance.stop_time = time.time()
                instance.pid = None
                self.stats['total_stops'] += 1
                
                if self.stats['running_services'] > 0:
                    self.stats['running_services'] -= 1
                
                logger.info(f"服务停止成功: {service_name}")
                return True
            else:
                instance.status = ServiceStatus.FAILED
                logger.error(f"服务停止失败: {service_name}")
                return False
                
        except Exception as e:
            instance.status = ServiceStatus.FAILED
            instance.error_message = str(e)
            logger.error(f"停止服务异常 ({service_name}): {e}")
            return False
    
    async def restart_service(self, service_name: str) -> bool:
        """
        重启服务
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否成功重启
        """
        try:
            logger.info(f"重启服务: {service_name}")
            
            # 停止服务
            if not await self.stop_service(service_name):
                return False
            
            # 等待一段时间
            await asyncio.sleep(2)
            
            # 启动服务
            if await self.start_service(service_name):
                with self.service_lock:
                    if service_name in self.services:
                        instance = self.services[service_name]
                        instance.restart_count += 1
                        instance.last_restart_time = time.time()
                        self.stats['total_restarts'] += 1
                
                logger.info(f"服务重启成功: {service_name}")
                return True
            else:
                logger.error(f"服务重启失败: {service_name}")
                return False
                
        except Exception as e:
            logger.error(f"重启服务异常 ({service_name}): {e}")
            return False
    
    async def start_all_services(self) -> bool:
        """
        启动所有服务
        
        Returns:
            bool: 是否成功启动所有服务
        """
        if self.startup_in_progress:
            logger.warning("服务启动正在进行中")
            return False
        
        try:
            self.startup_in_progress = True
            start_time = time.time()
            
            logger.info("开始启动所有服务")
            
            # 获取启动顺序
            startup_sequence = self.config_manager.get_startup_sequence()
            
            # 按顺序启动服务
            success_count = 0
            total_count = len(startup_sequence)
            
            for service_name in startup_sequence:
                if service_name in self.services:
                    if await self.start_service(service_name):
                        success_count += 1
                        
                        # 等待服务稳定
                        await asyncio.sleep(1)
                    else:
                        logger.error(f"启动服务失败: {service_name}")
                        
                        # 根据配置决定是否继续
                        if not self.config_manager.startup_config.wait_for_dependencies:
                            break
            
            self.stats['last_startup_time'] = time.time() - start_time
            
            logger.info(f"服务启动完成: {success_count}/{total_count}")
            return success_count == total_count
            
        except Exception as e:
            logger.error(f"启动所有服务异常: {e}")
            return False
        finally:
            self.startup_in_progress = False
    
    async def stop_all_services(self) -> bool:
        """
        停止所有服务
        
        Returns:
            bool: 是否成功停止所有服务
        """
        if self.shutdown_in_progress:
            logger.warning("服务关闭正在进行中")
            return False
        
        try:
            self.shutdown_in_progress = True
            start_time = time.time()
            
            logger.info("开始停止所有服务")
            
            # 获取运行中的服务
            running_services = []
            with self.service_lock:
                for service_name, instance in self.services.items():
                    if instance.status == ServiceStatus.RUNNING:
                        running_services.append(service_name)
            
            # 反向停止服务（与启动顺序相反）
            running_services.reverse()
            
            success_count = 0
            total_count = len(running_services)
            
            for service_name in running_services:
                if await self.stop_service(service_name):
                    success_count += 1
                    
                    # 等待服务关闭
                    await asyncio.sleep(1)
                else:
                    logger.error(f"停止服务失败: {service_name}")
            
            self.stats['last_shutdown_time'] = time.time() - start_time
            
            logger.info(f"服务关闭完成: {success_count}/{total_count}")
            return success_count == total_count
            
        except Exception as e:
            logger.error(f"停止所有服务异常: {e}")
            return False
        finally:
            self.shutdown_in_progress = False
    
    async def _check_dependencies(self, instance: ServiceInstance) -> bool:
        """
        检查服务依赖
        
        Args:
            instance: 服务实例
            
        Returns:
            bool: 依赖是否满足
        """
        if not instance.config.dependencies:
            return True
        
        for dep_name in instance.config.dependencies:
            if dep_name not in self.services:
                logger.error(f"依赖服务不存在: {dep_name}")
                return False
            
            dep_instance = self.services[dep_name]
            if dep_instance.status != ServiceStatus.RUNNING:
                logger.error(f"依赖服务未运行: {dep_name}")
                return False
            
            # 检查依赖服务健康状态
            if not dep_instance.is_healthy():
                logger.error(f"依赖服务不健康: {dep_name}")
                return False
        
        return True
    
    async def _start_process(self, instance: ServiceInstance) -> bool:
        """
        启动进程
        
        Args:
            instance: 服务实例
            
        Returns:
            bool: 是否成功启动
        """
        try:
            # 获取启动命令和环境
            command = instance.config.get_start_command()
            env_vars = instance.config.get_env_vars()
            working_dir = instance.config.get_working_directory()
            
            # 创建服务进程
            service_process = ServiceProcess(
                service_name=instance.name,
                command=command,
                working_dir=working_dir,
                env_vars=env_vars
            )
            
            # 启动进程
            if not service_process.start():
                return False
            
            # 更新实例信息
            instance.process = service_process
            instance.pid = service_process.pid
            
            # 创建PID文件
            if instance.pid_file:
                create_pid_file(instance.pid_file, instance.pid)
            
            # 注册到进程监控器
            if self.process_monitor:
                self.process_monitor.register_process(
                    pid=instance.pid,
                    name=instance.name,
                    service_name=instance.name
                )
            
            # 等待服务启动
            await asyncio.sleep(instance.config.startup_timeout)
            
            # 检查进程是否仍在运行
            if not is_process_running(instance.pid):
                logger.error(f"进程启动后立即退出: {instance.name}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"启动进程异常 ({instance.name}): {e}")
            return False
    
    async def _stop_process(self, instance: ServiceInstance) -> bool:
        """
        停止进程
        
        Args:
            instance: 服务实例
            
        Returns:
            bool: 是否成功停止
        """
        try:
            if not instance.pid:
                return True
            
            # 从进程监控器取消注册
            if self.process_monitor:
                self.process_monitor.unregister_process(instance.pid)
            
            # 停止进程
            if instance.process:
                success = instance.process.stop(timeout=instance.config.shutdown_timeout)
            else:
                success = kill_process_tree(instance.pid, timeout=instance.config.shutdown_timeout)
            
            # 清理PID文件
            if instance.pid_file:
                remove_pid_file(instance.pid_file)
            
            return success
            
        except Exception as e:
            logger.error(f"停止进程异常 ({instance.name}): {e}")
            return False
    
    def get_service_status(self, service_name: str) -> Optional[Dict[str, Any]]:
        """
        获取服务状态
        
        Args:
            service_name: 服务名称
            
        Returns:
            Optional[Dict[str, Any]]: 服务状态信息
        """
        with self.service_lock:
            if service_name not in self.services:
                return None
            
            instance = self.services[service_name]
            status_info = instance.to_dict()
            
            # 添加健康检查信息
            if self.health_checker:
                # 这里可以添加健康检查结果
                pass
            
            # 添加进程监控信息
            if self.process_monitor and instance.pid:
                process_info = self.process_monitor.get_process_info(instance.pid)
                if process_info:
                    status_info['process_info'] = process_info
            
            return status_info
    
    def get_all_services_status(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有服务状态
        
        Returns:
            Dict[str, Dict[str, Any]]: 所有服务状态信息
        """
        with self.service_lock:
            return {name: self.get_service_status(name) 
                   for name in self.services.keys()}
    
    def get_running_services(self) -> List[str]:
        """
        获取运行中的服务列表
        
        Returns:
            List[str]: 运行中的服务名称列表
        """
        with self.service_lock:
            return [name for name, instance in self.services.items() 
                   if instance.status == ServiceStatus.RUNNING]
    
    def get_stopped_services(self) -> List[str]:
        """
        获取已停止的服务列表
        
        Returns:
            List[str]: 已停止的服务名称列表
        """
        with self.service_lock:
            return [name for name, instance in self.services.items() 
                   if instance.status == ServiceStatus.STOPPED]
    
    def get_failed_services(self) -> List[str]:
        """
        获取失败的服务列表
        
        Returns:
            List[str]: 失败的服务名称列表
        """
        with self.service_lock:
            return [name for name, instance in self.services.items() 
                   if instance.status == ServiceStatus.FAILED]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        with self.service_lock:
            # 更新实时统计
            running_count = sum(1 for instance in self.services.values() 
                              if instance.status == ServiceStatus.RUNNING)
            failed_count = sum(1 for instance in self.services.values() 
                             if instance.status == ServiceStatus.FAILED)
            
            self.stats['running_services'] = running_count
            self.stats['failed_services'] = failed_count
            
            return self.stats.copy()
    
    def is_service_running(self, service_name: str) -> bool:
        """
        检查服务是否运行
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 服务是否运行
        """
        with self.service_lock:
            if service_name not in self.services:
                return False
            
            instance = self.services[service_name]
            return instance.status == ServiceStatus.RUNNING and instance.is_healthy()
    
    async def wait_for_service_ready(self, service_name: str, timeout: int = 30) -> bool:
        """
        等待服务准备就绪
        
        Args:
            service_name: 服务名称
            timeout: 超时时间
            
        Returns:
            bool: 服务是否准备就绪
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.is_service_running(service_name):
                return True
            
            await asyncio.sleep(1)
        
        return False
    
    async def graceful_shutdown(self, timeout: int = 60) -> bool:
        """
        优雅关闭所有服务
        
        Args:
            timeout: 超时时间
            
        Returns:
            bool: 是否成功关闭
        """
        logger.info("开始优雅关闭所有服务")
        
        # 设置超时
        shutdown_task = asyncio.create_task(self.stop_all_services())
        
        try:
            await asyncio.wait_for(shutdown_task, timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning("优雅关闭超时，将强制关闭")
            
            # 强制关闭所有进程
            with self.service_lock:
                for instance in self.services.values():
                    if instance.pid and is_process_running(instance.pid):
                        kill_process_tree(instance.pid, timeout=5)
            
            return False
    
    def __len__(self) -> int:
        """返回服务数量"""
        return len(self.services)
    
    def __contains__(self, service_name: str) -> bool:
        """检查服务是否存在"""
        return service_name in self.services
    
    def __iter__(self):
        """迭代服务名称"""
        return iter(self.services.keys())


# 创建服务管理器实例
def create_service_manager(config_manager: ServiceConfigManager,
                         process_monitor: Optional[ProcessMonitor] = None,
                         health_checker: Optional[HealthChecker] = None,
                         process_pool: Optional[ProcessPool] = None) -> ServiceManager:
    """
    创建服务管理器实例
    
    Args:
        config_manager: 配置管理器
        process_monitor: 进程监控器
        health_checker: 健康检查器
        process_pool: 进程池
        
    Returns:
        ServiceManager: 服务管理器实例
    """
    return ServiceManager(
        config_manager=config_manager,
        process_monitor=process_monitor,
        health_checker=health_checker,
        process_pool=process_pool
    )