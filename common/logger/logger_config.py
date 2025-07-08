"""
日志配置模块

该模块提供了日志系统的配置管理功能，支持从环境变量和配置文件读取配置，
包括日志级别、格式、轮转策略等。
"""

import os
import json
from typing import Dict, Any, Optional, Union
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum


class LogLevel(Enum):
    """日志级别枚举"""
    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class RotationConfig:
    """日志轮转配置"""
    # 按文件大小轮转
    size: Optional[str] = "100 MB"
    # 按时间轮转
    time: Optional[str] = None
    # 保留文件数量
    retention: Union[str, int] = "10 days"
    # 压缩格式
    compression: Optional[str] = "zip"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'size': self.size,
            'time': self.time,
            'retention': self.retention,
            'compression': self.compression
        }


@dataclass
class LoggerConfig:
    """日志配置类"""
    # 基础配置
    level: LogLevel = LogLevel.INFO
    format_string: str = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
    
    # 文件配置
    log_dir: str = "logs"
    enable_file_logging: bool = True
    enable_console_logging: bool = True
    
    # 异步配置
    enable_async: bool = True
    async_queue_size: int = 1000
    
    # JSON格式配置
    enable_json_format: bool = False
    json_fields: Dict[str, str] = field(default_factory=lambda: {
        "timestamp": "{time:YYYY-MM-DD HH:mm:ss.SSS}",
        "level": "{level}",
        "logger": "{name}",
        "module": "{module}",
        "function": "{function}",
        "line": "{line}",
        "message": "{message}",
        "process_id": "{process}",
        "thread_id": "{thread}",
    })
    
    # 轮转配置
    rotation: RotationConfig = field(default_factory=RotationConfig)
    
    # 性能配置
    colorize: bool = True
    backtrace: bool = True
    diagnose: bool = True
    catch_exceptions: bool = True
    
    # 采样配置（用于高频日志降级）
    enable_sampling: bool = False
    sampling_rate: float = 1.0  # 1.0 = 100%，0.1 = 10%
    
    # 上下文信息
    service_name: Optional[str] = None
    service_port: Optional[int] = None
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'LoggerConfig':
        """从字典创建配置对象"""
        # 处理日志级别
        if 'level' in config_dict:
            if isinstance(config_dict['level'], str):
                config_dict['level'] = LogLevel(config_dict['level'].upper())
        
        # 处理轮转配置
        if 'rotation' in config_dict and isinstance(config_dict['rotation'], dict):
            config_dict['rotation'] = RotationConfig(**config_dict['rotation'])
        
        return cls(**config_dict)
    
    @classmethod
    def from_env(cls, prefix: str = "LOG_") -> 'LoggerConfig':
        """从环境变量创建配置"""
        config = {}
        
        # 基础配置
        if level := os.getenv(f"{prefix}LEVEL"):
            config['level'] = LogLevel(level.upper())
        
        if log_dir := os.getenv(f"{prefix}DIR"):
            config['log_dir'] = log_dir
            
        if format_str := os.getenv(f"{prefix}FORMAT"):
            config['format_string'] = format_str
        
        # 布尔配置
        for key, env_key in [
            ('enable_file_logging', 'ENABLE_FILE'),
            ('enable_console_logging', 'ENABLE_CONSOLE'),
            ('enable_async', 'ENABLE_ASYNC'),
            ('enable_json_format', 'ENABLE_JSON'),
            ('colorize', 'COLORIZE'),
            ('backtrace', 'BACKTRACE'),
            ('diagnose', 'DIAGNOSE'),
            ('catch_exceptions', 'CATCH_EXCEPTIONS'),
            ('enable_sampling', 'ENABLE_SAMPLING'),
        ]:
            if value := os.getenv(f"{prefix}{env_key}"):
                config[key] = value.lower() in ('true', '1', 'yes', 'on')
        
        # 数值配置
        if queue_size := os.getenv(f"{prefix}QUEUE_SIZE"):
            config['async_queue_size'] = int(queue_size)
            
        if sampling_rate := os.getenv(f"{prefix}SAMPLING_RATE"):
            config['sampling_rate'] = float(sampling_rate)
        
        # 服务信息
        if service_name := os.getenv(f"{prefix}SERVICE_NAME"):
            config['service_name'] = service_name
            
        if service_port := os.getenv(f"{prefix}SERVICE_PORT"):
            config['service_port'] = int(service_port)
        
        # 轮转配置
        rotation_config = {}
        if rotation_size := os.getenv(f"{prefix}ROTATION_SIZE"):
            rotation_config['size'] = rotation_size
        if rotation_time := os.getenv(f"{prefix}ROTATION_TIME"):
            rotation_config['time'] = rotation_time
        if retention := os.getenv(f"{prefix}RETENTION"):
            rotation_config['retention'] = retention
        if compression := os.getenv(f"{prefix}COMPRESSION"):
            rotation_config['compression'] = compression
            
        if rotation_config:
            config['rotation'] = RotationConfig(**rotation_config)
        
        return cls(**config) if config else cls()
    
    def get_log_file_path(self, logger_type: str) -> str:
        """获取日志文件路径"""
        # 创建服务特定的目录
        if self.service_name and self.service_port:
            service_dir = f"{self.service_name}_{self.service_port}"
        else:
            service_dir = "default"
            
        log_dir = Path(self.log_dir) / service_dir
        
        # 根据日志类型确定文件名
        if logger_type == "general":
            filename = "general_{time:YYYY-MM-DD}.log"
        elif logger_type == "sls":
            filename = "sls_{time:YYYY-MM-DD}.log"
        elif logger_type == "battle":
            filename = "battle_{time:YYYY-MM-DD}.log"
        else:
            filename = f"{logger_type}_{{time:YYYY-MM-DD}}.log"
        
        return str(log_dir / filename)
    
    def get_loguru_config(self, logger_type: str = "general") -> Dict[str, Any]:
        """获取loguru的配置字典"""
        config = {
            "sink": self.get_log_file_path(logger_type),
            "level": self.level.value,
            "format": self.format_string,
            "rotation": self.rotation.size,
            "retention": self.rotation.retention,
            "compression": self.rotation.compression,
            "enqueue": self.enable_async,
            "backtrace": self.backtrace,
            "diagnose": self.diagnose,
            "catch": self.catch_exceptions,
        }
        
        # 添加JSON序列化器
        if self.enable_json_format:
            config["serialize"] = True
        
        return config
    
    def create_log_directory(self) -> None:
        """创建日志目录"""
        if self.service_name and self.service_port:
            service_dir = f"{self.service_name}_{self.service_port}"
        else:
            service_dir = "default"
            
        log_dir = Path(self.log_dir) / service_dir
        log_dir.mkdir(parents=True, exist_ok=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'level': self.level.value,
            'format_string': self.format_string,
            'log_dir': self.log_dir,
            'enable_file_logging': self.enable_file_logging,
            'enable_console_logging': self.enable_console_logging,
            'enable_async': self.enable_async,
            'async_queue_size': self.async_queue_size,
            'enable_json_format': self.enable_json_format,
            'json_fields': self.json_fields,
            'rotation': self.rotation.to_dict(),
            'colorize': self.colorize,
            'backtrace': self.backtrace,
            'diagnose': self.diagnose,
            'catch_exceptions': self.catch_exceptions,
            'enable_sampling': self.enable_sampling,
            'sampling_rate': self.sampling_rate,
            'service_name': self.service_name,
            'service_port': self.service_port,
        }


