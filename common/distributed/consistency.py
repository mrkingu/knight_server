"""
一致性保障模块

该模块提供分布式系统一致性保障功能，包括：
- 最终一致性保障
- 基于版本号的乐观锁
- 分布式缓存一致性
- 数据同步机制
- 冲突解决策略
- 一致性哈希实现
"""

import asyncio
import time
import json
import hashlib
import bisect
from typing import Dict, Any, Optional, List, Union, Callable, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import threading

from common.logger import logger


class ConsistencyLevel(Enum):
    """一致性级别枚举"""
    EVENTUAL = "eventual"           # 最终一致性
    STRONG = "strong"              # 强一致性
    WEAK = "weak"                  # 弱一致性
    MONOTONIC = "monotonic"        # 单调一致性
    CAUSAL = "causal"              # 因果一致性


class ConflictResolution(Enum):
    """冲突解决策略枚举"""
    LAST_WRITE_WINS = "last_write_wins"    # 最后写入胜出
    FIRST_WRITE_WINS = "first_write_wins"  # 第一个写入胜出
    VERSION_VECTOR = "version_vector"       # 版本向量
    TIMESTAMP = "timestamp"                 # 时间戳
    CUSTOM = "custom"                      # 自定义策略


class SyncDirection(Enum):
    """同步方向枚举"""
    PUSH = "push"                          # 推送
    PULL = "pull"                          # 拉取
    BIDIRECTIONAL = "bidirectional"       # 双向


@dataclass
class ConsistencyConfig:
    """一致性配置"""
    consistency_level: ConsistencyLevel = ConsistencyLevel.EVENTUAL
    conflict_resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS
    sync_interval: float = 30.0            # 同步间隔（秒）
    version_vector_size: int = 100         # 版本向量大小
    max_sync_retries: int = 3              # 最大同步重试次数
    sync_timeout: float = 10.0             # 同步超时时间
    enable_background_sync: bool = True     # 启用后台同步
    enable_conflict_detection: bool = True  # 启用冲突检测
    enable_version_tracking: bool = True    # 启用版本跟踪
    cache_ttl: int = 300                   # 缓存TTL（秒）


@dataclass
class VersionInfo:
    """版本信息"""
    version: int
    timestamp: float
    node_id: str
    checksum: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DataEntry:
    """数据条目"""
    key: str
    value: Any
    version_info: VersionInfo
    created_at: float
    updated_at: float
    is_deleted: bool = False
    conflict_resolved: bool = False


@dataclass
class SyncResult:
    """同步结果"""
    success: bool
    synced_count: int
    conflict_count: int
    error_count: int
    elapsed_time: float
    errors: List[str] = field(default_factory=list)


class ConsistencyError(Exception):
    """一致性异常基类"""
    pass


class VersionConflictError(ConsistencyError):
    """版本冲突异常"""
    pass


class SyncError(ConsistencyError):
    """同步异常"""
    pass


