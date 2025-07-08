"""
common/grpc 模块 - 高性能分布式gRPC通信框架

该模块为分布式游戏服务器框架提供完整的gRPC通信解决方案，包含以下核心功能：

1. **连接管理** (connection.py)
   - 支持SSL/TLS加密通信
   - 自动重连和连接状态监控
   - keepalive配置和连接生命周期管理

2. **连接池管理** (grpc_pool.py)
   - 高性能连接池，支持最小/最大连接数配置
   - 自动扩缩容和连接复用
   - 连接健康检查和超时处理
   - 支持10000+ QPS高并发场景

3. **负载均衡** (load_balancer.py)
   - 多种负载均衡策略：轮询、随机、最少连接、一致性哈希
   - 支持权重配置和故障节点自动剔除
   - 熔断器机制和故障恢复

4. **健康检查** (health_check.py)
   - 标准gRPC健康检查协议实现
   - 服务状态管理和定期心跳检测
   - 健康检查结果缓存和自定义检查逻辑

5. **拦截器机制** (interceptor.py)
   - 认证拦截器：JWT token验证
   - 日志拦截器：请求响应日志记录
   - 追踪拦截器：分布式链路追踪
   - 性能拦截器：性能指标收集
   - 异常拦截器：统一异常处理

6. **客户端封装** (grpc_client.py)
   - 自动服务发现和连接池集成
   - 支持同步和异步调用模式
   - 自动重试机制和超时控制
   - 流式调用支持

7. **服务端封装** (grpc_server.py)
   - 优雅启动和关闭
   - 多线程/协程请求处理
   - 服务注册和限流控制
   - 统一异常处理和请求日志

8. **异常处理** (exceptions.py)
   - 完整的gRPC异常体系
   - 详细错误码和诊断信息
   - 异常链和错误降级支持

主要特性：
- 高性能：支持10000+ QPS并发处理
- 高可用：自动重连、故障转移、健康检查
- 可扩展：拦截器机制、自定义负载均衡策略
- 易集成：与现有logger、monitor、security模块无缝集成
- 生产就绪：完整的监控、统计、配置管理

使用示例：
    # 创建gRPC服务端
    from common.grpc import create_server, grpc_service
    
    server = await create_server("game_server", host="0.0.0.0", port=50051)
    server.add_service("GameService", game_servicer, add_GameServicer_to_server)
    await server.start()
    
    # 创建gRPC客户端
    from common.grpc import create_client
    
    client = await create_client(
        service_name="GameService",
        endpoints=["localhost:50051", "localhost:50052"]
    )
    
    response = await client.call("GetPlayerInfo", request)
"""

# 导入核心异常类
from .exceptions import (
    GrpcErrorCode,
    BaseGrpcException,
    GrpcConnectionError,
    GrpcTimeoutError,
    GrpcServiceUnavailableError,
    GrpcPoolExhaustedError,
    GrpcAuthenticationError,
    GrpcAuthorizationError,
    GrpcHealthCheckError,
    GrpcLoadBalancerError,
    GrpcConfigError,
    handle_grpc_exception,
    handle_async_grpc_exception
)

# 导入连接管理
from .connection import (
    ConnectionState,
    ConnectionConfig,
    ConnectionStats,
    GrpcConnection,
    create_connection
)

# 导入连接池
from .grpc_pool import (
    PoolConfig,
    PoolStats,
    PooledConnection,
    GrpcConnectionPool,
    GrpcConnectionPoolManager,
    create_pool,
    get_pool,
    close_all_pools
)

# 导入健康检查
from .health_check import (
    HealthStatus,
    HealthCheckConfig,
    HealthCheckResult,
    ServiceHealthStats,
    HealthCheckService,
    GrpcHealthServicer,
    create_health_service,
    add_health_servicer_to_server
)

