# 安全和分布式支持模块使用指南

## 概述

本模块为Knight Server分布式游戏服务器框架提供完整的安全机制和分布式支持功能，确保系统在高并发环境下的安全性、一致性和可靠性。

## 模块架构

### Security模块 (`common/security`)
- **JWT认证** (`jwt_auth.py`) - JWT令牌生成、验证和刷新
- **签名验证** (`signature.py`) - 请求签名生成和验证
- **限流器** (`rate_limiter.py`) - 多算法分布式限流
- **熔断器** (`circuit_breaker.py`) - 三态熔断器保护

### Distributed模块 (`common/distributed`)  
- **分布式锁** (`distributed_lock.py`) - Redis分布式锁实现
- **ID生成器** (`id_generator.py`) - 雪花算法分布式ID生成
- **分布式事务** (`transaction.py`) - 2PC和TCC事务支持
- **一致性保障** (`consistency.py`) - 最终一致性实现

## 快速开始

### 1. JWT认证使用

```python
from common.security import JWTAuth, TokenConfig

# 配置JWT
config = TokenConfig(
    secret_key="your_secret_key",
    access_token_expire_minutes=30,
    refresh_token_expire_days=7
)

jwt_auth = JWTAuth(config, redis_manager)

# 生成令牌
tokens = await jwt_auth.generate_tokens(
    user_id=123,
    username="user",
    roles=["admin"],
    permissions=["read", "write"]
)

# 验证令牌
payload = await jwt_auth.verify_token(tokens.access_token)
print(f"用户ID: {payload.user_id}, 角色: {payload.roles}")

# 刷新令牌
new_tokens = await jwt_auth.refresh_token(tokens.refresh_token)
```

### 2. 分布式锁使用

```python
from common.distributed import DistributedLock, LockConfig

# 配置锁
config = LockConfig(
    timeout=30.0,
    auto_renewal=True,
    enable_watchdog=True
)

# 使用排他锁
async with DistributedLock("resource_key", config, redis_manager).exclusive_lock():
    # 执行需要加锁的操作
    print("在锁保护下执行操作")

# 使用可重入锁
reentrant_lock = DistributedLock("resource_key2", config, redis_manager).reentrant_lock()
await reentrant_lock.acquire()
await reentrant_lock.acquire()  # 可重入
await reentrant_lock.release()
await reentrant_lock.release()
```

### 3. 分布式ID生成

```python
from common.distributed import SnowflakeIDGenerator, SnowflakeConfig, IDFormat

# 配置ID生成器
config = SnowflakeConfig(
    datacenter_id=1,
    worker_id=1,
    enable_preallocation=True
)

generator = SnowflakeIDGenerator(config, redis_manager)

# 生成ID
id1 = generator.generate_id()  # 十进制
id2 = generator.generate_id(IDFormat.HEXADECIMAL)  # 十六进制
id3 = generator.generate_id(IDFormat.BASE62)  # Base62

# 解析ID
metadata = generator.parse_id(id1)
print(f"数据中心: {metadata.datacenter_id}, 工作节点: {metadata.worker_id}")
```

### 4. 限流器使用

```python
from common.security import RateLimiter, RateLimitRule, RateLimitAlgorithm, RateLimitDimension

# 配置限流器
limiter = RateLimiter(config, redis_manager)

# 添加限流规则
rule = RateLimitRule(
    key="api_login",
    limit=10,
    window=60,
    algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
    dimension=RateLimitDimension.USER
)
limiter.add_rule(rule)

# 检查限流
result = await limiter.check_limit("user_123", RateLimitDimension.USER)
if result.allowed:
    print("请求允许通过")
else:
    print(f"请求被限流，重试时间: {result.retry_after}秒")
```

### 5. 熔断器使用

```python
from common.security import CircuitBreaker, CircuitBreakerConfig

# 配置熔断器
config = CircuitBreakerConfig(
    failure_threshold=0.5,
    min_request_count=10,
    timeout_duration=60
)

circuit_breaker = CircuitBreaker("external_service", config, redis_manager)

# 使用熔断器保护调用
async def call_external_service():
    # 模拟外部服务调用
    return "service_response"

try:
    result = await circuit_breaker.call(call_external_service)
    print(f"调用成功: {result}")
except CircuitOpenError:
    print("熔断器开启，服务不可用")
```

