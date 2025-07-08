"""
gRPC客户端封装模块

该模块实现了高级gRPC客户端，支持服务发现、连接池、负载均衡、自动重试、
流式调用等功能。提供同步和异步调用模式。
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Callable, Union, AsyncIterator, Iterator
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

try:
    import grpc
    import grpc.aio
    from grpc import StatusCode
    GRPC_AVAILABLE = True
except ImportError:
    # 模拟grpc模块
    GRPC_AVAILABLE = False
    
    class StatusCode:
        OK = 'OK'
        UNAVAILABLE = 'UNAVAILABLE'
        DEADLINE_EXCEEDED = 'DEADLINE_EXCEEDED'
        UNAUTHENTICATED = 'UNAUTHENTICATED'

from .connection import GrpcConnection, ConnectionConfig
from .grpc_pool import GrpcConnectionPool, PoolConfig, create_pool
from .load_balancer import LoadBalancer, LoadBalancerStrategy, NodeInfo, create_balancer
from .interceptor import InterceptorChain, get_default_chain
from .health_check import HealthCheckService
from .exceptions import (
    GrpcConnectionError,
    GrpcTimeoutError,
    GrpcServiceUnavailableError,
    handle_async_grpc_exception
)


@dataclass
class RetryConfig:
    """重试配置"""
    max_attempts: int = 3               # 最大重试次数
    initial_backoff: float = 1.0        # 初始退避时间(秒)
    max_backoff: float = 10.0           # 最大退避时间(秒)
    backoff_multiplier: float = 2.0     # 退避倍数
    retryable_status_codes: List[str] = field(default_factory=lambda: [
        'UNAVAILABLE', 'DEADLINE_EXCEEDED', 'RESOURCE_EXHAUSTED'
    ])
    jitter: bool = True                 # 是否添加抖动


@dataclass
class ClientConfig:
    """客户端配置"""
    # 基本配置
    service_name: str                   # 服务名称
    default_timeout: float = 30.0       # 默认超时时间
    
    # 连接配置
    connection_config: Optional[ConnectionConfig] = None
    pool_config: Optional[PoolConfig] = None
    
    # 负载均衡配置
    load_balancer_strategy: LoadBalancerStrategy = LoadBalancerStrategy.ROUND_ROBIN
    enable_load_balancing: bool = True
    
    # 重试配置
    retry_config: Optional[RetryConfig] = None
    enable_retry: bool = True
    
    # 服务发现配置
    enable_service_discovery: bool = False
    discovery_interval: float = 30.0    # 服务发现间隔(秒)
    
    # 健康检查配置
    enable_health_check: bool = True
    health_check_interval: float = 60.0 # 健康检查间隔(秒)
    
    # 拦截器配置
    interceptor_chain: Optional[InterceptorChain] = None
    enable_default_interceptors: bool = True
    
    # 元数据配置
    default_metadata: Dict[str, str] = field(default_factory=dict)
    
    # 其他配置
    enable_compression: bool = False     # 启用压缩
    compression_algorithm: str = "gzip"  # 压缩算法


class GrpcClient:
    """gRPC客户端"""
    
    def __init__(self, config: ClientConfig):
        """
        初始化gRPC客户端
        
        Args:
            config: 客户端配置
        """
        self._config = config
        self._service_name = config.service_name
        
        # 连接管理
        self._connection_pool: Optional[GrpcConnectionPool] = None
        self._load_balancer: Optional[LoadBalancer] = None
        self._direct_connection: Optional[GrpcConnection] = None
        
        # 服务发现
        self._service_endpoints: List[str] = []
        self._discovery_task: Optional[asyncio.Task] = None
        
        # 健康检查
        self._health_service: Optional[HealthCheckService] = None
        self._health_check_task: Optional[asyncio.Task] = None
        
        # 拦截器
        self._interceptor_chain = config.interceptor_chain or get_default_chain()
        
        # 重试配置
        self._retry_config = config.retry_config or RetryConfig()
        
        # 统计信息
        self._stats = {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'retried_requests': 0,
            'avg_response_time': 0.0
        }
        
        # 状态标志
        self._initialized = False
        self._closed = False
        
        # 锁
        self._lock = asyncio.Lock()
    
    @property
    def service_name(self) -> str:
        """获取服务名称"""
        return self._service_name
    
    @property
    def is_initialized(self) -> bool:
        """是否已初始化"""
        return self._initialized
    
    @property
    def is_closed(self) -> bool:
        """是否已关闭"""
        return self._closed
    
    async def initialize(self, endpoints: Optional[List[str]] = None):
        """
        初始化客户端
        
        Args:
            endpoints: 服务端点列表
        """
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                # 设置端点
                if endpoints:
                    self._service_endpoints = endpoints
                
                # 初始化连接池或直连
                if len(self._service_endpoints) > 1 or self._config.enable_load_balancing:
                    await self._setup_load_balancing()
                else:
                    await self._setup_direct_connection()
                
                # 启动服务发现
                if self._config.enable_service_discovery:
                    await self._start_service_discovery()
                
                # 启动健康检查
                if self._config.enable_health_check:
                    await self._start_health_check()
                
                self._initialized = True
                
            except Exception as e:
                raise GrpcConnectionError(
                    message=f"客户端初始化失败: {str(e)}",
                    cause=e
                )
    
    async def _setup_load_balancing(self):
        """设置负载均衡"""
        if not self._service_endpoints:
            raise GrpcConnectionError(
                message="负载均衡模式需要至少一个端点"
            )
        
        # 创建负载均衡器
        balancer_name = f"{self._service_name}_balancer"
        nodes = [(endpoint, 100) for endpoint in self._service_endpoints]
        
        self._load_balancer = await create_balancer(
            name=balancer_name,
            strategy=self._config.load_balancer_strategy,
            nodes=nodes
        )
        
        # 创建连接池（用于每个端点）
        from .grpc_pool import create_pool
        self._connection_pools = {}
        for endpoint in self._service_endpoints:
            pool_name = f"{self._service_name}_{endpoint}"
            
            # 解析端点
            if ":" in endpoint:
                host, port = endpoint.rsplit(":", 1)
                port = int(port)
            else:
                host = endpoint
                port = None
            
            # 创建连接配置
            conn_config = self._config.connection_config or ConnectionConfig(
                target=host,
                port=port
            )
            conn_config.target = host
            conn_config.port = port
            
            # 创建连接池
            pool = await create_pool(
                name=pool_name,
                target=host,
                port=port,
                **(self._config.pool_config.__dict__ if self._config.pool_config else {})
            )
            
            self._connection_pools[endpoint] = pool
    
    async def _setup_direct_connection(self):
        """设置直连"""
        if not self._service_endpoints:
            raise GrpcConnectionError(
                message="直连模式需要端点"
            )
        
        endpoint = self._service_endpoints[0]
        
        # 解析端点
        if ":" in endpoint:
            host, port = endpoint.rsplit(":", 1)
            port = int(port)
        else:
            host = endpoint
            port = None
        
        # 创建连接配置
        conn_config = self._config.connection_config or ConnectionConfig(
            target=host,
            port=port
        )
        conn_config.target = host
        conn_config.port = port
        
        # 创建直连
        self._direct_connection = GrpcConnection(conn_config)
        await self._direct_connection.connect()
    
    async def _start_service_discovery(self):
        """启动服务发现"""
        # 这里应该集成实际的服务发现机制
        # 目前只是一个占位符
        self._discovery_task = asyncio.create_task(self._discovery_loop())
    
    async def _discovery_loop(self):
        """服务发现循环"""
        try:
            while not self._closed:
                await asyncio.sleep(self._config.discovery_interval)
                # 这里应该从服务注册中心获取最新的端点列表
                # await self._update_endpoints_from_registry()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略服务发现异常
    
    async def _start_health_check(self):
        """启动健康检查"""
        if not self._health_service:
            self._health_service = HealthCheckService()
            await self._health_service.start()
        
        self._health_check_task = asyncio.create_task(self._health_check_loop())
    
    async def _health_check_loop(self):
        """健康检查循环"""
        try:
            while not self._closed:
                await asyncio.sleep(self._config.health_check_interval)
                await self._perform_health_checks()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass  # 忽略健康检查异常
    
    async def _perform_health_checks(self):
        """执行健康检查"""
        if self._load_balancer:
            # 检查所有端点的健康状态
            for endpoint in self._service_endpoints:
                try:
                    pool = self._connection_pools.get(endpoint)
                    if pool:
                        async with pool.get_connection() as conn:
                            # 执行健康检查
                            result = await self._health_service.check_service_health(
                                conn.channel,
                                self._service_name
                            )
                            
                            # 更新负载均衡器中的节点状态
                            await self._load_balancer.update_node_health(
                                endpoint,
                                result.is_healthy
                            )
                except Exception:
                    # 健康检查失败，标记为不健康
                    await self._load_balancer.update_node_health(endpoint, False)
    
    @handle_async_grpc_exception
    async def call(
        self,
        method: str,
        request: Any,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> Any:
        """
        调用gRPC方法
        
        Args:
            method: 方法名
            request: 请求对象
            timeout: 超时时间
            metadata: 元数据
            **kwargs: 其他参数
            
        Returns:
            Any: 响应对象
        """
        if not self._initialized:
            raise GrpcConnectionError(
                message="客户端未初始化"
            )
        
        if self._closed:
            raise GrpcConnectionError(
                message="客户端已关闭"
            )
        
        # 合并元数据
        final_metadata = self._config.default_metadata.copy()
        if metadata:
            final_metadata.update(metadata)
        
        # 设置超时
        call_timeout = timeout or self._config.default_timeout
        
        # 执行调用（带重试）
        if self._config.enable_retry:
            return await self._call_with_retry(
                method, request, call_timeout, final_metadata, **kwargs
            )
        else:
            return await self._call_once(
                method, request, call_timeout, final_metadata, **kwargs
            )
    
    async def _call_with_retry(
        self,
        method: str,
        request: Any,
        timeout: float,
        metadata: Dict[str, str],
        **kwargs
    ) -> Any:
        """带重试的调用"""
        last_exception = None
        
        for attempt in range(self._retry_config.max_attempts):
            try:
                return await self._call_once(method, request, timeout, metadata, **kwargs)
                
            except Exception as e:
                last_exception = e
                
                # 检查是否应该重试
                if not self._should_retry(e, attempt):
                    break
                
                # 计算退避时间
                if attempt < self._retry_config.max_attempts - 1:
                    backoff_time = self._calculate_backoff(attempt)
                    await asyncio.sleep(backoff_time)
                    
                    self._stats['retried_requests'] += 1
        
        # 重试耗尽，抛出最后的异常
        raise last_exception
    
    def _should_retry(self, exception: Exception, attempt: int) -> bool:
        """判断是否应该重试"""
        if attempt >= self._retry_config.max_attempts - 1:
            return False
        
        # 检查异常类型和状态码
        if hasattr(exception, 'status_code'):
            status_code = exception.status_code
            return status_code in self._retry_config.retryable_status_codes
        
        # 对于网络错误等也进行重试
        return isinstance(exception, (ConnectionError, TimeoutError, GrpcConnectionError))
    
    def _calculate_backoff(self, attempt: int) -> float:
        """计算退避时间"""
        backoff = min(
            self._retry_config.initial_backoff * (self._retry_config.backoff_multiplier ** attempt),
            self._retry_config.max_backoff
        )
        
        # 添加抖动
        if self._retry_config.jitter:
            import random
            backoff *= (0.5 + random.random() * 0.5)
        
        return backoff
    
    async def _call_once(
        self,
        method: str,
        request: Any,
        timeout: float,
        metadata: Dict[str, str],
        **kwargs
    ) -> Any:
        """单次调用"""
        start_time = time.time()
        
        try:
            # 获取连接
            async with self._get_connection() as channel:
                # 执行拦截器链
                async def handler(req):
                    return await self._execute_grpc_call(
                        channel, method, req, timeout, metadata, **kwargs
                    )
                
                response, context = await self._interceptor_chain.execute(
                    method, request, handler, metadata=metadata, **kwargs
                )
                
                # 更新统计
                self._update_stats(True, time.time() - start_time)
                
                return response
                
        except Exception as e:
            # 更新统计
            self._update_stats(False, time.time() - start_time)
            raise
    
    @asynccontextmanager
    async def _get_connection(self):
        """获取连接"""
        if self._load_balancer:
            # 使用负载均衡选择端点
            node = await self._load_balancer.select_node()
            if not node:
                raise GrpcServiceUnavailableError(
                    message="没有可用的服务端点",
                    service_name=self._service_name,
                    endpoints=self._service_endpoints
                )
            
            pool = self._connection_pools.get(node.endpoint)
            if not pool:
                raise GrpcConnectionError(
                    message=f"未找到端点的连接池: {node.endpoint}",
                    endpoint=node.endpoint
                )
            
            async with pool.get_connection() as conn:
                try:
                    yield conn.channel
                    # 记录成功
                    await self._load_balancer.record_request_result(
                        node.endpoint, True
                    )
                except Exception as e:
                    # 记录失败
                    await self._load_balancer.record_request_result(
                        node.endpoint, False
                    )
                    raise
        else:
            # 使用直连
            if not self._direct_connection or not self._direct_connection.is_connected:
                raise GrpcConnectionError(
                    message="直连不可用",
                    endpoint=self._service_endpoints[0] if self._service_endpoints else "unknown"
                )
            
            async with self._direct_connection.use_connection() as channel:
                yield channel
    
    async def _execute_grpc_call(
        self,
        channel,
        method: str,
        request: Any,
        timeout: float,
        metadata: Dict[str, str],
        **kwargs
    ) -> Any:
        """执行实际的gRPC调用"""
        if not GRPC_AVAILABLE:
            # 模拟gRPC调用
            await asyncio.sleep(0.01)  # 模拟网络延迟
            return f"Mock response for {method}"
        
        # 这里应该根据method和服务类型执行实际的gRPC调用
        # 由于这是通用客户端，需要动态调用
        # 实际使用时应该为特定服务生成专门的客户端
        
        try:
            # 创建stub（这里需要根据实际服务定义）
            # stub = YourServiceStub(channel)
            
            # 执行调用
            # response = await asyncio.wait_for(
            #     stub.your_method(request, metadata=list(metadata.items())),
            #     timeout=timeout
            # )
            
            # 模拟响应
            await asyncio.sleep(0.01)
            return f"Response for {method}"
            
        except asyncio.TimeoutError:
            raise GrpcTimeoutError(
                message=f"调用超时: {method}",
                timeout=timeout,
                operation=method
            )
        except Exception as e:
            raise GrpcConnectionError(
                message=f"调用失败: {method} - {str(e)}",
                cause=e
            )
    
    def _update_stats(self, success: bool, response_time: float):
        """更新统计信息"""
        self._stats['total_requests'] += 1
        
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
    
    async def stream_call(
        self,
        method: str,
        request_iterator: AsyncIterator[Any],
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Any]:
        """
        流式调用
        
        Args:
            method: 方法名
            request_iterator: 请求迭代器
            timeout: 超时时间
            metadata: 元数据
            
        Yields:
            Any: 响应对象
        """
        # 合并元数据
        final_metadata = self._config.default_metadata.copy()
        if metadata:
            final_metadata.update(metadata)
        
        async with self._get_connection() as channel:
            # 这里应该执行实际的流式调用
            # 由于是通用实现，这里只是示例
            async for request in request_iterator:
                # 模拟处理
                await asyncio.sleep(0.01)
                yield f"Stream response for {method}"
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self._stats.copy()
        
        # 添加连接池统计
        if hasattr(self, '_connection_pools'):
            stats['connection_pools'] = {
                endpoint: pool.get_stats_dict()
                for endpoint, pool in self._connection_pools.items()
            }
        
        # 添加负载均衡器统计
        if self._load_balancer:
            stats['load_balancer'] = self._load_balancer.get_stats()
        
        # 添加配置信息
        stats['config'] = {
            'service_name': self._service_name,
            'endpoints': self._service_endpoints,
            'load_balancing_enabled': self._config.enable_load_balancing,
            'retry_enabled': self._config.enable_retry,
            'health_check_enabled': self._config.enable_health_check
        }
        
        return stats
    
    async def close(self):
        """关闭客户端"""
        if self._closed:
            return
        
        self._closed = True
        
        # 停止后台任务
        tasks = [self._discovery_task, self._health_check_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # 关闭连接池
        if hasattr(self, '_connection_pools'):
            for pool in self._connection_pools.values():
                await pool.close()
        
        # 关闭直连
        if self._direct_connection:
            await self._direct_connection.disconnect()
        
        # 停止健康检查服务
        if self._health_service:
            await self._health_service.stop()


class GrpcClientManager:
    """gRPC客户端管理器"""
    
    def __init__(self):
        self._clients: Dict[str, GrpcClient] = {}
        self._lock = asyncio.Lock()
    
    async def create_client(
        self,
        service_name: str,
        config: ClientConfig,
        endpoints: Optional[List[str]] = None
    ) -> GrpcClient:
        """
        创建客户端
        
        Args:
            service_name: 服务名称
            config: 客户端配置
            endpoints: 端点列表
            
        Returns:
            GrpcClient: 客户端实例
        """
        async with self._lock:
            if service_name in self._clients:
                raise GrpcConnectionError(
                    message=f"客户端已存在: {service_name}"
                )
            
            client = GrpcClient(config)
            await client.initialize(endpoints)
            self._clients[service_name] = client
            return client
    
    async def get_client(self, service_name: str) -> Optional[GrpcClient]:
        """获取客户端"""
        return self._clients.get(service_name)
    
    async def remove_client(self, service_name: str) -> bool:
        """移除客户端"""
        async with self._lock:
            client = self._clients.pop(service_name, None)
            if client:
                await client.close()
                return True
            return False
    
    async def close_all(self):
        """关闭所有客户端"""
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        
        if clients:
            await asyncio.gather(
                *[client.close() for client in clients],
                return_exceptions=True
            )
    
    def list_clients(self) -> List[str]:
        """列出所有客户端"""
        return list(self._clients.keys())


# 全局客户端管理器
_client_manager = GrpcClientManager()


# 便捷函数
async def create_client(
    service_name: str,
    endpoints: List[str],
    **kwargs
) -> GrpcClient:
    """
    创建客户端的便捷函数
    
    Args:
        service_name: 服务名称
        endpoints: 端点列表
        **kwargs: 其他配置参数
    """
    config = ClientConfig(service_name=service_name, **kwargs)
    return await _client_manager.create_client(service_name, config, endpoints)


async def get_client(service_name: str) -> Optional[GrpcClient]:
    """获取客户端"""
    return await _client_manager.get_client(service_name)


# 导出所有公共接口
__all__ = [
    'RetryConfig',
    'ClientConfig',
    'GrpcClient',
    'GrpcClientManager',
    'create_client',
    'get_client'
]