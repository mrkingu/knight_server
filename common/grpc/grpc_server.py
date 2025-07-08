"""
gRPC服务端封装模块

该模块实现了高级gRPC服务器，支持优雅启动关闭、多线程处理、服务注册、
请求限流、统一异常处理等功能。
"""

import asyncio
import time
import signal
import threading
from typing import Dict, List, Optional, Any, Callable, Set, Type
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

try:
    import grpc
    import grpc.aio
    from grpc import StatusCode
    from grpc_reflection.v1alpha import reflection
    GRPC_AVAILABLE = True
except ImportError:
    # 模拟grpc模块
    GRPC_AVAILABLE = False
    
    class grpc:
        @staticmethod
        def server(executor):
            return MockServer()
        
        class aio:
            @staticmethod
            def server():
                return MockAsyncServer()
    
    class reflection:
        @staticmethod
        def enable_server_reflection(service_names, server):
            pass
    
    class MockServer:
        def __init__(self):
            self.services = []
            self.port = None
        
        def add_insecure_port(self, address):
            self.port = address
            return address
        
        def add_secure_port(self, address, credentials):
            self.port = address
            return address
        
        def start(self):
            pass
        
        def stop(self, grace_period):
            pass
        
        def wait_for_termination(self, timeout=None):
            pass
    
    class MockAsyncServer:
        def __init__(self):
            self.services = []
            self.port = None
        
        def add_insecure_port(self, address):
            self.port = address
            return address
        
        def add_secure_port(self, address, credentials):
            self.port = address
            return address
        
        async def start(self):
            pass
        
        async def stop(self, grace_period):
            pass
        
        async def wait_for_termination(self):
            pass

from .health_check import HealthCheckService, add_health_servicer_to_server
from .interceptor import InterceptorChain, get_default_chain
from .exceptions import GrpcConfigError, handle_async_grpc_exception


@dataclass
class ServerConfig:
    """服务器配置"""
    # 基本配置
    host: str = "0.0.0.0"               # 监听地址
    port: int = 50051                   # 监听端口
    
    # 线程配置
    max_workers: int = 10               # 最大工作线程数
    
    # 超时配置
    grace_period: float = 30.0          # 优雅关闭超时(秒)
    
    # SSL配置
    use_ssl: bool = False               # 是否使用SSL
    ssl_cert_file: Optional[str] = None  # SSL证书文件
    ssl_key_file: Optional[str] = None   # SSL私钥文件
    ssl_ca_file: Optional[str] = None    # SSL CA文件
    
    # gRPC配置
    max_receive_message_length: int = 1024 * 1024 * 4  # 最大接收消息大小(4MB)
    max_send_message_length: int = 1024 * 1024 * 4     # 最大发送消息大小(4MB)
    keepalive_time_ms: int = 30000       # keepalive时间(毫秒)
    keepalive_timeout_ms: int = 5000     # keepalive超时(毫秒)
    keepalive_permit_without_calls: bool = True  # 允许无调用时keepalive
    max_concurrent_rpcs: Optional[int] = None    # 最大并发RPC数
    
    # 压缩配置
    compression: Optional[str] = None    # 压缩算法
    
    # 服务注册配置
    enable_service_registration: bool = False  # 启用服务注册
    service_name: Optional[str] = None   # 服务名称
    service_tags: Dict[str, str] = field(default_factory=dict)  # 服务标签
    
    # 健康检查配置
    enable_health_check: bool = True     # 启用健康检查
    
    # 反射配置
    enable_reflection: bool = False      # 启用gRPC反射
    
    # 限流配置
    enable_rate_limiting: bool = False   # 启用限流
    max_requests_per_second: float = 1000.0  # 每秒最大请求数
    
    # 日志配置
    enable_request_logging: bool = True  # 启用请求日志
    
    # 拦截器配置
    interceptor_chain: Optional[InterceptorChain] = None
    enable_default_interceptors: bool = True


@dataclass
class ServiceInfo:
    """服务信息"""
    service_name: str                   # 服务名称
    servicer: Any                       # 服务实现
    add_to_server_func: Callable        # 添加到服务器的函数
    description: Optional[str] = None   # 服务描述
    version: Optional[str] = None       # 服务版本
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据


