"""
gRPC服务端封装模块

提供高级的gRPC服务端封装，支持优雅启动和关闭、多线程处理、服务注册、
请求限流、日志记录、异常处理等功能。
"""

import asyncio
import threading
import time
import signal
from typing import Any, Dict, List, Optional, Callable, Set, Type
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from collections import defaultdict, deque

try:
    import grpc
    from grpc import aio as grpc_aio
except ImportError:
    grpc = None
    
    class MockServer:
        def add_insecure_port(self, address):
            pass
        
        def add_secure_port(self, address, credentials):
            pass
        
        async def start(self):
            pass
        
        async def stop(self, grace_period=None):
            pass
        
        async def wait_for_termination(self):
            pass
    
    class MockGrpcAio:
        Server = MockServer
        
        @staticmethod
        def server(options=None):
            return MockServer()
    
    grpc_aio = MockGrpcAio()

from ..logger import logger
from .interceptor import InterceptorChain, RequestContext, create_default_server_interceptors
from .health_check import HealthCheckService, add_health_service_to_server, create_default_health_service
from .exceptions import (
    GrpcException,
    GrpcConfigurationError,
    handle_grpc_exception_async
)


@dataclass
class RateLimitConfig:
    """限流配置"""
    
    enable: bool = False
    max_requests_per_second: float = 1000.0
    max_concurrent_requests: int = 100
    burst_capacity: int = 200
    
    # 按用户限流
    per_user_limit: bool = False
    max_requests_per_user: float = 100.0
    
    # 按方法限流
    per_method_limits: Dict[str, float] = field(default_factory=dict)


@dataclass
class ServerConfig:
    """服务器配置"""
    
    # 基本配置
    host: str = "0.0.0.0"
    port: int = 50051
    max_workers: int = 10
    
    # gRPC选项
    max_send_message_length: int = 4 * 1024 * 1024  # 4MB
    max_receive_message_length: int = 4 * 1024 * 1024  # 4MB
    max_concurrent_rpcs: Optional[int] = None
    
    # 超时配置
    request_timeout: float = 300.0  # 5分钟
    shutdown_timeout: float = 30.0
    
    # SSL/TLS配置
    enable_ssl: bool = False
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    ssl_ca_path: Optional[str] = None
    require_client_cert: bool = False
    
    # 限流配置
    rate_limit_config: RateLimitConfig = field(default_factory=RateLimitConfig)
    
    # 服务注册配置
    enable_service_registration: bool = False
    service_name: str = ""
    service_version: str = "1.0.0"
    service_metadata: Dict[str, str] = field(default_factory=dict)
    
    # 健康检查配置
    enable_health_check: bool = True
    health_check_services: List[str] = field(default_factory=list)
    
    # 拦截器配置
    enable_default_interceptors: bool = True
    custom_interceptors: List[Any] = field(default_factory=list)
    
    # 监控配置
    enable_metrics: bool = True
    metrics_port: Optional[int] = None
    
    # 日志配置
    log_requests: bool = True
    log_responses: bool = False
    
    def validate(self) -> None:
        """验证配置"""
        if self.port <= 0 or self.port > 65535:
            raise GrpcConfigurationError(f"无效的端口号: {self.port}")
        
        if self.max_workers <= 0:
            raise GrpcConfigurationError(f"max_workers必须大于0: {self.max_workers}")
        
        if self.enable_ssl:
            if not self.ssl_cert_path or not self.ssl_key_path:
                raise GrpcConfigurationError("启用SSL时必须提供证书和密钥文件路径")


