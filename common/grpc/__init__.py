"""
common/grpc 模块

该模块提供了高性能、可靠的gRPC通信解决方案，包含：

核心组件：
- GrpcConnection: gRPC连接管理，支持状态监控和自动重连
- GrpcConnectionPool: 高性能连接池，支持自动扩缩容和健康检查
- GrpcClient: 客户端封装，支持服务发现、负载均衡和自动重试
- GrpcServer: 服务端封装，支持限流、监控和优雅关闭

负载均衡：
- LoadBalancer: 负载均衡器基类
- RoundRobinBalancer: 轮询负载均衡
- RandomBalancer: 随机负载均衡
- LeastConnectionBalancer: 最少连接负载均衡
- ConsistentHashBalancer: 一致性哈希负载均衡
- WeightedRandomBalancer: 加权随机负载均衡
- FastestResponseBalancer: 最快响应负载均衡

拦截器：
- InterceptorChain: 拦截器链管理
- AuthInterceptor: 认证拦截器
- LoggingInterceptor: 日志拦截器
- TracingInterceptor: 链路追踪拦截器
- MetricsInterceptor: 性能监控拦截器
- ExceptionInterceptor: 异常处理拦截器

健康检查：
- HealthCheckService: 健康检查服务
- HealthChecker: 健康检查器基类
- DatabaseHealthChecker: 数据库健康检查器
- RedisHealthChecker: Redis健康检查器

异常处理：
- GrpcException: gRPC异常基类
- GrpcConnectionError: 连接异常
- GrpcTimeoutError: 超时异常
- GrpcServiceUnavailableError: 服务不可用异常
- GrpcPoolExhaustedError: 连接池耗尽异常
- GrpcAuthenticationError: 认证失败异常

使用示例：

1. 创建简单的gRPC客户端:
```python
from common.grpc import create_simple_client

client = create_simple_client(
    service_addresses=["localhost:50051", "localhost:50052"],
    service_name="user_service",
    timeout=30.0
)

async with client:
    response = await client.call("GetUser", request)
```

2. 创建gRPC服务器:
```python
from common.grpc import create_simple_server

server = create_simple_server(
    host="0.0.0.0",
    port=50051,
    max_workers=10
)

# 添加服务
server.add_service(UserServiceImpl(), add_UserServiceServicer_to_server)

async with server:
    await server.wait_for_termination()
```

3. 使用连接池:
```python
from common.grpc import GrpcConnectionPool, PoolConfig

config = PoolConfig(min_connections=2, max_connections=20)
pool = GrpcConnectionPool(config)

async with pool.get_connection() as conn:
    async with conn.get_channel() as channel:
        # 使用channel进行gRPC调用
```

主要特性：
- 高性能连接池，支持10000+ QPS
- 多种负载均衡策略
- 完整的拦截器机制
- 自动重连和故障转移
- 健康检查和监控
- 详细的中文注释
- 线程安全和异步支持
"""

# 核心连接和池管理
from .connection import (
    GrpcConnection,
    ConnectionConfig,
    ConnectionState,
    ConnectionStats
)

from .grpc_pool import (
    GrpcConnectionPool,
    PoolConfig,
    PoolStats,
    PooledConnection,
    MultiAddressPool
)

# 客户端和服务端
from .grpc_client import (
    GrpcClient,
    ClientConfig,
    RetryConfig,
    CallStats,
    create_simple_client,
    create_discovery_client
)

from .grpc_server import (
    GrpcServer,
    ServerConfig,
    RateLimitConfig,
    ServiceStats,
    RateLimiter,
    create_simple_server,
    create_secure_server,
    setup_signal_handlers
)

# 负载均衡
from .load_balancer import (
    LoadBalancer,
    LoadBalanceStrategy,
    ServerNode,
    RoundRobinBalancer,
    RandomBalancer,
    WeightedRandomBalancer,
    LeastConnectionBalancer,
    ConsistentHashBalancer,
    FastestResponseBalancer,
    LoadBalancerFactory,
    ConnectionAwareProxy
)

# 拦截器
from .interceptor import (
    BaseInterceptor,
    InterceptorChain,
    RequestContext,
    AuthInterceptor,
    LoggingInterceptor,
    TracingInterceptor,
    MetricsInterceptor,
    ExceptionInterceptor,
    create_default_server_interceptors,
    create_default_client_interceptors,
    create_auth_interceptors
)

