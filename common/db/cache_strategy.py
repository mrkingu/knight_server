"""
缓存策略模块

该模块实现多种缓存模式和策略，包含以下功能：
- Cache-Aside（旁路缓存）
- Write-Through（写穿透）
- Write-Behind（异步写入）
- LRU/LFU/FIFO缓存策略
- TTL管理
- 缓存预热
- 缓存降级
"""

import asyncio
import time
import weakref
from abc import ABC, abstractmethod
from collections import OrderedDict, defaultdict
from typing import Any, Dict, List, Optional, Union, Callable, TypeVar, Generic
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from common.logger import logger
from .redis_manager import redis_manager
from .mongo_manager import mongo_manager


T = TypeVar('T')


class CacheMode(Enum):
    """缓存模式"""
    CACHE_ASIDE = "cache_aside"
    WRITE_THROUGH = "write_through"
    WRITE_BEHIND = "write_behind"


class EvictionPolicy(Enum):
    """淘汰策略"""
    LRU = "lru"  # 最近最少使用
    LFU = "lfu"  # 最少使用频次
    FIFO = "fifo"  # 先进先出
    TTL = "ttl"  # 基于时间的淘汰


@dataclass
class CacheItem:
    """缓存项"""
    key: str
    value: Any
    created_at: float
    last_accessed: float
    access_count: int
    ttl: Optional[float] = None
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.ttl is None:
            return False
        return time.time() - self.created_at > self.ttl
    
    def touch(self):
        """更新访问时间和次数"""
        self.last_accessed = time.time()
        self.access_count += 1