@dataclass
class ServiceStats:
    """服务统计信息"""
    
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limited_requests: int = 0
    
    total_response_time: float = 0.0
    min_response_time: float = float('inf')
    max_response_time: float = 0.0
    
    concurrent_requests: int = 0
    peak_concurrent_requests: int = 0
    
    # 方法级统计
    method_stats: Dict[str, Dict[str, Any]] = field(default_factory=lambda: defaultdict(dict))
    
    # 最近的请求记录
    recent_requests: deque = field(default_factory=lambda: deque(maxlen=1000))
    
    start_time: float = field(default_factory=time.time)
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    @property
    def avg_response_time(self) -> float:
        """平均响应时间"""
        if self.successful_requests == 0:
            return 0.0
        return self.total_response_time / self.successful_requests
    
    @property
    def requests_per_second(self) -> float:
        """每秒请求数"""
        uptime = time.time() - self.start_time
        if uptime == 0:
            return 0.0
        return self.total_requests / uptime
    
    def record_request(
        self, 
        method: str, 
        success: bool, 
        response_time: float,
        user_id: Optional[str] = None
    ) -> None:
        """记录请求统计"""
        self.total_requests += 1
        
        if success:
            self.successful_requests += 1
            self.total_response_time += response_time
            self.min_response_time = min(self.min_response_time, response_time)
            self.max_response_time = max(self.max_response_time, response_time)
        else:
            self.failed_requests += 1
        
        # 方法级统计
        if method not in self.method_stats:
            self.method_stats[method] = {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "total_time": 0.0,
                "min_time": float('inf'),
                "max_time": 0.0
            }
        
        method_stat = self.method_stats[method]
        method_stat["total"] += 1
        
        if success:
            method_stat["successful"] += 1
            method_stat["total_time"] += response_time
            method_stat["min_time"] = min(method_stat["min_time"], response_time)
            method_stat["max_time"] = max(method_stat["max_time"], response_time)
        else:
            method_stat["failed"] += 1
        
        # 记录最近请求
        request_record = {
            "timestamp": time.time(),
            "method": method,
            "success": success,
            "response_time": response_time,
            "user_id": user_id
        }
        self.recent_requests.append(request_record)
    
    def increment_concurrent(self) -> None:
        """增加并发计数"""
        self.concurrent_requests += 1
        self.peak_concurrent_requests = max(self.peak_concurrent_requests, self.concurrent_requests)
    
    def decrement_concurrent(self) -> None:
        """减少并发计数"""
        self.concurrent_requests = max(0, self.concurrent_requests - 1)
    
    def record_rate_limit(self) -> None:
        """记录限流事件"""
        self.rate_limited_requests += 1
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        # 计算方法级平均响应时间
        processed_method_stats = {}
        for method, stats in self.method_stats.items():
            processed_stats = stats.copy()
            if stats["successful"] > 0:
                processed_stats["avg_time"] = stats["total_time"] / stats["successful"]
                processed_stats["success_rate"] = stats["successful"] / stats["total"]
            else:
                processed_stats["avg_time"] = 0.0
                processed_stats["success_rate"] = 0.0
            
            if processed_stats["min_time"] == float('inf'):
                processed_stats["min_time"] = 0.0
            
            processed_method_stats[method] = processed_stats
        
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "rate_limited_requests": self.rate_limited_requests,
            "success_rate": self.success_rate,
            "avg_response_time": self.avg_response_time,
            "min_response_time": self.min_response_time if self.min_response_time != float('inf') else 0.0,
            "max_response_time": self.max_response_time,
            "requests_per_second": self.requests_per_second,
            "concurrent_requests": self.concurrent_requests,
            "peak_concurrent_requests": self.peak_concurrent_requests,
            "uptime": time.time() - self.start_time,
            "method_stats": processed_method_stats
        }


