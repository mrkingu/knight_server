"""
Redis连接池管理器

该模块提供高性能、高可用的Redis连接池管理，包含以下功能：
- 连接池实现和管理
- 多Redis实例分片支持
- 连接健康检查和自动重连
- 缓存防护机制（雪崩、穿透、击穿）
- 分布式锁实现
- 发布订阅支持
"""

import asyncio
import hashlib
import json
import random
import time
import zlib
from typing import Any, Dict, List, Optional, Union, Callable, Set
from dataclasses import dataclass
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor

from common.logger import logger
from common.utils.singleton import Singleton

# Mock config loader for testing
def load_config():
    """Mock config loader"""
    return {
        'redis': {
            'default': {
                'host': 'localhost',
                'port': 6379,
                'db': 0,
                'password': None,
                'max_connections': 100,
                'socket_timeout': 5.0,
                'socket_connect_timeout': 5.0,
                'retry_on_timeout': True,
            },
            'buckets': {
                'user_data': {
                    'db': 0,
                    'expire_time': 86400,
                },
                'game_data': {
                    'db': 1,
                    'expire_time': 3600,
                },
            }
        }
    }


class RedisError(Exception):
    """Redis相关异常"""
    pass


class ConnectionPoolError(RedisError):
    """连接池相关异常"""
    pass


class LockError(RedisError):
    """分布式锁相关异常"""
    pass


