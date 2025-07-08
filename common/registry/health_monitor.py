"""
健康监控模块

该模块实现多种健康检查方式（HTTP、TCP、gRPC），支持自定义健康检查逻辑，
实现心跳上报机制、故障检测和自动摘除，以及健康状态变更通知。
"""

import asyncio
import time
import socket
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
try:
    from loguru import logger
except ImportError:
    from ..logger.mock_logger import logger

try:
    import aiohttp
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    logger.warning("aiohttp 未安装，HTTP健康检查将不可用")

try:
    import grpc
    import grpc.aio
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False
    logger.warning("grpcio 未安装，gRPC健康检查将不可用")

from ..utils.singleton import async_singleton
from .base_adapter import BaseRegistryAdapter, ServiceInfo, ServiceStatus, HealthChecker
from .exceptions import HealthCheckError, handle_async_registry_exception


class HealthCheckType(Enum):
    """健康检查类型"""
    HTTP = "http"          # HTTP健康检查
    HTTPS = "https"        # HTTPS健康检查
    TCP = "tcp"            # TCP连接检查
    GRPC = "grpc"          # gRPC健康检查
    CUSTOM = "custom"      # 自定义检查


@dataclass
class HealthCheckConfig:
    """健康检查配置"""
    check_type: HealthCheckType
    interval: float = 5.0                    # 检查间隔（秒）
    timeout: float = 3.0                     # 检查超时（秒）
    max_failures: int = 3                    # 最大失败次数
    success_threshold: int = 2               # 成功阈值（连续成功次数后标记为健康）
    
    # HTTP/HTTPS 特定配置
    path: str = "/health"                    # 健康检查路径
    expected_status: int = 200               # 期望的HTTP状态码
    expected_body: Optional[str] = None      # 期望的响应体内容
    headers: Dict[str, str] = field(default_factory=dict)  # 请求头
    
    # TCP 特定配置
    tcp_port: Optional[int] = None           # TCP端口（默认使用服务端口）
    
    # gRPC 特定配置
    grpc_service: str = ""                   # gRPC服务名
    
    # 自定义检查
    custom_checker: Optional[Callable] = None  # 自定义检查函数


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    service_id: str
    check_type: HealthCheckType
    status: ServiceStatus
    message: str
    response_time: float                     # 响应时间（毫秒）
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
    
    def is_healthy(self) -> bool:
        """判断是否健康"""
        return self.status == ServiceStatus.HEALTHY


@dataclass
class ServiceHealthState:
    """服务健康状态"""
    service_id: str
    current_status: ServiceStatus = ServiceStatus.UNKNOWN
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_check_time: float = 0.0
    last_success_time: float = 0.0
    last_failure_time: float = 0.0
    total_checks: int = 0
    total_failures: int = 0
    check_history: List[HealthCheckResult] = field(default_factory=list)
    
    def update_result(self, result: HealthCheckResult, config: HealthCheckConfig):
        """更新健康检查结果"""
        self.last_check_time = result.timestamp
        self.total_checks += 1
        
        # 保留最近的检查历史（最多100条）
        self.check_history.append(result)
        if len(self.check_history) > 100:
            self.check_history.pop(0)
        
        if result.is_healthy():
            self.consecutive_successes += 1
            self.consecutive_failures = 0
            self.last_success_time = result.timestamp
            
            # 检查是否达到健康阈值
            if (self.current_status != ServiceStatus.HEALTHY and 
                self.consecutive_successes >= config.success_threshold):
                self.current_status = ServiceStatus.HEALTHY
                
        else:
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            self.total_failures += 1
            self.last_failure_time = result.timestamp
            
            # 检查是否达到失败阈值
            if self.consecutive_failures >= config.max_failures:
                if self.consecutive_failures >= config.max_failures * 2:
                    self.current_status = ServiceStatus.CRITICAL
                else:
                    self.current_status = ServiceStatus.UNHEALTHY
    
    def get_success_rate(self) -> float:
        """获取成功率"""
        if self.total_checks == 0:
            return 0.0
        return (self.total_checks - self.total_failures) / self.total_checks
    
    def get_average_response_time(self) -> float:
        """获取平均响应时间"""
        if not self.check_history:
            return 0.0
        
        recent_history = self.check_history[-10:]  # 最近10次
        total_time = sum(result.response_time for result in recent_history)
        return total_time / len(recent_history)