class RateLimiter:
    """简单的令牌桶限流器"""
    
    def __init__(self, config: RateLimitConfig):
        """
        初始化限流器
        
        Args:
            config: 限流配置
        """
        self.config = config
        self.tokens = config.burst_capacity
        self.last_refill = time.time()
        self.lock = threading.Lock()
        
        # 用户限流
        self.user_buckets: Dict[str, Dict[str, Any]] = {}
        
        # 方法限流
        self.method_buckets: Dict[str, Dict[str, Any]] = {}
    
    def is_allowed(self, user_id: Optional[str] = None, method: Optional[str] = None) -> bool:
        """
        检查请求是否被允许
        
        Args:
            user_id: 用户ID
            method: 方法名
            
        Returns:
            bool: 是否允许请求
        """
        if not self.config.enable:
            return True
        
        with self.lock:
            current_time = time.time()
            
            # 全局限流检查
            if not self._check_global_limit(current_time):
                return False
            
            # 用户限流检查
            if self.config.per_user_limit and user_id:
                if not self._check_user_limit(user_id, current_time):
                    return False
            
            # 方法限流检查
            if method and method in self.config.per_method_limits:
                if not self._check_method_limit(method, current_time):
                    return False
            
            return True
    
    def _check_global_limit(self, current_time: float) -> bool:
        """检查全局限流"""
        self._refill_tokens(current_time)
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        
        return False
    
    def _check_user_limit(self, user_id: str, current_time: float) -> bool:
        """检查用户限流"""
        if user_id not in self.user_buckets:
            self.user_buckets[user_id] = {
                "tokens": self.config.max_requests_per_user,
                "last_refill": current_time
            }
        
        bucket = self.user_buckets[user_id]
        self._refill_user_tokens(bucket, current_time)
        
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        
        return False
    
    def _check_method_limit(self, method: str, current_time: float) -> bool:
        """检查方法限流"""
        limit = self.config.per_method_limits[method]
        
        if method not in self.method_buckets:
            self.method_buckets[method] = {
                "tokens": limit,
                "last_refill": current_time,
                "limit": limit
            }
        
        bucket = self.method_buckets[method]
        self._refill_method_tokens(bucket, current_time)
        
        if bucket["tokens"] >= 1:
            bucket["tokens"] -= 1
            return True
        
        return False
    
    def _refill_tokens(self, current_time: float) -> None:
        """补充全局令牌"""
        time_passed = current_time - self.last_refill
        tokens_to_add = time_passed * self.config.max_requests_per_second
        
        self.tokens = min(self.config.burst_capacity, self.tokens + tokens_to_add)
        self.last_refill = current_time
    
    def _refill_user_tokens(self, bucket: Dict[str, Any], current_time: float) -> None:
        """补充用户令牌"""
        time_passed = current_time - bucket["last_refill"]
        tokens_to_add = time_passed * self.config.max_requests_per_user
        
        bucket["tokens"] = min(self.config.max_requests_per_user, bucket["tokens"] + tokens_to_add)
        bucket["last_refill"] = current_time
    
    def _refill_method_tokens(self, bucket: Dict[str, Any], current_time: float) -> None:
        """补充方法令牌"""
        time_passed = current_time - bucket["last_refill"]
        tokens_to_add = time_passed * bucket["limit"]
        
        bucket["tokens"] = min(bucket["limit"], bucket["tokens"] + tokens_to_add)
        bucket["last_refill"] = current_time


