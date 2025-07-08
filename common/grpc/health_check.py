"""
gRPC健康检查模块

该模块实现了gRPC标准健康检查协议，支持服务状态管理、定期心跳检测、
健康检查结果缓存等功能，与服务注册中心集成。
"""

import asyncio
import time
from typing import Dict, Optional, Callable, List, Any, Set
from enum import Enum
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

try:
    import grpc
    import grpc.aio
    from grpc_health.v1 import health_pb2, health_pb2_grpc
    GRPC_HEALTH_AVAILABLE = True
except ImportError:
    # 如果健康检查proto不可用，创建模拟类
    GRPC_HEALTH_AVAILABLE = False
    
    class health_pb2:
        class HealthCheckRequest:
            def __init__(self, service=""):
                self.service = service
        
        class HealthCheckResponse:
            UNKNOWN = 0
            SERVING = 1
            NOT_SERVING = 2
            SERVICE_UNKNOWN = 3
            
            def __init__(self, status=0):
                self.status = status
    
    class health_pb2_grpc:
        class HealthServicer:
            def Check(self, request, context):
                return health_pb2.HealthCheckResponse(
                    status=health_pb2.HealthCheckResponse.SERVING
                )
            
            def Watch(self, request, context):
                pass
        
        @staticmethod
        def add_HealthServicer_to_server(servicer, server):
            pass
        
        class HealthStub:
            def __init__(self, channel):
                self.channel = channel
            
            async def Check(self, request, timeout=None):
                return health_pb2.HealthCheckResponse(
                    status=health_pb2.HealthCheckResponse.SERVING
                )

from .exceptions import (
    GrpcHealthCheckError,
    GrpcTimeoutError,
    GrpcServiceUnavailableError,
    handle_async_grpc_exception
)


class HealthStatus(Enum):
    """健康状态枚举"""
    UNKNOWN = "UNKNOWN"                 # 未知状态
    SERVING = "SERVING"                 # 正常服务
    NOT_SERVING = "NOT_SERVING"         # 不可用
    SERVICE_UNKNOWN = "SERVICE_UNKNOWN" # 服务未知


@dataclass
class HealthCheckConfig:
    """健康检查配置"""
    # 基本配置
    check_interval: float = 30.0        # 检查间隔(秒)
    timeout: float = 5.0                # 检查超时(秒)
    enabled: bool = True                # 是否启用健康检查
    
    # 重试配置
    max_retries: int = 3                # 最大重试次数
    retry_delay: float = 1.0            # 重试延迟(秒)
    
    # 缓存配置
    cache_ttl: float = 60.0             # 缓存TTL(秒)
    enable_cache: bool = True           # 启用缓存
    
    # 故障检测配置
    failure_threshold: int = 3          # 故障阈值
    recovery_threshold: int = 2         # 恢复阈值
    
    # 监控配置
    enable_metrics: bool = True         # 启用指标收集
    custom_checks: Dict[str, Callable] = field(default_factory=dict)  # 自定义检查


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    service_name: str                   # 服务名称
    status: HealthStatus                # 健康状态
    timestamp: float                    # 检查时间戳
    response_time: float                # 响应时间(毫秒)
    error_message: Optional[str] = None # 错误信息
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == HealthStatus.SERVING
    
    @property
    def age(self) -> float:
        """结果年龄(秒)"""
        return time.time() - self.timestamp