class ConsistentHashRing:
    """一致性哈希环"""
    
    def __init__(self, nodes: List[str] = None, replicas: int = 100):
        """
        初始化一致性哈希环
        
        Args:
            nodes: 节点列表
            replicas: 虚拟节点数量
        """
        self.replicas = replicas
        self.ring: Dict[int, str] = {}
        self.sorted_keys: List[int] = []
        self.nodes: Set[str] = set()
        self.lock = threading.RLock()
        
        if nodes:
            for node in nodes:
                self.add_node(node)
    
    def _hash(self, key: str) -> int:
        """计算哈希值"""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)
    
    def add_node(self, node: str):
        """添加节点"""
        with self.lock:
            if node in self.nodes:
                return
            
            self.nodes.add(node)
            
            for i in range(self.replicas):
                virtual_key = f"{node}:{i}"
                hash_value = self._hash(virtual_key)
                self.ring[hash_value] = node
                bisect.insort(self.sorted_keys, hash_value)
            
            logger.info(f"添加节点到一致性哈希环: {node}")
    
    def remove_node(self, node: str):
        """移除节点"""
        with self.lock:
            if node not in self.nodes:
                return
            
            self.nodes.remove(node)
            
            for i in range(self.replicas):
                virtual_key = f"{node}:{i}"
                hash_value = self._hash(virtual_key)
                if hash_value in self.ring:
                    del self.ring[hash_value]
                    self.sorted_keys.remove(hash_value)
            
            logger.info(f"从一致性哈希环移除节点: {node}")
    
    def get_node(self, key: str) -> Optional[str]:
        """获取键对应的节点"""
        with self.lock:
            if not self.ring:
                return None
            
            hash_value = self._hash(key)
            
            # 查找第一个大于等于hash_value的节点
            idx = bisect.bisect_right(self.sorted_keys, hash_value)
            if idx == len(self.sorted_keys):
                idx = 0
            
            return self.ring[self.sorted_keys[idx]]
    
    def get_nodes(self, key: str, count: int) -> List[str]:
        """获取键对应的多个节点（用于副本）"""
        with self.lock:
            if not self.ring or count <= 0:
                return []
            
            hash_value = self._hash(key)
            nodes = []
            seen_nodes = set()
            
            # 从哈希值开始查找
            idx = bisect.bisect_right(self.sorted_keys, hash_value)
            
            for _ in range(len(self.sorted_keys)):
                if idx >= len(self.sorted_keys):
                    idx = 0
                
                node = self.ring[self.sorted_keys[idx]]
                if node not in seen_nodes:
                    nodes.append(node)
                    seen_nodes.add(node)
                    
                    if len(nodes) >= count:
                        break
                
                idx += 1
            
            return nodes
    
    def get_all_nodes(self) -> List[str]:
        """获取所有节点"""
        with self.lock:
            return list(self.nodes)


class OptimisticLock:
    """乐观锁实现"""
    
    def __init__(self, redis_manager=None):
        self.redis_manager = redis_manager
        self.local_versions: Dict[str, int] = {}
        self.lock = threading.RLock()
    
    async def get_version(self, key: str) -> int:
        """获取键的版本号"""
        if self.redis_manager:
            try:
                version_key = f"version:{key}"
                version = await self.redis_manager.get(version_key)
                return int(version) if version else 0
            except Exception as e:
                logger.error(f"获取版本号失败: {key}, 错误: {e}")
        
        # 降级到本地版本
        with self.lock:
            return self.local_versions.get(key, 0)
    
    async def increment_version(self, key: str) -> int:
        """递增版本号"""
        if self.redis_manager:
            try:
                version_key = f"version:{key}"
                new_version = await self.redis_manager.incr(version_key)
                return new_version
            except Exception as e:
                logger.error(f"递增版本号失败: {key}, 错误: {e}")
        
        # 降级到本地版本
        with self.lock:
            current_version = self.local_versions.get(key, 0)
            new_version = current_version + 1
            self.local_versions[key] = new_version
            return new_version
    
    async def compare_and_set(self, key: str, expected_version: int, new_value: Any) -> bool:
        """比较并设置（CAS操作）"""
        if self.redis_manager:
            try:
                # 使用Lua脚本保证原子性
                lua_script = """
                local key = KEYS[1]
                local version_key = KEYS[2]
                local expected_version = tonumber(ARGV[1])
                local new_value = ARGV[2]
                
                local current_version = tonumber(redis.call('GET', version_key)) or 0
                
                if current_version == expected_version then
                    redis.call('SET', key, new_value)
                    redis.call('INCR', version_key)
                    return 1
                else
                    return 0
                end
                """
                
                version_key = f"version:{key}"
                result = await self.redis_manager.eval(
                    lua_script,
                    2,
                    key,
                    version_key,
                    expected_version,
                    json.dumps(new_value) if not isinstance(new_value, str) else new_value
                )
                
                return result == 1
                
            except Exception as e:
                logger.error(f"CAS操作失败: {key}, 错误: {e}")
                return False
        
        # 降级到本地实现
        with self.lock:
            current_version = self.local_versions.get(key, 0)
            if current_version == expected_version:
                self.local_versions[key] = current_version + 1
                return True
            return False
    
    async def read_with_version(self, key: str) -> Tuple[Any, int]:
        """读取数据和版本号"""
        if self.redis_manager:
            try:
                # 使用pipeline提高性能
                pipe = self.redis_manager.pipeline()
                pipe.get(key)
                pipe.get(f"version:{key}")
                results = await pipe.execute()
                
                value = results[0]
                version = int(results[1]) if results[1] else 0
                
                if value and not isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except json.JSONDecodeError:
                        pass
                
                return value, version
                
            except Exception as e:
                logger.error(f"读取数据和版本失败: {key}, 错误: {e}")
                return None, 0
        
        # 降级到本地实现
        with self.lock:
            version = self.local_versions.get(key, 0)
            return None, version