class GrpcServer:
    """
    高级gRPC服务器
    
    提供服务注册、健康检查、限流、监控等高级功能。
    """
    
    def __init__(self, config: ServerConfig):
        """
        初始化gRPC服务器
        
        Args:
            config: 服务器配置
        """
        config.validate()
        self.config = config
        
        # gRPC服务器实例
        self.server: Optional[grpc_aio.Server] = None
        
        # 服务管理
        self.registered_services: Dict[str, Any] = {}
        self.service_handlers: Dict[str, Callable] = {}
        
        # 拦截器链
        self.interceptor_chain: Optional[InterceptorChain] = None
        
        # 限流器
        self.rate_limiter: Optional[RateLimiter] = None
        
        # 健康检查服务
        self.health_service: Optional[HealthCheckService] = None
        
        # 统计信息
        self.stats = ServiceStats()
        
        # 状态管理
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._startup_complete = asyncio.Event()
        
        # 后台任务
        self._monitor_task: Optional[asyncio.Task] = None
        self._registry_task: Optional[asyncio.Task] = None
        
        logger.info(f"创建gRPC服务器: {config.host}:{config.port}")
    
    async def initialize(self) -> None:
        """初始化服务器"""
        try:
            # 初始化拦截器链
            await self._initialize_interceptors()
            
            # 初始化限流器
            self._initialize_rate_limiter()
            
            # 初始化健康检查服务
            await self._initialize_health_service()
            
            # 创建gRPC服务器
            await self._create_server()
            
            logger.info("gRPC服务器初始化完成")
            
        except Exception as e:
            logger.error(f"gRPC服务器初始化失败: {e}")
            raise GrpcException(f"服务器初始化失败: {e}", cause=e)
    
    async def _initialize_interceptors(self) -> None:
        """初始化拦截器链"""
        interceptors = []
        
        if self.config.enable_default_interceptors:
            interceptors.extend(create_default_server_interceptors())
        
        interceptors.extend(self.config.custom_interceptors)
        
        self.interceptor_chain = InterceptorChain(interceptors)
        logger.debug("服务器拦截器链初始化完成")
    
    def _initialize_rate_limiter(self) -> None:
        """初始化限流器"""
        if self.config.rate_limit_config.enable:
            self.rate_limiter = RateLimiter(self.config.rate_limit_config)
            logger.debug("限流器初始化完成")
    
    async def _initialize_health_service(self) -> None:
        """初始化健康检查服务"""
        if self.config.enable_health_check:
            self.health_service = create_default_health_service()
            
            # 添加配置的健康检查服务
            for service_name in self.config.health_check_services:
                await self.health_service.set_service_status(
                    service_name, 
                    "SERVING"  # 假设服务健康
                )
            
            await self.health_service.start()
            logger.debug("健康检查服务初始化完成")
    
    async def _create_server(self) -> None:
        """创建gRPC服务器"""
        if not grpc_aio:
            raise GrpcConfigurationError("grpcio未安装，无法创建服务器")
        
        # 创建gRPC选项
        options = [
            ('grpc.max_send_message_length', self.config.max_send_message_length),
            ('grpc.max_receive_message_length', self.config.max_receive_message_length),
        ]
        
        if self.config.max_concurrent_rpcs:
            options.append(('grpc.max_concurrent_streams', self.config.max_concurrent_rpcs))
        
        # 创建服务器
        self.server = grpc_aio.server(
            options=options
        )
        
        # 添加健康检查服务
        if self.health_service:
            add_health_service_to_server(self.server, self.health_service)
        
        # 配置SSL
        if self.config.enable_ssl:
            await self._configure_ssl()
        else:
            listen_addr = f"{self.config.host}:{self.config.port}"
            self.server.add_insecure_port(listen_addr)
        
        logger.debug("gRPC服务器创建完成")
    
    async def _configure_ssl(self) -> None:
        """配置SSL"""
        try:
            # 读取证书文件
            with open(self.config.ssl_cert_path, 'rb') as cert_file:
                cert_data = cert_file.read()
            
            with open(self.config.ssl_key_path, 'rb') as key_file:
                key_data = key_file.read()
            
            # 读取CA证书（如果有）
            ca_data = None
            if self.config.ssl_ca_path:
                with open(self.config.ssl_ca_path, 'rb') as ca_file:
                    ca_data = ca_file.read()
            
            # 创建SSL凭据
            credentials = grpc.ssl_server_credentials(
                [(key_data, cert_data)],
                root_certificates=ca_data,
                require_client_auth=self.config.require_client_cert
            )
            
            # 添加安全端口
            listen_addr = f"{self.config.host}:{self.config.port}"
            self.server.add_secure_port(listen_addr, credentials)
            
            logger.info(f"SSL配置完成: {listen_addr}")
            
        except Exception as e:
            raise GrpcConfigurationError(f"SSL配置失败: {e}", cause=e)
    
    def add_service(self, servicer: Any, add_servicer_func: Callable) -> None:
        """
        添加服务
        
        Args:
            servicer: 服务实现
            add_servicer_func: 添加服务的函数
        """
        if self.server is None:
            raise GrpcException("服务器未初始化")
        
        service_name = servicer.__class__.__name__
        
        # 包装服务方法以添加拦截器和统计
        wrapped_servicer = self._wrap_servicer(servicer)
        
        # 添加服务到服务器
        add_servicer_func(wrapped_servicer, self.server)
        
        self.registered_services[service_name] = servicer
        
        logger.info(f"添加服务: {service_name}")
    
    def _wrap_servicer(self, servicer: Any) -> Any:
        """
        包装服务实现以添加拦截器和统计
        
        Args:
            servicer: 原始服务实现
            
        Returns:
            Any: 包装后的服务实现
        """
        class WrappedServicer:
            def __init__(self, original_servicer, server_instance):
                self._original = original_servicer
                self._server = server_instance
                
                # 动态添加所有原始方法
                for attr_name in dir(original_servicer):
                    if not attr_name.startswith('_'):
                        attr = getattr(original_servicer, attr_name)
                        if callable(attr):
                            wrapped_method = self._wrap_method(attr, attr_name)
                            setattr(self, attr_name, wrapped_method)
            
            def _wrap_method(self, original_method, method_name):
                """包装单个方法"""
                async def wrapped(*args, **kwargs):
                    return await self._server._handle_request(
                        original_method, method_name, *args, **kwargs
                    )
                return wrapped
        
        return WrappedServicer(servicer, self)
    
    async def _handle_request(self, original_method: Callable, method_name: str, *args, **kwargs) -> Any:
        """
        处理请求（添加拦截器和统计）
        
        Args:
            original_method: 原始方法
            method_name: 方法名
            *args: 位置参数
            **kwargs: 关键字参数
            
        Returns:
            Any: 响应结果
        """
        start_time = time.time()
        
        # 创建请求上下文
        context = RequestContext(
            method_name=method_name,
            service_name=self.config.service_name,
            start_time=start_time
        )
        
        # 增加并发计数
        self.stats.increment_concurrent()
        
        try:
            # 检查限流
            if self.rate_limiter and not self.rate_limiter.is_allowed(
                user_id=context.user_id,
                method=method_name
            ):
                self.stats.record_rate_limit()
                raise GrpcException("请求频率超限", error_code=429)
            
            # 检查并发限制
            if (self.config.rate_limit_config.max_concurrent_requests > 0 and
                self.stats.concurrent_requests > self.config.rate_limit_config.max_concurrent_requests):
                raise GrpcException("并发请求数超限", error_code=429)
            
            # 处理请求拦截器
            request = args[0] if args else None
            if self.interceptor_chain and request:
                request = await self.interceptor_chain.process_request(context, request)
                args = (request,) + args[1:]
            
            # 执行原始方法
            response = await original_method(*args, **kwargs)
            
            # 处理响应拦截器
            if self.interceptor_chain:
                response = await self.interceptor_chain.process_response(context, response)
            
            # 记录成功统计
            duration = time.time() - start_time
            self.stats.record_request(method_name, True, duration, context.user_id)
            
            return response
            
        except Exception as e:
            # 记录失败统计
            duration = time.time() - start_time
            self.stats.record_request(method_name, False, duration, context.user_id)
            
            # 处理异常拦截器
            if self.interceptor_chain and self.interceptor_chain.exception_interceptor:
                handled_exception = self.interceptor_chain.exception_interceptor.handle_exception(context, e)
                raise handled_exception
            
            raise
            
        finally:
            # 减少并发计数
            self.stats.decrement_concurrent()
    
    async def start(self) -> None:
        """启动服务器"""
        if self._running:
            logger.warning("服务器已在运行中")
            return
        
        try:
            if not self.server:
                await self.initialize()
            
            # 启动服务器
            await self.server.start()
            self._running = True
            
            # 启动后台任务
            await self._start_background_tasks()
            
            # 服务注册
            if self.config.enable_service_registration:
                await self._register_service()
            
            # 标记启动完成
            self._startup_complete.set()
            
            logger.info(f"gRPC服务器启动成功: {self.config.host}:{self.config.port}")
            
        except Exception as e:
            logger.error(f"gRPC服务器启动失败: {e}")
            await self.stop()
            raise
    
    async def _start_background_tasks(self) -> None:
        """启动后台任务"""
        # 启动监控任务
        if self.config.enable_metrics:
            self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        # 启动服务注册维护任务
        if self.config.enable_service_registration:
            self._registry_task = asyncio.create_task(self._registry_loop())
    
    async def _monitor_loop(self) -> None:
        """监控循环"""
        while self._running:
            try:
                # 输出统计信息
                stats = self.get_stats()
                logger.info(f"服务器统计: {stats}")
                
                await asyncio.sleep(60)  # 每分钟输出一次统计
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环异常: {e}")
                await asyncio.sleep(60)
    
    async def _registry_loop(self) -> None:
        """服务注册维护循环"""
        while self._running:
            try:
                # 维护服务注册
                await self._maintain_service_registration()
                
                await asyncio.sleep(30)  # 每30秒维护一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"服务注册维护异常: {e}")
                await asyncio.sleep(30)
    
    async def _register_service(self) -> None:
        """注册服务到服务发现中心"""
        try:
            # 这里应该集成实际的服务注册逻辑
            # 例如注册到Consul、Etcd等
            service_info = {
                "name": self.config.service_name,
                "version": self.config.service_version,
                "address": self.config.host,
                "port": self.config.port,
                "metadata": self.config.service_metadata,
                "health_check": f"http://{self.config.host}:{self.config.port}/health"
            }
            
            logger.info(f"注册服务: {service_info}")
            
            # 实际的注册逻辑
            # await registry_client.register_service(service_info)
            
        except Exception as e:
            logger.error(f"服务注册失败: {e}")
    
    async def _maintain_service_registration(self) -> None:
        """维护服务注册"""
        try:
            # 发送心跳或更新服务信息
            # await registry_client.heartbeat(self.config.service_name)
            pass
        except Exception as e:
            logger.warning(f"服务注册维护失败: {e}")
    
    async def stop(self, grace_period: Optional[float] = None) -> None:
        """
        停止服务器
        
        Args:
            grace_period: 优雅关闭时间（秒）
        """
        if not self._running:
            return
        
        grace_period = grace_period or self.config.shutdown_timeout
        
        logger.info(f"开始停止gRPC服务器，优雅关闭时间: {grace_period}秒")
        
        self._running = False
        
        # 取消后台任务
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        if self._registry_task and not self._registry_task.done():
            self._registry_task.cancel()
            try:
                await self._registry_task
            except asyncio.CancelledError:
                pass
        
        # 注销服务
        if self.config.enable_service_registration:
            await self._unregister_service()
        
        # 停止健康检查服务
        if self.health_service:
            await self.health_service.stop()
        
        # 停止gRPC服务器
        if self.server:
            await self.server.stop(grace_period)
        
        # 设置关闭事件
        self._shutdown_event.set()
        
        logger.info("gRPC服务器已停止")
    
    async def _unregister_service(self) -> None:
        """注销服务"""
        try:
            # 从服务发现中心注销服务
            # await registry_client.unregister_service(self.config.service_name)
            logger.info(f"注销服务: {self.config.service_name}")
        except Exception as e:
            logger.error(f"服务注销失败: {e}")
    
    async def wait_for_termination(self) -> None:
        """等待服务器终止"""
        if self.server:
            await self.server.wait_for_termination()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取服务器统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        server_stats = {
            "server": {
                "running": self._running,
                "host": self.config.host,
                "port": self.config.port,
                "ssl_enabled": self.config.enable_ssl,
                "registered_services": list(self.registered_services.keys()),
            },
            "stats": self.stats.to_dict(),
            "interceptors": self.interceptor_chain.get_stats() if self.interceptor_chain else {},
            "health_service": self.health_service.get_stats() if self.health_service else {}
        }
        
        return server_stats
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.stop()


