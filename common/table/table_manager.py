"""
配置表管理器模块

提供统一的配置管理接口，支持加载、缓存、热更新等功能。
"""

import os
import threading
import time
from typing import Dict, Any, List, Type, TypeVar, Optional, Union, Generic
from dataclasses import dataclass
from pathlib import Path

from common.logger import logger

from .types import (
    BaseConfig, ConfigId, CacheConfig, LoaderConfig, HotReloadConfig,
    ConfigMetadata, ConfigRegistry, CacheStrategy
)
from .table_loader import ConfigLoader, LoadResult
from .table_cache import ConfigCache
from .hot_reload import HotReloadManager
from .exceptions import (
    ConfigNotFoundError, ConfigLoadError, ConfigManagerError,
    TableError, HotReloadError
)

T = TypeVar('T', bound=BaseConfig)


@dataclass
class ManagerStats:
    """管理器统计信息"""
    total_configs: int = 0
    loaded_files: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    reload_count: int = 0
    last_reload_time: Optional[float] = None
    hot_reload_enabled: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total_configs': self.total_configs,
            'loaded_files': self.loaded_files,
            'cache_hits': self.cache_hits,
            'cache_misses': self.cache_misses,
            'reload_count': self.reload_count,
            'last_reload_time': self.last_reload_time,
            'hot_reload_enabled': self.hot_reload_enabled
        }