@dataclass
class RedisConfig:
    """Redis配置"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 100
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 5.0
    retry_on_timeout: bool = True
    decode_responses: bool = True
    encoding: str = "utf-8"
    
    # 健康检查配置
    health_check_interval: float = 30.0
    
    # 分片配置
    bucket_count: int = 16
    hash_method: str = "crc32"


@dataclass
class CacheStrategy:
    """缓存策略配置"""
    ttl: int = 3600  # 默认过期时间
    max_ttl: int = 86400  # 最大过期时间
    null_cache_ttl: int = 60  # 空值缓存时间
    
    # 防雪崩配置
    enable_random_ttl: bool = True
    ttl_variance: float = 0.2  # TTL随机偏差
    
    # 防穿透配置
    enable_null_cache: bool = True
    
    # 防击穿配置
    enable_lock: bool = True
    lock_timeout: int = 30


class MockRedisPool:
    """Mock Redis连接池实现（用于无Redis依赖的环境）"""
    
    def __init__(self, config: RedisConfig):
        self.config = config
        self._storage: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        
    async def execute(self, command: str, *args, **kwargs) -> Any:
        """执行Redis命令的模拟实现"""
        async with self._lock:
            return await self._execute_command(command, *args)
    
    async def _execute_command(self, command: str, *args) -> Any:
        """模拟执行Redis命令"""
        command = command.upper()
        current_time = time.time()
        
        # 清理过期键
        expired_keys = [k for k, exp_time in self._expiry.items() if exp_time <= current_time]
        for key in expired_keys:
            self._storage.pop(key, None)
            self._expiry.pop(key, None)
        
        if command == "GET":
            key = args[0]
            return self._storage.get(key)
            
        elif command == "SET":
            key, value = args[0], args[1]
            self._storage[key] = value
            return "OK"
            
        elif command == "SETEX":
            key, ttl, value = args[0], args[1], args[2]
            self._storage[key] = value
            self._expiry[key] = current_time + ttl
            return "OK"
            
        elif command == "DEL":
            deleted = 0
            for key in args:
                if key in self._storage:
                    del self._storage[key]
                    self._expiry.pop(key, None)
                    deleted += 1
            return deleted
            
        elif command == "EXISTS":
            return int(args[0] in self._storage)
            
        elif command == "TTL":
            key = args[0]
            if key not in self._storage:
                return -2
            if key not in self._expiry:
                return -1
            remaining = self._expiry[key] - current_time
            return int(remaining) if remaining > 0 else -2
            
        elif command == "MGET":
            return [self._storage.get(key) for key in args]
            
        elif command == "MSET":
            for i in range(0, len(args), 2):
                self._storage[args[i]] = args[i + 1]
            return "OK"
            
        elif command == "PING":
            return "PONG"
            
        else:
            logger.warning(f"Mock Redis: 不支持的命令 {command}")
            return None


class RedisConnectionPool:
    """Redis连接池"""
    
    def __init__(self, config: RedisConfig):
        self.config = config
        self._pool = None
        self._redis_module = None
        self._lock = asyncio.Lock()
        self._is_mock = False
        
        # 尝试导入Redis模块
        try:
            import redis.asyncio as redis_async
            self._redis_module = redis_async
            logger.info(f"使用真实Redis连接池: {config.host}:{config.port}")
        except ImportError:
            logger.warning("Redis模块未安装，使用Mock实现")
            self._is_mock = True
    
    async def initialize(self):
        """初始化连接池"""
        async with self._lock:
            if self._pool is not None:
                return
                
            if self._is_mock:
                self._pool = MockRedisPool(self.config)
            else:
                self._pool = self._redis_module.ConnectionPool(
                    host=self.config.host,
                    port=self.config.port,
                    db=self.config.db,
                    password=self.config.password,
                    max_connections=self.config.max_connections,
                    socket_timeout=self.config.socket_timeout,
                    socket_connect_timeout=self.config.socket_connect_timeout,
                    retry_on_timeout=self.config.retry_on_timeout,
                    decode_responses=self.config.decode_responses,
                    encoding=self.config.encoding
                )
            
            logger.info(f"Redis连接池初始化完成: {self.config.host}:{self.config.port}")
    
    async def get_connection(self):
        """获取Redis连接"""
        if self._pool is None:
            await self.initialize()
        
        if self._is_mock:
            return self._pool
        else:
            return self._redis_module.Redis(connection_pool=self._pool)
    
    @asynccontextmanager
    async def acquire(self):
        """获取连接的上下文管理器"""
        conn = await self.get_connection()
        try:
            yield conn
        finally:
            if not self._is_mock and hasattr(conn, 'close'):
                await conn.close()
    
    async def close(self):
        """关闭连接池"""
        if self._pool and not self._is_mock:
            await self._pool.disconnect()
        self._pool = None
        logger.info("Redis连接池已关闭")
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            async with self.acquire() as conn:
                if self._is_mock:
                    result = await conn.execute("PING")
                else:
                    result = await conn.ping()
                return result == "PONG" or result is True
        except Exception as e:
            logger.error(f"Redis健康检查失败: {e}")
            return False


class BloomFilter:
    """布隆过滤器（简单实现）"""
    
    def __init__(self, expected_items: int = 1000000, false_positive_rate: float = 0.001):
        """
        初始化布隆过滤器
        
        Args:
            expected_items: 预期项目数量
            false_positive_rate: 误判率
        """
        self.expected_items = expected_items
        self.false_positive_rate = false_positive_rate
        
        # 计算最优参数
        self.bit_size = int(-expected_items * (self.false_positive_rate ** 0.5) / 0.693)
        self.hash_count = int(self.bit_size * 0.693 / expected_items)
        
        # 使用字典模拟位数组
        self._bits: Set[int] = set()
        
        logger.info(f"布隆过滤器初始化: bits={self.bit_size}, hashes={self.hash_count}")
    
    def add(self, item: str):
        """添加项目到过滤器"""
        for i in range(self.hash_count):
            hash_value = self._hash(item, i) % self.bit_size
            self._bits.add(hash_value)
    
    def contains(self, item: str) -> bool:
        """检查项目是否可能存在"""
        for i in range(self.hash_count):
            hash_value = self._hash(item, i) % self.bit_size
            if hash_value not in self._bits:
                return False
        return True
    
    def _hash(self, item: str, seed: int) -> int:
        """哈希函数"""
        return hash(f"{item}:{seed}") & 0x7FFFFFFF


class DistributedLock:
    """分布式锁"""
    
    def __init__(self, redis_pool: RedisConnectionPool, key: str, 
                 timeout: int = 30, retry_interval: float = 0.1, max_retries: int = 100):
        """
        初始化分布式锁
        
        Args:
            redis_pool: Redis连接池
            key: 锁键名
            timeout: 锁超时时间
            retry_interval: 重试间隔
            max_retries: 最大重试次数
        """
        self.redis_pool = redis_pool
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        self.identifier = f"{time.time()}:{random.randint(1000, 9999)}"
        self._acquired = False
    
    async def acquire(self) -> bool:
        """获取锁"""
        for attempt in range(self.max_retries):
            try:
                async with self.redis_pool.acquire() as conn:
                    if self.redis_pool._is_mock:
                        # Mock实现
                        result = await conn.execute("SET", self.key, self.identifier, "NX", "EX", self.timeout)
                        if result == "OK":
                            self._acquired = True
                            return True
                    else:
                        # 真实Redis实现
                        result = await conn.set(self.key, self.identifier, nx=True, ex=self.timeout)
                        if result:
                            self._acquired = True
                            return True
                
                await asyncio.sleep(self.retry_interval)
                
            except Exception as e:
                logger.error(f"获取分布式锁失败: {e}")
                await asyncio.sleep(self.retry_interval)
        
        return False
    
    async def release(self) -> bool:
        """释放锁"""
        if not self._acquired:
            return True
        
        try:
            async with self.redis_pool.acquire() as conn:
                if self.redis_pool._is_mock:
                    # Mock实现：检查标识符然后删除
                    current = await conn.execute("GET", self.key)
                    if current == self.identifier:
                        await conn.execute("DEL", self.key)
                        self._acquired = False
                        return True
                else:
                    # 使用Lua脚本保证原子性
                    lua_script = """
                    if redis.call("GET", KEYS[1]) == ARGV[1] then
                        return redis.call("DEL", KEYS[1])
                    else
                        return 0
                    end
                    """
                    result = await conn.eval(lua_script, 1, self.key, self.identifier)
                    if result:
                        self._acquired = False
                        return True
                        
        except Exception as e:
            logger.error(f"释放分布式锁失败: {e}")
        
        return False
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        success = await self.acquire()
        if not success:
            raise LockError(f"无法获取锁: {self.key}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.release()


class RedisManager(Singleton):
    """Redis管理器"""
    
    def __init__(self):
        """初始化Redis管理器"""
        if hasattr(self, '_initialized'):
            return
        
        self._pools: Dict[str, RedisConnectionPool] = {}
        self._bloom_filter: Optional[BloomFilter] = None
        self._cache_strategy = CacheStrategy()
        self._initialized = True
        
        logger.info("Redis管理器初始化完成")
    
    async def initialize(self, config_data: Optional[Dict] = None):
        """
        初始化Redis连接池
        
        Args:
            config_data: 配置数据，如果为None则从配置文件加载
        """
        if config_data is None:
            config = load_config()
            redis_config = config.get('redis', {})
        else:
            redis_config = config_data
        
        # 初始化默认连接池
        default_config = RedisConfig(**redis_config.get('default', {}))
        self._pools['default'] = RedisConnectionPool(default_config)
        await self._pools['default'].initialize()
        
        # 初始化分片连接池
        buckets_config = redis_config.get('buckets', {})
        for bucket_name, bucket_conf in buckets_config.items():
            # 只使用RedisConfig支持的字段
            valid_config = {}
            for key, value in bucket_conf.items():
                if key in {'host', 'port', 'db', 'password', 'max_connections', 
                          'socket_timeout', 'socket_connect_timeout', 'retry_on_timeout',
                          'decode_responses', 'encoding', 'health_check_interval',
                          'bucket_count', 'hash_method'}:
                    valid_config[key] = value
            
            pool_config = RedisConfig(**{**redis_config.get('default', {}), **valid_config})
            self._pools[bucket_name] = RedisConnectionPool(pool_config)
            await self._pools[bucket_name].initialize()
        
        # 初始化布隆过滤器
        bloom_config = redis_config.get('bloom_filter', {})
        self._bloom_filter = BloomFilter(**bloom_config)
        
        # 更新缓存策略
        cache_config = redis_config.get('cache_strategy', {})
        self._cache_strategy = CacheStrategy(**cache_config)
        
        logger.info(f"Redis管理器初始化完成，共 {len(self._pools)} 个连接池")
    
    def _get_bucket_name(self, key: str) -> str:
        """根据键名获取分片桶名"""
        if len(self._pools) <= 1:
            return 'default'
        
        # 使用CRC32哈希算法
        hash_value = zlib.crc32(key.encode()) & 0xffffffff
        bucket_index = hash_value % len(self._pools)
        bucket_names = list(self._pools.keys())
        return bucket_names[bucket_index]
    
    def _get_pool(self, key: str = None, pool_name: str = None) -> RedisConnectionPool:
        """获取连接池"""
        if pool_name:
            if pool_name not in self._pools:
                raise ConnectionPoolError(f"连接池 {pool_name} 不存在")
            return self._pools[pool_name]
        
        if key:
            bucket_name = self._get_bucket_name(key)
            return self._pools.get(bucket_name, self._pools['default'])
        
        return self._pools['default']
    
    def _add_random_ttl(self, ttl: int) -> int:
        """添加随机TTL偏差（防雪崩）"""
        if not self._cache_strategy.enable_random_ttl:
            return ttl
        
        variance = int(ttl * self._cache_strategy.ttl_variance)
        random_offset = random.randint(-variance, variance)
        return max(ttl + random_offset, 1)
    
    async def get(self, key: str, pool_name: str = None) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 键名
            pool_name: 连接池名称
            
        Returns:
            缓存值或None
        """
        pool = self._get_pool(key, pool_name)
        
        try:
            async with pool.acquire() as conn:
                if pool._is_mock:
                    result = await conn.execute("GET", key)
                else:
                    result = await conn.get(key)
                
                if result is not None:
                    # 尝试JSON反序列化
                    try:
                        return json.loads(result)
                    except (json.JSONDecodeError, TypeError):
                        return result
                
                return None
                
        except Exception as e:
            logger.error(f"Redis GET 操作失败 {key}: {e}")
            return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None, pool_name: str = None) -> bool:
        """
        设置缓存值
        
        Args:
            key: 键名
            value: 值
            ttl: 过期时间（秒）
            pool_name: 连接池名称
            
        Returns:
            是否设置成功
        """
        pool = self._get_pool(key, pool_name)
        
        # 序列化值
        if isinstance(value, (dict, list, tuple)):
            serialized_value = json.dumps(value, ensure_ascii=False)
        else:
            serialized_value = str(value)
        
        # 计算TTL
        if ttl is None:
            ttl = self._cache_strategy.ttl
        ttl = min(ttl, self._cache_strategy.max_ttl)
        ttl = self._add_random_ttl(ttl)
        
        try:
            async with pool.acquire() as conn:
                if pool._is_mock:
                    result = await conn.execute("SETEX", key, ttl, serialized_value)
                    success = result == "OK"
                else:
                    result = await conn.setex(key, ttl, serialized_value)
                    success = result is True
                
                if success:
                    logger.debug(f"Redis SET 成功: {key} (TTL: {ttl})")
                
                return success
                
        except Exception as e:
            logger.error(f"Redis SET 操作失败 {key}: {e}")
            return False
    
    async def delete(self, *keys: str, pool_name: str = None) -> int:
        """
        删除缓存键
        
        Args:
            keys: 键名列表
            pool_name: 连接池名称
            
        Returns:
            删除的键数量
        """
        if not keys:
            return 0
        
        # 按分片分组
        pools_keys = {}
        for key in keys:
            if pool_name:
                pool = self._pools[pool_name]
            else:
                pool = self._get_pool(key)
            
            pool_id = id(pool)
            if pool_id not in pools_keys:
                pools_keys[pool_id] = (pool, [])
            pools_keys[pool_id][1].append(key)
        
        total_deleted = 0
        
        for pool, key_list in pools_keys.values():
            try:
                async with pool.acquire() as conn:
                    if pool._is_mock:
                        deleted = await conn.execute("DEL", *key_list)
                    else:
                        deleted = await conn.delete(*key_list)
                    
                    total_deleted += deleted
                    logger.debug(f"Redis DEL 成功: {key_list} (删除 {deleted} 个)")
                    
            except Exception as e:
                logger.error(f"Redis DEL 操作失败 {key_list}: {e}")
        
        return total_deleted
    
    async def exists(self, key: str, pool_name: str = None) -> bool:
        """
        检查键是否存在
        
        Args:
            key: 键名
            pool_name: 连接池名称
            
        Returns:
            是否存在
        """
        pool = self._get_pool(key, pool_name)
        
        try:
            async with pool.acquire() as conn:
                if pool._is_mock:
                    result = await conn.execute("EXISTS", key)
                else:
                    result = await conn.exists(key)
                
                return bool(result)
                
        except Exception as e:
            logger.error(f"Redis EXISTS 操作失败 {key}: {e}")
            return False
    
    async def mget(self, keys: List[str], pool_name: str = None) -> List[Optional[Any]]:
        """
        批量获取缓存值
        
        Args:
            keys: 键名列表
            pool_name: 连接池名称
            
        Returns:
            值列表
        """
        if not keys:
            return []
        
        if pool_name:
            # 使用指定连接池
            pool = self._pools[pool_name]
            async with pool.acquire() as conn:
                if pool._is_mock:
                    results = await conn.execute("MGET", *keys)
                else:
                    results = await conn.mget(keys)
                
                # 反序列化结果
                return [self._deserialize_value(result) for result in results]
        else:
            # 按分片分组处理
            pools_keys = {}
            key_pool_map = {}
            
            for i, key in enumerate(keys):
                pool = self._get_pool(key)
                pool_id = id(pool)
                
                if pool_id not in pools_keys:
                    pools_keys[pool_id] = (pool, [], [])
                
                pools_keys[pool_id][1].append(key)
                pools_keys[pool_id][2].append(i)
                key_pool_map[i] = pool_id
            
            # 并发获取各分片的值
            results = [None] * len(keys)
            
            async def get_from_pool(pool, key_list, indices):
                try:
                    async with pool.acquire() as conn:
                        if pool._is_mock:
                            values = await conn.execute("MGET", *key_list)
                        else:
                            values = await conn.mget(key_list)
                        
                        for i, value in enumerate(values):
                            results[indices[i]] = self._deserialize_value(value)
                except Exception as e:
                    logger.error(f"Redis MGET 批量操作失败: {e}")
            
            tasks = [
                get_from_pool(pool, key_list, indices)
                for pool, key_list, indices in pools_keys.values()
            ]
            
            await asyncio.gather(*tasks, return_exceptions=True)
            return results
    
    async def mset(self, mapping: Dict[str, Any], ttl: Optional[int] = None, pool_name: str = None) -> bool:
        """
        批量设置缓存值
        
        Args:
            mapping: 键值映射
            ttl: 过期时间（秒）
            pool_name: 连接池名称
            
        Returns:
            是否全部设置成功
        """
        if not mapping:
            return True
        
        if pool_name:
            # 使用指定连接池
            pool = self._pools[pool_name]
            serialized_mapping = {}
            for key, value in mapping.items():
                serialized_mapping[key] = self._serialize_value(value)
            
            async with pool.acquire() as conn:
                if pool._is_mock:
                    flat_data = []
                    for key, value in serialized_mapping.items():
                        flat_data.extend([key, value])
                    result = await conn.execute("MSET", *flat_data)
                    success = result == "OK"
                else:
                    result = await conn.mset(serialized_mapping)
                    success = result is True
                
                # 设置TTL
                if success and ttl:
                    for key in mapping.keys():
                        final_ttl = self._add_random_ttl(ttl)
                        if pool._is_mock:
                            await conn.execute("EXPIRE", key, final_ttl)
                        else:
                            await conn.expire(key, final_ttl)
                
                return success
        else:
            # 按分片分组处理
            pools_mapping = {}
            
            for key, value in mapping.items():
                pool = self._get_pool(key)
                pool_id = id(pool)
                
                if pool_id not in pools_mapping:
                    pools_mapping[pool_id] = (pool, {})
                
                pools_mapping[pool_id][1][key] = value
            
            # 并发设置各分片的值
            async def set_to_pool(pool, key_value_map):
                try:
                    serialized_mapping = {}
                    for key, value in key_value_map.items():
                        serialized_mapping[key] = self._serialize_value(value)
                    
                    async with pool.acquire() as conn:
                        if pool._is_mock:
                            flat_data = []
                            for key, value in serialized_mapping.items():
                                flat_data.extend([key, value])
                            result = await conn.execute("MSET", *flat_data)
                            success = result == "OK"
                        else:
                            result = await conn.mset(serialized_mapping)
                            success = result is True
                        
                        # 设置TTL
                        if success and ttl:
                            for key in key_value_map.keys():
                                final_ttl = self._add_random_ttl(ttl)
                                if pool._is_mock:
                                    await conn.execute("EXPIRE", key, final_ttl)
                                else:
                                    await conn.expire(key, final_ttl)
                        
                        return success
                except Exception as e:
                    logger.error(f"Redis MSET 批量操作失败: {e}")
                    return False
            
            tasks = [
                set_to_pool(pool, key_value_map)
                for pool, key_value_map in pools_mapping.values()
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return all(isinstance(r, bool) and r for r in results)
    
    def _serialize_value(self, value: Any) -> str:
        """序列化值"""
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False)
        else:
            return str(value)
    
    def _deserialize_value(self, value: Any) -> Any:
        """反序列化值"""
        if value is None:
            return None
        
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        
        return value
    
    async def create_lock(self, key: str, timeout: int = 30, 
                         retry_interval: float = 0.1, max_retries: int = 100) -> DistributedLock:
        """
        创建分布式锁
        
        Args:
            key: 锁键名
            timeout: 锁超时时间
            retry_interval: 重试间隔
            max_retries: 最大重试次数
            
        Returns:
            分布式锁实例
        """
        pool = self._get_pool(key)
        return DistributedLock(pool, key, timeout, retry_interval, max_retries)
    
    async def get_with_bloom_filter(self, key: str, pool_name: str = None) -> Optional[Any]:
        """
        使用布隆过滤器防穿透的GET操作
        
        Args:
            key: 键名
            pool_name: 连接池名称
            
        Returns:
            缓存值或None
        """
        if self._bloom_filter and not self._bloom_filter.contains(key):
            logger.debug(f"布隆过滤器拦截: {key}")
            return None
        
        result = await self.get(key, pool_name)
        
        # 如果结果为空且启用了空值缓存
        if result is None and self._cache_strategy.enable_null_cache:
            # 设置空值缓存
            await self.set(key, "__NULL__", self._cache_strategy.null_cache_ttl, pool_name)
            # 添加到布隆过滤器
            if self._bloom_filter:
                self._bloom_filter.add(key)
        elif result == "__NULL__":
            return None
        elif result is not None and self._bloom_filter:
            # 添加到布隆过滤器
            self._bloom_filter.add(key)
        
        return result
    
    async def set_with_bloom_filter(self, key: str, value: Any, ttl: Optional[int] = None, 
                                   pool_name: str = None) -> bool:
        """
        使用布隆过滤器的SET操作
        
        Args:
            key: 键名
            value: 值
            ttl: 过期时间（秒）
            pool_name: 连接池名称
            
        Returns:
            是否设置成功
        """
        success = await self.set(key, value, ttl, pool_name)
        
        if success and self._bloom_filter:
            self._bloom_filter.add(key)
        
        return success
    
    async def health_check(self) -> Dict[str, bool]:
        """
        健康检查所有连接池
        
        Returns:
            各连接池的健康状态
        """
        results = {}
        
        async def check_pool(name, pool):
            results[name] = await pool.health_check()
        
        tasks = [check_pool(name, pool) for name, pool in self._pools.items()]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        return results
    
    async def close(self):
        """关闭所有连接池"""
        tasks = [pool.close() for pool in self._pools.values()]
        await asyncio.gather(*tasks, return_exceptions=True)
        self._pools.clear()
        logger.info("Redis管理器已关闭")


# 全局Redis管理器实例
redis_manager = RedisManager()


# 便捷函数
async def get_redis_value(key: str, pool_name: str = None) -> Optional[Any]:
    """获取Redis值的便捷函数"""
    return await redis_manager.get(key, pool_name)


async def set_redis_value(key: str, value: Any, ttl: Optional[int] = None, 
                         pool_name: str = None) -> bool:
    """设置Redis值的便捷函数"""
    return await redis_manager.set(key, value, ttl, pool_name)


async def delete_redis_keys(*keys: str, pool_name: str = None) -> int:
    """删除Redis键的便捷函数"""
    return await redis_manager.delete(*keys, pool_name=pool_name)


async def create_redis_lock(key: str, timeout: int = 30) -> DistributedLock:
    """创建Redis分布式锁的便捷函数"""
    return await redis_manager.create_lock(key, timeout)