class RateLimiter:
    """简单的令牌桶限流器"""
    
    def __init__(self, max_requests_per_second: float):
        self.max_requests_per_second = max_requests_per_second
        self.tokens = max_requests_per_second
        self.last_update = time.time()
        self.lock = threading.Lock()
    
    def acquire(self) -> bool:
        """获取令牌"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            
            # 添加令牌
            self.tokens = min(
                self.max_requests_per_second,
                self.tokens + elapsed * self.max_requests_per_second
            )
            self.last_update = now
            
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


class GrpcServer:
    """gRPC服务器"""
    
    def __init__(self, config: ServerConfig):
        """
        初始化gRPC服务器
        
        Args:
            config: 服务器配置
        """
        self._config = config
        self._server: Optional[Union['grpc.Server', 'grpc.aio.Server']] = None
        
        # 服务管理
        self._services: Dict[str, ServiceInfo] = {}
        self._service_endpoints: Set[str] = set()
        
        # 健康检查
        self._health_service: Optional[HealthCheckService] = None
        
        # 拦截器
        self._interceptor_chain = config.interceptor_chain or get_default_chain()
        
        # 限流器
        self._rate_limiter: Optional[RateLimiter] = None
        if config.enable_rate_limiting:
            self._rate_limiter = RateLimiter(config.max_requests_per_second)
        
        # 统计信息
        self._stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'active_requests': 0,
            'avg_response_time': 0.0,
            'start_time': None,
            'last_request_time': None
        }
        
        # 状态标志
        self._running = False
        self._stopping = False
        
        # 线程池
        self._executor: Optional[ThreadPoolExecutor] = None
        
        # 信号处理
        self._shutdown_event = asyncio.Event()
        
        # 锁
        self._lock = asyncio.Lock()
    
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._running
    
    @property
    def is_stopping(self) -> bool:
        """是否正在停止"""
        return self._stopping
    
    @property
    def address(self) -> str:
        """获取服务器地址"""
        return f"{self._config.host}:{self._config.port}"
    
    def add_service(
        self,
        service_name: str,
        servicer: Any,
        add_to_server_func: Callable,
        description: Optional[str] = None,
        version: Optional[str] = None,
        **metadata
    ):
        """
        添加服务
        
        Args:
            service_name: 服务名称
            servicer: 服务实现
            add_to_server_func: 添加到服务器的函数
            description: 服务描述
            version: 服务版本
            **metadata: 元数据
        """
        if self._running:
            raise GrpcConfigError(
                message="服务器运行时无法添加服务",
                config_key="add_service"
            )
        
        service_info = ServiceInfo(
            service_name=service_name,
            servicer=servicer,
            add_to_server_func=add_to_server_func,
            description=description,
            version=version,
            metadata=metadata
        )
        
        self._services[service_name] = service_info
        
        # 注册健康检查
        if self._health_service:
            self._health_service.register_service(service_name)
    
    def remove_service(self, service_name: str) -> bool:
        """
        移除服务
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否移除成功
        """
        if self._running:
            raise GrpcConfigError(
                message="服务器运行时无法移除服务",
                config_key="remove_service"
            )
        
        service_info = self._services.pop(service_name, None)
        
        if service_info and self._health_service:
            self._health_service.unregister_service(service_name)
        
        return service_info is not None
    
    def get_service(self, service_name: str) -> Optional[ServiceInfo]:
        """获取服务信息"""
        return self._services.get(service_name)
    
    def list_services(self) -> List[str]:
        """列出所有服务"""
        return list(self._services.keys())
    
    async def start(self):
        """启动服务器"""
        if self._running:
            return
        
        async with self._lock:
            if self._running:
                return
            
            try:
                await self._setup_server()
                await self._start_server()
                self._running = True
                self._stats['start_time'] = time.time()
                
                # 注册到服务发现
                if self._config.enable_service_registration:
                    await self._register_service()
                
            except Exception as e:
                raise GrpcConfigError(
                    message=f"服务器启动失败: {str(e)}",
                    config_key="server_start",
                    cause=e
                )
    
    async def _setup_server(self):
        """设置服务器"""
        # 创建线程池
        self._executor = ThreadPoolExecutor(
            max_workers=self._config.max_workers,
            thread_name_prefix="grpc_worker"
        )
        
        # 创建服务器选项
        options = [
            ('grpc.max_receive_message_length', self._config.max_receive_message_length),
            ('grpc.max_send_message_length', self._config.max_send_message_length),
            ('grpc.keepalive_time_ms', self._config.keepalive_time_ms),
            ('grpc.keepalive_timeout_ms', self._config.keepalive_timeout_ms),
            ('grpc.keepalive_permit_without_calls', self._config.keepalive_permit_without_calls),
        ]
        
        if self._config.max_concurrent_rpcs:
            options.append(('grpc.max_concurrent_rpcs', self._config.max_concurrent_rpcs))
        
        if self._config.compression:
            options.append(('grpc.default_compression', self._config.compression))
        
        # 创建服务器
        if GRPC_AVAILABLE:
            self._server = grpc.aio.server(options=options)
        else:
            self._server = MockAsyncServer()
        
        # 添加服务
        for service_name, service_info in self._services.items():
            try:
                service_info.add_to_server_func(service_info.servicer, self._server)
            except Exception as e:
                raise GrpcConfigError(
                    message=f"添加服务失败: {service_name} - {str(e)}",
                    config_key="add_service",
                    config_value=service_name,
                    cause=e
                )
        
        # 设置健康检查
        if self._config.enable_health_check:
            if not self._health_service:
                self._health_service = HealthCheckService()
                await self._health_service.start()
            
            add_health_servicer_to_server(self._health_service, self._server)
        
        # 启用反射
        if self._config.enable_reflection and GRPC_AVAILABLE:
            service_names = list(self._services.keys())
            if self._config.enable_health_check:
                service_names.append('grpc.health.v1.Health')
            
            reflection.enable_server_reflection(service_names, self._server)
        
        # 添加端口
        listen_addr = f"{self._config.host}:{self._config.port}"
        
        if self._config.use_ssl:
            credentials = self._create_ssl_credentials()
            port = self._server.add_secure_port(listen_addr, credentials)
        else:
            port = self._server.add_insecure_port(listen_addr)
        
        if not port:
            raise GrpcConfigError(
                message=f"无法绑定端口: {listen_addr}",
                config_key="server_port",
                config_value=listen_addr
            )
    
    def _create_ssl_credentials(self):
        """创建SSL凭据"""
        if not GRPC_AVAILABLE:
            return None
        
        try:
            # 读取证书文件
            private_key = None
            certificate_chain = None
            root_certificates = None
            
            if self._config.ssl_key_file:
                with open(self._config.ssl_key_file, 'rb') as f:
                    private_key = f.read()
            
            if self._config.ssl_cert_file:
                with open(self._config.ssl_cert_file, 'rb') as f:
                    certificate_chain = f.read()
            
            if self._config.ssl_ca_file:
                with open(self._config.ssl_ca_file, 'rb') as f:
                    root_certificates = f.read()
            
            return grpc.ssl_server_credentials(
                [(private_key, certificate_chain)],
                root_certificates=root_certificates,
                require_client_auth=root_certificates is not None
            )
        except Exception as e:
            raise GrpcConfigError(
                message=f"创建SSL凭据失败: {str(e)}",
                config_key="ssl_credentials",
                cause=e
            )
    
    async def _start_server(self):
        """启动服务器"""
        await self._server.start()
        
        # 设置信号处理
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            """信号处理函数"""
            print(f"收到信号 {signum}，开始优雅关闭...")
            asyncio.create_task(self.stop())
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def _register_service(self):
        """注册服务到服务发现"""
        # 这里应该集成实际的服务注册机制
        # 目前只是一个占位符
        pass
    
    async def stop(self, grace_period: Optional[float] = None):
        """停止服务器"""
        if not self._running or self._stopping:
            return
        
        self._stopping = True
        stop_grace_period = grace_period or self._config.grace_period
        
        try:
            # 从服务发现中注销
            if self._config.enable_service_registration:
                await self._unregister_service()
            
            # 停止健康检查
            if self._health_service:
                await self._health_service.stop()
            
            # 停止服务器
            if self._server:
                await self._server.stop(stop_grace_period)
            
            # 关闭线程池
            if self._executor:
                self._executor.shutdown(wait=True)
            
            self._running = False
            self._stopping = False
            self._shutdown_event.set()
            
        except Exception as e:
            print(f"停止服务器时发生错误: {str(e)}")
            raise
    
    async def _unregister_service(self):
        """从服务发现中注销服务"""
        # 这里应该集成实际的服务注销机制
        # 目前只是一个占位符
        pass
    
    async def wait_for_termination(self):
        """等待服务器终止"""
        if self._server:
            await self._server.wait_for_termination()
        else:
            await self._shutdown_event.wait()
    
    def update_service_health(self, service_name: str, is_healthy: bool):
        """更新服务健康状态"""
        if self._health_service:
            from .health_check import HealthStatus
            status = HealthStatus.SERVING if is_healthy else HealthStatus.NOT_SERVING
            self._health_service.set_service_status(service_name, status)
    
    def record_request(self, success: bool, response_time: float):
        """记录请求统计"""
        self._stats['total_requests'] += 1
        self._stats['last_request_time'] = time.time()
        
        if success:
            self._stats['successful_requests'] += 1
        else:
            self._stats['failed_requests'] += 1
        
        # 更新平均响应时间
        if self._stats['avg_response_time'] == 0:
            self._stats['avg_response_time'] = response_time
        else:
            self._stats['avg_response_time'] = (
                self._stats['avg_response_time'] * 0.9 + response_time * 0.1
            )
    
    def check_rate_limit(self) -> bool:
        """检查限流"""
        if self._rate_limiter:
            return self._rate_limiter.acquire()
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self._stats.copy()
        
        # 添加运行时间
        if stats['start_time']:
            stats['uptime'] = time.time() - stats['start_time']
        
        # 添加成功率
        if stats['total_requests'] > 0:
            stats['success_rate'] = stats['successful_requests'] / stats['total_requests']
        else:
            stats['success_rate'] = 0.0
        
        # 添加服务信息
        stats['services'] = {
            name: {
                'description': info.description,
                'version': info.version,
                'metadata': info.metadata
            }
            for name, info in self._services.items()
        }
        
        # 添加配置信息
        stats['config'] = {
            'address': self.address,
            'max_workers': self._config.max_workers,
            'use_ssl': self._config.use_ssl,
            'health_check_enabled': self._config.enable_health_check,
            'rate_limiting_enabled': self._config.enable_rate_limiting,
            'reflection_enabled': self._config.enable_reflection
        }
        
        # 添加健康检查统计
        if self._health_service:
            stats['health_check'] = self._health_service.get_stats_summary()
        
        return stats


class GrpcServerManager:
    """gRPC服务器管理器"""
    
    def __init__(self):
        self._servers: Dict[str, GrpcServer] = {}
        self._lock = asyncio.Lock()
    
    async def create_server(
        self,
        name: str,
        config: ServerConfig
    ) -> GrpcServer:
        """
        创建服务器
        
        Args:
            name: 服务器名称
            config: 服务器配置
            
        Returns:
            GrpcServer: 服务器实例
        """
        async with self._lock:
            if name in self._servers:
                raise GrpcConfigError(
                    message=f"服务器已存在: {name}",
                    config_key="server_name",
                    config_value=name
                )
            
            server = GrpcServer(config)
            self._servers[name] = server
            return server
    
    async def get_server(self, name: str) -> Optional[GrpcServer]:
        """获取服务器"""
        return self._servers.get(name)
    
    async def remove_server(self, name: str) -> bool:
        """移除服务器"""
        async with self._lock:
            server = self._servers.pop(name, None)
            if server:
                if server.is_running:
                    await server.stop()
                return True
            return False
    
    async def stop_all(self):
        """停止所有服务器"""
        async with self._lock:
            servers = list(self._servers.values())
            self._servers.clear()
        
        if servers:
            await asyncio.gather(
                *[server.stop() for server in servers if server.is_running],
                return_exceptions=True
            )
    
    def list_servers(self) -> List[str]:
        """列出所有服务器"""
        return list(self._servers.keys())
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有服务器的统计信息"""
        return {
            name: server.get_stats()
            for name, server in self._servers.items()
        }