def setup_signal_handlers(server: GrpcServer) -> None:
    """
    设置信号处理器以实现优雅关闭
    
    Args:
        server: gRPC服务器实例
    """
    def signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，开始优雅关闭")
        asyncio.create_task(server.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


# 便捷函数
def create_simple_server(
    host: str = "0.0.0.0",
    port: int = 50051,
    max_workers: int = 10,
    enable_health_check: bool = True,
    enable_metrics: bool = True
) -> GrpcServer:
    """
    创建简单的gRPC服务器
    
    Args:
        host: 主机地址
        port: 端口号
        max_workers: 最大工作线程数
        enable_health_check: 是否启用健康检查
        enable_metrics: 是否启用监控
        
    Returns:
        GrpcServer: gRPC服务器实例
    """
    config = ServerConfig(
        host=host,
        port=port,
        max_workers=max_workers,
        enable_health_check=enable_health_check,
        enable_metrics=enable_metrics
    )
    
    return GrpcServer(config)


def create_secure_server(
    host: str,
    port: int,
    ssl_cert_path: str,
    ssl_key_path: str,
    ssl_ca_path: Optional[str] = None,
    require_client_cert: bool = False,
    **kwargs
) -> GrpcServer:
    """
    创建安全的gRPC服务器
    
    Args:
        host: 主机地址
        port: 端口号
        ssl_cert_path: SSL证书文件路径
        ssl_key_path: SSL密钥文件路径
        ssl_ca_path: CA证书文件路径
        require_client_cert: 是否要求客户端证书
        **kwargs: 其他配置参数
        
    Returns:
        GrpcServer: gRPC服务器实例
    """
    config = ServerConfig(
        host=host,
        port=port,
        enable_ssl=True,
        ssl_cert_path=ssl_cert_path,
        ssl_key_path=ssl_key_path,
        ssl_ca_path=ssl_ca_path,
        require_client_cert=require_client_cert,
        **kwargs
    )
    
    return GrpcServer(config)