class EventualConsistencyManager:
    """最终一致性管理器"""
    
    def __init__(self, config: ConsistencyConfig, redis_manager=None):
        """
        初始化最终一致性管理器
        
        Args:
            config: 一致性配置
            redis_manager: Redis管理器
        """
        self.config = config
        self.redis_manager = redis_manager
        self.data_store: Dict[str, DataEntry] = {}
        self.pending_sync: Dict[str, DataEntry] = {}
        self.node_id = f"node_{int(time.time())}"
        self.sync_task: Optional[asyncio.Task] = None
        self.lock = threading.RLock()
        
        # 乐观锁
        self.optimistic_lock = OptimisticLock(redis_manager)
        
        # 一致性哈希环
        self.hash_ring = ConsistentHashRing()
        
        # 启动后台同步任务
        if self.config.enable_background_sync:
            self.sync_task = asyncio.create_task(self._background_sync_loop())
    
    def _generate_checksum(self, value: Any) -> str:
        """生成数据校验和"""
        value_str = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
        return hashlib.md5(value_str.encode()).hexdigest()
    
    def _create_version_info(self, version: int = None) -> VersionInfo:
        """创建版本信息"""
        if version is None:
            version = int(time.time() * 1000000)  # 微秒级时间戳
        
        return VersionInfo(
            version=version,
            timestamp=time.time(),
            node_id=self.node_id
        )
    
    async def put(self, key: str, value: Any, expected_version: int = None) -> bool:
        """存储数据"""
        current_time = time.time()
        
        try:
            # 如果指定了期望版本，使用乐观锁
            if expected_version is not None:
                success = await self.optimistic_lock.compare_and_set(key, expected_version, value)
                if not success:
                    raise VersionConflictError(f"版本冲突: 键={key}, 期望版本={expected_version}")
                version = expected_version + 1
            else:
                # 递增版本号
                version = await self.optimistic_lock.increment_version(key)
            
            # 创建数据条目
            version_info = self._create_version_info(version)
            version_info.checksum = self._generate_checksum(value)
            
            entry = DataEntry(
                key=key,
                value=value,
                version_info=version_info,
                created_at=current_time,
                updated_at=current_time
            )
            
            # 存储到本地
            with self.lock:
                self.data_store[key] = entry
                self.pending_sync[key] = entry
            
            # 存储到Redis
            if self.redis_manager:
                await self._store_to_redis(entry)
            
            logger.debug(f"存储数据成功: {key}, 版本: {version}")
            return True
            
        except Exception as e:
            logger.error(f"存储数据失败: {key}, 错误: {e}")
            return False
    
    async def get(self, key: str, consistency_level: ConsistencyLevel = None) -> Tuple[Any, VersionInfo]:
        """获取数据"""
        if consistency_level is None:
            consistency_level = self.config.consistency_level
        
        try:
            if consistency_level == ConsistencyLevel.STRONG:
                # 强一致性：从Redis获取最新数据
                return await self._get_from_redis(key)
            elif consistency_level == ConsistencyLevel.EVENTUAL:
                # 最终一致性：优先从本地获取
                with self.lock:
                    entry = self.data_store.get(key)
                    if entry and not entry.is_deleted:
                        return entry.value, entry.version_info
                
                # 本地没有，从Redis获取
                return await self._get_from_redis(key)
            else:
                # 其他一致性级别暂时按最终一致性处理
                return await self.get(key, ConsistencyLevel.EVENTUAL)
                
        except Exception as e:
            logger.error(f"获取数据失败: {key}, 错误: {e}")
            return None, None
    
    async def delete(self, key: str, expected_version: int = None) -> bool:
        """删除数据"""
        try:
            # 乐观锁检查
            if expected_version is not None:
                current_value, current_version = await self.optimistic_lock.read_with_version(key)
                if current_version != expected_version:
                    raise VersionConflictError(f"版本冲突: 键={key}, 期望版本={expected_version}, 当前版本={current_version}")
            
            # 递增版本号
            version = await self.optimistic_lock.increment_version(key)
            
            # 创建删除标记
            version_info = self._create_version_info(version)
            entry = DataEntry(
                key=key,
                value=None,
                version_info=version_info,
                created_at=time.time(),
                updated_at=time.time(),
                is_deleted=True
            )
            
            # 存储删除标记
            with self.lock:
                self.data_store[key] = entry
                self.pending_sync[key] = entry
            
            # 在Redis中设置删除标记
            if self.redis_manager:
                await self._store_to_redis(entry)
            
            logger.debug(f"删除数据成功: {key}, 版本: {version}")
            return True
            
        except Exception as e:
            logger.error(f"删除数据失败: {key}, 错误: {e}")
            return False
    
    async def _store_to_redis(self, entry: DataEntry):
        """存储到Redis"""
        if not self.redis_manager:
            return
        
        try:
            data = {
                'value': entry.value,
                'version': entry.version_info.version,
                'timestamp': entry.version_info.timestamp,
                'node_id': entry.version_info.node_id,
                'checksum': entry.version_info.checksum,
                'created_at': entry.created_at,
                'updated_at': entry.updated_at,
                'is_deleted': entry.is_deleted,
                'metadata': entry.version_info.metadata
            }
            
            await self.redis_manager.setex(
                entry.key,
                self.config.cache_ttl,
                json.dumps(data)
            )
            
        except Exception as e:
            logger.error(f"存储到Redis失败: {entry.key}, 错误: {e}")
    
    async def _get_from_redis(self, key: str) -> Tuple[Any, VersionInfo]:
        """从Redis获取数据"""
        if not self.redis_manager:
            return None, None
        
        try:
            data_str = await self.redis_manager.get(key)
            if not data_str:
                return None, None
            
            data = json.loads(data_str)
            
            if data.get('is_deleted', False):
                return None, None
            
            version_info = VersionInfo(
                version=data['version'],
                timestamp=data['timestamp'],
                node_id=data['node_id'],
                checksum=data.get('checksum'),
                metadata=data.get('metadata', {})
            )
            
            return data['value'], version_info
            
        except Exception as e:
            logger.error(f"从Redis获取数据失败: {key}, 错误: {e}")
            return None, None
    
    async def _background_sync_loop(self):
        """后台同步循环"""
        while True:
            try:
                await asyncio.sleep(self.config.sync_interval)
                await self.sync_pending_data()
            except asyncio.CancelledError:
                logger.debug("后台同步任务已取消")
                break
            except Exception as e:
                logger.error(f"后台同步异常: {e}")
    
    async def sync_pending_data(self) -> SyncResult:
        """同步待同步的数据"""
        start_time = time.time()
        synced_count = 0
        conflict_count = 0
        error_count = 0
        errors = []
        
        try:
            # 获取待同步的数据
            with self.lock:
                pending_entries = list(self.pending_sync.values())
                self.pending_sync.clear()
            
            for entry in pending_entries:
                try:
                    await self._sync_entry(entry)
                    synced_count += 1
                except VersionConflictError as e:
                    conflict_count += 1
                    errors.append(str(e))
                    logger.warning(f"同步冲突: {e}")
                except Exception as e:
                    error_count += 1
                    errors.append(str(e))
                    logger.error(f"同步错误: {e}")
            
            elapsed_time = time.time() - start_time
            
            result = SyncResult(
                success=error_count == 0,
                synced_count=synced_count,
                conflict_count=conflict_count,
                error_count=error_count,
                elapsed_time=elapsed_time,
                errors=errors
            )
            
            if synced_count > 0:
                logger.info(f"同步完成: 成功={synced_count}, 冲突={conflict_count}, 错误={error_count}, 耗时={elapsed_time:.2f}s")
            
            return result
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            logger.error(f"同步失败: {e}")
            return SyncResult(
                success=False,
                synced_count=synced_count,
                conflict_count=conflict_count,
                error_count=error_count + 1,
                elapsed_time=elapsed_time,
                errors=[str(e)]
            )
    
    async def _sync_entry(self, entry: DataEntry):
        """同步单个数据条目"""
        if not self.redis_manager:
            return
        
        # 获取远程版本
        remote_value, remote_version_info = await self._get_from_redis(entry.key)
        
        if remote_version_info is None:
            # 远程不存在，直接写入
            await self._store_to_redis(entry)
            return
        
        # 检查冲突
        if remote_version_info.version > entry.version_info.version:
            # 远程版本更新，可能需要解决冲突
            await self._resolve_conflict(entry, remote_value, remote_version_info)
        elif remote_version_info.version < entry.version_info.version:
            # 本地版本更新，写入远程
            await self._store_to_redis(entry)
        else:
            # 版本相同，检查校验和
            if (entry.version_info.checksum and 
                remote_version_info.checksum and 
                entry.version_info.checksum != remote_version_info.checksum):
                # 校验和不同，解决冲突
                await self._resolve_conflict(entry, remote_value, remote_version_info)
    
    async def _resolve_conflict(self, local_entry: DataEntry, remote_value: Any, remote_version_info: VersionInfo):
        """解决冲突"""
        if not self.config.enable_conflict_detection:
            return
        
        strategy = self.config.conflict_resolution
        
        if strategy == ConflictResolution.LAST_WRITE_WINS:
            # 最后写入胜出
            if remote_version_info.timestamp > local_entry.version_info.timestamp:
                # 使用远程值
                await self._apply_remote_value(local_entry.key, remote_value, remote_version_info)
            else:
                # 使用本地值
                await self._store_to_redis(local_entry)
        
        elif strategy == ConflictResolution.FIRST_WRITE_WINS:
            # 第一个写入胜出
            if remote_version_info.timestamp < local_entry.version_info.timestamp:
                # 使用远程值
                await self._apply_remote_value(local_entry.key, remote_value, remote_version_info)
            else:
                # 使用本地值
                await self._store_to_redis(local_entry)
        
        elif strategy == ConflictResolution.VERSION_VECTOR:
            # 版本向量（简化实现）
            if remote_version_info.version > local_entry.version_info.version:
                await self._apply_remote_value(local_entry.key, remote_value, remote_version_info)
            else:
                await self._store_to_redis(local_entry)
        
        elif strategy == ConflictResolution.TIMESTAMP:
            # 时间戳
            if remote_version_info.timestamp > local_entry.version_info.timestamp:
                await self._apply_remote_value(local_entry.key, remote_value, remote_version_info)
            else:
                await self._store_to_redis(local_entry)
        
        else:
            # 默认使用最后写入胜出
            if remote_version_info.timestamp > local_entry.version_info.timestamp:
                await self._apply_remote_value(local_entry.key, remote_value, remote_version_info)
            else:
                await self._store_to_redis(local_entry)
        
        logger.debug(f"冲突解决完成: {local_entry.key}, 策略: {strategy.value}")
    
    async def _apply_remote_value(self, key: str, remote_value: Any, remote_version_info: VersionInfo):
        """应用远程值"""
        entry = DataEntry(
            key=key,
            value=remote_value,
            version_info=remote_version_info,
            created_at=time.time(),
            updated_at=time.time(),
            conflict_resolved=True
        )
        
        with self.lock:
            self.data_store[key] = entry
    
    def add_node_to_hash_ring(self, node: str):
        """添加节点到一致性哈希环"""
        self.hash_ring.add_node(node)
    
    def remove_node_from_hash_ring(self, node: str):
        """从一致性哈希环移除节点"""
        self.hash_ring.remove_node(node)
    
    def get_responsible_nodes(self, key: str, replica_count: int = 3) -> List[str]:
        """获取键的负责节点"""
        return self.hash_ring.get_nodes(key, replica_count)
    
    def list_local_keys(self) -> List[str]:
        """列出本地存储的键"""
        with self.lock:
            return [key for key, entry in self.data_store.items() if not entry.is_deleted]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self.lock:
            total_entries = len(self.data_store)
            deleted_entries = sum(1 for entry in self.data_store.values() if entry.is_deleted)
            pending_sync_count = len(self.pending_sync)
        
        return {
            'node_id': self.node_id,
            'total_entries': total_entries,
            'active_entries': total_entries - deleted_entries,
            'deleted_entries': deleted_entries,
            'pending_sync_count': pending_sync_count,
            'hash_ring_nodes': len(self.hash_ring.get_all_nodes()),
            'config': {
                'consistency_level': self.config.consistency_level.value,
                'conflict_resolution': self.config.conflict_resolution.value,
                'sync_interval': self.config.sync_interval,
                'enable_background_sync': self.config.enable_background_sync
            }
        }
    
    async def close(self):
        """关闭管理器"""
        if self.sync_task:
            self.sync_task.cancel()
            try:
                await self.sync_task
            except asyncio.CancelledError:
                pass
        
        logger.info("最终一致性管理器已关闭")