# 健康检查
from .health_check import (
    HealthCheckService,
    HealthChecker,
    HealthStatus,
    HealthCheckResult,
    DefaultHealthChecker,
    DatabaseHealthChecker,
    RedisHealthChecker,
    CompositeHealthChecker,
    GrpcHealthServicer,
    add_health_service_to_server,
    create_default_health_service,
    create_database_health_service,
    create_redis_health_service
)

# 配置管理
from .config import (
    GrpcConfig,
    load_grpc_config_from_setting,
    get_grpc_config,
    set_grpc_config,
    update_grpc_config,
    get_default_connection_config,
    get_default_pool_config,
    get_default_client_config,
    get_default_server_config,
    is_metrics_enabled,
    get_metrics_port,
    get_registry_endpoints,
    get_registry_namespace
)

# 异常处理
from .exceptions import (
    GrpcException,
    GrpcErrorCode,
    GrpcConnectionError,
    GrpcTimeoutError,
    GrpcServiceUnavailableError,
    GrpcPoolExhaustedError,
    GrpcAuthenticationError,
    GrpcConfigurationError,
    GrpcHealthCheckError,
    GrpcSerializationError,
    handle_grpc_exception,
    handle_grpc_exception_async
)

# 导出列表
__all__ = [
    # 连接管理
    'GrpcConnection',
    'ConnectionConfig', 
    'ConnectionState',
    'ConnectionStats',
    
    # 连接池
    'GrpcConnectionPool',
    'PoolConfig',
    'PoolStats', 
    'PooledConnection',
    'MultiAddressPool',
    
    # 客户端
    'GrpcClient',
    'ClientConfig',
    'RetryConfig',
    'CallStats',
    'create_simple_client',
    'create_discovery_client',
    
    # 服务端
    'GrpcServer',
    'ServerConfig',
    'RateLimitConfig',
    'ServiceStats',
    'RateLimiter',
    'create_simple_server',
    'create_secure_server',
    'setup_signal_handlers',
    
    # 负载均衡
    'LoadBalancer',
    'LoadBalanceStrategy',
    'ServerNode',
    'RoundRobinBalancer',
    'RandomBalancer', 
    'WeightedRandomBalancer',
    'LeastConnectionBalancer',
    'ConsistentHashBalancer',
    'FastestResponseBalancer',
    'LoadBalancerFactory',
    'ConnectionAwareProxy',
    
    # 拦截器
    'BaseInterceptor',
    'InterceptorChain',
    'RequestContext',
    'AuthInterceptor',
    'LoggingInterceptor',
    'TracingInterceptor', 
    'MetricsInterceptor',
    'ExceptionInterceptor',
    'create_default_server_interceptors',
    'create_default_client_interceptors',
    'create_auth_interceptors',
    
    # 健康检查
    'HealthCheckService',
    'HealthChecker',
    'HealthStatus',
    'HealthCheckResult',
    'DefaultHealthChecker',
    'DatabaseHealthChecker',
    'RedisHealthChecker',
    'CompositeHealthChecker',
    'GrpcHealthServicer',
    'add_health_service_to_server',
    'create_default_health_service',
    'create_database_health_service',
    'create_redis_health_service',
    
    # 异常
    'GrpcException',
    'GrpcErrorCode',
    'GrpcConnectionError',
    'GrpcTimeoutError',
    'GrpcServiceUnavailableError',
    'GrpcPoolExhaustedError',
    'GrpcAuthenticationError',
    'GrpcConfigurationError',
    'GrpcHealthCheckError',
    'GrpcSerializationError',
    'handle_grpc_exception',
    'handle_grpc_exception_async',
    
    # 配置管理
    'GrpcConfig',
    'load_grpc_config_from_setting',
    'get_grpc_config',
    'set_grpc_config',
    'update_grpc_config',
    'get_default_connection_config',
    'get_default_pool_config',
    'get_default_client_config',
    'get_default_server_config',
    'is_metrics_enabled',
    'get_metrics_port',
    'get_registry_endpoints',
    'get_registry_namespace',
]