class CacheStats:
    """缓存统计"""
    
    def __init__(self):
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.evictions = 0
        self.errors = 0
        self.start_time = time.time()
    
    @property
    def hit_rate(self) -> float:
        """命中率"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    @property
    def miss_rate(self) -> float:
        """未命中率"""
        return 1.0 - self.hit_rate
    
    def reset(self):
        """重置统计"""
        self.hits = 0
        self.misses = 0
        self.sets = 0
        self.deletes = 0
        self.evictions = 0
        self.errors = 0
        self.start_time = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        runtime = time.time() - self.start_time
        return {
            'hits': self.hits,
            'misses': self.misses,
            'sets': self.sets,
            'deletes': self.deletes,
            'evictions': self.evictions,
            'errors': self.errors,
            'hit_rate': self.hit_rate,
            'miss_rate': self.miss_rate,
            'runtime_seconds': runtime
        }


class BaseCacheStrategy(ABC, Generic[T]):
    """基础缓存策略"""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._storage: Dict[str, CacheItem] = {}
        self._stats = CacheStats()
        self._lock = asyncio.Lock()
    
    @abstractmethod
    async def get(self, key: str) -> Optional[T]:
        """获取缓存值"""
        pass
    
    @abstractmethod
    async def set(self, key: str, value: T, ttl: Optional[float] = None) -> bool:
        """设置缓存值"""
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """删除缓存值"""
        pass
    
    @abstractmethod
    def _evict(self) -> Optional[str]:
        """淘汰策略"""
        pass
    
    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        async with self._lock:
            if key in self._storage:
                item = self._storage[key]
                if item.is_expired():
                    del self._storage[key]
                    return False
                return True
            return False
    
    async def clear(self):
        """清空缓存"""
        async with self._lock:
            self._storage.clear()
            logger.info("缓存已清空")
    
    async def size(self) -> int:
        """获取缓存大小"""
        async with self._lock:
            return len(self._storage)
    
    def get_stats(self) -> CacheStats:
        """获取统计信息"""
        return self._stats
    
    async def cleanup_expired(self):
        """清理过期项"""
        async with self._lock:
            expired_keys = []
            for key, item in self._storage.items():
                if item.is_expired():
                    expired_keys.append(key)
            
            for key in expired_keys:
                del self._storage[key]
                self._stats.evictions += 1
            
            if expired_keys:
                logger.debug(f"清理过期缓存项: {len(expired_keys)}个")


class LRUCacheStrategy(BaseCacheStrategy[T]):
    """LRU（最近最少使用）缓存策略"""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        super().__init__(max_size, default_ttl)
        self._access_order = OrderedDict()
    
    async def get(self, key: str) -> Optional[T]:
        async with self._lock:
            if key in self._storage:
                item = self._storage[key]
                
                # 检查是否过期
                if item.is_expired():
                    del self._storage[key]
                    self._access_order.pop(key, None)
                    self._stats.misses += 1
                    return None
                
                # 更新访问信息
                item.touch()
                self._access_order.move_to_end(key)
                self._stats.hits += 1
                return item.value
            
            self._stats.misses += 1
            return None
    
    async def set(self, key: str, value: T, ttl: Optional[float] = None) -> bool:
        async with self._lock:
            try:
                # 如果缓存已满，先淘汰
                if key not in self._storage and len(self._storage) >= self.max_size:
                    evicted_key = self._evict()
                    if evicted_key:
                        logger.debug(f"LRU淘汰缓存项: {evicted_key}")
                
                # 创建缓存项
                ttl = ttl or self.default_ttl
                item = CacheItem(
                    key=key,
                    value=value,
                    created_at=time.time(),
                    last_accessed=time.time(),
                    access_count=1,
                    ttl=ttl
                )
                
                self._storage[key] = item
                self._access_order[key] = True
                self._access_order.move_to_end(key)
                self._stats.sets += 1
                
                return True
                
            except Exception as e:
                logger.error(f"LRU缓存设置失败: {e}")
                self._stats.errors += 1
                return False
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._storage:
                del self._storage[key]
                self._access_order.pop(key, None)
                self._stats.deletes += 1
                return True
            return False
    
    def _evict(self) -> Optional[str]:
        """淘汰最近最少使用的项"""
        if not self._access_order:
            return None
        
        # 获取最老的键
        oldest_key = next(iter(self._access_order))
        del self._storage[oldest_key]
        del self._access_order[oldest_key]
        self._stats.evictions += 1
        
        return oldest_key


class LFUCacheStrategy(BaseCacheStrategy[T]):
    """LFU（最少使用频次）缓存策略"""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        super().__init__(max_size, default_ttl)
        self._freq_buckets = defaultdict(set)  # 频次 -> 键集合
        self._key_freq = {}  # 键 -> 频次
        self._min_freq = 0
    
    async def get(self, key: str) -> Optional[T]:
        async with self._lock:
            if key in self._storage:
                item = self._storage[key]
                
                # 检查是否过期
                if item.is_expired():
                    self._remove_key(key)
                    self._stats.misses += 1
                    return None
                
                # 更新访问信息和频次
                item.touch()
                self._update_freq(key)
                self._stats.hits += 1
                return item.value
            
            self._stats.misses += 1
            return None
    
    async def set(self, key: str, value: T, ttl: Optional[float] = None) -> bool:
        async with self._lock:
            try:
                # 如果缓存已满，先淘汰
                if key not in self._storage and len(self._storage) >= self.max_size:
                    evicted_key = self._evict()
                    if evicted_key:
                        logger.debug(f"LFU淘汰缓存项: {evicted_key}")
                
                # 创建缓存项
                ttl = ttl or self.default_ttl
                item = CacheItem(
                    key=key,
                    value=value,
                    created_at=time.time(),
                    last_accessed=time.time(),
                    access_count=1,
                    ttl=ttl
                )
                
                # 如果是更新现有键
                if key in self._storage:
                    self._remove_key(key)
                
                self._storage[key] = item
                self._key_freq[key] = 1
                self._freq_buckets[1].add(key)
                self._min_freq = 1
                self._stats.sets += 1
                
                return True
                
            except Exception as e:
                logger.error(f"LFU缓存设置失败: {e}")
                self._stats.errors += 1
                return False
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._storage:
                self._remove_key(key)
                self._stats.deletes += 1
                return True
            return False
    
    def _update_freq(self, key: str):
        """更新键的访问频次"""
        old_freq = self._key_freq[key]
        new_freq = old_freq + 1
        
        # 从旧频次桶中移除
        self._freq_buckets[old_freq].discard(key)
        
        # 添加到新频次桶
        self._freq_buckets[new_freq].add(key)
        self._key_freq[key] = new_freq
        
        # 更新最小频次
        if old_freq == self._min_freq and not self._freq_buckets[old_freq]:
            self._min_freq = new_freq
    
    def _remove_key(self, key: str):
        """移除键"""
        if key in self._key_freq:
            freq = self._key_freq[key]
            self._freq_buckets[freq].discard(key)
            del self._key_freq[key]
        
        if key in self._storage:
            del self._storage[key]
    
    def _evict(self) -> Optional[str]:
        """淘汰使用频次最少的项"""
        if not self._freq_buckets[self._min_freq]:
            return None
        
        # 从最小频次桶中随机选择一个键淘汰
        evicted_key = self._freq_buckets[self._min_freq].pop()
        self._remove_key(evicted_key)
        self._stats.evictions += 1
        
        return evicted_key


class FIFOCacheStrategy(BaseCacheStrategy[T]):
    """FIFO（先进先出）缓存策略"""
    
    def __init__(self, max_size: int = 1000, default_ttl: Optional[float] = None):
        super().__init__(max_size, default_ttl)
        self._insertion_order = OrderedDict()
    
    async def get(self, key: str) -> Optional[T]:
        async with self._lock:
            if key in self._storage:
                item = self._storage[key]
                
                # 检查是否过期
                if item.is_expired():
                    del self._storage[key]
                    self._insertion_order.pop(key, None)
                    self._stats.misses += 1
                    return None
                
                # 更新访问信息（但不改变插入顺序）
                item.touch()
                self._stats.hits += 1
                return item.value
            
            self._stats.misses += 1
            return None
    
    async def set(self, key: str, value: T, ttl: Optional[float] = None) -> bool:
        async with self._lock:
            try:
                # 如果缓存已满，先淘汰
                if key not in self._storage and len(self._storage) >= self.max_size:
                    evicted_key = self._evict()
                    if evicted_key:
                        logger.debug(f"FIFO淘汰缓存项: {evicted_key}")
                
                # 创建缓存项
                ttl = ttl or self.default_ttl
                item = CacheItem(
                    key=key,
                    value=value,
                    created_at=time.time(),
                    last_accessed=time.time(),
                    access_count=1,
                    ttl=ttl
                )
                
                # 如果是更新现有键，保持插入顺序
                if key not in self._storage:
                    self._insertion_order[key] = True
                
                self._storage[key] = item
                self._stats.sets += 1
                
                return True
                
            except Exception as e:
                logger.error(f"FIFO缓存设置失败: {e}")
                self._stats.errors += 1
                return False
    
    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._storage:
                del self._storage[key]
                self._insertion_order.pop(key, None)
                self._stats.deletes += 1
                return True
            return False
    
    def _evict(self) -> Optional[str]:
        """淘汰最先插入的项"""
        if not self._insertion_order:
            return None
        
        # 获取最先插入的键
        oldest_key = next(iter(self._insertion_order))
        del self._storage[oldest_key]
        del self._insertion_order[oldest_key]
        self._stats.evictions += 1
        
        return oldest_key


class CacheAsideStrategy:
    """Cache-Aside（旁路缓存）策略"""
    
    def __init__(self, cache_strategy: BaseCacheStrategy, 
                 loader: Callable[[str], Any] = None,
                 saver: Callable[[str, Any], bool] = None):
        self.cache_strategy = cache_strategy
        self.loader = loader  # 数据加载函数
        self.saver = saver    # 数据保存函数
    
    async def get(self, key: str) -> Optional[Any]:
        """获取数据（先查缓存，再查数据库）"""
        # 先从缓存获取
        value = await self.cache_strategy.get(key)
        if value is not None:
            return value
        
        # 缓存未命中，从数据库加载
        if self.loader:
            try:
                value = await self._call_async(self.loader, key)
                if value is not None:
                    # 加载成功，更新缓存
                    await self.cache_strategy.set(key, value)
                return value
            except Exception as e:
                logger.error(f"数据加载失败 {key}: {e}")
        
        return None
    
    async def set(self, key: str, value: Any) -> bool:
        """设置数据（先更新数据库，再更新缓存）"""
        # 先保存到数据库
        if self.saver:
            try:
                success = await self._call_async(self.saver, key, value)
                if not success:
                    return False
            except Exception as e:
                logger.error(f"数据保存失败 {key}: {e}")
                return False
        
        # 更新缓存
        return await self.cache_strategy.set(key, value)
    
    async def delete(self, key: str) -> bool:
        """删除数据（先删除缓存，再删除数据库）"""
        # 先删除缓存
        await self.cache_strategy.delete(key)
        
        # 如果有删除器，删除数据库数据
        # 这里简化处理，实际应该有数据库删除函数
        return True
    
    async def _call_async(self, func: Callable, *args, **kwargs):
        """调用可能是异步或同步的函数"""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)


class WriteThroughStrategy:
    """Write-Through（写穿透）策略"""
    
    def __init__(self, cache_strategy: BaseCacheStrategy,
                 loader: Callable[[str], Any] = None,
                 saver: Callable[[str, Any], bool] = None):
        self.cache_strategy = cache_strategy
        self.loader = loader
        self.saver = saver
    
    async def get(self, key: str) -> Optional[Any]:
        """获取数据"""
        return await self.cache_strategy.get(key)
    
    async def set(self, key: str, value: Any) -> bool:
        """设置数据（同时更新缓存和数据库）"""
        # 同时更新缓存和数据库
        cache_success = await self.cache_strategy.set(key, value)
        
        db_success = True
        if self.saver:
            try:
                db_success = await self._call_async(self.saver, key, value)
            except Exception as e:
                logger.error(f"数据库保存失败 {key}: {e}")
                db_success = False
        
        # 如果数据库保存失败，删除缓存
        if not db_success and cache_success:
            await self.cache_strategy.delete(key)
        
        return cache_success and db_success
    
    async def _call_async(self, func: Callable, *args, **kwargs):
        """调用可能是异步或同步的函数"""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        else:
            return func(*args, **kwargs)


class WriteBehindStrategy:
    """Write-Behind（异步写入）策略"""
    
    def __init__(self, cache_strategy: BaseCacheStrategy,
                 saver: Callable[[str, Any], bool] = None,
                 write_delay: float = 5.0,
                 batch_size: int = 100):
        self.cache_strategy = cache_strategy
        self.saver = saver
        self.write_delay = write_delay
        self.batch_size = batch_size
        
        # 待写入队列
        self._write_queue: Dict[str, Any] = {}
        self._write_lock = asyncio.Lock()
        self._write_task = None
        self._stop_event = asyncio.Event()
        
        # 启动后台写入任务
        self._start_write_task()
    
    async def get(self, key: str) -> Optional[Any]:
        """获取数据"""
        return await self.cache_strategy.get(key)
    
    async def set(self, key: str, value: Any) -> bool:
        """设置数据（立即更新缓存，异步写入数据库）"""
        # 立即更新缓存
        cache_success = await self.cache_strategy.set(key, value)
        
        # 添加到写入队列
        async with self._write_lock:
            self._write_queue[key] = value
        
        return cache_success
    
    async def delete(self, key: str) -> bool:
        """删除数据"""
        # 立即删除缓存
        cache_success = await self.cache_strategy.delete(key)
        
        # 从写入队列中移除
        async with self._write_lock:
            self._write_queue.pop(key, None)
        
        return cache_success
    
    def _start_write_task(self):
        """启动后台写入任务"""
        if self._write_task is None or self._write_task.done():
            self._write_task = asyncio.create_task(self._background_writer())
    
    async def _background_writer(self):
        """后台写入任务"""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.write_delay)
                
                # 获取待写入数据
                async with self._write_lock:
                    if not self._write_queue:
                        continue
                    
                    # 批量处理
                    items_to_write = dict(list(self._write_queue.items())[:self.batch_size])
                    for key in items_to_write:
                        del self._write_queue[key]
                
                # 批量写入数据库
                if items_to_write and self.saver:
                    await self._batch_write(items_to_write)
                
            except Exception as e:
                logger.error(f"后台写入任务异常: {e}")
    
    async def _batch_write(self, items: Dict[str, Any]):
        """批量写入数据库"""
        for key, value in items.items():
            try:
                if asyncio.iscoroutinefunction(self.saver):
                    await self.saver(key, value)
                else:
                    self.saver(key, value)
            except Exception as e:
                logger.error(f"异步写入失败 {key}: {e}")
                # 写入失败，重新加入队列
                async with self._write_lock:
                    self._write_queue[key] = value
    
    async def flush(self):
        """强制刷新所有待写入数据"""
        async with self._write_lock:
            if self._write_queue and self.saver:
                await self._batch_write(self._write_queue.copy())
                self._write_queue.clear()
    
    async def close(self):
        """关闭写入策略"""
        self._stop_event.set()
        
        # 刷新剩余数据
        await self.flush()
        
        # 等待后台任务结束
        if self._write_task and not self._write_task.done():
            await self._write_task


class CacheManager:
    """缓存管理器"""
    
    def __init__(self):
        self._strategies: Dict[str, BaseCacheStrategy] = {}
        self._cleanup_task = None
        self._cleanup_interval = 300  # 5分钟清理一次
    
    def register_strategy(self, name: str, strategy: BaseCacheStrategy):
        """注册缓存策略"""
        self._strategies[name] = strategy
        logger.info(f"注册缓存策略: {name}")
        
        # 启动清理任务
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_expired())
    
    def get_strategy(self, name: str) -> Optional[BaseCacheStrategy]:
        """获取缓存策略"""
        return self._strategies.get(name)
    
    def create_lru_strategy(self, name: str, max_size: int = 1000, 
                           default_ttl: Optional[float] = None) -> LRUCacheStrategy:
        """创建LRU策略"""
        strategy = LRUCacheStrategy(max_size, default_ttl)
        self.register_strategy(name, strategy)
        return strategy
    
    def create_lfu_strategy(self, name: str, max_size: int = 1000,
                           default_ttl: Optional[float] = None) -> LFUCacheStrategy:
        """创建LFU策略"""
        strategy = LFUCacheStrategy(max_size, default_ttl)
        self.register_strategy(name, strategy)
        return strategy
    
    def create_fifo_strategy(self, name: str, max_size: int = 1000,
                            default_ttl: Optional[float] = None) -> FIFOCacheStrategy:
        """创建FIFO策略"""
        strategy = FIFOCacheStrategy(max_size, default_ttl)
        self.register_strategy(name, strategy)
        return strategy
    
    async def _cleanup_expired(self):
        """定期清理过期项"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                
                for name, strategy in self._strategies.items():
                    await strategy.cleanup_expired()
                    
            except Exception as e:
                logger.error(f"缓存清理任务异常: {e}")
    
    async def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有策略的统计信息"""
        stats = {}
        for name, strategy in self._strategies.items():
            stats[name] = strategy.get_stats().to_dict()
        return stats
    
    async def clear_all(self):
        """清空所有缓存"""
        for strategy in self._strategies.values():
            await strategy.clear()
        logger.info("已清空所有缓存")


# 全局缓存管理器
cache_manager = CacheManager()


# 便捷函数
def create_lru_cache(name: str, max_size: int = 1000, 
                    default_ttl: Optional[float] = None) -> LRUCacheStrategy:
    """创建LRU缓存的便捷函数"""
    return cache_manager.create_lru_strategy(name, max_size, default_ttl)


def create_lfu_cache(name: str, max_size: int = 1000,
                    default_ttl: Optional[float] = None) -> LFUCacheStrategy:
    """创建LFU缓存的便捷函数"""
    return cache_manager.create_lfu_strategy(name, max_size, default_ttl)


def create_fifo_cache(name: str, max_size: int = 1000,
                     default_ttl: Optional[float] = None) -> FIFOCacheStrategy:
    """创建FIFO缓存的便捷函数"""
    return cache_manager.create_fifo_strategy(name, max_size, default_ttl)


def get_cache_strategy(name: str) -> Optional[BaseCacheStrategy]:
    """获取缓存策略的便捷函数"""
    return cache_manager.get_strategy(name)