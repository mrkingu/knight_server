"""
配置管理模块

该模块提供了配置管理的基础类，支持从环境变量和配置文件加载配置，
配置验证和默认值设置，以及配置的动态重载功能。
"""

import os
import json
import yaml
from typing import Any, Dict, Optional, Type, TypeVar, get_type_hints
from abc import ABC, abstractmethod
from pathlib import Path
from pydantic import BaseModel, ValidationError
from loguru import logger

T = TypeVar('T', bound='BaseConfig')


class ConfigError(Exception):
    """配置相关异常"""
    pass


class BaseConfig(ABC):
    """
    配置基类
    
    提供配置加载、验证、缓存和动态重载的基础功能。
    所有具体配置类都应该继承此类。
    """
    
    _instance: Optional['BaseConfig'] = None
    _config_cache: Dict[str, Any] = {}
    _file_watchers: Dict[str, float] = {}
    
    def __init__(self):
        """初始化配置"""
        self._config_data: Dict[str, Any] = {}
        self._env_prefix: str = self.__class__.__name__.upper().replace('CONFIG', '')
        self._config_file: Optional[str] = None
        self._auto_reload: bool = False
        
    @classmethod
    def get_instance(cls: Type[T]) -> T:
        """
        获取配置单例实例
        
        Returns:
            T: 配置实例
        """
        if cls._instance is None:
            cls._instance = cls()
            cls._instance.load()
        return cls._instance
    
    @abstractmethod
    def get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置
        
        子类必须实现此方法来提供默认配置值
        
        Returns:
            Dict[str, Any]: 默认配置字典
        """
        pass
    
    def load(self, config_file: Optional[str] = None) -> None:
        """
        加载配置
        
        按优先级顺序：环境变量 > 配置文件 > 默认配置
        
        Args:
            config_file: 配置文件路径
        """
        try:
            # 1. 加载默认配置
            self._config_data = self.get_default_config().copy()
            
            # 2. 从配置文件加载
            if config_file:
                self._config_file = config_file
                file_config = self._load_from_file(config_file)
                self._merge_config(file_config)
            
            # 3. 从环境变量加载
            env_config = self._load_from_env()
            self._merge_config(env_config)
            
            # 4. 验证配置
            self._validate_config()
            
            logger.info(f"配置加载成功: {self.__class__.__name__}")
            
        except Exception as e:
            logger.error(f"配置加载失败: {e}")
            raise ConfigError(f"配置加载失败: {e}")
    
    def reload(self) -> bool:
        """
        重新加载配置
        
        Returns:
            bool: 是否成功重载
        """
        try:
            old_config = self._config_data.copy()
            self.load(self._config_file)
            
            # 检查配置是否有变化
            if old_config != self._config_data:
                logger.info(f"配置已更新: {self.__class__.__name__}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"配置重载失败: {e}")
            return False
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点分隔的嵌套键
            default: 默认值
            
        Returns:
            Any: 配置值
        """
        keys = key.split('.')
        value = self._config_data
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        设置配置值
        
        Args:
            key: 配置键，支持点分隔的嵌套键
            value: 配置值
        """
        keys = key.split('.')
        config = self._config_data
        
        # 创建嵌套字典路径
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return self._config_data.copy()
    
    def enable_auto_reload(self, interval: float = 5.0) -> None:
        """
        启用自动重载
        
        Args:
            interval: 检查间隔（秒）
        """
        self._auto_reload = True
        # 这里可以实现文件监控逻辑
        logger.info(f"配置自动重载已启用，检查间隔: {interval}秒")
    
    def _load_from_file(self, config_file: str) -> Dict[str, Any]:
        """
        从文件加载配置
        
        Args:
            config_file: 配置文件路径
            
        Returns:
            Dict[str, Any]: 配置字典
        """
        file_path = Path(config_file)
        
        if not file_path.exists():
            logger.warning(f"配置文件不存在: {config_file}")
            return {}
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                if file_path.suffix.lower() in ['.yml', '.yaml']:
                    return yaml.safe_load(f) or {}
                elif file_path.suffix.lower() == '.json':
                    return json.load(f) or {}
                else:
                    logger.warning(f"不支持的配置文件格式: {file_path.suffix}")
                    return {}
                    
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            raise ConfigError(f"读取配置文件失败: {e}")
    
    def _load_from_env(self) -> Dict[str, Any]:
        """
        从环境变量加载配置
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        env_config = {}
        prefix = f"{self._env_prefix}_"
        
        for key, value in os.environ.items():
            if key.startswith(prefix):
                # 移除前缀并转换为小写
                config_key = key[len(prefix):].lower()
                
                # 处理嵌套键（使用双下划线分隔）
                if '__' in config_key:
                    config_key = config_key.replace('__', '.')
                
                # 尝试转换数据类型
                env_config[config_key] = self._convert_env_value(value)
        
        return env_config
    
    def _convert_env_value(self, value: str) -> Any:
        """
        转换环境变量值的数据类型
        
        Args:
            value: 环境变量值
            
        Returns:
            Any: 转换后的值
        """
        # 布尔值
        if value.lower() in ('true', 'yes', '1', 'on'):
            return True
        elif value.lower() in ('false', 'no', '0', 'off'):
            return False
        
        # 数字
        try:
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass
        
        # JSON
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            pass
        
        # 字符串
        return value
    
    def _merge_config(self, new_config: Dict[str, Any]) -> None:
        """
        合并配置
        
        Args:
            new_config: 新配置字典
        """
        def merge_dict(target: dict, source: dict) -> dict:
            """递归合并字典"""
            for key, value in source.items():
                if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                    merge_dict(target[key], value)
                else:
                    target[key] = value
            return target
        
        merge_dict(self._config_data, new_config)
    
    def _validate_config(self) -> None:
        """
        验证配置
        
        子类可以重写此方法来实现自定义验证逻辑
        """
        # 基础验证：检查必需的配置项
        required_keys = getattr(self, '_required_keys', [])
        
        for key in required_keys:
            if self.get(key) is None:
                raise ConfigError(f"缺少必需的配置项: {key}")
        
        logger.debug("配置验证通过")


