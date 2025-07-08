"""
配置缓存管理模块

实现配置的缓存管理，支持LRU、LFU等多种缓存策略。
"""

import time
import threading
from typing import Dict, Any, Optional, Type, TypeVar, Generic, List, Tuple
from collections import OrderedDict
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from .types import BaseConfig, CacheConfig, CacheStrategy as CacheStrategyEnum, ConfigId
from .exceptions import CacheError

T = TypeVar('T', bound=BaseConfig)


@dataclass
class CacheStats:
    """缓存统计信息"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0
    hit_rate: float = 0.0
    
    def update_hit_rate(self):
        """更新命中率"""
        total = self.hits + self.misses
        self.hit_rate = self.hits / total if total > 0 else 0.0


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    access_time: float = field(default_factory=time.time)
    access_count: int = 0
    create_time: float = field(default_factory=time.time)
    
    def touch(self):
        """更新访问时间和次数"""
        self.access_time = time.time()
        self.access_count += 1


class CacheStrategy(ABC):
    """缓存策略基类"""
    
    def __init__(self, max_size: int):
        """
        初始化缓存策略
        
        Args:
            max_size: 最大缓存大小
        """
        self.max_size = max_size
        self._cache: Dict[Any, CacheEntry] = {}
        self._stats = CacheStats(max_size=max_size)
        self._lock = threading.RLock()
    
    @abstractmethod
    def get(self, key: Any) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[Any]: 缓存值，不存在时返回None
        """
        pass
    
    @abstractmethod
    def put(self, key: Any, value: Any) -> None:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
        """
        pass
    
    @abstractmethod
    def remove(self, key: Any) -> bool:
        """
        移除缓存项
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 是否移除成功
        """
        pass
    
    @abstractmethod
    def _evict(self) -> None:
        """执行缓存驱逐"""
        pass
    
    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._stats = CacheStats(max_size=self.max_size)
    
    def size(self) -> int:
        """获取缓存大小"""
        with self._lock:
            return len(self._cache)
    
    def stats(self) -> CacheStats:
        """获取缓存统计信息"""
        with self._lock:
            self._stats.size = len(self._cache)
            self._stats.update_hit_rate()
            return self._stats
    
    def contains(self, key: Any) -> bool:
        """检查缓存中是否存在指定键"""
        with self._lock:
            return key in self._cache


class LRUCache(CacheStrategy):
    """LRU缓存策略"""
    
    def __init__(self, max_size: int):
        super().__init__(max_size)
        self._order: OrderedDict = OrderedDict()
    
    def get(self, key: Any) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                entry.touch()
                # 更新访问顺序
                self._order.move_to_end(key)
                self._stats.hits += 1
                return entry.value
            else:
                self._stats.misses += 1
                return None
    
    def put(self, key: Any, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            if key in self._cache:
                # 更新现有条目
                self._cache[key].value = value
                self._cache[key].touch()
                self._order.move_to_end(key)
            else:
                # 添加新条目
                if len(self._cache) >= self.max_size:
                    self._evict()
                
                self._cache[key] = CacheEntry(value)
                self._order[key] = None
    
    def remove(self, key: Any) -> bool:
        """移除缓存项"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                del self._order[key]
                return True
            return False
    
    def _evict(self) -> None:
        """执行LRU驱逐"""
        if self._order:
            # 移除最少使用的项
            oldest_key = next(iter(self._order))
            del self._cache[oldest_key]
            del self._order[oldest_key]
            self._stats.evictions += 1


