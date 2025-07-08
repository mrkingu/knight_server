"""
安全和分布式模块基础测试

该测试文件验证安全和分布式模块的基本功能。
"""

import asyncio
import pytest
import time
import json
from unittest.mock import AsyncMock, MagicMock

# 导入安全模块
from common.security import (
    JWTAuth, TokenConfig, TokenType,
    SignatureVerifier, SignatureConfig, SignatureRequest,
    RateLimiter, RateLimitConfig, RateLimitAlgorithm, RateLimitDimension,
    CircuitBreaker, CircuitBreakerConfig, CircuitState
)

# 导入分布式模块
from common.distributed import (
    DistributedLock, LockConfig, LockType,
    SnowflakeIDGenerator, SnowflakeConfig, IDFormat,
    TransactionCoordinator, TransactionConfig, TransactionType,
    EventualConsistencyManager, ConsistencyConfig, ConsistencyLevel
)


class MockRedisManager:
    """模拟Redis管理器"""
    
    def __init__(self):
        self.data = {}
        self.expiry = {}
        self.script_results = {}
    
    async def get(self, key):
        if key in self.expiry and time.time() > self.expiry[key]:
            del self.data[key]
            del self.expiry[key]
            return None
        return self.data.get(key)
    
    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        if ex:
            self.expiry[key] = time.time() + ex
        return True
    
    async def setex(self, key, ex, value):
        self.data[key] = value
        self.expiry[key] = time.time() + ex
        return True
    
    async def delete(self, *keys):
        deleted = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                self.expiry.pop(key, None)
                deleted += 1
        return deleted
    
    async def exists(self, key):
        if key in self.expiry and time.time() > self.expiry[key]:
            del self.data[key]
            del self.expiry[key]
            return False
        return key in self.data
    
    async def incr(self, key):
        current = int(self.data.get(key, 0))
        new_value = current + 1
        self.data[key] = str(new_value)
        return new_value
    
    async def eval(self, script, num_keys, *args):
        # 简化的Lua脚本模拟
        script_hash = hash(script)
        if script_hash in self.script_results:
            return self.script_results[script_hash]
        return 1  # 默认返回成功
    
    async def keys(self, pattern):
        # 简单的模式匹配
        import fnmatch
        return [key for key in self.data.keys() if fnmatch.fnmatch(key, pattern)]
    
    async def expire(self, key, ex):
        if key in self.data:
            self.expiry[key] = time.time() + ex
            return True
        return False


class TestSecurityModules:
    """安全模块测试"""
    
    @pytest.fixture
    def mock_redis(self):
        return MockRedisManager()
    
    @pytest.mark.asyncio
    async def test_jwt_auth_basic(self, mock_redis):
        """测试JWT认证基本功能"""
        config = TokenConfig(
            secret_key="test_secret",
            access_token_expire_minutes=30,
            refresh_token_expire_days=7
        )
        
        jwt_auth = JWTAuth(config, mock_redis)
        
        # 生成令牌
        tokens = await jwt_auth.generate_tokens(
            user_id=123,
            username="test_user",
            roles=["user"],
            permissions=["read", "write"]
        )
        
        assert tokens.access_token is not None
        assert tokens.refresh_token is not None
        assert tokens.expires_in > 0
        
        # 验证访问令牌
        payload = await jwt_auth.verify_token(tokens.access_token, TokenType.ACCESS)
        assert payload.user_id == 123
        assert payload.username == "test_user"
        assert "user" in payload.roles
        
        # 刷新令牌
        new_tokens = await jwt_auth.refresh_token(tokens.refresh_token)
        assert new_tokens.access_token != tokens.access_token
    
    @pytest.mark.asyncio
    async def test_signature_verification(self, mock_redis):
        """测试签名验证功能"""
        config = SignatureConfig(
            secret_key="test_signature_secret",
            timestamp_tolerance=300,
            enable_nonce_check=True
        )
        
        verifier = SignatureVerifier(config, mock_redis)
        
        # 创建签名请求
        request = SignatureRequest(
            method="POST",
            url="/api/test",
            headers={"Content-Type": "application/json"},
            params={"param1": "value1"},
            body='{"test": "data"}',
            timestamp=int(time.time()),
            nonce="test_nonce_123"
        )
        
        # 生成签名
        signature_result = verifier.generate_signature(request)
        assert signature_result.signature is not None
        assert signature_result.timestamp > 0
        assert signature_result.nonce is not None
        
        # 验证签名
        request.signature = signature_result.signature
        is_valid = await verifier.verify_signature(request)
        assert is_valid is True
    
    @pytest.mark.asyncio
    async def test_rate_limiter(self, mock_redis):
        """测试限流器功能"""
        config = RateLimitConfig(
            default_algorithm=RateLimitAlgorithm.TOKEN_BUCKET,
            default_limit=10,
            default_window=60
        )
        
        limiter = RateLimiter(config, mock_redis)
        
        # 测试限流检查
        result = await limiter.check_limit(
            identifier="user_123",
            dimension=RateLimitDimension.USER
        )
        
        assert result.allowed is True
        assert result.remaining >= 0
        assert result.reset_time > 0
    
    @pytest.mark.asyncio
    async def test_circuit_breaker(self, mock_redis):
        """测试熔断器功能"""
        config = CircuitBreakerConfig(
            failure_threshold=0.5,
            min_request_count=5,
            timeout_duration=60
        )
        
        circuit_breaker = CircuitBreaker("test_service", config, mock_redis)
        
        # 初始状态应该是关闭的
        assert circuit_breaker.get_state() == CircuitState.CLOSED
        
        # 测试成功调用
        async def success_func():
            return "success"
        
        result = await circuit_breaker.call(success_func)
        assert result == "success"
        
        # 测试失败调用
        async def failure_func():
            raise Exception("test error")
        
        try:
            await circuit_breaker.call(failure_func)
        except Exception:
            pass
        
        # 获取指标
        metrics = circuit_breaker.get_metrics()
        assert metrics.total_calls >= 2
        
        await circuit_breaker.close()