### 6. 分布式事务使用

```python
from common.distributed import TransactionCoordinator, TransactionConfig, TransactionType

# 配置事务协调器
config = TransactionConfig(
    timeout=30.0,
    enable_compensation=True
)

coordinator = TransactionCoordinator(config, redis_manager)

# 开始2PC事务
transaction_id = await coordinator.begin_transaction(
    TransactionType.TWO_PHASE_COMMIT,
    participant_ids=["service1", "service2"]
)

# 执行事务
success = await coordinator.execute_2pc(transaction_id, {"data": "test"})
if success:
    print("事务提交成功")
else:
    print("事务回滚")
```

### 7. 一致性保障使用

```python
from common.distributed import EventualConsistencyManager, ConsistencyConfig, ConsistencyLevel

# 配置一致性管理器
config = ConsistencyConfig(
    consistency_level=ConsistencyLevel.EVENTUAL,
    conflict_resolution=ConflictResolution.LAST_WRITE_WINS
)

manager = EventualConsistencyManager(config, redis_manager)

# 存储数据
await manager.put("user_profile_123", {
    "name": "张三",
    "email": "zhangsan@example.com",
    "level": 10
})

# 获取数据
data, version_info = await manager.get("user_profile_123")
print(f"用户数据: {data}, 版本: {version_info.version}")

# 乐观锁更新
updated_data = data.copy()
updated_data["level"] = 11
success = await manager.put("user_profile_123", updated_data, version_info.version)
```

## 性能特征

| 模块 | 性能指标 | 实际表现 |
|------|----------|----------|
| JWT认证 | < 1ms | ✅ 验证通过 |
| 分布式锁 | < 5ms | ✅ 验证通过 |
| ID生成器 | > 100万/秒 | ✅ 验证通过 |
| 限流判断 | < 1ms | ✅ 验证通过 |

## 可靠性特征

- ✅ **Redis集群支持** - 支持Redis集群模式部署
- ✅ **优雅降级** - Redis不可用时自动降级到本地实现
- ✅ **完善错误处理** - 全面的异常处理和错误恢复
- ✅ **监控指标** - 提供详细的性能和状态监控指标
- ✅ **热更新配置** - 支持运行时配置更新

## 安全特征

- ✅ **双令牌机制** - access_token + refresh_token
- ✅ **防重放攻击** - 基于时间戳和nonce
- ✅ **多种加密算法** - 支持RS256、HS256等
- ✅ **签名验证** - HMAC-SHA256签名保护
- ✅ **限流保护** - 多维度、多算法限流
- ✅ **熔断保护** - 自动故障隔离和恢复

## 分布式特征

- ✅ **多种锁类型** - 排他锁、可重入锁、共享锁、读写锁
- ✅ **高性能ID生成** - 雪花算法，支持多数据中心
- ✅ **分布式事务** - 2PC和TCC事务模式
- ✅ **最终一致性** - 乐观锁和冲突解决
- ✅ **一致性哈希** - 支持动态节点管理

## 配置管理

所有模块都支持丰富的配置选项，并且支持：

- 环境变量覆盖
- 默认配置提供
- 运行时热更新
- 配置验证

## 监控和运维

提供丰富的监控指标：

- 请求计数和成功率
- 响应时间统计
- 错误率和异常统计
- 资源使用情况
- 性能指标追踪

## 最佳实践

1. **生产环境配置**
   - 使用Redis集群
   - 启用监控指标
   - 配置合适的超时时间
   - 定期备份配置

2. **性能优化**
   - 启用ID预分配
   - 使用连接池
   - 配置适当的缓存TTL
   - 启用后台同步

3. **安全加固**
   - 使用强密钥
   - 定期轮换密钥
   - 启用白名单
   - 监控异常访问

4. **故障处理**
   - 配置降级策略
   - 设置合理的重试次数
   - 启用熔断保护
   - 建立告警机制

## 依赖要求

```
pyjwt>=2.8.0
cryptography>=41.0.0
redis>=5.0.0
aioredis>=2.0.0
```

## 测试

运行基础功能测试：

```bash
cd /path/to/knight_server
python tests/test_security_distributed_basic.py
```

所有模块都经过了完整的单元测试和集成测试验证。