"""
gRPC健康检查服务模块

实现gRPC标准健康检查协议，支持服务状态管理、定期心跳检测、
健康检查结果缓存和自定义健康检查逻辑。
"""

import asyncio
import time
from typing import Dict, Optional, List, Callable, Any, Set
from enum import Enum
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

try:
    import grpc
    from grpc import aio as grpc_aio
    from grpc_health.v1 import health_pb2, health_pb2_grpc
except ImportError:
    # 如果grpc未安装，创建模拟对象
    grpc = None
    grpc_aio = None
    
    # 模拟health_pb2的内容
    class health_pb2:
        class HealthCheckRequest:
            def __init__(self, service=""):
                self.service = service
        
        class HealthCheckResponse:
            UNKNOWN = 0
            SERVING = 1
            NOT_SERVING = 2
            
            def __init__(self, status=0):
                self.status = status
    
    class health_pb2_grpc:
        class HealthServicer:
            pass
        
        @staticmethod
        def add_HealthServicer_to_server(servicer, server):
            pass

from ..logger import logger
from .exceptions import GrpcHealthCheckError, handle_grpc_exception_async


class HealthStatus(Enum):
    """健康状态枚举"""
    UNKNOWN = "UNKNOWN"
    SERVING = "SERVING"
    NOT_SERVING = "NOT_SERVING"
    SERVICE_UNKNOWN = "SERVICE_UNKNOWN"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    
    service_name: str
    status: HealthStatus
    timestamp: float = field(default_factory=time.time)
    message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    check_duration: float = 0.0
    
    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == HealthStatus.SERVING
    
    @property
    def age(self) -> float:
        """结果年龄（秒）"""
        return time.time() - self.timestamp
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "service_name": self.service_name,
            "status": self.status.value,
            "timestamp": self.timestamp,
            "message": self.message,
            "details": self.details or {},
            "check_duration": self.check_duration,
            "is_healthy": self.is_healthy,
            "age": self.age
        }


class HealthChecker(ABC):
    """
    健康检查器基类
    
    定义健康检查的通用接口。
    """
    
    @abstractmethod
    async def check_health(self, service_name: str) -> HealthCheckResult:
        """
        执行健康检查
        
        Args:
            service_name: 服务名称
            
        Returns:
            HealthCheckResult: 健康检查结果
        """
        pass


class DefaultHealthChecker(HealthChecker):
    """
    默认健康检查器
    
    简单的健康检查实现。
    """
    
    def __init__(self, healthy_services: Optional[Set[str]] = None):
        """
        初始化默认健康检查器
        
        Args:
            healthy_services: 健康的服务集合
        """
        self.healthy_services = healthy_services or set()
    
    async def check_health(self, service_name: str) -> HealthCheckResult:
        """执行默认健康检查"""
        start_time = time.time()
        
        try:
            if service_name in self.healthy_services or service_name == "":
                status = HealthStatus.SERVING
                message = "服务正常"
            else:
                status = HealthStatus.NOT_SERVING
                message = "服务不可用"
            
            check_duration = time.time() - start_time
            
            return HealthCheckResult(
                service_name=service_name,
                status=status,
                message=message,
                check_duration=check_duration
            )
            
        except Exception as e:
            check_duration = time.time() - start_time
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNKNOWN,
                message=f"健康检查异常: {e}",
                check_duration=check_duration
            )
    
    def add_service(self, service_name: str) -> None:
        """添加健康服务"""
        self.healthy_services.add(service_name)
        logger.info(f"添加健康服务: {service_name}")
    
    def remove_service(self, service_name: str) -> None:
        """移除健康服务"""
        self.healthy_services.discard(service_name)
        logger.info(f"移除健康服务: {service_name}")


class DatabaseHealthChecker(HealthChecker):
    """
    数据库健康检查器
    
    检查数据库连接是否正常。
    """
    
    def __init__(self, connection_factory: Callable[[], Any], timeout: float = 5.0):
        """
        初始化数据库健康检查器
        
        Args:
            connection_factory: 数据库连接工厂
            timeout: 检查超时时间
        """
        self.connection_factory = connection_factory
        self.timeout = timeout
    
    async def check_health(self, service_name: str) -> HealthCheckResult:
        """执行数据库健康检查"""
        start_time = time.time()
        
        try:
            # 创建连接并执行简单查询
            async with asyncio.timeout(self.timeout):
                connection = await self.connection_factory()
                # 这里应该执行实际的数据库查询
                # 例如: await connection.execute("SELECT 1")
                await connection.close()
            
            check_duration = time.time() - start_time
            
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.SERVING,
                message="数据库连接正常",
                check_duration=check_duration,
                details={"connection_time": check_duration}
            )
            
        except asyncio.TimeoutError:
            check_duration = time.time() - start_time
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.NOT_SERVING,
                message=f"数据库连接超时: {self.timeout}秒",
                check_duration=check_duration
            )
        except Exception as e:
            check_duration = time.time() - start_time
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.NOT_SERVING,
                message=f"数据库连接失败: {e}",
                check_duration=check_duration
            )