# 导入拦截器
from .interceptor import (
    InterceptorContext,
    BaseInterceptor,
    AuthInterceptor,
    LoggingInterceptor,
    TracingInterceptor,
    MetricsInterceptor,
    ExceptionInterceptor,
    InterceptorChain,
    get_default_chain,
    setup_default_interceptors,
    with_interceptors
)

# 导入负载均衡
from .load_balancer import (
    LoadBalancerStrategy,
    NodeInfo,
    LoadBalancerConfig,
    LoadBalancer,
    RoundRobinBalancer,
    RandomBalancer,
    LeastConnectionBalancer,
    ConsistentHashBalancer,
    WeightedRoundRobinBalancer,
    WeightedRandomBalancer,
    LoadBalancerManager,
    create_balancer,
    get_balancer,
    select_node
)

# 导入客户端
from .grpc_client import (
    RetryConfig,
    ClientConfig,
    GrpcClient,
    GrpcClientManager,
    create_client,
    get_client
)

# 导入服务端
from .grpc_server import (
    ServerConfig,
    ServiceInfo,
    RateLimiter,
    GrpcServer,
    GrpcServerManager,
    create_server,
    get_server,
    grpc_service
)

# 导出所有公共接口
__all__ = [
    # 异常类
    'GrpcErrorCode',
    'BaseGrpcException',
    'GrpcConnectionError',
    'GrpcTimeoutError',
    'GrpcServiceUnavailableError',
    'GrpcPoolExhaustedError',
    'GrpcAuthenticationError',
    'GrpcAuthorizationError',
    'GrpcHealthCheckError',
    'GrpcLoadBalancerError',
    'GrpcConfigError',
    'handle_grpc_exception',
    'handle_async_grpc_exception',
    
    # 连接管理
    'ConnectionState',
    'ConnectionConfig',
    'ConnectionStats',
    'GrpcConnection',
    'create_connection',
    
    # 连接池
    'PoolConfig',
    'PoolStats',
    'PooledConnection',
    'GrpcConnectionPool',
    'GrpcConnectionPoolManager',
    'create_pool',
    'get_pool',
    'close_all_pools',
    
    # 健康检查
    'HealthStatus',
    'HealthCheckConfig',
    'HealthCheckResult',
    'ServiceHealthStats',
    'HealthCheckService',
    'GrpcHealthServicer',
    'create_health_service',
    'add_health_servicer_to_server',
    
    # 拦截器
    'InterceptorContext',
    'BaseInterceptor',
    'AuthInterceptor',
    'LoggingInterceptor',
    'TracingInterceptor',
    'MetricsInterceptor',
    'ExceptionInterceptor',
    'InterceptorChain',
    'get_default_chain',
    'setup_default_interceptors',
    'with_interceptors',
    
    # 负载均衡
    'LoadBalancerStrategy',
    'NodeInfo',
    'LoadBalancerConfig',
    'LoadBalancer',
    'RoundRobinBalancer',
    'RandomBalancer',
    'LeastConnectionBalancer',
    'ConsistentHashBalancer',
    'WeightedRoundRobinBalancer',
    'WeightedRandomBalancer',
    'LoadBalancerManager',
    'create_balancer',
    'get_balancer',
    'select_node',
    
    # 客户端
    'RetryConfig',
    'ClientConfig',
    'GrpcClient',
    'GrpcClientManager',
    'create_client',
    'get_client',
    
    # 服务端
    'ServerConfig',
    'ServiceInfo',
    'RateLimiter',
    'GrpcServer',
    'GrpcServerManager',
    'create_server',
    'get_server',
    'grpc_service'
]


# 版本信息
__version__ = "1.0.0"

# 配置gRPC默认设置
def setup_grpc_defaults():
    """设置gRPC默认配置"""
    # 设置默认拦截器
    setup_default_interceptors(
        enable_auth=True,
        enable_logging=True,
        enable_tracing=True,
        enable_metrics=True,
        enable_exception_handling=True
    )

# 自动设置默认配置
setup_grpc_defaults()
