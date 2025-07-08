"""
环境管理器

该模块提供环境管理功能，根据环境变量自动选择配置，
提供获取当前配置的全局接口，并支持配置的热更新通知。
"""

import os
import threading
import time
from typing import Dict, Any, Optional, Type, Callable, List
from enum import Enum
from loguru import logger

from .config import BaseConfig, ConfigError
from .development import DevelopmentConfig
from .production import ProductionConfig


class Environment(Enum):
    """环境枚举"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"
    STAGING = "staging"


class ConfigChangeEvent:
    """配置变更事件"""
    
    def __init__(self, old_config: Dict[str, Any], new_config: Dict[str, Any], 
                 changed_keys: List[str]):
        """
        初始化配置变更事件
        
        Args:
            old_config: 旧配置
            new_config: 新配置
            changed_keys: 变更的配置键列表
        """
        self.old_config = old_config
        self.new_config = new_config
        self.changed_keys = changed_keys
        self.timestamp = time.time()


class EnvironmentManager:
    """
    环境管理器
    
    负责环境检测、配置加载、配置热更新和变更通知。
    """
    
    _instance: Optional['EnvironmentManager'] = None
    _lock = threading.Lock()
    
    def __init__(self):
        """初始化环境管理器"""
        self._environment: Optional[Environment] = None
        self._config: Optional[BaseConfig] = None
        self._config_class_map: Dict[Environment, Type[BaseConfig]] = {
            Environment.DEVELOPMENT: DevelopmentConfig,
            Environment.PRODUCTION: ProductionConfig,
            Environment.TESTING: DevelopmentConfig,  # 测试环境使用开发配置
            Environment.STAGING: ProductionConfig,   # 预发环境使用生产配置
        }
        self._change_handlers: List[Callable[[ConfigChangeEvent], None]] = []
        self._hot_reload_enabled = False
        self._reload_thread: Optional[threading.Thread] = None
        self._stop_reload = threading.Event()
        
    @classmethod
    def get_instance(cls) -> 'EnvironmentManager':
        """
        获取环境管理器单例实例
        
        Returns:
            EnvironmentManager: 环境管理器实例
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def detect_environment(self) -> Environment:
        """
        检测当前环境
        
        优先级：ENV环境变量 > ENVIRONMENT环境变量 > PYTHON_ENV环境变量 > 默认开发环境
        
        Returns:
            Environment: 当前环境
        """
        # 检查多个可能的环境变量
        env_vars = ['ENV', 'ENVIRONMENT', 'PYTHON_ENV', 'APP_ENV']
        
        for env_var in env_vars:
            env_value = os.getenv(env_var, '').lower()
            if env_value:
                try:
                    environment = Environment(env_value)
                    logger.info(f"检测到环境: {environment.value} (来源: {env_var})")
                    return environment
                except ValueError:
                    logger.warning(f"无效的环境值: {env_value} (来源: {env_var})")
                    continue
        
        # 默认开发环境
        logger.info("未检测到环境配置，使用默认开发环境")
        return Environment.DEVELOPMENT
    
    def initialize(self, environment: Optional[Environment] = None, 
                  config_file: Optional[str] = None) -> None:
        """
        初始化环境管理器
        
        Args:
            environment: 指定环境，如果为None则自动检测
            config_file: 配置文件路径
        """
        try:
            # 确定环境
            self._environment = environment or self.detect_environment()
            
            # 获取配置类
            config_class = self._config_class_map.get(self._environment)
            if not config_class:
                raise ConfigError(f"不支持的环境: {self._environment}")
            
            # 加载配置
            self._config = config_class.get_instance()
            if config_file:
                self._config.load(config_file)
            
            logger.info(f"环境管理器初始化完成: {self._environment.value}")
            
        except Exception as e:
            logger.error(f"环境管理器初始化失败: {e}")
            raise ConfigError(f"环境管理器初始化失败: {e}")
    
    def get_config(self) -> BaseConfig:
        """
        获取当前配置
        
        Returns:
            BaseConfig: 当前配置实例
            
        Raises:
            ConfigError: 如果环境管理器未初始化
        """
        if self._config is None:
            raise ConfigError("环境管理器未初始化，请先调用initialize()方法")
        return self._config
    
    def get_environment(self) -> Environment:
        """
        获取当前环境
        
        Returns:
            Environment: 当前环境
            
        Raises:
            ConfigError: 如果环境管理器未初始化
        """
        if self._environment is None:
            raise ConfigError("环境管理器未初始化，请先调用initialize()方法")
        return self._environment
    
    def is_development(self) -> bool:
        """
        检查是否为开发环境
        
        Returns:
            bool: 是否为开发环境
        """
        return self.get_environment() == Environment.DEVELOPMENT
    
    def is_production(self) -> bool:
        """
        检查是否为生产环境
        
        Returns:
            bool: 是否为生产环境
        """
        return self.get_environment() == Environment.PRODUCTION
    
    def is_testing(self) -> bool:
        """
        检查是否为测试环境
        
        Returns:
            bool: 是否为测试环境
        """
        return self.get_environment() == Environment.TESTING
    
    def is_staging(self) -> bool:
        """
        检查是否为预发环境
        
        Returns:
            bool: 是否为预发环境
        """
        return self.get_environment() == Environment.STAGING
    
    def register_config_class(self, environment: Environment, 
                            config_class: Type[BaseConfig]) -> None:
        """
        注册配置类
        
        Args:
            environment: 环境
            config_class: 配置类
        """
        self._config_class_map[environment] = config_class
        logger.info(f"注册配置类: {environment.value} -> {config_class.__name__}")
    
    def add_change_handler(self, handler: Callable[[ConfigChangeEvent], None]) -> None:
        """
        添加配置变更处理器
        
        Args:
            handler: 变更处理器函数
        """
        self._change_handlers.append(handler)
        logger.debug(f"添加配置变更处理器: {handler.__name__}")
    
    def remove_change_handler(self, handler: Callable[[ConfigChangeEvent], None]) -> None:
        """
        移除配置变更处理器
        
        Args:
            handler: 变更处理器函数
        """
        if handler in self._change_handlers:
            self._change_handlers.remove(handler)
            logger.debug(f"移除配置变更处理器: {handler.__name__}")
    
    def reload_config(self) -> bool:
        """
        重新加载配置
        
        Returns:
            bool: 是否成功重载
        """
        if self._config is None:
            logger.warning("配置未初始化，无法重载")
            return False
        
        try:
            # 保存旧配置
            old_config = self._config.to_dict()
            
            # 重新加载配置
            success = self._config.reload()
            
            if success:
                # 获取新配置
                new_config = self._config.to_dict()
                
                # 找出变更的键
                changed_keys = self._find_changed_keys(old_config, new_config)
                
                if changed_keys:
                    # 触发变更事件
                    event = ConfigChangeEvent(old_config, new_config, changed_keys)
                    self._notify_config_change(event)
                    
                    logger.info(f"配置重载成功，变更键: {changed_keys}")
                else:
                    logger.info("配置重载成功，无变更")
            
            return success
            
        except Exception as e:
            logger.error(f"配置重载失败: {e}")
            return False
    
    def enable_hot_reload(self, interval: float = 30.0) -> None:
        """
        启用配置热更新
        
        Args:
            interval: 检查间隔（秒）
        """
        if self._hot_reload_enabled:
            logger.warning("热更新已启用")
            return
        
        self._hot_reload_enabled = True
        self._stop_reload.clear()
        
        def reload_worker():
            """热更新工作线程"""
            while not self._stop_reload.wait(interval):
                try:
                    self.reload_config()
                except Exception as e:
                    logger.error(f"热更新失败: {e}")
        
        self._reload_thread = threading.Thread(target=reload_worker, daemon=True)
        self._reload_thread.start()
        
        logger.info(f"配置热更新已启用，检查间隔: {interval}秒")
    
    def disable_hot_reload(self) -> None:
        """禁用配置热更新"""
        if not self._hot_reload_enabled:
            return
        
        self._hot_reload_enabled = False
        self._stop_reload.set()
        
        if self._reload_thread and self._reload_thread.is_alive():
            self._reload_thread.join(timeout=5.0)
        
        logger.info("配置热更新已禁用")
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        获取配置值的便捷方法
        
        Args:
            key: 配置键
            default: 默认值
            
        Returns:
            Any: 配置值
        """
        return self.get_config().get(key, default)
    
    def set_config_value(self, key: str, value: Any) -> None:
        """
        设置配置值的便捷方法
        
        Args:
            key: 配置键
            value: 配置值
        """
        old_config = self.get_config().to_dict()
        self.get_config().set(key, value)
        new_config = self.get_config().to_dict()
        
        # 触发变更事件
        changed_keys = [key]
        event = ConfigChangeEvent(old_config, new_config, changed_keys)
        self._notify_config_change(event)
    
    def _find_changed_keys(self, old_config: Dict[str, Any], 
                          new_config: Dict[str, Any], prefix: str = '') -> List[str]:
        """
        找出变更的配置键
        
        Args:
            old_config: 旧配置
            new_config: 新配置
            prefix: 键前缀
            
        Returns:
            List[str]: 变更的键列表
        """
        changed_keys = []
        
        # 检查新增和修改的键
        for key, value in new_config.items():
            full_key = f"{prefix}.{key}" if prefix else key
            
            if key not in old_config:
                changed_keys.append(full_key)
            elif isinstance(value, dict) and isinstance(old_config[key], dict):
                changed_keys.extend(
                    self._find_changed_keys(old_config[key], value, full_key)
                )
            elif old_config[key] != value:
                changed_keys.append(full_key)
        
        # 检查删除的键
        for key in old_config:
            if key not in new_config:
                full_key = f"{prefix}.{key}" if prefix else key
                changed_keys.append(full_key)
        
        return changed_keys
    
    def _notify_config_change(self, event: ConfigChangeEvent) -> None:
        """
        通知配置变更
        
        Args:
            event: 配置变更事件
        """
        for handler in self._change_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"配置变更处理器执行失败: {handler.__name__}: {e}")


# 全局环境管理器实例
env_manager = EnvironmentManager.get_instance()


# 便捷函数
def initialize_environment(environment: Optional[Environment] = None, 
                         config_file: Optional[str] = None) -> None:
    """
    初始化环境的便捷函数
    
    Args:
        environment: 指定环境
        config_file: 配置文件路径
    """
    env_manager.initialize(environment, config_file)


def get_config() -> BaseConfig:
    """
    获取当前配置的便捷函数
    
    Returns:
        BaseConfig: 当前配置实例
    """
    return env_manager.get_config()


def get_environment() -> Environment:
    """
    获取当前环境的便捷函数
    
    Returns:
        Environment: 当前环境
    """
    return env_manager.get_environment()


def is_development() -> bool:
    """检查是否为开发环境"""
    return env_manager.is_development()


def is_production() -> bool:
    """检查是否为生产环境"""
    return env_manager.is_production()


def is_testing() -> bool:
    """检查是否为测试环境"""
    return env_manager.is_testing()


def is_staging() -> bool:
    """检查是否为预发环境"""
    return env_manager.is_staging()


def get_config_value(key: str, default: Any = None) -> Any:
    """
    获取配置值的便捷函数
    
    Args:
        key: 配置键
        default: 默认值
        
    Returns:
        Any: 配置值
    """
    return env_manager.get_config_value(key, default)


def set_config_value(key: str, value: Any) -> None:
    """
    设置配置值的便捷函数
    
    Args:
        key: 配置键
        value: 配置值
    """
    env_manager.set_config_value(key, value)


def enable_hot_reload(interval: float = 30.0) -> None:
    """
    启用配置热更新的便捷函数
    
    Args:
        interval: 检查间隔（秒）
    """
    env_manager.enable_hot_reload(interval)


def disable_hot_reload() -> None:
    """禁用配置热更新的便捷函数"""
    env_manager.disable_hot_reload()


def add_config_change_handler(handler: Callable[[ConfigChangeEvent], None]) -> None:
    """
    添加配置变更处理器的便捷函数
    
    Args:
        handler: 变更处理器函数
    """
    env_manager.add_change_handler(handler)


# 默认配置变更处理器示例
def default_config_change_handler(event: ConfigChangeEvent) -> None:
    """
    默认配置变更处理器
    
    Args:
        event: 配置变更事件
    """
    logger.info(f"配置变更检测: {len(event.changed_keys)} 个键发生变化")
    for key in event.changed_keys:
        old_value = event.old_config.get(key.replace('.', '_'), 'N/A')  # 简化处理
        new_value = event.new_config.get(key.replace('.', '_'), 'N/A')
        logger.debug(f"  {key}: {old_value} -> {new_value}")


# 注册默认处理器
add_config_change_handler(default_config_change_handler)