class TestDistributedModules:
    """分布式模块测试"""
    
    @pytest.fixture
    def mock_redis(self):
        return MockRedisManager()
    
    @pytest.mark.asyncio
    async def test_distributed_lock(self, mock_redis):
        """测试分布式锁功能"""
        config = LockConfig(
            timeout=30.0,
            auto_renewal=False,  # 测试时禁用自动续期
            enable_watchdog=False  # 测试时禁用看门狗
        )
        
        lock = DistributedLock("test_resource", config, mock_redis).exclusive_lock()
        
        # 获取锁
        acquired = await lock.acquire()
        assert acquired is True
        
        # 检查锁状态
        is_locked = await lock.is_locked()
        assert is_locked is True
        
        # 释放锁
        released = await lock.release()
        assert released is True
        
        # 检查锁状态
        is_locked = await lock.is_locked()
        assert is_locked is False
    
    def test_id_generator(self):
        """测试分布式ID生成器功能"""
        config = SnowflakeConfig(
            datacenter_id=1,
            worker_id=1,
            enable_preallocation=False,  # 测试时禁用预分配
            enable_redis_coordination=False  # 测试时禁用Redis协调
        )
        
        generator = SnowflakeIDGenerator(config)
        
        # 生成ID
        id1 = generator.generate_id()
        id2 = generator.generate_id()
        
        assert id1 != id2
        assert id1 > 0
        assert id2 > 0
        assert id2 > id1  # 后生成的ID应该更大
        
        # 测试不同格式
        hex_id = generator.generate_id(IDFormat.HEXADECIMAL)
        assert isinstance(hex_id, str)
        
        base62_id = generator.generate_id(IDFormat.BASE62)
        assert isinstance(base62_id, str)
        
        # 解析ID
        metadata = generator.parse_id(id1)
        assert metadata.datacenter_id == 1
        assert metadata.worker_id == 1
        assert metadata.id_value == id1
    
    @pytest.mark.asyncio
    async def test_transaction_coordinator(self, mock_redis):
        """测试分布式事务协调器功能"""
        config = TransactionConfig(
            timeout=30.0,
            enable_persistent=False,  # 测试时禁用持久化
            enable_audit_log=True
        )
        
        coordinator = TransactionCoordinator(config, mock_redis)
        
        # 开始事务
        transaction_id = await coordinator.begin_transaction(
            TransactionType.TWO_PHASE_COMMIT,
            participant_ids=["participant1", "participant2"],
            business_data={"test": "data"}
        )
        
        assert transaction_id is not None
        
        # 获取事务上下文
        context = coordinator.get_transaction(transaction_id)
        assert context is not None
        assert context.transaction_type == TransactionType.TWO_PHASE_COMMIT
        assert len(context.participants) == 2
        
        # 获取统计信息
        stats = coordinator.get_transaction_stats()
        assert stats['total_transactions'] >= 1
        
        await coordinator.close()
    
    @pytest.mark.asyncio
    async def test_consistency_manager(self, mock_redis):
        """测试一致性管理器功能"""
        config = ConsistencyConfig(
            consistency_level=ConsistencyLevel.EVENTUAL,
            enable_background_sync=False,  # 测试时禁用后台同步
            enable_conflict_detection=True
        )
        
        manager = EventualConsistencyManager(config, mock_redis)
        
        # 存储数据
        success = await manager.put("test_key", "test_value")
        assert success is True
        
        # 获取数据
        value, version_info = await manager.get("test_key")
        assert value == "test_value"
        assert version_info is not None
        assert version_info.version > 0
        
        # 更新数据
        success = await manager.put("test_key", "updated_value", version_info.version)
        assert success is True
        
        # 获取更新后的数据
        new_value, new_version_info = await manager.get("test_key")
        assert new_value == "updated_value"
        assert new_version_info.version > version_info.version
        
        # 删除数据
        success = await manager.delete("test_key", new_version_info.version)
        assert success is True
        
        # 获取统计信息
        stats = manager.get_stats()
        assert stats['total_entries'] >= 1
        
        await manager.close()