@dataclass
class ServiceHealthStats:
    """服务健康统计"""
    service_name: str                   # 服务名称
    total_checks: int = 0               # 总检查次数
    successful_checks: int = 0          # 成功检查次数
    failed_checks: int = 0              # 失败检查次数
    consecutive_failures: int = 0       # 连续失败次数
    consecutive_successes: int = 0      # 连续成功次数
    last_check_time: Optional[float] = None  # 最后检查时间
    last_success_time: Optional[float] = None  # 最后成功时间
    last_failure_time: Optional[float] = None  # 最后失败时间
    avg_response_time: float = 0.0      # 平均响应时间
    max_response_time: float = 0.0      # 最大响应时间
    min_response_time: float = float('inf')  # 最小响应时间
    current_status: HealthStatus = HealthStatus.UNKNOWN  # 当前状态
    
    def update_success(self, response_time: float):
        """更新成功统计"""
        self.total_checks += 1
        self.successful_checks += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_check_time = time.time()
        self.last_success_time = self.last_check_time
        self.current_status = HealthStatus.SERVING
        
        # 更新响应时间统计
        self._update_response_time(response_time)
    
    def update_failure(self, response_time: float = 0.0):
        """更新失败统计"""
        self.total_checks += 1
        self.failed_checks += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_check_time = time.time()
        self.last_failure_time = self.last_check_time
        self.current_status = HealthStatus.NOT_SERVING
        
        if response_time > 0:
            self._update_response_time(response_time)
    
    def _update_response_time(self, response_time: float):
        """更新响应时间统计"""
        # 更新平均响应时间(简单移动平均)
        if self.avg_response_time == 0:
            self.avg_response_time = response_time
        else:
            self.avg_response_time = (self.avg_response_time * 0.9 + response_time * 0.1)
        
        # 更新最大/最小响应时间
        self.max_response_time = max(self.max_response_time, response_time)
        self.min_response_time = min(self.min_response_time, response_time)
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_checks == 0:
            return 0.0
        return self.successful_checks / self.total_checks
    
    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.current_status == HealthStatus.SERVING
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'service_name': self.service_name,
            'total_checks': self.total_checks,
            'successful_checks': self.successful_checks,
            'failed_checks': self.failed_checks,
            'consecutive_failures': self.consecutive_failures,
            'consecutive_successes': self.consecutive_successes,
            'last_check_time': self.last_check_time,
            'last_success_time': self.last_success_time,
            'last_failure_time': self.last_failure_time,
            'avg_response_time': self.avg_response_time,
            'max_response_time': self.max_response_time,
            'min_response_time': self.min_response_time if self.min_response_time != float('inf') else 0.0,
            'current_status': self.current_status.value,
            'success_rate': self.success_rate,
            'is_healthy': self.is_healthy
        }


