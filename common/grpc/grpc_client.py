"""
gRPC客户端封装模块

提供高级的gRPC客户端封装，支持自动服务发现、连接池、负载均衡、
自动重试、请求超时控制、流式调用等功能。
"""

import asyncio
import time
import random
from typing import Any, Dict, List, Optional, Union, Callable, AsyncIterator, Iterator
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from functools import wraps

try:
    import grpc
    from grpc import aio as grpc_aio
except ImportError:
    grpc = None
    
    class MockChannel:
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
    
    class MockGrpcAio:
        Channel = MockChannel
    
    grpc_aio = MockGrpcAio()

from ..logger import logger
from .connection import GrpcConnection, ConnectionConfig
from .grpc_pool import GrpcConnectionPool, PoolConfig, MultiAddressPool
from .load_balancer import LoadBalancer, LoadBalancerFactory, LoadBalanceStrategy, ServerNode
from .interceptor import InterceptorChain, RequestContext, create_default_client_interceptors
from .exceptions import (
    GrpcConnectionError,
    GrpcTimeoutError,
    GrpcServiceUnavailableError,
    GrpcException,
    handle_grpc_exception_async
)


@dataclass
class RetryConfig:
    """重试配置"""
    
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    
    # 可重试的状态码
    retryable_status_codes: List[int] = field(default_factory=lambda: [
        grpc.StatusCode.UNAVAILABLE.value if grpc else 14,
        grpc.StatusCode.DEADLINE_EXCEEDED.value if grpc else 4,
        grpc.StatusCode.RESOURCE_EXHAUSTED.value if grpc else 8,
        grpc.StatusCode.ABORTED.value if grpc else 10,
    ])
    
    def calculate_delay(self, attempt: int) -> float:
        """
        计算重试延迟
        
        Args:
            attempt: 尝试次数（从1开始）
            
        Returns:
            float: 延迟时间（秒）
        """
        delay = min(self.initial_delay * (self.backoff_multiplier ** (attempt - 1)), self.max_delay)
        
        if self.jitter:
            # 添加抖动，避免惊群效应
            delay = delay * (0.5 + random.random() * 0.5)
        
        return delay
    
    def is_retryable(self, status_code: int) -> bool:
        """
        检查状态码是否可重试
        
        Args:
            status_code: gRPC状态码
            
        Returns:
            bool: 是否可重试
        """
        return status_code in self.retryable_status_codes


@dataclass
class ClientConfig:
    """客户端配置"""
    
    # 服务发现配置
    service_name: str = ""
    service_addresses: List[str] = field(default_factory=list)
    
    # 连接配置
    connection_config: ConnectionConfig = field(default_factory=ConnectionConfig)
    pool_config: PoolConfig = field(default_factory=PoolConfig)
    
    # 负载均衡配置
    load_balance_strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN
    
    # 重试配置
    retry_config: RetryConfig = field(default_factory=RetryConfig)
    
    # 超时配置
    default_timeout: float = 30.0
    connect_timeout: float = 10.0
    
    # 服务发现配置
    enable_service_discovery: bool = False
    discovery_interval: float = 60.0
    
    # 拦截器配置
    enable_default_interceptors: bool = True
    custom_interceptors: List[Any] = field(default_factory=list)
    
    # 统计配置
    enable_stats: bool = True
    stats_window_size: int = 1000
    
    def validate(self) -> None:
        """验证配置"""
        if not self.service_name and not self.service_addresses:
            raise GrpcException("必须提供service_name或service_addresses")
        
        if self.default_timeout <= 0:
            raise GrpcException("default_timeout必须大于0")