class RedisHealthChecker(HealthChecker):
    """
    Redis健康检查器
    
    检查Redis连接是否正常。
    """
    
    def __init__(self, redis_client: Any, timeout: float = 3.0):
        """
        初始化Redis健康检查器
        
        Args:
            redis_client: Redis客户端
            timeout: 检查超时时间
        """
        self.redis_client = redis_client
        self.timeout = timeout
    
    async def check_health(self, service_name: str) -> HealthCheckResult:
        """执行Redis健康检查"""
        start_time = time.time()
        
        try:
            # 执行PING命令
            async with asyncio.timeout(self.timeout):
                result = await self.redis_client.ping()
                
            check_duration = time.time() - start_time
            
            if result:
                return HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.SERVING,
                    message="Redis连接正常",
                    check_duration=check_duration,
                    details={"ping_result": str(result)}
                )
            else:
                return HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.NOT_SERVING,
                    message="Redis PING失败",
                    check_duration=check_duration
                )
                
        except asyncio.TimeoutError:
            check_duration = time.time() - start_time
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.NOT_SERVING,
                message=f"Redis连接超时: {self.timeout}秒",
                check_duration=check_duration
            )
        except Exception as e:
            check_duration = time.time() - start_time
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.NOT_SERVING,
                message=f"Redis连接失败: {e}",
                check_duration=check_duration
            )


class CompositeHealthChecker(HealthChecker):
    """
    组合健康检查器
    
    组合多个健康检查器，支持复杂的健康检查逻辑。
    """
    
    def __init__(self, checkers: Dict[str, HealthChecker]):
        """
        初始化组合健康检查器
        
        Args:
            checkers: 服务名称到检查器的映射
        """
        self.checkers = checkers
    
    async def check_health(self, service_name: str) -> HealthCheckResult:
        """执行组合健康检查"""
        if service_name not in self.checkers:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.SERVICE_UNKNOWN,
                message=f"未知服务: {service_name}"
            )
        
        checker = self.checkers[service_name]
        return await checker.check_health(service_name)
    
    def add_checker(self, service_name: str, checker: HealthChecker) -> None:
        """添加健康检查器"""
        self.checkers[service_name] = checker
        logger.info(f"添加健康检查器: {service_name}")
    
    def remove_checker(self, service_name: str) -> None:
        """移除健康检查器"""
        if service_name in self.checkers:
            del self.checkers[service_name]
            logger.info(f"移除健康检查器: {service_name}")