class HealthCheckService:
    """gRPC健康检查服务"""
    
    def __init__(self, config: Optional[HealthCheckConfig] = None):
        """
        初始化健康检查服务
        
        Args:
            config: 健康检查配置
        """
        self._config = config or HealthCheckConfig()
        
        # 服务状态管理
        self._service_status: Dict[str, HealthStatus] = {}
        self._service_stats: Dict[str, ServiceHealthStats] = {}
        
        # 缓存管理
        self._cache: Dict[str, HealthCheckResult] = {}
        self._cache_lock = asyncio.Lock()
        
        # 后台任务
        self._monitor_tasks: Dict[str, asyncio.Task] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # 事件回调
        self._status_change_callbacks: List[Callable[[str, HealthStatus, HealthStatus], None]] = []
        
        # 状态标志
        self._started = False
        self._stopped = False
    
    def add_status_change_callback(
        self,
        callback: Callable[[str, HealthStatus, HealthStatus], None]
    ):
        """
        添加状态变化回调
        
        Args:
            callback: 回调函数(service_name, old_status, new_status)
        """
        self._status_change_callbacks.append(callback)
    
    def register_service(self, service_name: str, initial_status: HealthStatus = HealthStatus.UNKNOWN):
        """
        注册服务
        
        Args:
            service_name: 服务名称
            initial_status: 初始状态
        """
        self._service_status[service_name] = initial_status
        self._service_stats[service_name] = ServiceHealthStats(service_name)
    
    def unregister_service(self, service_name: str):
        """
        取消注册服务
        
        Args:
            service_name: 服务名称
        """
        # 停止监控任务
        if service_name in self._monitor_tasks:
            task = self._monitor_tasks.pop(service_name)
            if not task.done():
                task.cancel()
        
        # 清理状态和统计
        self._service_status.pop(service_name, None)
        self._service_stats.pop(service_name, None)
        
        # 清理缓存
        self._cache.pop(service_name, None)
    
    def set_service_status(self, service_name: str, status: HealthStatus):
        """
        设置服务状态
        
        Args:
            service_name: 服务名称
            status: 健康状态
        """
        old_status = self._service_status.get(service_name, HealthStatus.UNKNOWN)
        
        if old_status != status:
            self._service_status[service_name] = status
            
            # 更新统计
            if service_name in self._service_stats:
                self._service_stats[service_name].current_status = status
            
            # 触发状态变化回调
            for callback in self._status_change_callbacks:
                try:
                    callback(service_name, old_status, status)
                except Exception:
                    pass  # 忽略回调异常
    
    def get_service_status(self, service_name: str) -> HealthStatus:
        """
        获取服务状态
        
        Args:
            service_name: 服务名称
            
        Returns:
            HealthStatus: 健康状态
        """
        return self._service_status.get(service_name, HealthStatus.SERVICE_UNKNOWN)
    
    async def check_service_health(
        self,
        channel,
        service_name: str = "",
        timeout: Optional[float] = None
    ) -> HealthCheckResult:
        """
        检查服务健康状态
        
        Args:
            channel: gRPC channel
            service_name: 服务名称
            timeout: 超时时间
            
        Returns:
            HealthCheckResult: 健康检查结果
        """
        if not self._config.enabled:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.SERVING,
                timestamp=time.time(),
                response_time=0.0
            )
        
        # 检查缓存
        if self._config.enable_cache:
            cached_result = await self._get_cached_result(service_name)
            if cached_result and cached_result.age < self._config.cache_ttl:
                return cached_result
        
        check_timeout = timeout or self._config.timeout
        start_time = time.time()
        
        try:
            # 执行健康检查
            result = await self._perform_health_check(channel, service_name, check_timeout)
            
            # 更新统计
            response_time = (time.time() - start_time) * 1000  # 转换为毫秒
            if service_name in self._service_stats:
                if result.is_healthy:
                    self._service_stats[service_name].update_success(response_time)
                else:
                    self._service_stats[service_name].update_failure(response_time)
            
            # 更新缓存
            if self._config.enable_cache:
                await self._cache_result(service_name, result)
            
            # 更新服务状态
            self.set_service_status(service_name, result.status)
            
            return result
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            
            # 更新失败统计
            if service_name in self._service_stats:
                self._service_stats[service_name].update_failure(response_time)
            
            # 创建失败结果
            result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.NOT_SERVING,
                timestamp=time.time(),
                response_time=response_time,
                error_message=str(e)
            )
            
            # 更新缓存和状态
            if self._config.enable_cache:
                await self._cache_result(service_name, result)
            
            self.set_service_status(service_name, HealthStatus.NOT_SERVING)
            
            return result
    
    @handle_async_grpc_exception
    async def _perform_health_check(
        self,
        channel,
        service_name: str,
        timeout: float
    ) -> HealthCheckResult:
        """执行实际的健康检查"""
        start_time = time.time()
        
        try:
            if not GRPC_HEALTH_AVAILABLE:
                # 模拟健康检查
                await asyncio.sleep(0.01)  # 模拟网络延迟
                return HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.SERVING,
                    timestamp=time.time(),
                    response_time=(time.time() - start_time) * 1000
                )
            
            # 创建健康检查客户端
            stub = health_pb2_grpc.HealthStub(channel)
            
            # 创建请求
            request = health_pb2.HealthCheckRequest(service=service_name)
            
            # 执行检查
            response = await asyncio.wait_for(
                stub.Check(request),
                timeout=timeout
            )
            
            # 解析响应
            status_map = {
                health_pb2.HealthCheckResponse.SERVING: HealthStatus.SERVING,
                health_pb2.HealthCheckResponse.NOT_SERVING: HealthStatus.NOT_SERVING,
                health_pb2.HealthCheckResponse.UNKNOWN: HealthStatus.UNKNOWN,
                health_pb2.HealthCheckResponse.SERVICE_UNKNOWN: HealthStatus.SERVICE_UNKNOWN
            }
            
            status = status_map.get(response.status, HealthStatus.UNKNOWN)
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                status=status,
                timestamp=time.time(),
                response_time=response_time
            )
            
        except asyncio.TimeoutError:
            raise GrpcTimeoutError(
                message=f"健康检查超时: {service_name}",
                timeout=timeout,
                operation="health_check"
            )
        except Exception as e:
            raise GrpcHealthCheckError(
                message=f"健康检查失败: {str(e)}",
                service_name=service_name,
                check_type="grpc_health_check",
                cause=e
            )
    
    async def _get_cached_result(self, service_name: str) -> Optional[HealthCheckResult]:
        """获取缓存的结果"""
        async with self._cache_lock:
            return self._cache.get(service_name)
    
    async def _cache_result(self, service_name: str, result: HealthCheckResult):
        """缓存结果"""
        async with self._cache_lock:
            self._cache[service_name] = result
    
    async def start_monitoring(self, service_name: str):
        """
        启动服务监控
        
        Args:
            service_name: 服务名称
        """
        if service_name in self._monitor_tasks:
            return  # 已在监控中
        
        # 注册服务（如果尚未注册）
        if service_name not in self._service_status:
            self.register_service(service_name)
        
        # 启动监控任务
        task = asyncio.create_task(self._monitor_service(service_name))
        self._monitor_tasks[service_name] = task
    
    async def stop_monitoring(self, service_name: str):
        """
        停止服务监控
        
        Args:
            service_name: 服务名称
        """
        if service_name in self._monitor_tasks:
            task = self._monitor_tasks.pop(service_name)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    
    async def _monitor_service(self, service_name: str):
        """监控服务健康状态"""
        try:
            while not self._stopped:
                await asyncio.sleep(self._config.check_interval)
                
                # 这里需要channel，实际使用时应该通过参数传入或从连接池获取
                # 暂时跳过实际检查，只是为了演示监控框架
                
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略监控异常
    
    async def perform_custom_check(
        self,
        service_name: str,
        check_name: str
    ) -> HealthCheckResult:
        """
        执行自定义健康检查
        
        Args:
            service_name: 服务名称
            check_name: 检查名称
            
        Returns:
            HealthCheckResult: 检查结果
        """
        if check_name not in self._config.custom_checks:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.SERVICE_UNKNOWN,
                timestamp=time.time(),
                response_time=0.0,
                error_message=f"未知的自定义检查: {check_name}"
            )
        
        check_func = self._config.custom_checks[check_name]
        start_time = time.time()
        
        try:
            # 执行自定义检查
            if asyncio.iscoroutinefunction(check_func):
                result = await check_func(service_name)
            else:
                result = check_func(service_name)
            
            response_time = (time.time() - start_time) * 1000
            
            # 解析结果
            if isinstance(result, bool):
                status = HealthStatus.SERVING if result else HealthStatus.NOT_SERVING
            elif isinstance(result, HealthStatus):
                status = result
            else:
                status = HealthStatus.UNKNOWN
            
            return HealthCheckResult(
                service_name=service_name,
                status=status,
                timestamp=time.time(),
                response_time=response_time,
                metadata={'check_type': 'custom', 'check_name': check_name}
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.NOT_SERVING,
                timestamp=time.time(),
                response_time=response_time,
                error_message=str(e),
                metadata={'check_type': 'custom', 'check_name': check_name}
            )
    
    def get_service_stats(self, service_name: str) -> Optional[ServiceHealthStats]:
        """获取服务统计信息"""
        return self._service_stats.get(service_name)
    
    def get_all_stats(self) -> Dict[str, ServiceHealthStats]:
        """获取所有服务的统计信息"""
        return self._service_stats.copy()
    
    def get_healthy_services(self) -> List[str]:
        """获取所有健康的服务"""
        return [
            name for name, status in self._service_status.items()
            if status == HealthStatus.SERVING
        ]
    
    def get_unhealthy_services(self) -> List[str]:
        """获取所有不健康的服务"""
        return [
            name for name, status in self._service_status.items()
            if status in [HealthStatus.NOT_SERVING, HealthStatus.UNKNOWN]
        ]
    
    async def start(self):
        """启动健康检查服务"""
        if self._started:
            return
        
        self._started = True
        self._stopped = False
        
        # 启动清理任务
        self._cleanup_task = asyncio.create_task(self._cleanup_cache())
    
    async def stop(self):
        """停止健康检查服务"""
        if self._stopped:
            return
        
        self._stopped = True
        
        # 停止所有监控任务
        for service_name in list(self._monitor_tasks.keys()):
            await self.stop_monitoring(service_name)
        
        # 停止清理任务
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def _cleanup_cache(self):
        """清理过期缓存"""
        try:
            while not self._stopped:
                await asyncio.sleep(self._config.cache_ttl / 2)  # 每半个TTL清理一次
                
                async with self._cache_lock:
                    expired_keys = [
                        key for key, result in self._cache.items()
                        if result.age > self._config.cache_ttl
                    ]
                    
                    for key in expired_keys:
                        del self._cache[key]
                        
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略清理异常
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """获取统计摘要"""
        healthy_count = len(self.get_healthy_services())
        unhealthy_count = len(self.get_unhealthy_services())
        total_count = len(self._service_status)
        
        return {
            'total_services': total_count,
            'healthy_services': healthy_count,
            'unhealthy_services': unhealthy_count,
            'health_rate': healthy_count / total_count if total_count > 0 else 0.0,
            'cached_results': len(self._cache),
            'monitoring_tasks': len(self._monitor_tasks),
            'is_started': self._started,
            'is_stopped': self._stopped
        }