class HTTPHealthChecker(HealthChecker):
    """HTTP健康检查器"""
    
    def __init__(self, session: Optional[Any] = None):
        self._session = session
        self._session_created = False
    
    async def _ensure_session(self):
        """确保HTTP会话存在"""
        if not HTTP_AVAILABLE:
            raise HealthCheckError("aiohttp 未安装，无法进行HTTP健康检查")
        
        if not self._session:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
            self._session_created = True
    
    async def check_health(self, service: ServiceInfo) -> ServiceStatus:
        """执行HTTP健康检查"""
        await self._ensure_session()
        
        # 构建URL
        protocol = "https" if service.health_check_url and service.health_check_url.startswith("https") else "http"
        if service.health_check_url:
            url = service.health_check_url
        else:
            url = f"{protocol}://{service.host}:{service.port}/health"
        
        try:
            start_time = time.time()
            
            async with self._session.get(url, timeout=service.health_check_timeout) as response:
                response_time = (time.time() - start_time) * 1000
                
                if response.status == 200:
                    # 可以添加响应体检查
                    return ServiceStatus.HEALTHY
                else:
                    logger.debug(f"HTTP健康检查失败: {service.id} -> {response.status}")
                    return ServiceStatus.UNHEALTHY
                    
        except asyncio.TimeoutError:
            logger.debug(f"HTTP健康检查超时: {service.id}")
            return ServiceStatus.UNHEALTHY
        except Exception as e:
            logger.debug(f"HTTP健康检查异常: {service.id} - {e}")
            return ServiceStatus.UNHEALTHY
    
    def supports(self, check_type: str) -> bool:
        """检查是否支持指定的检查类型"""
        return check_type.lower() in ["http", "https"]
    
    async def close(self):
        """关闭HTTP会话"""
        if self._session and self._session_created:
            await self._session.close()


class TCPHealthChecker(HealthChecker):
    """TCP健康检查器"""
    
    async def check_health(self, service: ServiceInfo) -> ServiceStatus:
        """执行TCP健康检查"""
        try:
            start_time = time.time()
            
            # 尝试建立TCP连接
            future = asyncio.open_connection(service.host, service.port)
            reader, writer = await asyncio.wait_for(future, timeout=service.health_check_timeout)
            
            # 立即关闭连接
            writer.close()
            await writer.wait_closed()
            
            response_time = (time.time() - start_time) * 1000
            return ServiceStatus.HEALTHY
            
        except asyncio.TimeoutError:
            logger.debug(f"TCP健康检查超时: {service.id}")
            return ServiceStatus.UNHEALTHY
        except Exception as e:
            logger.debug(f"TCP健康检查失败: {service.id} - {e}")
            return ServiceStatus.UNHEALTHY
    
    def supports(self, check_type: str) -> bool:
        """检查是否支持指定的检查类型"""
        return check_type.lower() == "tcp"


class GRPCHealthChecker(HealthChecker):
    """gRPC健康检查器"""
    
    async def check_health(self, service: ServiceInfo) -> ServiceStatus:
        """执行gRPC健康检查"""
        if not GRPC_AVAILABLE:
            raise HealthCheckError("grpcio 未安装，无法进行gRPC健康检查")
        
        try:
            # 创建gRPC通道
            channel = grpc.aio.insecure_channel(f"{service.host}:{service.port}")
            
            # 导入健康检查proto
            from grpc_health.v1 import health_pb2, health_pb2_grpc
            
            # 创建健康检查客户端
            health_stub = health_pb2_grpc.HealthStub(channel)
            
            # 执行健康检查
            request = health_pb2.HealthCheckRequest(service="")
            response = await asyncio.wait_for(
                health_stub.Check(request),
                timeout=service.health_check_timeout
            )
            
            await channel.close()
            
            if response.status == health_pb2.HealthCheckResponse.SERVING:
                return ServiceStatus.HEALTHY
            else:
                return ServiceStatus.UNHEALTHY
                
        except asyncio.TimeoutError:
            logger.debug(f"gRPC健康检查超时: {service.id}")
            return ServiceStatus.UNHEALTHY
        except Exception as e:
            logger.debug(f"gRPC健康检查失败: {service.id} - {e}")
            return ServiceStatus.UNHEALTHY
    
    def supports(self, check_type: str) -> bool:
        """检查是否支持指定的检查类型"""
        return check_type.lower() == "grpc"


