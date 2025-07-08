# 服务注册发现模块实现文档

## 概述

本文档详细介绍了为 Knight Server 分布式游戏服务器框架实现的服务注册发现模块。该模块提供了完整的服务注册、发现、健康监控和负载均衡功能，支持 etcd 和 consul 两种注册中心。

## 🏗️ 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层 (Application)                      │
├─────────────────────────────────────────────────────────────┤
│  ServiceRegistry │ ServiceDiscovery │ HealthMonitor │ LB    │
├─────────────────────────────────────────────────────────────┤
│                 RegistryFactory (工厂模式)                   │
├─────────────────────────────────────────────────────────────┤
│         BaseRegistryAdapter (适配器接口)                     │
├─────────────────────────────────────────────────────────────┤
│   EtcdAdapter      │     ConsulAdapter     │   扩展...       │
├─────────────────────────────────────────────────────────────┤
│     etcd服务器      │      consul服务器      │               │
└─────────────────────────────────────────────────────────────┘
```

## 📁 目录结构

```
common/registry/
├── __init__.py              # 模块导出和便捷函数
├── exceptions.py            # 异常定义和处理装饰器
├── base_adapter.py          # 基础适配器接口
├── etcd_adapter.py          # etcd适配器实现
├── consul_adapter.py        # consul适配器实现
├── service_registry.py      # 服务注册器
├── service_discovery.py     # 服务发现器
├── health_monitor.py        # 健康监控器
├── load_balancer.py         # 负载均衡器
└── registry_factory.py      # 注册中心工厂
```

## 🔧 核心组件

### 1. 基础数据结构

#### ServiceInfo - 服务信息
```python
@dataclass
class ServiceInfo:
    name: str                     # 服务名称
    id: str                       # 服务唯一标识
    host: str                     # 服务主机地址
    port: int                     # 服务端口号
    tags: List[str] = None        # 服务标签
    metadata: Dict[str, Any] = None  # 服务元数据
    version: str = "1.0.0"        # 服务版本
    weight: int = 100             # 服务权重
    status: ServiceStatus = ServiceStatus.UNKNOWN