class PydanticConfig(BaseConfig):
    """
    基于Pydantic的配置类
    
    提供强类型配置验证和自动类型转换
    """
    
    def __init__(self, model_class: Type[BaseModel]):
        """
        初始化
        
        Args:
            model_class: Pydantic模型类
        """
        super().__init__()
        self._model_class = model_class
        self._model_instance: Optional[BaseModel] = None
    
    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        # 从Pydantic模型的字段默认值生成默认配置
        defaults = {}
        for field_name, field_info in self._model_class.__fields__.items():
            if field_info.default is not None:
                defaults[field_name] = field_info.default
        return defaults
    
    def _validate_config(self) -> None:
        """使用Pydantic验证配置"""
        try:
            self._model_instance = self._model_class(**self._config_data)
            # 更新配置数据为验证后的值
            self._config_data = self._model_instance.dict()
            logger.debug("Pydantic配置验证通过")
            
        except ValidationError as e:
            logger.error(f"配置验证失败: {e}")
            raise ConfigError(f"配置验证失败: {e}")
    
    @property
    def model(self) -> BaseModel:
        """
        获取Pydantic模型实例
        
        Returns:
            BaseModel: 模型实例
        """
        if self._model_instance is None:
            raise ConfigError("配置尚未加载或验证失败")
        return self._model_instance


def load_config(config_class: Type[T], config_file: Optional[str] = None) -> T:
    """
    加载配置的便捷函数
    
    Args:
        config_class: 配置类
        config_file: 配置文件路径
        
    Returns:
        T: 配置实例
    """
    config = config_class.get_instance()
    if config_file:
        config.load(config_file)
    return config


# 注册中心配置示例
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