@pytest.mark.asyncio
async def test_integration_example():
    """集成测试示例"""
    mock_redis = MockRedisManager()
    
    # JWT认证
    jwt_config = TokenConfig(secret_key="integration_test_secret")
    jwt_auth = JWTAuth(jwt_config, mock_redis)
    
    tokens = await jwt_auth.generate_tokens(
        user_id=1001,
        username="integration_user",
        roles=["admin"],
        permissions=["all"]
    )
    
    # 验证令牌
    payload = await jwt_auth.verify_token(tokens.access_token)
    assert payload.user_id == 1001
    
    # 分布式锁
    lock_config = LockConfig(timeout=10.0, auto_renewal=False, enable_watchdog=False)
    lock = DistributedLock("integration_resource", lock_config, mock_redis).exclusive_lock()
    
    async with lock:
        # 在锁保护下执行操作
        
        # 生成分布式ID
        id_config = SnowflakeConfig(datacenter_id=1, worker_id=1, enable_preallocation=False)
        id_generator = SnowflakeIDGenerator(id_config)
        
        unique_id = id_generator.generate_id()
        assert unique_id > 0
        
        # 一致性存储
        consistency_config = ConsistencyConfig(enable_background_sync=False)
        consistency_manager = EventualConsistencyManager(consistency_config, mock_redis)
        
        await consistency_manager.put(f"user_data_{unique_id}", {
            "user_id": payload.user_id,
            "username": payload.username,
            "login_time": time.time()
        })
        
        stored_data, version_info = await consistency_manager.get(f"user_data_{unique_id}")
        assert stored_data["user_id"] == payload.user_id
        
        await consistency_manager.close()


if __name__ == "__main__":
    # 运行基本功能测试
    async def run_basic_tests():
        """运行基本功能测试"""
        print("开始安全和分布式模块基础测试...")
        
        mock_redis = MockRedisManager()
        
        # 测试JWT认证
        print("测试JWT认证...")
        jwt_config = TokenConfig(secret_key="test_secret")
        jwt_auth = JWTAuth(jwt_config, mock_redis)
        
        tokens = await jwt_auth.generate_tokens(
            user_id=123,
            username="test_user",
            roles=["user"],
            permissions=["read"]
        )
        
        payload = await jwt_auth.verify_token(tokens.access_token)
        print(f"JWT认证测试通过: 用户ID={payload.user_id}, 用户名={payload.username}")
        
        # 测试分布式锁
        print("测试分布式锁...")
        lock_config = LockConfig(timeout=10.0, auto_renewal=False, enable_watchdog=False)
        lock = DistributedLock("test_resource", lock_config, mock_redis).exclusive_lock()
        
        acquired = await lock.acquire()
        if acquired:
            print("分布式锁获取成功")
            await lock.release()
            print("分布式锁释放成功")
        
        # 测试ID生成器
        print("测试分布式ID生成器...")
        id_config = SnowflakeConfig(datacenter_id=1, worker_id=1, enable_preallocation=False)
        id_generator = SnowflakeIDGenerator(id_config)
        
        id1 = id_generator.generate_id()
        id2 = id_generator.generate_id()
        print(f"生成的ID: {id1}, {id2}")
        assert id1 != id2
        
        # 测试一致性管理器
        print("测试一致性管理器...")
        consistency_config = ConsistencyConfig(enable_background_sync=False)
        consistency_manager = EventualConsistencyManager(consistency_config, mock_redis)
        
        await consistency_manager.put("test_key", "test_value")
        value, version_info = await consistency_manager.get("test_key")
        print(f"一致性存储测试通过: 值={value}, 版本={version_info.version}")
        
        await consistency_manager.close()
        
        print("所有基础测试通过！")
    
    # 运行测试
    asyncio.run(run_basic_tests())