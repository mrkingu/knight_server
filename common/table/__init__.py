"""
配置表管理模块

该模块提供了配置表的加载、缓存、热更新等功能。

主要功能：
- 配置加载：支持从JSON文件加载配置并转换为Python对象
- 配置缓存：提供LRU、LFU等多种缓存策略
- 热更新：监控文件变化并自动重新加载配置
- 类型安全：支持泛型，确保类型安全访问
- 线程安全：支持多线程环境下的安全访问

使用示例：
```python
from common.table import TableManager, ItemConfig

# 获取单个配置
config = TableManager.get_config(ItemConfig, item_id=1001)

# 获取某类型的所有配置
all_items = TableManager.get_all_configs(ItemConfig)

# 手动重载配置
TableManager.reload_config(ItemConfig)
```
"""

from .table_manager import TableManager, table_manager
from .types import (
    BaseConfig, ItemConfig, SkillConfig, ConfigId, ConfigType,
    ConfigMetadata, CacheConfig, LoaderConfig, HotReloadConfig,
    CacheStrategy, ConfigRegistry
)
from .table_loader import ConfigLoader, LoadResult
from .table_cache import ConfigCache, CacheStats
from .hot_reload import HotReloadManager, ReloadEvent, ReloadEventType
from .exceptions import (
    TableError, ConfigNotFoundError, ConfigLoadError,
    ConfigValidationError, ConfigTypeError, HotReloadError,
    CacheError, ConfigManagerError, SchemaValidationError
)

__all__ = [
    # 主要类
    'TableManager',
    'table_manager',
    
    # 配置类型
    'BaseConfig',
    'ItemConfig', 
    'SkillConfig',
    'ConfigId',
    'ConfigType',
    
    # 配置类
    'ConfigMetadata',
    'CacheConfig',
    'LoaderConfig', 
    'HotReloadConfig',
    'CacheStrategy',
    'ConfigRegistry',
    
    # 加载器
    'ConfigLoader',
    'LoadResult',
    
    # 缓存
    'ConfigCache',
    'CacheStats',
    
    # 热更新
    'HotReloadManager',
    'ReloadEvent',
    'ReloadEventType',
    
    # 异常
    'TableError',
    'ConfigNotFoundError',
    'ConfigLoadError',
    'ConfigValidationError',
    'ConfigTypeError',
    'HotReloadError',
    'CacheError',
    'ConfigManagerError',
    'SchemaValidationError'
]