class LFUCache(CacheStrategy):
    """LFU缓存策略"""
    
    def __init__(self, max_size: int):
        super().__init__(max_size)
        self._frequencies: Dict[Any, int] = {}
    
    def get(self, key: Any) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                entry.touch()
                self._frequencies[key] = entry.access_count
                self._stats.hits += 1
                return entry.value
            else:
                self._stats.misses += 1
                return None
    
    def put(self, key: Any, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            if key in self._cache:
                # 更新现有条目
                self._cache[key].value = value
                self._cache[key].touch()
                self._frequencies[key] = self._cache[key].access_count
            else:
                # 添加新条目
                if len(self._cache) >= self.max_size:
                    self._evict()
                
                entry = CacheEntry(value)
                self._cache[key] = entry
                self._frequencies[key] = entry.access_count
    
    def remove(self, key: Any) -> bool:
        """移除缓存项"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                del self._frequencies[key]
                return True
            return False
    
    def _evict(self) -> None:
        """执行LFU驱逐"""
        if self._frequencies:
            # 找到使用频率最低的项
            min_freq_key = min(self._frequencies.items(), key=lambda x: x[1])[0]
            del self._cache[min_freq_key]
            del self._frequencies[min_freq_key]
            self._stats.evictions += 1


class FIFOCache(CacheStrategy):
    """FIFO缓存策略"""
    
    def __init__(self, max_size: int):
        super().__init__(max_size)
        self._insertion_order: List[Any] = []
    
    def get(self, key: Any) -> Optional[Any]:
        """获取缓存值"""
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                entry.touch()
                self._stats.hits += 1
                return entry.value
            else:
                self._stats.misses += 1
                return None
    
    def put(self, key: Any, value: Any) -> None:
        """设置缓存值"""
        with self._lock:
            if key in self._cache:
                # 更新现有条目
                self._cache[key].value = value
                self._cache[key].touch()
            else:
                # 添加新条目
                if len(self._cache) >= self.max_size:
                    self._evict()
                
                self._cache[key] = CacheEntry(value)
                self._insertion_order.append(key)
    
    def remove(self, key: Any) -> bool:
        """移除缓存项"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._insertion_order.remove(key)
                return True
            return False
    
    def _evict(self) -> None:
        """执行FIFO驱逐"""
        if self._insertion_order:
            # 移除最早插入的项
            oldest_key = self._insertion_order.pop(0)
            del self._cache[oldest_key]
            self._stats.evictions += 1


class NoCache(CacheStrategy):
    """无缓存策略"""
    
    def __init__(self, max_size: int = 0):
        super().__init__(0)
    
    def get(self, key: Any) -> Optional[Any]:
        """获取缓存值（始终返回None）"""
        self._stats.misses += 1
        return None
    
    def put(self, key: Any, value: Any) -> None:
        """设置缓存值（不执行任何操作）"""
        pass
    
    def remove(self, key: Any) -> bool:
        """移除缓存项（始终返回False）"""
        return False
    
    def _evict(self) -> None:
        """执行驱逐（不执行任何操作）"""
        pass


class ConfigCache(Generic[T]):
    """
    配置缓存管理器
    
    支持多种缓存策略和TTL
    """
    
    def __init__(self, config: CacheConfig):
        """
        初始化配置缓存
        
        Args:
            config: 缓存配置
        """
        self.config = config
        self._cache_strategy = self._create_cache_strategy()
        self._ttl_enabled = config.ttl is not None
    
    def _create_cache_strategy(self) -> CacheStrategy:
        """创建缓存策略"""
        strategy_map = {
            CacheStrategyEnum.LRU: LRUCache,
            CacheStrategyEnum.LFU: LFUCache,
            CacheStrategyEnum.FIFO: FIFOCache,
            CacheStrategyEnum.NO_CACHE: NoCache,
        }
        
        strategy_class = strategy_map.get(self.config.strategy)
        if strategy_class is None:
            raise CacheError("create_strategy", f"不支持的缓存策略: {self.config.strategy}")
        
        return strategy_class(self.config.max_size)
    
    def get(self, key: Any) -> Optional[T]:
        """
        获取缓存配置
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[T]: 缓存的配置对象
        """
        try:
            entry = self._cache_strategy.get(key)
            if entry is None:
                return None
            
            # 检查TTL
            if self._ttl_enabled:
                if isinstance(entry, CacheEntry):
                    if time.time() - entry.create_time > self.config.ttl:
                        self._cache_strategy.remove(key)
                        return None
                    return entry.value
                else:
                    # 兼容旧的缓存项
                    return entry
            
            return entry.value if isinstance(entry, CacheEntry) else entry
            
        except Exception as e:
            raise CacheError("get", str(e))
    
    def put(self, key: Any, value: T) -> None:
        """
        设置缓存配置
        
        Args:
            key: 缓存键
            value: 配置对象
        """
        try:
            self._cache_strategy.put(key, value)
        except Exception as e:
            raise CacheError("put", str(e))
    
    def remove(self, key: Any) -> bool:
        """
        移除缓存配置
        
        Args:
            key: 缓存键
            
        Returns:
            bool: 是否移除成功
        """
        try:
            return self._cache_strategy.remove(key)
        except Exception as e:
            raise CacheError("remove", str(e))
    
    def clear(self) -> None:
        """清空缓存"""
        try:
            self._cache_strategy.clear()
        except Exception as e:
            raise CacheError("clear", str(e))
    
    def size(self) -> int:
        """获取缓存大小"""
        return self._cache_strategy.size()
    
    def stats(self) -> CacheStats:
        """获取缓存统计信息"""
        return self._cache_strategy.stats()
    
    def contains(self, key: Any) -> bool:
        """检查缓存中是否存在指定键"""
        return self._cache_strategy.contains(key)
    
    def cleanup_expired(self) -> int:
        """
        清理过期缓存项
        
        Returns:
            int: 清理的项目数量
        """
        if not self._ttl_enabled:
            return 0
        
        try:
            expired_keys = []
            current_time = time.time()
            
            # 找出过期的键
            for key in list(self._cache_strategy._cache.keys()):
                entry = self._cache_strategy._cache[key]
                if isinstance(entry, CacheEntry):
                    if current_time - entry.create_time > self.config.ttl:
                        expired_keys.append(key)
            
            # 删除过期的项
            for key in expired_keys:
                self._cache_strategy.remove(key)
            
            return len(expired_keys)
            
        except Exception as e:
            raise CacheError("cleanup_expired", str(e))