@async_singleton
class HealthMonitor:
    """
    健康监控器
    
    负责监控服务健康状态，支持多种检查方式，提供故障检测、
    自动摘除和健康状态变更通知功能。
    """
    
    def __init__(self):
        """初始化健康监控器"""
        self._adapters: Dict[str, BaseRegistryAdapter] = {}
        self._checkers: Dict[HealthCheckType, HealthChecker] = {}
        self._health_states: Dict[str, ServiceHealthState] = {}  # service_id -> state
        self._check_configs: Dict[str, HealthCheckConfig] = {}  # service_id -> config
        self._check_tasks: Dict[str, asyncio.Task] = {}  # service_id -> task
        self._status_change_callbacks: List[Callable[[str, ServiceStatus, ServiceStatus], None]] = []
        self._lock = asyncio.Lock()
        self._running = False
        
        # 注册默认检查器
        self._register_default_checkers()
    
    def _register_default_checkers(self):
        """注册默认的健康检查器"""
        self._checkers[HealthCheckType.HTTP] = HTTPHealthChecker()
        self._checkers[HealthCheckType.HTTPS] = HTTPHealthChecker()
        self._checkers[HealthCheckType.TCP] = TCPHealthChecker()
        self._checkers[HealthCheckType.GRPC] = GRPCHealthChecker()
    
    def add_adapter(self, name: str, adapter: BaseRegistryAdapter) -> None:
        """
        添加注册中心适配器
        
        Args:
            name: 适配器名称
            adapter: 适配器实例
        """
        self._adapters[name] = adapter
        logger.info(f"添加健康监控适配器: {name}")
    
    def register_custom_checker(self, check_type: HealthCheckType, checker: HealthChecker) -> None:
        """
        注册自定义健康检查器
        
        Args:
            check_type: 检查类型
            checker: 检查器实例
        """
        self._checkers[check_type] = checker
        logger.info(f"注册自定义健康检查器: {check_type.value}")
    
    def add_status_change_callback(self, callback: Callable[[str, ServiceStatus, ServiceStatus], None]) -> None:
        """
        添加状态变更回调函数
        
        Args:
            callback: 回调函数，参数为 (service_id, old_status, new_status)
        """
        self._status_change_callbacks.append(callback)
    
    @handle_async_registry_exception
    async def start_monitoring(self, service: ServiceInfo, config: Optional[HealthCheckConfig] = None) -> None:
        """
        开始监控服务健康状态
        
        Args:
            service: 服务信息
            config: 健康检查配置
        """
        if not config:
            # 使用默认配置
            config = HealthCheckConfig(
                check_type=HealthCheckType.HTTP,
                interval=service.health_check_interval,
                timeout=service.health_check_timeout
            )
        
        async with self._lock:
            # 初始化健康状态
            if service.id not in self._health_states:
                self._health_states[service.id] = ServiceHealthState(service_id=service.id)
            
            self._check_configs[service.id] = config
            
            # 启动检查任务
            if service.id not in self._check_tasks:
                task = asyncio.create_task(self._health_check_loop(service, config))
                self._check_tasks[service.id] = task
                logger.info(f"开始健康监控: {service.name}/{service.id}")
    
    async def stop_monitoring(self, service_id: str) -> None:
        """
        停止监控服务健康状态
        
        Args:
            service_id: 服务ID
        """
        async with self._lock:
            if service_id in self._check_tasks:
                task = self._check_tasks.pop(service_id)
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                
                logger.info(f"停止健康监控: {service_id}")
            
            # 清理状态（可选，保留历史记录）
            # if service_id in self._health_states:
            #     del self._health_states[service_id]
            # if service_id in self._check_configs:
            #     del self._check_configs[service_id]
    
    async def perform_health_check(self, service: ServiceInfo, config: HealthCheckConfig) -> HealthCheckResult:
        """
        执行单次健康检查
        
        Args:
            service: 服务信息
            config: 检查配置
            
        Returns:
            HealthCheckResult: 检查结果
        """
        start_time = time.time()
        
        try:
            # 获取对应的检查器
            checker = self._checkers.get(config.check_type)
            if not checker:
                raise HealthCheckError(f"不支持的健康检查类型: {config.check_type.value}")
            
            # 执行检查
            status = await asyncio.wait_for(
                checker.check_health(service),
                timeout=config.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_id=service.id,
                check_type=config.check_type,
                status=status,
                message="健康检查成功" if status == ServiceStatus.HEALTHY else "健康检查失败",
                response_time=response_time,
                timestamp=time.time()
            )
            
        except asyncio.TimeoutError:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_id=service.id,
                check_type=config.check_type,
                status=ServiceStatus.UNHEALTHY,
                message="健康检查超时",
                response_time=response_time,
                timestamp=time.time()
            )
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service_id=service.id,
                check_type=config.check_type,
                status=ServiceStatus.UNHEALTHY,
                message=f"健康检查异常: {e}",
                response_time=response_time,
                timestamp=time.time(),
                details={"error": str(e)}
            )
    
    async def _health_check_loop(self, service: ServiceInfo, config: HealthCheckConfig) -> None:
        """健康检查循环"""
        try:
            while service.id in self._check_tasks:
                try:
                    # 执行健康检查
                    result = await self.perform_health_check(service, config)
                    
                    # 更新健康状态
                    await self._update_health_state(service.id, result, config)
                    
                    # 等待下次检查
                    await asyncio.sleep(config.interval)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"健康检查循环异常: {service.id} - {e}")
                    await asyncio.sleep(config.interval)
                    
        except Exception as e:
            logger.error(f"健康检查任务失败: {service.id} - {e}")
        finally:
            # 清理任务
            if service.id in self._check_tasks:
                del self._check_tasks[service.id]
    
    async def _update_health_state(
        self, 
        service_id: str, 
        result: HealthCheckResult, 
        config: HealthCheckConfig
    ) -> None:
        """更新健康状态"""
        async with self._lock:
            if service_id not in self._health_states:
                self._health_states[service_id] = ServiceHealthState(service_id=service_id)
            
            state = self._health_states[service_id]
            old_status = state.current_status
            
            # 更新状态
            state.update_result(result, config)
            new_status = state.current_status
            
            # 如果状态发生变化，通知注册中心和回调函数
            if old_status != new_status:
                logger.info(f"服务健康状态变更: {service_id} {old_status.value} -> {new_status.value}")
                
                # 更新注册中心
                await self._update_registry_status(service_id, new_status)
                
                # 调用回调函数
                for callback in self._status_change_callbacks:
                    try:
                        callback(service_id, old_status, new_status)
                    except Exception as e:
                        logger.error(f"状态变更回调函数执行失败: {e}")
    
    async def _update_registry_status(self, service_id: str, status: ServiceStatus) -> None:
        """更新注册中心中的服务状态"""
        for adapter_name, adapter in self._adapters.items():
            try:
                await adapter.update_service_status(service_id, status)
            except Exception as e:
                logger.error(f"更新注册中心状态失败: {adapter_name} -> {service_id} - {e}")
    
    def get_service_health(self, service_id: str) -> Optional[ServiceHealthState]:
        """
        获取服务健康状态
        
        Args:
            service_id: 服务ID
            
        Returns:
            Optional[ServiceHealthState]: 健康状态
        """
        return self._health_states.get(service_id)
    
    def get_all_health_states(self) -> Dict[str, ServiceHealthState]:
        """获取所有服务的健康状态"""
        return self._health_states.copy()
    
    def get_healthy_services(self) -> List[str]:
        """获取所有健康的服务ID列表"""
        return [
            service_id for service_id, state in self._health_states.items()
            if state.current_status == ServiceStatus.HEALTHY
        ]
    
    def get_unhealthy_services(self) -> List[str]:
        """获取所有不健康的服务ID列表"""
        return [
            service_id for service_id, state in self._health_states.items()
            if state.current_status in [ServiceStatus.UNHEALTHY, ServiceStatus.CRITICAL]
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_services = len(self._health_states)
        healthy_count = len(self.get_healthy_services())
        unhealthy_count = len(self.get_unhealthy_services())
        
        return {
            "total_services": total_services,
            "healthy_services": healthy_count,
            "unhealthy_services": unhealthy_count,
            "active_monitors": len(self._check_tasks),
            "registered_checkers": len(self._checkers),
            "health_rate": healthy_count / total_services if total_services > 0 else 0.0
        }
    
    async def shutdown(self) -> None:
        """关闭健康监控器"""
        logger.info("开始关闭健康监控器...")
        
        async with self._lock:
            # 停止所有检查任务
            tasks = list(self._check_tasks.values())
            for task in tasks:
                if not task.done():
                    task.cancel()
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            
            # 关闭HTTP会话
            for checker in self._checkers.values():
                if hasattr(checker, 'close'):
                    try:
                        await checker.close()
                    except Exception as e:
                        logger.error(f"关闭健康检查器失败: {e}")
            
            # 清理状态
            self._check_tasks.clear()
            
            logger.info("健康监控器关闭完成")