# 全局服务器管理器
_server_manager = GrpcServerManager()


# 便捷函数
async def create_server(
    name: str,
    host: str = "0.0.0.0",
    port: int = 50051,
    **kwargs
) -> GrpcServer:
    """
    创建服务器的便捷函数
    
    Args:
        name: 服务器名称
        host: 监听地址
        port: 监听端口
        **kwargs: 其他配置参数
    """
    config = ServerConfig(host=host, port=port, **kwargs)
    return await _server_manager.create_server(name, config)


async def get_server(name: str) -> Optional[GrpcServer]:
    """获取服务器"""
    return await _server_manager.get_server(name)


# 简化的服务器装饰器
def grpc_service(service_name: str, add_to_server_func: Callable):
    """
    gRPC服务装饰器
    
    Args:
        service_name: 服务名称
        add_to_server_func: 添加到服务器的函数
    """
    def decorator(cls):
        # 添加服务信息到类
        cls._grpc_service_name = service_name
        cls._grpc_add_to_server_func = add_to_server_func
        
        return cls
    
    return decorator


# 导出所有公共接口
__all__ = [
    'ServerConfig',
    'ServiceInfo',
    'RateLimiter',
    'GrpcServer',
    'GrpcServerManager',
    'create_server',
    'get_server',
    'grpc_service'
]