```

#### ServiceStatus - 服务状态
```python
class ServiceStatus(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"
```

### 2. 服务注册器 (ServiceRegistry)

**功能特性：**
- 单例模式管理
- 自动生成唯一服务ID
- 多注册中心同时注册
- 自动续期机制
- 优雅关闭处理

**使用示例：**
```python
# 创建服务信息
service_info = ServiceInfo(
    name="logic_service",
    host="192.168.1.100",
    port=8001,
    tags=["game", "logic"],
    metadata={"version": "1.0.0", "weight": 100}
)

# 注册服务
registry = await ServiceRegistry.get_instance()
results = await registry.register(service_info)
```

### 3. 服务发现器 (ServiceDiscovery)

**功能特性：**
- 智能缓存机制
- 多种过滤条件
- 服务变更事件订阅
- 自动缓存刷新
- 详细统计信息

**使用示例：**
```python
# 发现服务
discovery = await ServiceDiscovery.get_instance()
services = await discovery.discover(
    service_name="logic_service",
    tags=["game"],
    healthy_only=True
)
```

### 4. 健康监控器 (HealthMonitor)

**支持的检查类型：**
- HTTP/HTTPS 健康检查
- TCP 连接检查
- gRPC 健康检查
- 自定义检查逻辑

**功能特性：**
- 可配置检查间隔和超时
- 故障阈值和恢复机制
- 状态变更通知
- 健康统计信息

**使用示例：**
```python
# 配置健康检查
health_config = HealthCheckConfig(
    check_type=HealthCheckType.HTTP,
    interval=5.0,
    timeout=3.0,
    max_failures=3
)

# 开始监控
monitor = await HealthMonitor.get_instance()
await monitor.start_monitoring(service, health_config)
```

### 5. 负载均衡器 (LoadBalancer)

**支持的算法：**
- 轮询 (Round Robin)
- 随机 (Random)
- 加权轮询 (Weighted Round Robin)
- 最少连接 (Least Connections)
- 一致性哈希 (Consistent Hash)
- IP哈希 (IP Hash)
- 响应时间最优 (Response Time)

**使用示例：**
```python
# 创建负载均衡器
balancer = LoadBalancer(LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN)

# 选择服务实例
selected_service = await balancer.select(services)

# 使用请求上下文管理器
async with RequestContext(balancer, selected_service) as ctx:
    # 执行请求
    response = await make_request(selected_service)
    if not response.success:
        ctx.mark_failed()
```

### 6. 注册中心工厂 (RegistryFactory)

**功能特性：**
- 单例模式管理
- 多种注册中心支持
- 配置验证
- 模板生成

**使用示例：**
```python
# 创建适配器
factory = await RegistryFactory.get_instance()
adapter = factory.create_adapter("etcd", config, "primary")

# 从配置创建多个适配器
adapters = factory.create_from_config(registry_config)
```

## 🔌 适配器实现

### etcd 适配器 (EtcdAdapter)

**功能特性：**
- 基于 aioetcd3 的异步实现
- 服务租约和自动续期
- 服务变更监听
- 模拟模式支持（开发环境）

**配置示例：**
```python
etcd_config = {
    "endpoints": ["http://localhost:2379"],
    "timeout": 5,
    "username": None,
    "password": None
}
```

### consul 适配器 (ConsulAdapter)

**功能特性：**
- 基于 aiohttp 的 HTTP API 实现
- 健康检查配置支持
- 服务变更通知
- 标签和元数据支持

**配置示例：**
```python
consul_config = {
    "host": "localhost",
    "port": 8500,
    "token": None,
    "scheme": "http"
}
```

## ⚙️ 配置管理

### 完整配置示例
```python
REGISTRY_CONFIG = {
    "type": "etcd",  # 或 "consul"
    "etcd": {
        "endpoints": ["http://localhost:2379"],
        "timeout": 5,
        "username": None,
        "password": None
    },
    "consul": {
        "host": "localhost",
        "port": 8500,
        "token": None,
        "scheme": "http"
    },
    "service": {
        "ttl": 10,  # 服务TTL
        "health_check_interval": 5,  # 健康检查间隔
        "deregister_critical_after": "30s"  # 严重故障后注销时间
    }
}
```

### 多注册中心配置
```python
multi_config = {
    "adapters": {
        "primary": {
            "type": "etcd",
            "config": {...}
        },
        "backup": {
            "type": "consul",
            "config": {...}
        }
    }
}
```

## 🚀 快速开始

### 1. 基础使用
```python
import asyncio
from common.registry import (
    ServiceInfo, ServiceStatus,
    create_service_registry,
    create_service_discovery,
    create_load_balancer,
    LoadBalanceStrategy
)

async def main():
    # 创建配置
    config = {
        "type": "etcd",
        "config": {
            "endpoints": ["http://localhost:2379"],
            "timeout": 5
        }
    }
    
    # 创建服务注册器
    registry = await create_service_registry(config)
    
    # 创建服务信息
    service = ServiceInfo(
        name="my_service",
        host="localhost",
        port=8080,
        status=ServiceStatus.HEALTHY
    )
    
    # 注册服务
    await registry.register(service)
    
    # 创建服务发现器
    discovery = await create_service_discovery(config)
    
    # 发现服务
    services = await discovery.discover("my_service")
    
    # 负载均衡
    balancer = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN)
    selected = await balancer.select(services)
    
    print(f"选择的服务: {selected.id} -> {selected.address}")

# 运行示例
asyncio.run(main())
```

### 2. 完整流程示例
请参考 `examples/registry_example.py` 文件获取完整的使用示例。

## 🔄 扩展支持

### 添加新的注册中心适配器
1. 继承 `BaseRegistryAdapter` 基类
2. 实现所有抽象方法
3. 在工厂中注册新的适配器类型

```python
class NewRegistryAdapter(BaseRegistryAdapter):
    async def connect(self) -> None:
        # 实现连接逻辑
        pass
    
    async def register_service(self, service: ServiceInfo) -> bool:
        # 实现服务注册
        pass
    
    # ... 实现其他方法