@dataclass
class CallStats:
    """调用统计信息"""
    
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    timeout_calls: int = 0
    retry_calls: int = 0
    
    total_duration: float = 0.0
    min_duration: float = float('inf')
    max_duration: float = 0.0
    
    # 最近的调用记录
    recent_calls: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls
    
    @property
    def avg_duration(self) -> float:
        """平均持续时间"""
        if self.successful_calls == 0:
            return 0.0
        return self.total_duration / self.successful_calls
    
    def record_call(self, success: bool, duration: float, retries: int = 0, timeout: bool = False) -> None:
        """记录调用统计"""
        self.total_calls += 1
        
        if success:
            self.successful_calls += 1
            self.total_duration += duration
            self.min_duration = min(self.min_duration, duration)
            self.max_duration = max(self.max_duration, duration)
        else:
            self.failed_calls += 1
        
        if timeout:
            self.timeout_calls += 1
        
        if retries > 0:
            self.retry_calls += 1
        
        # 记录最近的调用
        call_record = {
            "timestamp": time.time(),
            "success": success,
            "duration": duration,
            "retries": retries,
            "timeout": timeout
        }
        
        self.recent_calls.append(call_record)
        
        # 保持最近调用记录的数量
        if len(self.recent_calls) > 100:
            self.recent_calls = self.recent_calls[-100:]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "timeout_calls": self.timeout_calls,
            "retry_calls": self.retry_calls,
            "success_rate": self.success_rate,
            "avg_duration": self.avg_duration,
            "min_duration": self.min_duration if self.min_duration != float('inf') else 0,
            "max_duration": self.max_duration,
            "total_duration": self.total_duration
        }