class LoggerConfigManager:
    """日志配置管理器"""
    
    def __init__(self):
        self._configs: Dict[str, LoggerConfig] = {}
        self._default_config: Optional[LoggerConfig] = None
    
    def set_default_config(self, config: LoggerConfig) -> None:
        """设置默认配置"""
        self._default_config = config
    
    def get_default_config(self) -> LoggerConfig:
        """获取默认配置"""
        if self._default_config is None:
            self._default_config = LoggerConfig()
        return self._default_config
    
    def set_config(self, logger_type: str, config: LoggerConfig) -> None:
        """设置特定类型的配置"""
        self._configs[logger_type] = config
    
    def get_config(self, logger_type: str) -> LoggerConfig:
        """获取特定类型的配置"""
        return self._configs.get(logger_type, self.get_default_config())
    
    def load_from_dict(self, config_dict: Dict[str, Any]) -> None:
        """从字典加载配置"""
        # 加载默认配置
        if 'default' in config_dict:
            self.set_default_config(LoggerConfig.from_dict(config_dict['default']))
        
        # 加载特定类型配置
        for logger_type in ['general', 'sls', 'battle']:
            if logger_type in config_dict:
                # 继承默认配置并覆盖特定设置
                base_config = self.get_default_config().to_dict()
                base_config.update(config_dict[logger_type])
                self.set_config(logger_type, LoggerConfig.from_dict(base_config))
    
    def update_service_info(self, service_name: str, service_port: int) -> None:
        """更新所有配置的服务信息"""
        # 更新默认配置
        if self._default_config:
            self._default_config.service_name = service_name
            self._default_config.service_port = service_port
        
        # 更新所有特定配置
        for config in self._configs.values():
            config.service_name = service_name
            config.service_port = service_port


# 全局配置管理器实例
config_manager = LoggerConfigManager()