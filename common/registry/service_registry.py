"""
服务注册模块

该模块实现服务注册功能，支持自动生成唯一服务ID、服务元数据注册、
优雅关闭时的自动注销，以及多注册中心同时注册。
"""

import asyncio
import time
import socket
import threading
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
try:
    from loguru import logger
except ImportError:
    from ..logger.mock_logger import logger

try:
    from ..utils.id_generator import generate_unique_id
except ImportError:
    # 简单的 ID 生成器备用实现
    import uuid
    import time
    import socket
    
    def generate_unique_id(prefix: str = "") -> str:
        """生成唯一ID的简单实现"""
        timestamp = int(time.time() * 1000)
        hostname = socket.gethostname()[:8]
        unique_part = str(uuid.uuid4())[:8]
        
        if prefix:
            return f"{prefix}-{hostname}-{timestamp}-{unique_part}"
        else:
            return f"{hostname}-{timestamp}-{unique_part}"
from ..utils.singleton import async_singleton
from .base_adapter import BaseRegistryAdapter, ServiceInfo, ServiceStatus
from .exceptions import (
    BaseRegistryException, ServiceRegistrationError,
    handle_async_registry_exception
)


@dataclass
class RegistrationResult:
    """注册结果"""
    service_id: str
    adapter_name: str
    success: bool
    error: Optional[Exception] = None
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@async_singleton
class ServiceRegistry:
    """
    服务注册器
    
    负责管理服务的注册、注销和续期，支持多注册中心同时注册，
    提供优雅关闭和自动续期功能。
    """
    
    def __init__(self):
        """初始化服务注册器"""
        self._adapters: Dict[str, BaseRegistryAdapter] = {}
        self._registered_services: Dict[str, ServiceInfo] = {}  # service_id -> ServiceInfo
        self._adapter_services: Dict[str, Set[str]] = {}  # adapter_name -> set of service_ids
        self._renewal_tasks: Dict[str, asyncio.Task] = {}  # service_id -> renewal task
        self._shutdown_handlers: List[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        
        # 设置优雅关闭处理
        self._setup_shutdown_handlers()
    
    def _setup_shutdown_handlers(self):
        """设置优雅关闭处理器"""
        import signal
        
        def signal_handler(signum, frame):
            """信号处理器"""
            logger.info(f"接收到信号 {signum}，开始优雅关闭...")
            asyncio.create_task(self.shutdown())
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def add_adapter(self, name: str, adapter: BaseRegistryAdapter) -> None:
        """
        添加注册中心适配器
        
        Args:
            name: 适配器名称
            adapter: 适配器实例
        """
        self._adapters[name] = adapter
        self._adapter_services[name] = set()
        logger.info(f"添加注册中心适配器: {name}")
    
    def remove_adapter(self, name: str) -> bool:
        """
        移除注册中心适配器
        
        Args:
            name: 适配器名称
            
        Returns:
            bool: 是否成功移除
        """
        if name in self._adapters:
            del self._adapters[name]
            if name in self._adapter_services:
                del self._adapter_services[name]
            logger.info(f"移除注册中心适配器: {name}")
            return True
        return False
    
    def generate_service_id(
        self, 
        service_name: str, 
        host: Optional[str] = None, 
        port: Optional[int] = None
    ) -> str:
        """
        生成唯一的服务ID
        
        格式：{service_name}-{hostname}-{port}-{timestamp}-{random}
        
        Args:
            service_name: 服务名称
            host: 主机地址
            port: 端口号
            
        Returns:
            str: 唯一的服务ID
        """
        if not host:
            host = socket.gethostname()
        
        # 清理主机名（移除非字母数字字符）
        clean_host = ''.join(c for c in host if c.isalnum() or c in '-_')
        
        # 生成基础前缀
        prefix_parts = [service_name, clean_host]
        if port:
            prefix_parts.append(str(port))
            
        prefix = '-'.join(prefix_parts)
        
        # 使用工具生成唯一ID
        return generate_unique_id(prefix)
    
    @handle_async_registry_exception
    async def register(
        self, 
        service: ServiceInfo,
        adapters: Optional[List[str]] = None,
        auto_renew: bool = True
    ) -> Dict[str, RegistrationResult]:
        """
        注册服务到注册中心
        
        Args:
            service: 服务信息
            adapters: 指定的适配器列表，None表示使用所有适配器
            auto_renew: 是否自动续期
            
        Returns:
            Dict[str, RegistrationResult]: 注册结果，key为适配器名称
        """
        if not self._adapters:
            raise ServiceRegistrationError("没有可用的注册中心适配器")
        
        # 确定要使用的适配器
        target_adapters = adapters if adapters else list(self._adapters.keys())
        invalid_adapters = [name for name in target_adapters if name not in self._adapters]
        
        if invalid_adapters:
            raise ServiceRegistrationError(f"未知的适配器: {invalid_adapters}")
        
        results: Dict[str, RegistrationResult] = {}
        
        async with self._lock:
            try:
                # 如果没有指定服务ID，自动生成
                if not service.id:
                    service.id = self.generate_service_id(service.name, service.host, service.port)
                
                logger.info(f"开始注册服务: {service.name}/{service.id}")
                
                # 逐个适配器注册
                successful_adapters = []
                
                for adapter_name in target_adapters:
                    adapter = self._adapters[adapter_name]
                    
                    try:
                        # 连接适配器
                        if not adapter.is_connected:
                            await adapter.connect()
                        
                        # 注册服务
                        success = await adapter.register_service(service)
                        
                        if success:
                            successful_adapters.append(adapter_name)
                            self._adapter_services[adapter_name].add(service.id)
                            
                            results[adapter_name] = RegistrationResult(
                                service_id=service.id,
                                adapter_name=adapter_name,
                                success=True
                            )
                            
                            logger.info(f"服务注册成功: {adapter_name} -> {service.name}/{service.id}")
                        else:
                            results[adapter_name] = RegistrationResult(
                                service_id=service.id,
                                adapter_name=adapter_name,
                                success=False,
                                error=Exception("注册返回失败")
                            )
                            
                    except Exception as e:
                        logger.error(f"服务注册失败: {adapter_name} -> {service.name}/{service.id} - {e}")
                        results[adapter_name] = RegistrationResult(
                            service_id=service.id,
                            adapter_name=adapter_name,
                            success=False,
                            error=e
                        )
                
                # 如果至少有一个适配器注册成功，则保存服务信息
                if successful_adapters:
                    self._registered_services[service.id] = service
                    
                    # 启动自动续期
                    if auto_renew:
                        await self._start_renewal_task(service.id)
                        
                    logger.info(f"服务注册完成: {service.name}/{service.id} -> "
                              f"{len(successful_adapters)}/{len(target_adapters)} 个适配器成功")
                else:
                    logger.error(f"服务注册失败: {service.name}/{service.id} -> 所有适配器都失败")
                    raise ServiceRegistrationError(
                        f"所有适配器注册失败: {service.name}/{service.id}",
                        service_name=service.name,
                        service_id=service.id
                    )
                
                return results
                
            except Exception as e:
                logger.error(f"服务注册过程异常: {service.name} - {e}")
                # 清理部分注册的服务
                await self._cleanup_partial_registration(service.id, results)
                raise
    
    @handle_async_registry_exception
    async def deregister(
        self, 
        service_id: str,
        adapters: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """
        从注册中心注销服务
        
        Args:
            service_id: 服务ID
            adapters: 指定的适配器列表，None表示使用所有相关适配器
            
        Returns:
            Dict[str, bool]: 注销结果，key为适配器名称，value为是否成功
        """
        if service_id not in self._registered_services:
            logger.warning(f"尝试注销未知服务: {service_id}")
            return {}
        
        # 确定要注销的适配器
        if adapters:
            target_adapters = [name for name in adapters if name in self._adapters]
        else:
            target_adapters = [
                name for name, service_ids in self._adapter_services.items()
                if service_id in service_ids
            ]
        
        results: Dict[str, bool] = {}
        
        async with self._lock:
            try:
                service = self._registered_services[service_id]
                logger.info(f"开始注销服务: {service.name}/{service_id}")
                
                # 停止续期任务
                await self._stop_renewal_task(service_id)
                
                # 逐个适配器注销
                for adapter_name in target_adapters:
                    adapter = self._adapters[adapter_name]
                    
                    try:
                        success = await adapter.deregister_service(service_id)
                        results[adapter_name] = success
                        
                        if success:
                            self._adapter_services[adapter_name].discard(service_id)
                            logger.info(f"服务注销成功: {adapter_name} -> {service.name}/{service_id}")
                        else:
                            logger.warning(f"服务注销失败: {adapter_name} -> {service.name}/{service_id}")
                            
                    except Exception as e:
                        logger.error(f"服务注销异常: {adapter_name} -> {service.name}/{service_id} - {e}")
                        results[adapter_name] = False
                
                # 如果所有适配器都注销成功，或者没有剩余的适配器，则清理本地记录
                remaining_adapters = [
                    name for name, service_ids in self._adapter_services.items()
                    if service_id in service_ids
                ]
                
                if not remaining_adapters:
                    del self._registered_services[service_id]
                    logger.info(f"服务完全注销: {service.name}/{service_id}")
                
                return results
                
            except Exception as e:
                logger.error(f"服务注销过程异常: {service_id} - {e}")
                raise ServiceRegistrationError(
                    f"注销服务失败: {e}",
                    service_id=service_id,
                    cause=e
                )
    
    async def update_service_status(
        self, 
        service_id: str, 
        status: ServiceStatus,
        adapters: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """
        更新服务状态
        
        Args:
            service_id: 服务ID
            status: 新状态
            adapters: 指定的适配器列表
            
        Returns:
            Dict[str, bool]: 更新结果
        """
        if service_id not in self._registered_services:
            logger.warning(f"尝试更新未知服务状态: {service_id}")
            return {}
        
        service = self._registered_services[service_id]
        service.status = status
        service.last_seen = time.time()
        
        # 确定要更新的适配器
        if adapters:
            target_adapters = [name for name in adapters if name in self._adapters]
        else:
            target_adapters = [
                name for name, service_ids in self._adapter_services.items()
                if service_id in service_ids
            ]
        
        results: Dict[str, bool] = {}
        
        for adapter_name in target_adapters:
            adapter = self._adapters[adapter_name]
            
            try:
                success = await adapter.update_service_status(service_id, status)
                results[adapter_name] = success
                
                if success:
                    logger.debug(f"服务状态更新成功: {adapter_name} -> {service_id} -> {status.value}")
                else:
                    logger.warning(f"服务状态更新失败: {adapter_name} -> {service_id}")
                    
            except Exception as e:
                logger.error(f"服务状态更新异常: {adapter_name} -> {service_id} - {e}")
                results[adapter_name] = False
        
        return results
    
    async def get_registered_services(self) -> Dict[str, ServiceInfo]:
        """
        获取已注册的服务列表
        
        Returns:
            Dict[str, ServiceInfo]: 服务列表，key为服务ID
        """
        return self._registered_services.copy()
    
    async def get_service_info(self, service_id: str) -> Optional[ServiceInfo]:
        """
        获取服务信息
        
        Args:
            service_id: 服务ID
            
        Returns:
            Optional[ServiceInfo]: 服务信息
        """
        return self._registered_services.get(service_id)
    
    async def _start_renewal_task(self, service_id: str) -> None:
        """启动服务续期任务"""
        if service_id in self._renewal_tasks:
            return  # 任务已存在
        
        service = self._registered_services[service_id]
        renewal_interval = max(1, service.ttl // 3)  # 每 TTL/3 时间续期一次
        
        async def renewal_loop():
            """续期循环"""
            while service_id in self._registered_services and not self._shutdown_event.is_set():
                try:
                    await asyncio.sleep(renewal_interval)
                    
                    if self._shutdown_event.is_set():
                        break
                    
                    # 续期所有相关适配器
                    for adapter_name, service_ids in self._adapter_services.items():
                        if service_id in service_ids:
                            adapter = self._adapters[adapter_name]
                            try:
                                await adapter.renew_lease(service_id)
                                logger.debug(f"服务续期成功: {adapter_name} -> {service_id}")
                            except Exception as e:
                                logger.warning(f"服务续期失败: {adapter_name} -> {service_id} - {e}")
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"服务续期任务异常: {service_id} - {e}")
                    await asyncio.sleep(renewal_interval)
        
        task = asyncio.create_task(renewal_loop())
        self._renewal_tasks[service_id] = task
        logger.debug(f"启动服务续期任务: {service_id}, 间隔: {renewal_interval}秒")
    
    async def _stop_renewal_task(self, service_id: str) -> None:
        """停止服务续期任务"""
        if service_id in self._renewal_tasks:
            task = self._renewal_tasks.pop(service_id)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            logger.debug(f"停止服务续期任务: {service_id}")
    
    async def _cleanup_partial_registration(
        self, 
        service_id: str, 
        results: Dict[str, RegistrationResult]
    ) -> None:
        """清理部分注册的服务"""
        successful_adapters = [
            adapter_name for adapter_name, result in results.items()
            if result.success
        ]
        
        if successful_adapters:
            logger.info(f"清理部分注册的服务: {service_id}")
            try:
                await self.deregister(service_id, successful_adapters)
            except Exception as e:
                logger.error(f"清理部分注册失败: {service_id} - {e}")
    
    async def shutdown(self) -> None:
        """
        优雅关闭服务注册器
        
        注销所有已注册的服务并清理资源
        """
        logger.info("开始优雅关闭服务注册器...")
        self._shutdown_event.set()
        
        async with self._lock:
            try:
                # 注销所有服务
                service_ids = list(self._registered_services.keys())
                for service_id in service_ids:
                    try:
                        await self.deregister(service_id)
                    except Exception as e:
                        logger.error(f"关闭时注销服务失败: {service_id} - {e}")
                
                # 停止所有续期任务
                tasks = list(self._renewal_tasks.values())
                for task in tasks:
                    if not task.done():
                        task.cancel()
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # 断开所有适配器连接
                for adapter_name, adapter in self._adapters.items():
                    try:
                        await adapter.disconnect()
                    except Exception as e:
                        logger.error(f"断开适配器连接失败: {adapter_name} - {e}")
                
                # 清理状态
                self._registered_services.clear()
                self._adapter_services.clear()
                self._renewal_tasks.clear()
                
                logger.info("服务注册器优雅关闭完成")
                
            except Exception as e:
                logger.error(f"优雅关闭异常: {e}")
                raise