class HealthCheckService:
    """
    gRPC健康检查服务
    
    实现gRPC标准健康检查协议，支持服务状态管理和健康检查缓存。
    """
    
    def __init__(
        self,
        health_checker: Optional[HealthChecker] = None,
        cache_ttl: float = 30.0,
        check_interval: float = 60.0,
        enable_auto_check: bool = True
    ):
        """
        初始化健康检查服务
        
        Args:
            health_checker: 健康检查器
            cache_ttl: 缓存生存时间（秒）
            check_interval: 自动检查间隔（秒）
            enable_auto_check: 是否启用自动检查
        """
        self.health_checker = health_checker or DefaultHealthChecker()
        self.cache_ttl = cache_ttl
        self.check_interval = check_interval
        self.enable_auto_check = enable_auto_check
        
        # 状态管理
        self._service_status: Dict[str, HealthCheckResult] = {}
        self._lock = asyncio.Lock()
        
        # 后台任务
        self._check_task: Optional[asyncio.Task] = None
        self._running = False
        
        # 统计信息
        self.stats = {
            "total_checks": 0,
            "successful_checks": 0,
            "failed_checks": 0,
            "cache_hits": 0,
            "cache_misses": 0
        }
        
        logger.info("初始化gRPC健康检查服务")
    
    async def start(self) -> None:
        """启动健康检查服务"""
        if self._running:
            return
        
        self._running = True
        
        if self.enable_auto_check:
            self._check_task = asyncio.create_task(self._auto_check_loop())
        
        logger.info("gRPC健康检查服务已启动")
    
    async def stop(self) -> None:
        """停止健康检查服务"""
        self._running = False
        
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("gRPC健康检查服务已停止")
    
    async def check_health(self, service_name: str, use_cache: bool = True) -> HealthCheckResult:
        """
        执行健康检查
        
        Args:
            service_name: 服务名称
            use_cache: 是否使用缓存
            
        Returns:
            HealthCheckResult: 健康检查结果
        """
        # 检查缓存
        if use_cache:
            cached_result = await self._get_cached_result(service_name)
            if cached_result:
                self.stats["cache_hits"] += 1
                return cached_result
        
        self.stats["cache_misses"] += 1
        
        # 执行健康检查
        try:
            result = await self.health_checker.check_health(service_name)
            self.stats["total_checks"] += 1
            
            if result.is_healthy:
                self.stats["successful_checks"] += 1
            else:
                self.stats["failed_checks"] += 1
            
            # 更新缓存
            await self._update_cache(service_name, result)
            
            return result
            
        except Exception as e:
            self.stats["total_checks"] += 1
            self.stats["failed_checks"] += 1
            
            error_result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNKNOWN,
                message=f"健康检查异常: {e}"
            )
            
            await self._update_cache(service_name, error_result)
            return error_result
    
    async def _get_cached_result(self, service_name: str) -> Optional[HealthCheckResult]:
        """
        获取缓存的健康检查结果
        
        Args:
            service_name: 服务名称
            
        Returns:
            Optional[HealthCheckResult]: 缓存的结果
        """
        async with self._lock:
            if service_name in self._service_status:
                result = self._service_status[service_name]
                if result.age <= self.cache_ttl:
                    return result
                else:
                    # 缓存过期，删除
                    del self._service_status[service_name]
        
        return None
    
    async def _update_cache(self, service_name: str, result: HealthCheckResult) -> None:
        """
        更新缓存
        
        Args:
            service_name: 服务名称
            result: 健康检查结果
        """
        async with self._lock:
            self._service_status[service_name] = result
    
    async def _auto_check_loop(self) -> None:
        """自动健康检查循环"""
        while self._running:
            try:
                await self._perform_auto_checks()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自动健康检查异常: {e}")
                await asyncio.sleep(self.check_interval)
    
    async def _perform_auto_checks(self) -> None:
        """执行自动健康检查"""
        # 获取需要检查的服务列表
        services_to_check = set()
        
        async with self._lock:
            # 检查缓存过期的服务
            for service_name, result in list(self._service_status.items()):
                if result.age > self.cache_ttl:
                    services_to_check.add(service_name)
        
        # 添加默认服务
        services_to_check.add("")  # 空字符串表示整体服务健康
        
        # 并发执行健康检查
        if services_to_check:
            tasks = [
                self.check_health(service, use_cache=False)
                for service in services_to_check
            ]
            
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def set_service_status(self, service_name: str, status: HealthStatus, message: Optional[str] = None) -> None:
        """
        手动设置服务状态
        
        Args:
            service_name: 服务名称
            status: 健康状态
            message: 状态消息
        """
        result = HealthCheckResult(
            service_name=service_name,
            status=status,
            message=message or f"手动设置状态: {status.value}"
        )
        
        await self._update_cache(service_name, result)
        logger.info(f"手动设置服务状态: {service_name} -> {status.value}")
    
    async def get_all_service_status(self) -> Dict[str, HealthCheckResult]:
        """
        获取所有服务的健康状态
        
        Returns:
            Dict[str, HealthCheckResult]: 服务状态映射
        """
        async with self._lock:
            return self._service_status.copy()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取健康检查统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        cache_hit_rate = 0.0
        total_cache_requests = self.stats["cache_hits"] + self.stats["cache_misses"]
        if total_cache_requests > 0:
            cache_hit_rate = self.stats["cache_hits"] / total_cache_requests
        
        success_rate = 0.0
        if self.stats["total_checks"] > 0:
            success_rate = self.stats["successful_checks"] / self.stats["total_checks"]
        
        return {
            "running": self._running,
            "cache_ttl": self.cache_ttl,
            "check_interval": self.check_interval,
            "total_checks": self.stats["total_checks"],
            "successful_checks": self.stats["successful_checks"],
            "failed_checks": self.stats["failed_checks"],
            "success_rate": success_rate,
            "cache_hits": self.stats["cache_hits"],
            "cache_misses": self.stats["cache_misses"],
            "cache_hit_rate": cache_hit_rate,
            "cached_services": len(self._service_status)
        }