# 默认配置实例
default_config = ConsistencyConfig()

# 默认一致性管理器实例
_default_manager = None


def get_consistency_manager(config: ConsistencyConfig = None, redis_manager=None) -> EventualConsistencyManager:
    """
    获取一致性管理器实例
    
    Args:
        config: 一致性配置
        redis_manager: Redis管理器
        
    Returns:
        EventualConsistencyManager: 一致性管理器实例
    """
    global _default_manager
    
    if config is None:
        config = default_config
    
    if _default_manager is None:
        _default_manager = EventualConsistencyManager(config, redis_manager)
    
    return _default_manager


# 便捷函数
async def put_data(key: str, value: Any, expected_version: int = None, 
                  config: ConsistencyConfig = None) -> bool:
    """存储数据的便捷函数"""
    manager = get_consistency_manager(config)
    return await manager.put(key, value, expected_version)


async def get_data(key: str, consistency_level: ConsistencyLevel = None,
                  config: ConsistencyConfig = None) -> Tuple[Any, VersionInfo]:
    """获取数据的便捷函数"""
    manager = get_consistency_manager(config)
    return await manager.get(key, consistency_level)


async def delete_data(key: str, expected_version: int = None,
                     config: ConsistencyConfig = None) -> bool:
    """删除数据的便捷函数"""
    manager = get_consistency_manager(config)
    return await manager.delete(key, expected_version)


async def sync_data(config: ConsistencyConfig = None) -> SyncResult:
    """同步数据的便捷函数"""
    manager = get_consistency_manager(config)
    return await manager.sync_pending_data()


def create_consistent_hash_ring(nodes: List[str] = None, replicas: int = 100) -> ConsistentHashRing:
    """创建一致性哈希环的便捷函数"""
    return ConsistentHashRing(nodes, replicas)


# 一致性装饰器
def eventual_consistency(key_func: Callable = None, consistency_level: ConsistencyLevel = ConsistencyLevel.EVENTUAL):
    """最终一致性装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            # 尝试从缓存获取
            manager = get_consistency_manager()
            cached_value, version_info = await manager.get(cache_key, consistency_level)
            
            if cached_value is not None:
                return cached_value
            
            # 执行函数并缓存结果
            result = await func(*args, **kwargs)
            await manager.put(cache_key, result)
            
            return result
        
        return wrapper
    return decorator