# 注册新适配器
factory = await RegistryFactory.get_instance()
factory.register_adapter_type("new_registry", NewRegistryAdapter)
```

### 添加新的健康检查器
```python
class CustomHealthChecker(HealthChecker):
    async def check_health(self, service: ServiceInfo) -> ServiceStatus:
        # 实现自定义健康检查逻辑
        pass
    
    def supports(self, check_type: str) -> bool:
        return check_type == "custom"

# 注册健康检查器
monitor = await HealthMonitor.get_instance()
monitor.register_custom_checker(HealthCheckType.CUSTOM, CustomHealthChecker())
```

## 🛡️ 容错机制

### 1. 异常处理
- 完整的异常类层次结构
- 详细的错误信息和诊断
- 自动重试机制

### 2. 降级处理
- 注册中心不可用时的本地缓存
- 模拟模式支持（开发环境）
- 故障转移机制

### 3. 健康检查
- 多种检查方式
- 故障阈值配置
- 自动摘除和恢复

## 📊 监控和统计

### 服务发现统计
```python
stats = discovery.get_stats()
# {
#     "cache_hits": 150,
#     "cache_misses": 20,
#     "discoveries": 170,
#     "errors": 5
# }
```

### 健康监控统计
```python
stats = monitor.get_stats()
# {
#     "total_services": 10,
#     "healthy_services": 8,
#     "unhealthy_services": 2,
#     "health_rate": 0.8
# }
```

### 负载均衡统计
```python
stats = balancer.get_stats()
# {
#     "strategy": "weighted_round_robin",
#     "failed_services": 1,
#     "balancer_stats": {...}
# }
```

## 🧪 测试支持

### 模拟模式
模块支持模拟模式，无需实际的 etcd 或 consul 服务器即可进行开发和测试。

### 单元测试
模块设计考虑了可测试性，所有组件都支持依赖注入和模拟。

## 🔧 依赖要求

### 核心依赖
- Python 3.8+
- asyncio

### 可选依赖
- aioetcd3>=1.12.0 (etcd 支持)
- python-consul2>=0.1.5 (consul 支持)
- aiohttp>=3.8.0 (HTTP 健康检查)
- grpcio (gRPC 健康检查)
- loguru (日志记录)

### 备用方案
模块提供了所有可选依赖的备用实现，确保在缺少外部依赖时仍能正常工作。

## 🎯 性能优化

### 1. 缓存机制
- 智能缓存策略
- 自动缓存刷新
- 缓存失效机制

### 2. 连接管理
- 连接池支持
- 自动重连机制
- 资源清理

### 3. 异步处理
- 完全异步设计
- 非阻塞操作
- 并发控制

## 🚀 生产部署建议

### 1. 配置优化
- 合理设置 TTL 和健康检查间隔
- 配置适当的重试和超时参数
- 启用监控和日志记录

### 2. 高可用性
- 配置多个注册中心实例
- 启用健康检查和自动故障恢复
- 实施监控和告警

### 3. 性能调优
- 根据负载选择合适的负载均衡策略
- 调优缓存 TTL 和刷新策略
- 监控性能指标和资源使用

## 📚 更多资源

- 完整使用示例：`examples/registry_example.py`
- 配置模板：`setting/config.py`
- API 文档：查看各模块的详细注释
- 测试用例：运行基础功能测试验证安装

---

**注意事项：**
- 该模块为分布式游戏服务器框架设计，充分考虑了高并发和高可用性需求
- 支持水平扩展，可以轻松添加新的注册中心类型和健康检查方式
- 生产环境建议使用真实的 etcd 或 consul 集群，开发环境可使用模拟模式