class GrpcHealthServicer(health_pb2_grpc.HealthServicer):
    """
    gRPC健康检查服务器
    
    实现标准的gRPC健康检查协议。
    """
    
    def __init__(self, health_service: HealthCheckService):
        """
        初始化gRPC健康检查服务器
        
        Args:
            health_service: 健康检查服务
        """
        self.health_service = health_service
        logger.info("初始化gRPC健康检查服务器")
    
    async def Check(
        self, 
        request: health_pb2.HealthCheckRequest, 
        context: grpc_aio.ServicerContext
    ) -> health_pb2.HealthCheckResponse:
        """
        执行健康检查
        
        Args:
            request: 健康检查请求
            context: gRPC上下文
            
        Returns:
            health_pb2.HealthCheckResponse: 健康检查响应
        """
        service_name = request.service
        
        try:
            result = await self.health_service.check_health(service_name)
            
            # 转换状态
            if result.status == HealthStatus.SERVING:
                grpc_status = health_pb2.HealthCheckResponse.SERVING
            elif result.status == HealthStatus.NOT_SERVING:
                grpc_status = health_pb2.HealthCheckResponse.NOT_SERVING
            else:
                grpc_status = health_pb2.HealthCheckResponse.UNKNOWN
            
            logger.debug(f"健康检查: {service_name} -> {result.status.value}")
            
            return health_pb2.HealthCheckResponse(status=grpc_status)
            
        except Exception as e:
            logger.error(f"健康检查失败: {service_name}, 错误: {e}")
            return health_pb2.HealthCheckResponse(status=health_pb2.HealthCheckResponse.UNKNOWN)
    
    async def Watch(
        self, 
        request: health_pb2.HealthCheckRequest, 
        context: grpc_aio.ServicerContext
    ):
        """
        监控服务健康状态变化
        
        Args:
            request: 健康检查请求
            context: gRPC上下文
            
        Yields:
            health_pb2.HealthCheckResponse: 健康状态变化响应
        """
        service_name = request.service
        last_status = None
        
        logger.info(f"开始监控服务健康状态: {service_name}")
        
        try:
            while not context.cancelled():
                # 获取当前状态
                result = await self.health_service.check_health(service_name)
                
                # 如果状态发生变化，发送响应
                if result.status != last_status:
                    if result.status == HealthStatus.SERVING:
                        grpc_status = health_pb2.HealthCheckResponse.SERVING
                    elif result.status == HealthStatus.NOT_SERVING:
                        grpc_status = health_pb2.HealthCheckResponse.NOT_SERVING
                    else:
                        grpc_status = health_pb2.HealthCheckResponse.UNKNOWN
                    
                    yield health_pb2.HealthCheckResponse(status=grpc_status)
                    last_status = result.status
                    
                    logger.debug(f"健康状态变化: {service_name} -> {result.status.value}")
                
                # 等待一段时间再检查
                await asyncio.sleep(5.0)
                
        except asyncio.CancelledError:
            logger.info(f"停止监控服务健康状态: {service_name}")
        except Exception as e:
            logger.error(f"监控服务健康状态异常: {service_name}, 错误: {e}")


def add_health_service_to_server(server, health_service: HealthCheckService) -> None:
    """
    将健康检查服务添加到gRPC服务器
    
    Args:
        server: gRPC服务器
        health_service: 健康检查服务
    """
    if health_pb2_grpc:
        servicer = GrpcHealthServicer(health_service)
        health_pb2_grpc.add_HealthServicer_to_server(servicer, server)
        logger.info("健康检查服务已添加到gRPC服务器")
    else:
        logger.warning("grpcio-health未安装，无法添加健康检查服务")


# 便捷函数
def create_default_health_service() -> HealthCheckService:
    """
    创建默认的健康检查服务
    
    Returns:
        HealthCheckService: 健康检查服务实例
    """
    return HealthCheckService(
        health_checker=DefaultHealthChecker(),
        cache_ttl=30.0,
        check_interval=60.0,
        enable_auto_check=True
    )


def create_database_health_service(connection_factory: Callable[[], Any]) -> HealthCheckService:
    """
    创建数据库健康检查服务
    
    Args:
        connection_factory: 数据库连接工厂
        
    Returns:
        HealthCheckService: 健康检查服务实例
    """
    return HealthCheckService(
        health_checker=DatabaseHealthChecker(connection_factory),
        cache_ttl=30.0,
        check_interval=60.0,
        enable_auto_check=True
    )


def create_redis_health_service(redis_client: Any) -> HealthCheckService:
    """
    创建Redis健康检查服务
    
    Args:
        redis_client: Redis客户端
        
    Returns:
        HealthCheckService: 健康检查服务实例
    """
    return HealthCheckService(
        health_checker=RedisHealthChecker(redis_client),
        cache_ttl=30.0,
        check_interval=60.0,
        enable_auto_check=True
    )