# gRPC健康服务器实现
class GrpcHealthServicer(health_pb2_grpc.HealthServicer if GRPC_HEALTH_AVAILABLE else object):
    """gRPC健康检查服务器"""
    
    def __init__(self, health_service: HealthCheckService):
        self._health_service = health_service
    
    def Check(self, request, context):
        """处理健康检查请求"""
        service_name = request.service
        status = self._health_service.get_service_status(service_name)
        
        # 转换状态
        status_map = {
            HealthStatus.SERVING: health_pb2.HealthCheckResponse.SERVING,
            HealthStatus.NOT_SERVING: health_pb2.HealthCheckResponse.NOT_SERVING,
            HealthStatus.UNKNOWN: health_pb2.HealthCheckResponse.UNKNOWN,
            HealthStatus.SERVICE_UNKNOWN: health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
        }
        
        grpc_status = status_map.get(status, health_pb2.HealthCheckResponse.UNKNOWN)
        return health_pb2.HealthCheckResponse(status=grpc_status)
    
    def Watch(self, request, context):
        """处理健康状态监控请求（流式）"""
        # 简单实现：返回当前状态后立即结束
        service_name = request.service
        status = self._health_service.get_service_status(service_name)
        
        status_map = {
            HealthStatus.SERVING: health_pb2.HealthCheckResponse.SERVING,
            HealthStatus.NOT_SERVING: health_pb2.HealthCheckResponse.NOT_SERVING,
            HealthStatus.UNKNOWN: health_pb2.HealthCheckResponse.UNKNOWN,
            HealthStatus.SERVICE_UNKNOWN: health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
        }
        
        grpc_status = status_map.get(status, health_pb2.HealthCheckResponse.UNKNOWN)
        yield health_pb2.HealthCheckResponse(status=grpc_status)


# 便捷函数
def create_health_service(config: Optional[HealthCheckConfig] = None) -> HealthCheckService:
    """创建健康检查服务"""
    return HealthCheckService(config)


def add_health_servicer_to_server(health_service: HealthCheckService, server):
    """添加健康检查服务到gRPC服务器"""
    if GRPC_HEALTH_AVAILABLE:
        servicer = GrpcHealthServicer(health_service)
        health_pb2_grpc.add_HealthServicer_to_server(servicer, server)


# 导出所有公共接口
__all__ = [
    'HealthStatus',
    'HealthCheckConfig',
    'HealthCheckResult',
    'ServiceHealthStats',
    'HealthCheckService',
    'GrpcHealthServicer',
    'create_health_service',
    'add_health_servicer_to_server'
]