class TableManager:
    """
    配置表管理器
    
    提供统一的配置管理接口，支持加载、缓存、热更新等功能。
    使用单例模式确保全局唯一实例。
    """
    
    _instance: Optional['TableManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, 
                 config_dir: str = "json_data",
                 cache_config: Optional[CacheConfig] = None,
                 loader_config: Optional[LoaderConfig] = None,
                 hot_reload_config: Optional[HotReloadConfig] = None):
        """
        初始化配置表管理器
        
        Args:
            config_dir: 配置目录
            cache_config: 缓存配置
            loader_config: 加载器配置  
            hot_reload_config: 热更新配置
        """
        # 防止重复初始化
        if hasattr(self, '_initialized'):
            return
        
        self.config_dir = config_dir
        
        # 设置默认配置
        self.cache_config = cache_config or CacheConfig()
        self.loader_config = loader_config or LoaderConfig(config_dir=config_dir)
        self.hot_reload_config = hot_reload_config or HotReloadConfig()
        
        # 初始化组件
        self._loader = ConfigLoader(self.loader_config)
        self._cache: Dict[Type[BaseConfig], ConfigCache] = {}
        self._hot_reload_manager: Optional[HotReloadManager] = None
        
        # 存储配置数据
        self._config_data: Dict[Type[BaseConfig], Dict[ConfigId, BaseConfig]] = {}
        self._metadata: Dict[str, ConfigMetadata] = {}
        
        # 统计信息
        self._stats = ManagerStats()
        
        # 线程安全锁
        self._config_lock = threading.RLock()
        
        # 标记已初始化
        self._initialized = True
        
        logger.info(f"配置表管理器初始化完成: {config_dir}")
    
    @classmethod
    def get_instance(cls) -> 'TableManager':
        """
        获取单例实例
        
        Returns:
            TableManager: 管理器实例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def initialize(self) -> None:
        """
        初始化配置表管理器
        
        执行配置加载和热更新启动
        """
        try:
            # 加载所有配置
            self.load_all_configs()
            
            # 启动热更新
            if self.hot_reload_config.enabled:
                self._setup_hot_reload()
            
            logger.info("配置表管理器初始化完成")
            
        except Exception as e:
            raise ConfigManagerError(f"初始化失败: {str(e)}")
    
    def load_all_configs(self) -> None:
        """加载所有配置文件"""
        try:
            with self._config_lock:
                # 加载配置目录
                results = self._loader.load_config_directory(self.config_dir)
                
                # 处理加载结果
                self._process_load_results(results)
                
                # 更新统计信息
                self._update_stats()
                
            logger.info(f"配置加载完成: {len(results)} 个文件")
            
        except Exception as e:
            raise ConfigLoadError(self.config_dir, f"加载所有配置失败: {str(e)}")
    
    def _process_load_results(self, results: Dict[str, LoadResult]) -> None:
        """
        处理加载结果
        
        Args:
            results: 加载结果字典
        """
        for filename, result in results.items():
            if result.success and result.metadata:
                # 存储元数据
                self._metadata[filename] = result.metadata
                
                # 重新加载配置到内存
                self._reload_config_from_file(result.metadata.file_path)
            else:
                # 记录错误
                for error in result.errors:
                    logger.error(f"加载配置文件失败 {filename}: {error}")
    
    def _reload_config_from_file(self, file_path: str) -> None:
        """
        从文件重新加载配置
        
        Args:
            file_path: 配置文件路径
        """
        try:
            # 重新加载文件
            result = self._loader.load_config_file(file_path)
            
            if result.success and result.data:
                # 提取配置类和配置数据
                config_class = result.metadata.config_class
                config_data = result.data
                
                # 更新内存中的配置数据
                if config_class not in self._config_data:
                    self._config_data[config_class] = {}
                
                self._config_data[config_class].update(config_data)
                
                logger.info(f"重新加载配置文件: {file_path}")
            else:
                logger.error(f"重新加载配置文件失败: {file_path}")
                
        except Exception as e:
            logger.error(f"重新加载配置文件异常: {file_path} - {str(e)}")
    
    def get_config(self, config_class: Type[T], config_id: ConfigId) -> T:
        """
        获取单个配置
        
        Args:
            config_class: 配置类型
            config_id: 配置ID
            
        Returns:
            T: 配置对象
            
        Raises:
            ConfigNotFoundError: 配置未找到
        """
        try:
            with self._config_lock:
                # 尝试从缓存获取
                cache = self._get_cache(config_class)
                cached_config = cache.get(config_id)
                
                if cached_config is not None:
                    self._stats.cache_hits += 1
                    return cached_config
                
                # 从内存数据获取
                config_data = self._config_data.get(config_class, {})
                config = config_data.get(config_id)
                
                if config is None:
                    self._stats.cache_misses += 1
                    raise ConfigNotFoundError(config_class.__name__, config_id)
                
                # 添加到缓存
                cache.put(config_id, config)
                self._stats.cache_misses += 1
                
                return config
                
        except ConfigNotFoundError:
            raise
        except Exception as e:
            raise ConfigManagerError(f"获取配置失败: {str(e)}")
    
    def get_all_configs(self, config_class: Type[T]) -> Dict[ConfigId, T]:
        """
        获取某类型的所有配置
        
        Args:
            config_class: 配置类型
            
        Returns:
            Dict[ConfigId, T]: 配置字典
        """
        try:
            with self._config_lock:
                return self._config_data.get(config_class, {}).copy()
                
        except Exception as e:
            raise ConfigManagerError(f"获取所有配置失败: {str(e)}")
    
    def reload_config(self, config_class: Type[T]) -> None:
        """
        手动重载某类型的配置
        
        Args:
            config_class: 配置类型
        """
        try:
            with self._config_lock:
                # 清空缓存
                if config_class in self._cache:
                    self._cache[config_class].clear()
                
                # 重新加载配置
                self._reload_config_type(config_class)
                
                # 更新统计信息
                self._stats.reload_count += 1
                self._stats.last_reload_time = time.time()
                
            logger.info(f"重新加载配置类型: {config_class.__name__}")
            
        except Exception as e:
            raise ConfigManagerError(f"重载配置失败: {str(e)}")
    
    def _reload_config_type(self, config_class: Type[T]) -> None:
        """
        重新加载指定类型的配置
        
        Args:
            config_class: 配置类型
        """
        # 这里需要根据配置类型找到对应的文件并重新加载
        # 简化实现，实际中需要建立配置类型和文件的映射关系
        config_type_name = config_class.__name__.lower().replace('config', '')
        
        # 查找对应的配置文件
        config_files = self._loader.get_config_files(self.config_dir)
        for file_path in config_files:
            filename = os.path.basename(file_path).lower()
            if config_type_name in filename:
                self._reload_config_from_file(file_path)
                break
    
    def _get_cache(self, config_class: Type[T]) -> ConfigCache[T]:
        """
        获取配置缓存
        
        Args:
            config_class: 配置类型
            
        Returns:
            ConfigCache[T]: 配置缓存
        """
        if config_class not in self._cache:
            self._cache[config_class] = ConfigCache(self.cache_config)
        return self._cache[config_class]
    
    def _setup_hot_reload(self) -> None:
        """设置热更新"""
        try:
            self._hot_reload_manager = HotReloadManager(
                self.hot_reload_config,
                self.config_dir
            )
            
            # 添加重载回调
            self._hot_reload_manager.add_reload_callback(self._on_config_file_changed)
            
            # 启动热更新
            self._hot_reload_manager.start()
            
            self._stats.hot_reload_enabled = True
            logger.info("热更新功能已启用")
            
        except Exception as e:
            logger.error(f"设置热更新失败: {str(e)}")
    
    def _on_config_file_changed(self, file_path: str) -> None:
        """
        配置文件变化回调
        
        Args:
            file_path: 变化的文件路径
        """
        try:
            logger.info(f"配置文件变化: {file_path}")
            
            # 重新加载文件
            self._reload_config_from_file(file_path)
            
            # 清空相关缓存
            self._clear_related_cache(file_path)
            
            # 更新统计信息
            self._stats.reload_count += 1
            self._stats.last_reload_time = time.time()
            
        except Exception as e:
            logger.error(f"处理配置文件变化失败: {file_path} - {str(e)}")
    
    def _clear_related_cache(self, file_path: str) -> None:
        """
        清空相关缓存
        
        Args:
            file_path: 文件路径
        """
        try:
            # 根据文件名判断配置类型并清空对应缓存
            filename = os.path.basename(file_path).lower()
            
            for config_class in self._cache:
                config_type_name = config_class.__name__.lower().replace('config', '')
                if config_type_name in filename:
                    self._cache[config_class].clear()
                    logger.info(f"清空缓存: {config_class.__name__}")
                    break
                    
        except Exception as e:
            logger.error(f"清空相关缓存失败: {str(e)}")
    
    def _update_stats(self) -> None:
        """更新统计信息"""
        self._stats.total_configs = sum(len(configs) for configs in self._config_data.values())
        self._stats.loaded_files = len(self._metadata)
    
    def get_stats(self) -> ManagerStats:
        """
        获取统计信息
        
        Returns:
            ManagerStats: 统计信息
        """
        with self._config_lock:
            # 更新缓存统计
            total_hits = 0
            total_misses = 0
            
            for cache in self._cache.values():
                cache_stats = cache.stats()
                total_hits += cache_stats.hits
                total_misses += cache_stats.misses
            
            self._stats.cache_hits = total_hits
            self._stats.cache_misses = total_misses
            self._stats.hot_reload_enabled = (
                self._hot_reload_manager is not None and 
                self._hot_reload_manager.is_running()
            )
            
            return self._stats
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            Dict[str, Any]: 缓存统计信息
        """
        stats = {}
        
        with self._config_lock:
            for config_class, cache in self._cache.items():
                cache_stats = cache.stats()
                stats[config_class.__name__] = {
                    'hits': cache_stats.hits,
                    'misses': cache_stats.misses,
                    'hit_rate': cache_stats.hit_rate,
                    'size': cache_stats.size,
                    'max_size': cache_stats.max_size,
                    'evictions': cache_stats.evictions
                }
        
        return stats
    
    def clear_cache(self, config_class: Type[T] = None) -> None:
        """
        清空缓存
        
        Args:
            config_class: 配置类型，为None时清空所有缓存
        """
        with self._config_lock:
            if config_class is None:
                # 清空所有缓存
                for cache in self._cache.values():
                    cache.clear()
                logger.info("清空所有缓存")
            else:
                # 清空指定类型的缓存
                if config_class in self._cache:
                    self._cache[config_class].clear()
                    logger.info(f"清空缓存: {config_class.__name__}")
    
    def cleanup_expired_cache(self) -> int:
        """
        清理过期缓存
        
        Returns:
            int: 清理的项目数量
        """
        total_cleaned = 0
        
        with self._config_lock:
            for cache in self._cache.values():
                cleaned = cache.cleanup_expired()
                total_cleaned += cleaned
        
        if total_cleaned > 0:
            logger.info(f"清理过期缓存: {total_cleaned} 项")
        
        return total_cleaned
    
    def shutdown(self) -> None:
        """关闭配置表管理器"""
        try:
            # 停止热更新
            if self._hot_reload_manager:
                self._hot_reload_manager.stop()
                self._hot_reload_manager = None
            
            # 清空缓存
            self.clear_cache()
            
            # 清空数据
            with self._config_lock:
                self._config_data.clear()
                self._metadata.clear()
            
            logger.info("配置表管理器已关闭")
            
        except Exception as e:
            logger.error(f"关闭配置表管理器失败: {str(e)}")
    
    def get_config_metadata(self, filename: str) -> Optional[ConfigMetadata]:
        """
        获取配置元数据
        
        Args:
            filename: 文件名
            
        Returns:
            Optional[ConfigMetadata]: 配置元数据
        """
        return self._metadata.get(filename)
    
    def list_config_files(self) -> List[str]:
        """
        列出所有配置文件
        
        Returns:
            List[str]: 配置文件列表
        """
        return list(self._metadata.keys())
    
    def validate_config_file(self, file_path: str) -> List[str]:
        """
        验证配置文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            List[str]: 验证错误列表
        """
        return self._loader.validate_config_file(file_path)
    
    def add_config_type(self, config_type: str, config_class: Type[BaseConfig]) -> None:
        """
        添加配置类型
        
        Args:
            config_type: 配置类型名称
            config_class: 配置类
        """
        self._loader.add_config_type(config_type, config_class)
        logger.info(f"添加配置类型: {config_type}")
    
    def force_reload_file(self, file_path: str) -> None:
        """
        强制重新加载文件
        
        Args:
            file_path: 文件路径
        """
        if self._hot_reload_manager:
            self._hot_reload_manager.force_reload(file_path)
        else:
            self._reload_config_from_file(file_path)
    
    def enable_hot_reload(self) -> None:
        """启用热更新"""
        if not self._hot_reload_manager:
            self._setup_hot_reload()
        elif not self._hot_reload_manager.is_running():
            self._hot_reload_manager.start()
    
    def disable_hot_reload(self) -> None:
        """禁用热更新"""
        if self._hot_reload_manager:
            self._hot_reload_manager.stop()
    
    def is_hot_reload_enabled(self) -> bool:
        """检查热更新是否启用"""
        return (
            self._hot_reload_manager is not None and 
            self._hot_reload_manager.is_running()
        )


# 全局实例
table_manager = TableManager.get_instance()