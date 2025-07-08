"""
日志工厂模块

该模块提供日志工厂类，负责创建和管理日志实例，
支持单例模式、延迟初始化和动态配置。
"""

import threading
from typing import Dict, Optional, Type, Any
from pathlib import Path

from ..utils.singleton import SingletonMeta
from .logger_config import LoggerConfig, LoggerConfigManager, config_manager
from .base_logger import BaseLogger


class LoggerFactory(metaclass=SingletonMeta):
    """
    日志工厂类
    
    负责创建和管理不同类型的日志实例，支持单例模式、
    延迟初始化和配置管理。
    """
    
    def __init__(self):
        """初始化日志工厂"""
        self._loggers: Dict[str, BaseLogger] = {}
        self._config_manager = config_manager
        self._lock = threading.Lock()
        self._initialized = False
        
        # 服务信息
        self._service_name: Optional[str] = None
        self._service_port: Optional[int] = None
    
    def initialize(self, service_type: str = "default", port: int = 8000, 
                   config_dict: Optional[Dict[str, Any]] = None) -> None:
        """
        初始化日志工厂
        
        Args:
            service_type: 服务类型（如 gate, logic, battle）
            port: 服务端口号
            config_dict: 自定义配置字典
        """
        with self._lock:
            if self._initialized:
                return
            
            self._service_name = service_type
            self._service_port = port
            
            # 设置默认配置
            default_config = LoggerConfig(
                service_name=service_type,
                service_port=port,
            )
            self._config_manager.set_default_config(default_config)
            
            # 如果提供了配置字典，加载配置
            if config_dict:
                self._config_manager.load_from_dict(config_dict)
            
            # 更新所有配置的服务信息
            self._config_manager.update_service_info(service_type, port)
            
            self._initialized = True
    
    def get_logger(self, logger_type: str = "general") -> BaseLogger:
        """
        获取日志器实例
        
        Args:
            logger_type: 日志器类型（general, sls, battle）
            
        Returns:
            BaseLogger: 日志器实例
        """
        # 确保工厂已初始化
        if not self._initialized:
            self.initialize()
        
        # 检查是否已存在该类型的日志器
        if logger_type in self._loggers:
            return self._loggers[logger_type]
        
        with self._lock:
            # 双重检查锁定
            if logger_type in self._loggers:
                return self._loggers[logger_type]
            
            # 获取配置
            config = self._config_manager.get_config(logger_type)
            
            # 创建日志器
            logger = self._create_logger(logger_type, config)
            self._loggers[logger_type] = logger
            
            return logger
    
    def _create_logger(self, logger_type: str, config: LoggerConfig) -> BaseLogger:
        """
        创建指定类型的日志器
        
        Args:
            logger_type: 日志器类型
            config: 日志配置
            
        Returns:
            BaseLogger: 日志器实例
        """
        # 根据类型创建不同的日志器
        if logger_type == "sls":
            from .sls_logger import SLSLogger
            return SLSLogger(logger_type, config)
        elif logger_type == "battle":
            from .battle_logger import BattleLogger
            return BattleLogger(logger_type, config)
        else:
            # 默认创建基础日志器
            return BaseLogger(logger_type, config)
    
    def create_custom_logger(self, name: str, config: LoggerConfig) -> BaseLogger:
        """
        创建自定义日志器
        
        Args:
            name: 日志器名称
            config: 日志配置
            
        Returns:
            BaseLogger: 日志器实例
        """
        with self._lock:
            if name in self._loggers:
                return self._loggers[name]
            
            logger = BaseLogger(name, config)
            self._loggers[name] = logger
            return logger
    
    def get_or_create_logger(self, logger_type: str, 
                           custom_config: Optional[LoggerConfig] = None) -> BaseLogger:
        """
        获取或创建日志器
        
        Args:
            logger_type: 日志器类型
            custom_config: 自定义配置（可选）
            
        Returns:
            BaseLogger: 日志器实例
        """
        if custom_config:
            return self.create_custom_logger(logger_type, custom_config)
        else:
            return self.get_logger(logger_type)
    
    def set_logger_level(self, logger_type: str, level: str) -> None:
        """
        设置日志器级别
        
        Args:
            logger_type: 日志器类型
            level: 日志级别
        """
        if logger_type in self._loggers:
            self._loggers[logger_type].set_level(level)
        
        # 同时更新配置管理器中的配置
        config = self._config_manager.get_config(logger_type)
        from .logger_config import LogLevel
        config.level = LogLevel(level.upper())
    
    def set_global_level(self, level: str) -> None:
        """
        设置全局日志级别
        
        Args:
            level: 日志级别
        """
        from .logger_config import LogLevel
        log_level = LogLevel(level.upper())
        
        # 更新默认配置
        self._config_manager.get_default_config().level = log_level
        
        # 更新所有已创建的日志器
        for logger in self._loggers.values():
            logger.set_level(level)
    
    def reload_config(self, config_dict: Dict[str, Any]) -> None:
        """
        重新加载配置
        
        Args:
            config_dict: 新的配置字典
        """
        with self._lock:
            # 关闭现有日志器
            for logger in self._loggers.values():
                logger.close()
            
            # 清空日志器缓存
            self._loggers.clear()
            
            # 重新加载配置
            self._config_manager.load_from_dict(config_dict)
            
            # 更新服务信息
            if self._service_name and self._service_port:
                self._config_manager.update_service_info(
                    self._service_name, self._service_port
                )
    
    def get_logger_info(self) -> Dict[str, Any]:
        """
        获取日志器信息
        
        Returns:
            Dict: 日志器信息
        """
        return {
            'service_name': self._service_name,
            'service_port': self._service_port,
            'initialized': self._initialized,
            'logger_count': len(self._loggers),
            'logger_types': list(self._loggers.keys()),
        }
    
    def cleanup(self) -> None:
        """清理资源"""
        with self._lock:
            for logger in self._loggers.values():
                logger.close()
            self._loggers.clear()
            self._initialized = False
    
    def __del__(self):
        """析构函数"""
        try:
            self.cleanup()
        except:
            pass


# 全局日志工厂实例
logger_factory = LoggerFactory()


# 便捷函数
def get_logger(logger_type: str = "general") -> BaseLogger:
    """
    获取日志器的便捷函数
    
    Args:
        logger_type: 日志器类型
        
    Returns:
        BaseLogger: 日志器实例
    """
    return logger_factory.get_logger(logger_type)


def initialize_logging(service_type: str = "default", port: int = 8000,
                      config_dict: Optional[Dict[str, Any]] = None) -> None:
    """
    初始化日志系统的便捷函数
    
    Args:
        service_type: 服务类型
        port: 服务端口
        config_dict: 配置字典
    """
    logger_factory.initialize(service_type, port, config_dict)


def set_global_log_level(level: str) -> None:
    """
    设置全局日志级别的便捷函数
    
    Args:
        level: 日志级别
    """
    logger_factory.set_global_level(level)


def get_logger_factory() -> LoggerFactory:
    """
    获取日志工厂实例
    
    Returns:
        LoggerFactory: 日志工厂实例
    """
    return logger_factory