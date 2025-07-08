"""
配置表类型定义模块

定义配置表相关的类型、泛型和基础类。
"""

from typing import TypeVar, Generic, Dict, Any, Optional, Type, Union
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

# 泛型类型变量
T = TypeVar('T', bound='BaseConfig')
ConfigId = Union[int, str]

class ConfigType(Enum):
    """配置类型枚举"""
    ITEM = "item"
    SKILL = "skill"
    MONSTER = "monster"
    LEVEL = "level"
    SYSTEM = "system"


@dataclass
class ConfigMetadata:
    """配置元数据"""
    file_path: str
    config_type: ConfigType
    last_modified: float
    version: str = "1.0.0"
    checksum: Optional[str] = None


class BaseConfig(ABC):
    """
    配置基类
    
    所有配置表类都应该继承这个基类
    """
    
    def __init__(self, **kwargs):
        """
        初始化配置
        
        Args:
            **kwargs: 配置数据
        """
        self._data = kwargs
        self._validate()
    
    @abstractmethod
    def get_id(self) -> ConfigId:
        """
        获取配置ID
        
        Returns:
            ConfigId: 配置的唯一标识
        """
        pass
    
    @abstractmethod
    def _validate(self) -> None:
        """
        验证配置数据的有效性
        
        Raises:
            ValueError: 配置数据无效时抛出
        """
        pass
    
    def get_data(self) -> Dict[str, Any]:
        """
        获取配置数据
        
        Returns:
            Dict[str, Any]: 配置数据字典
        """
        return self._data.copy()
    
    def __getattr__(self, name: str) -> Any:
        """
        支持属性访问方式获取配置数据
        
        Args:
            name: 属性名
            
        Returns:
            Any: 属性值
        """
        if name in self._data:
            return self._data[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


class ItemConfig(BaseConfig):
    """
    物品配置表
    
    示例配置类
    """
    
    def get_id(self) -> ConfigId:
        """获取物品ID"""
        return self._data.get('id', 0)
    
    def _validate(self) -> None:
        """验证物品配置"""
        if 'id' not in self._data:
            raise ValueError("物品配置缺少ID字段")
        if 'name' not in self._data:
            raise ValueError("物品配置缺少名称字段")
        if not isinstance(self._data['id'], int):
            raise ValueError("物品ID必须是整数")


class SkillConfig(BaseConfig):
    """
    技能配置表
    
    示例配置类
    """
    
    def get_id(self) -> ConfigId:
        """获取技能ID"""
        return self._data.get('id', 0)
    
    def _validate(self) -> None:
        """验证技能配置"""
        if 'id' not in self._data:
            raise ValueError("技能配置缺少ID字段")
        if 'name' not in self._data:
            raise ValueError("技能配置缺少名称字段")
        if not isinstance(self._data['id'], int):
            raise ValueError("技能ID必须是整数")


class CacheStrategy(Enum):
    """缓存策略枚举"""
    LRU = "lru"          # 最近最少使用
    LFU = "lfu"          # 最少使用频率
    FIFO = "fifo"        # 先进先出
    NO_CACHE = "no_cache" # 不缓存


@dataclass
class CacheConfig:
    """缓存配置"""
    strategy: CacheStrategy = CacheStrategy.LRU
    max_size: int = 1000
    ttl: Optional[float] = None  # 生存时间(秒)
    enable_stats: bool = True


@dataclass
class LoaderConfig:
    """加载器配置"""
    config_dir: str = "json_data"
    file_pattern: str = "*.json"
    encoding: str = "utf-8"
    validate_schema: bool = True
    auto_reload: bool = True
    reload_interval: float = 1.0  # 文件检查间隔(秒)


@dataclass
class HotReloadConfig:
    """热更新配置"""
    enabled: bool = True
    watch_recursive: bool = True
    ignore_patterns: list = None
    debounce_delay: float = 0.5  # 防抖延迟(秒)
    
    def __post_init__(self):
        if self.ignore_patterns is None:
            self.ignore_patterns = ["*.tmp", "*.bak", "*~"]


class ConfigRegistry:
    """
    配置注册表
    
    用于注册和查找配置类
    """
    
    _registry: Dict[str, Type[BaseConfig]] = {}
    
    @classmethod
    def register(cls, config_name: str, config_class: Type[BaseConfig]) -> None:
        """
        注册配置类
        
        Args:
            config_name: 配置名称
            config_class: 配置类
        """
        cls._registry[config_name] = config_class
    
    @classmethod
    def get(cls, config_name: str) -> Optional[Type[BaseConfig]]:
        """
        获取配置类
        
        Args:
            config_name: 配置名称
            
        Returns:
            Optional[Type[BaseConfig]]: 配置类，如果不存在则返回None
        """
        return cls._registry.get(config_name)
    
    @classmethod
    def list_configs(cls) -> list:
        """
        列出所有已注册的配置
        
        Returns:
            list: 配置名称列表
        """
        return list(cls._registry.keys())


# 自动注册示例配置类
ConfigRegistry.register("item", ItemConfig)
ConfigRegistry.register("skill", SkillConfig)