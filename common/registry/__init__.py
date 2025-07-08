"""
服务注册发现模块

该模块为分布式游戏服务器框架提供完整的服务注册发现功能，支持多种注册中心
(etcd、consul)，提供服务自动注册、健康检查、服务发现和负载均衡等功能。

主要组件:
- BaseRegistryAdapter: 统一的注册中心接口
- ServiceRegistry: 服务注册器 (单例)
- ServiceDiscovery: 服务发现器 (单例)
- HealthMonitor: 健康监控器 (单例)  
- LoadBalancer: 负载均衡器
- RegistryFactory: 注册中心工厂 (单例)

支持的注册中心:
- etcd: 基于 aioetcd3 的异步实现
- consul: 基于 aiohttp 的 HTTP API 实现

主要特性:
- 异步支持 (async/await)
- 多种负载均衡策略
- 智能缓存和故障恢复
- 完善的健康检查
- 服务变更事件订阅
- 详细的监控统计

使用示例:
    # 创建服务信息
    service_info = ServiceInfo(
        name="logic_service",
        host="192.168.1.100", 
        port=8001,
        tags=["game", "logic"],
        metadata={"version": "1.0.0", "weight": 100}
    )
    
    # 服务注册
    registry = await ServiceRegistry.get_instance()
    await registry.register(service_info)
    
    # 服务发现
    discovery = await ServiceDiscovery.get_instance()
    services = await discovery.discover("logic_service", tags=["game"])
    
    # 负载均衡
    balancer = LoadBalancer(strategy=LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN)
    selected_service = await balancer.select(services)
"""

# 导入异常类
from .exceptions import (
    RegistryErrorCode,
    BaseRegistryException,
    RegistryConnectionError,
    RegistryTimeoutError,
    ServiceRegistrationError,
    ServiceDiscoveryError,
    HealthCheckError,
    LoadBalancerError,
    RegistryConfigError,
    handle_registry_exception,
    handle_async_registry_exception
)

# 导入基础适配器和数据结构
from .base_adapter import (
    BaseRegistryAdapter,
    ServiceInfo,
    ServiceStatus,
    WatchEvent,
    HealthChecker
)

# 导入适配器实现
from .etcd_adapter import EtcdAdapter

try:
    from .consul_adapter import ConsulAdapter
except ImportError:
    ConsulAdapter = None

# 导入核心功能模块
from .service_registry import ServiceRegistry, RegistrationResult
from .service_discovery import (
    ServiceDiscovery,
    DiscoveryFilter,
    CacheEntry
)
from .health_monitor import (
    HealthMonitor,
    HealthCheckType,
    HealthCheckConfig,
    HealthCheckResult,
    ServiceHealthState,
    HTTPHealthChecker,
    TCPHealthChecker,
    GRPCHealthChecker
)
from .load_balancer import (
    LoadBalancer,
    LoadBalanceStrategy,
    LoadBalanceContext,
    ConnectionStats,
    RequestContext,
    BaseLoadBalancer,
    RoundRobinBalancer,
    RandomBalancer,
    WeightedRoundRobinBalancer,
    LeastConnectionsBalancer,
    ConsistentHashBalancer,
    IPHashBalancer,
    ResponseTimeBalancer
)

# 导入注册中心工厂
from .registry_factory import (
    RegistryFactory,
    create_registry_adapter,
    create_registry_adapters_from_config,
    get_registry_adapter,
    validate_registry_config,
    generate_etcd_config,
    generate_consul_config,
    generate_multi_adapter_config
)

# 导出所有公共接口
__all__ = [
    # 异常类
    'RegistryErrorCode',
    'BaseRegistryException',
    'RegistryConnectionError',
    'RegistryTimeoutError',
    'ServiceRegistrationError',
    'ServiceDiscoveryError',
    'HealthCheckError',
    'LoadBalancerError',
    'RegistryConfigError',
    'handle_registry_exception',
    'handle_async_registry_exception',
    
    # 基础接口和数据结构
    'BaseRegistryAdapter',
    'ServiceInfo',
    'ServiceStatus',
    'WatchEvent',
    'HealthChecker',
    
    # 适配器实现
    'EtcdAdapter',
    'ConsulAdapter',
    
    # 核心功能模块
    'ServiceRegistry',
    'RegistrationResult',
    'ServiceDiscovery',
    'DiscoveryFilter',
    'CacheEntry',
    'HealthMonitor',
    'HealthCheckType',
    'HealthCheckConfig',
    'HealthCheckResult',
    'ServiceHealthState',
    'HTTPHealthChecker',
    'TCPHealthChecker',
    'GRPCHealthChecker',
    
    # 负载均衡
    'LoadBalancer',
    'LoadBalanceStrategy',
    'LoadBalanceContext',
    'ConnectionStats',
    'RequestContext',
    'BaseLoadBalancer',
    'RoundRobinBalancer',
    'RandomBalancer',
    'WeightedRoundRobinBalancer',
    'LeastConnectionsBalancer',
    'ConsistentHashBalancer',
    'IPHashBalancer',
    'ResponseTimeBalancer',
    
    # 注册中心工厂
    'RegistryFactory',
    'create_registry_adapter',
    'create_registry_adapters_from_config',
    'get_registry_adapter',
    'validate_registry_config',
    'generate_etcd_config',
    'generate_consul_config',
    'generate_multi_adapter_config'
]


# 便捷函数

async def create_service_registry(config: dict = None) -> ServiceRegistry:
    """
    创建服务注册器的便捷函数
    
    Args:
        config: 注册中心配置
        
    Returns:
        ServiceRegistry: 服务注册器实例
    """
    registry = await ServiceRegistry.get_instance()
    
    if config:
        # 创建适配器并添加到注册器
        adapters = create_registry_adapters_from_config(config)
        for name, adapter in adapters.items():
            registry.add_adapter(name, adapter)
    
    return registry


async def create_service_discovery(config: dict = None) -> ServiceDiscovery:
    """
    创建服务发现器的便捷函数
    
    Args:
        config: 注册中心配置
        
    Returns:
        ServiceDiscovery: 服务发现器实例
    """
    discovery = await ServiceDiscovery.get_instance()
    
    if config:
        # 创建适配器并添加到发现器
        adapters = create_registry_adapters_from_config(config)
        for name, adapter in adapters.items():
            discovery.add_adapter(name, adapter)
    
    return discovery


async def create_health_monitor(config: dict = None) -> HealthMonitor:
    """
    创建健康监控器的便捷函数
    
    Args:
        config: 注册中心配置
        
    Returns:
        HealthMonitor: 健康监控器实例
    """
    monitor = await HealthMonitor.get_instance()
    
    if config:
        # 创建适配器并添加到监控器
        adapters = create_registry_adapters_from_config(config)
        for name, adapter in adapters.items():
            monitor.add_adapter(name, adapter)
    
    return monitor


def create_load_balancer(strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN) -> LoadBalancer:
    """
    创建负载均衡器的便捷函数
    
    Args:
        strategy: 负载均衡策略
        
    Returns:
        LoadBalancer: 负载均衡器实例
    """
    return LoadBalancer(strategy)


# 版本信息
__version__ = "1.0.0"
__author__ = "Knight Server Team"