class GrpcClient:
    """
    高级gRPC客户端
    
    提供连接池、负载均衡、自动重试、服务发现等高级功能。
    """
    
    def __init__(self, config: ClientConfig):
        """
        初始化gRPC客户端
        
        Args:
            config: 客户端配置
        """
        config.validate()
        self.config = config
        
        # 连接池管理
        self.connection_pools: Dict[str, GrpcConnectionPool] = {}
        self.multi_pool: Optional[MultiAddressPool] = None
        
        # 负载均衡器
        self.load_balancer: Optional[LoadBalancer] = None
        
        # 拦截器链
        self.interceptor_chain: Optional[InterceptorChain] = None
        
        # 统计信息
        self.stats = CallStats()
        self.method_stats: Dict[str, CallStats] = {}
        
        # 状态管理
        self._initialized = False
        self._closed = False
        self._lock = asyncio.Lock()
        
        # 服务发现任务
        self._discovery_task: Optional[asyncio.Task] = None
        
        logger.info(f"创建gRPC客户端: {config.service_name}")
    
    async def initialize(self) -> None:
        """初始化客户端"""
        if self._initialized:
            return
        
        async with self._lock:
            if self._initialized:
                return
            
            try:
                # 初始化拦截器链
                await self._initialize_interceptors()
                
                # 初始化连接池
                await self._initialize_connection_pools()
                
                # 初始化负载均衡器
                await self._initialize_load_balancer()
                
                # 启动服务发现
                if self.config.enable_service_discovery:
                    await self._start_service_discovery()
                
                self._initialized = True
                logger.info(f"gRPC客户端初始化完成: {self.config.service_name}")
                
            except Exception as e:
                logger.error(f"gRPC客户端初始化失败: {e}")
                raise GrpcException(f"客户端初始化失败: {e}", cause=e)
    
    async def _initialize_interceptors(self) -> None:
        """初始化拦截器链"""
        interceptors = []
        
        if self.config.enable_default_interceptors:
            interceptors.extend(create_default_client_interceptors())
        
        interceptors.extend(self.config.custom_interceptors)
        
        self.interceptor_chain = InterceptorChain(interceptors)
        logger.debug("拦截器链初始化完成")
    
    async def _initialize_connection_pools(self) -> None:
        """初始化连接池"""
        if self.config.service_addresses:
            # 使用指定的地址列表
            pool_configs = {}
            
            for address in self.config.service_addresses:
                # 解析地址
                if ':' in address:
                    host, port = address.split(':', 1)
                    port = int(port)
                else:
                    host = address
                    port = 50051  # 默认端口
                
                # 创建连接配置
                conn_config = ConnectionConfig(
                    host=host,
                    port=port,
                    **self.config.connection_config.__dict__
                )
                
                # 创建池配置
                pool_config = PoolConfig(
                    connection_config=conn_config,
                    **{k: v for k, v in self.config.pool_config.__dict__.items() 
                       if k != 'connection_config'}
                )
                
                pool_configs[address] = pool_config
            
            # 创建多地址连接池
            self.multi_pool = MultiAddressPool(pool_configs)
            await self.multi_pool.initialize()
            
        else:
            logger.warning("未提供服务地址，等待服务发现")
    
    async def _initialize_load_balancer(self) -> None:
        """初始化负载均衡器"""
        if self.config.service_addresses:
            # 创建服务器节点
            servers = []
            for address in self.config.service_addresses:
                if ':' in address:
                    host, port = address.split(':', 1)
                    port = int(port)
                else:
                    host = address
                    port = 50051
                
                server = ServerNode(address=host, port=port)
                servers.append(server)
            
            # 创建负载均衡器
            self.load_balancer = LoadBalancerFactory.create(
                strategy=self.config.load_balance_strategy,
                servers=servers
            )
            
            # 启动健康监控
            self.load_balancer.start_health_monitoring()
            
            logger.debug(f"负载均衡器初始化完成: {self.config.load_balance_strategy.value}")
    
    async def _start_service_discovery(self) -> None:
        """启动服务发现"""
        self._discovery_task = asyncio.create_task(self._service_discovery_loop())
        logger.info(f"启动服务发现: {self.config.service_name}")
    
    async def _service_discovery_loop(self) -> None:
        """服务发现循环"""
        while not self._closed:
            try:
                await self._discover_services()
                await asyncio.sleep(self.config.discovery_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"服务发现异常: {e}")
                await asyncio.sleep(self.config.discovery_interval)
    
    async def _discover_services(self) -> None:
        """执行服务发现"""
        # 这里应该集成实际的服务发现机制
        # 例如从注册中心获取服务地址列表
        logger.debug(f"执行服务发现: {self.config.service_name}")
        
        # 示例实现：这里应该调用实际的服务发现API
        try:
            # from ..registry import get_service_addresses
            # addresses = await get_service_addresses(self.config.service_name)
            # await self._update_service_addresses(addresses)
            pass
        except Exception as e:
            logger.warning(f"服务发现失败: {e}")
    
    async def _update_service_addresses(self, addresses: List[str]) -> None:
        """
        更新服务地址列表
        
        Args:
            addresses: 新的地址列表
        """
        if set(addresses) != set(self.config.service_addresses):
            self.config.service_addresses = addresses
            
            # 重新初始化连接池和负载均衡器
            await self._initialize_connection_pools()
            await self._initialize_load_balancer()
            
            logger.info(f"服务地址已更新: {addresses}")
    
    @handle_grpc_exception_async
    async def call(
        self,
        method: str,
        request: Any,
        timeout: Optional[float] = None,
        metadata: Optional[List[tuple]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        执行一元调用
        
        Args:
            method: 方法名
            request: 请求对象
            timeout: 超时时间
            metadata: 元数据
            context: 请求上下文
            
        Returns:
            Any: 响应对象
        """
        if not self._initialized:
            await self.initialize()
        
        if self._closed:
            raise GrpcConnectionError("客户端已关闭")
        
        timeout = timeout or self.config.default_timeout
        context = context or {}
        
        # 创建请求上下文
        request_context = RequestContext(
            method_name=method,
            service_name=self.config.service_name,
            **context
        )
        
        # 重试逻辑
        last_exception = None
        
        for attempt in range(1, self.config.retry_config.max_attempts + 1):
            try:
                start_time = time.time()
                
                # 执行调用
                response = await self._execute_call(
                    method, request, timeout, metadata, request_context
                )
                
                # 记录成功统计
                duration = time.time() - start_time
                self._record_call_stats(method, True, duration, attempt - 1)
                
                return response
                
            except Exception as e:
                last_exception = e
                duration = time.time() - start_time
                
                # 检查是否可重试
                if attempt < self.config.retry_config.max_attempts and self._is_retryable(e):
                    delay = self.config.retry_config.calculate_delay(attempt)
                    logger.warning(f"调用失败，{delay:.2f}秒后重试 (尝试 {attempt}/{self.config.retry_config.max_attempts}): {e}")
                    await asyncio.sleep(delay)
                    continue
                else:
                    # 记录失败统计
                    timeout_occurred = isinstance(e, (asyncio.TimeoutError, GrpcTimeoutError))
                    self._record_call_stats(method, False, duration, attempt - 1, timeout_occurred)
                    raise
        
        # 如果所有重试都失败了，抛出最后一个异常
        if last_exception:
            raise last_exception
    
    async def _execute_call(
        self,
        method: str,
        request: Any,
        timeout: float,
        metadata: Optional[List[tuple]],
        context: RequestContext
    ) -> Any:
        """
        执行单次调用
        
        Args:
            method: 方法名
            request: 请求对象
            timeout: 超时时间
            metadata: 元数据
            context: 请求上下文
            
        Returns:
            Any: 响应对象
        """
        # 选择服务器
        server = await self._select_server(context)
        
        # 获取连接
        async with self._get_connection(server.endpoint) as connection:
            # 获取gRPC频道
            async with connection.get_channel() as channel:
                try:
                    # 处理请求拦截器
                    if self.interceptor_chain:
                        request = await self.interceptor_chain.process_request(context, request)
                    
                    # 执行gRPC调用
                    stub_class = self._get_stub_class(method)
                    stub = stub_class(channel)
                    method_func = getattr(stub, method.split('.')[-1])
                    
                    # 设置调用选项
                    call_options = {}
                    if timeout:
                        call_options['timeout'] = timeout
                    if metadata:
                        call_options['metadata'] = metadata
                    
                    # 执行调用
                    response = await method_func(request, **call_options)
                    
                    # 处理响应拦截器
                    if self.interceptor_chain:
                        response = await self.interceptor_chain.process_response(context, response)
                    
                    # 记录服务器统计
                    if self.load_balancer:
                        self.load_balancer.record_request(server.endpoint, True, context.duration)
                    
                    return response
                    
                except Exception as e:
                    # 记录服务器统计
                    if self.load_balancer:
                        self.load_balancer.record_request(server.endpoint, False, context.duration)
                    
                    # 处理异常拦截器
                    if self.interceptor_chain and self.interceptor_chain.exception_interceptor:
                        handled_exception = self.interceptor_chain.exception_interceptor.handle_exception(context, e)
                        raise handled_exception
                    
                    raise
    
    def _get_stub_class(self, method: str) -> type:
        """
        获取存根类
        
        Args:
            method: 方法名（格式：ServiceName.MethodName）
            
        Returns:
            type: 存根类
        """
        # 这里应该根据方法名动态获取对应的存根类
        # 示例实现，实际使用时需要根据proto文件生成的类来实现
        if '.' in method:
            service_name = method.split('.')[0]
        else:
            service_name = self.config.service_name
        
        # 这里应该有一个映射表或动态导入机制
        # 例如：return getattr(pb2_grpc, f"{service_name}Stub")
        raise NotImplementedError("需要实现存根类获取逻辑")
    
    async def _select_server(self, context: RequestContext) -> ServerNode:
        """
        选择服务器
        
        Args:
            context: 请求上下文
            
        Returns:
            ServerNode: 选中的服务器
        """
        if not self.load_balancer:
            raise GrpcServiceUnavailableError("负载均衡器未初始化")
        
        return await self.load_balancer.select_server(context.to_dict())
    
    @asynccontextmanager
    async def _get_connection(self, address: str):
        """
        获取连接的上下文管理器
        
        Args:
            address: 服务器地址
        """
        if self.multi_pool:
            async with self.multi_pool.get_connection(address) as connection:
                yield connection
        else:
            raise GrpcConnectionError("连接池未初始化")
    
    def _is_retryable(self, exception: Exception) -> bool:
        """
        检查异常是否可重试
        
        Args:
            exception: 异常对象
            
        Returns:
            bool: 是否可重试
        """
        if isinstance(exception, GrpcException):
            # 检查gRPC状态码
            status_code = getattr(exception, 'status_code', None)
            if status_code:
                return self.config.retry_config.is_retryable(status_code)
        
        # 连接错误通常可重试
        if isinstance(exception, (GrpcConnectionError, ConnectionError)):
            return True
        
        # 超时错误可重试
        if isinstance(exception, (GrpcTimeoutError, asyncio.TimeoutError)):
            return True
        
        return False
    
    def _record_call_stats(
        self, 
        method: str, 
        success: bool, 
        duration: float, 
        retries: int = 0, 
        timeout: bool = False
    ) -> None:
        """
        记录调用统计
        
        Args:
            method: 方法名
            success: 是否成功
            duration: 持续时间
            retries: 重试次数
            timeout: 是否超时
        """
        # 全局统计
        self.stats.record_call(success, duration, retries, timeout)
        
        # 方法级统计
        if method not in self.method_stats:
            self.method_stats[method] = CallStats()
        
        self.method_stats[method].record_call(success, duration, retries, timeout)
    
    async def stream_call(
        self,
        method: str,
        request_iterator: AsyncIterator[Any],
        timeout: Optional[float] = None,
        metadata: Optional[List[tuple]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Any]:
        """
        执行流式调用
        
        Args:
            method: 方法名
            request_iterator: 请求迭代器
            timeout: 超时时间
            metadata: 元数据
            context: 请求上下文
            
        Yields:
            Any: 响应对象
        """
        if not self._initialized:
            await self.initialize()
        
        if self._closed:
            raise GrpcConnectionError("客户端已关闭")
        
        timeout = timeout or self.config.default_timeout
        context = context or {}
        
        # 创建请求上下文
        request_context = RequestContext(
            method_name=method,
            service_name=self.config.service_name,
            **context
        )
        
        # 选择服务器
        server = await self._select_server(request_context)
        
        # 获取连接
        async with self._get_connection(server.endpoint) as connection:
            async with connection.get_channel() as channel:
                try:
                    # 创建存根
                    stub_class = self._get_stub_class(method)
                    stub = stub_class(channel)
                    method_func = getattr(stub, method.split('.')[-1])
                    
                    # 设置调用选项
                    call_options = {}
                    if timeout:
                        call_options['timeout'] = timeout
                    if metadata:
                        call_options['metadata'] = metadata
                    
                    # 执行流式调用
                    response_stream = method_func(request_iterator, **call_options)
                    
                    async for response in response_stream:
                        # 处理响应拦截器
                        if self.interceptor_chain:
                            response = await self.interceptor_chain.process_response(request_context, response)
                        
                        yield response
                    
                    # 记录成功统计
                    self._record_call_stats(method, True, request_context.duration)
                    
                except Exception as e:
                    # 记录失败统计
                    self._record_call_stats(method, False, request_context.duration)
                    
                    # 处理异常
                    if self.interceptor_chain and self.interceptor_chain.exception_interceptor:
                        handled_exception = self.interceptor_chain.exception_interceptor.handle_exception(request_context, e)
                        raise handled_exception
                    
                    raise
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取客户端统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        return {
            "client": {
                "service_name": self.config.service_name,
                "initialized": self._initialized,
                "closed": self._closed,
                "service_addresses": self.config.service_addresses,
                "load_balance_strategy": self.config.load_balance_strategy.value,
            },
            "global_stats": self.stats.to_dict(),
            "method_stats": {
                method: stats.to_dict()
                for method, stats in self.method_stats.items()
            },
            "load_balancer": self.load_balancer.get_stats() if self.load_balancer else None,
            "connection_pools": self.multi_pool.get_all_stats() if self.multi_pool else {},
            "interceptors": self.interceptor_chain.get_stats() if self.interceptor_chain else {}
        }
    
    async def close(self) -> None:
        """关闭客户端"""
        if self._closed:
            return
        
        self._closed = True
        
        # 停止服务发现
        if self._discovery_task and not self._discovery_task.done():
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass
        
        # 停止负载均衡器监控
        if self.load_balancer:
            await self.load_balancer.stop_health_monitoring()
        
        # 关闭连接池
        if self.multi_pool:
            await self.multi_pool.close()
        
        logger.info(f"gRPC客户端已关闭: {self.config.service_name}")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()


# 便捷函数
def create_simple_client(
    service_addresses: List[str],
    service_name: str = "",
    timeout: float = 30.0,
    max_retries: int = 3,
    load_balance_strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN
) -> GrpcClient:
    """
    创建简单的gRPC客户端
    
    Args:
        service_addresses: 服务地址列表
        service_name: 服务名称
        timeout: 默认超时时间
        max_retries: 最大重试次数
        load_balance_strategy: 负载均衡策略
        
    Returns:
        GrpcClient: gRPC客户端实例
    """
    config = ClientConfig(
        service_name=service_name,
        service_addresses=service_addresses,
        default_timeout=timeout,
        load_balance_strategy=load_balance_strategy,
        retry_config=RetryConfig(max_attempts=max_retries)
    )
    
    return GrpcClient(config)


def create_discovery_client(
    service_name: str,
    timeout: float = 30.0,
    max_retries: int = 3,
    discovery_interval: float = 60.0,
    load_balance_strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN
) -> GrpcClient:
    """
    创建支持服务发现的gRPC客户端
    
    Args:
        service_name: 服务名称
        timeout: 默认超时时间
        max_retries: 最大重试次数
        discovery_interval: 服务发现间隔
        load_balance_strategy: 负载均衡策略
        
    Returns:
        GrpcClient: gRPC客户端实例
    """
    config = ClientConfig(
        service_name=service_name,
        default_timeout=timeout,
        load_balance_strategy=load_balance_strategy,
        retry_config=RetryConfig(max_attempts=max_retries),
        enable_service_discovery=True,
        discovery_interval=discovery_interval
    )
    
    return GrpcClient(config)