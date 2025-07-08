"""
common/logger 模块

该模块提供了基于loguru的高性能日志系统，支持三种日志类型：
- logger: 通用日志，记录常规业务逻辑  
- sls_logger: SLS（阿里云日志服务）专用日志，用于上报到云端
- battle_logger: 战斗日志，记录战斗相关的详细信息

主要特性：
- 基于loguru实现，支持异步日志
- 支持按服务类型和端口号区分日志文件
- 支持日志轮转（按大小和时间）
- 支持日志级别动态配置
- 线程安全，支持多进程环境
- 支持结构化日志（JSON格式）
- 延迟初始化，使用时自动创建

使用示例：
    # 服务启动时初始化（可选，也可以延迟初始化）
    from common.logger import LoggerFactory
    LoggerFactory.initialize(service_type="gate", port=8001)

    # 业务代码中使用
    from common.logger import logger, sls_logger, battle_logger

    # 普通日志
    logger.info("用户登录", user_id=12345, ip="192.168.1.1")

    # SLS日志
    sls_logger.warning("支付异常", order_id="ORDER123", amount=100.0)

    # 战斗日志
    battle_logger.debug("技能释放", battle_id="BATTLE456", skill_id=1001, damage=500)
"""

from typing import Optional

# 导入核心类
from .logger_config import LoggerConfig, LogLevel, RotationConfig, LoggerConfigManager
from .base_logger import BaseLogger
from .logger_factory import LoggerFactory, logger_factory
from .sls_logger import SLSLogger, SLSConfig
from .battle_logger import BattleLogger, BattleConfig

# 导入便捷函数
from .logger_factory import (
    get_logger, 
    initialize_logging, 
    set_global_log_level, 
    get_logger_factory
)

# 全局日志对象（延迟初始化）
_logger: Optional[BaseLogger] = None
_sls_logger: Optional[SLSLogger] = None  
_battle_logger: Optional[BattleLogger] = None


def _get_or_create_logger() -> BaseLogger:
    """获取或创建通用日志器"""
    global _logger
    if _logger is None:
        _logger = logger_factory.get_logger("general")
    return _logger


def _get_or_create_sls_logger() -> SLSLogger:
    """获取或创建SLS日志器"""
    global _sls_logger
    if _sls_logger is None:
        _sls_logger = logger_factory.get_logger("sls")
    return _sls_logger


def _get_or_create_battle_logger() -> BattleLogger:
    """获取或创建战斗日志器"""
    global _battle_logger
    if _battle_logger is None:
        _battle_logger = logger_factory.get_logger("battle")
    return _battle_logger


# 创建属性访问器，实现延迟初始化
class _LoggerProxy:
    """日志器代理类，实现延迟初始化"""
    
    def __getattr__(self, name):
        logger_instance = _get_or_create_logger()
        return getattr(logger_instance, name)
    
    def __call__(self, *args, **kwargs):
        logger_instance = _get_or_create_logger()
        return logger_instance(*args, **kwargs)


class _SLSLoggerProxy:
    """SLS日志器代理类，实现延迟初始化"""
    
    def __getattr__(self, name):
        logger_instance = _get_or_create_sls_logger()
        return getattr(logger_instance, name)
    
    def __call__(self, *args, **kwargs):
        logger_instance = _get_or_create_sls_logger()
        return logger_instance(*args, **kwargs)


class _BattleLoggerProxy:
    """战斗日志器代理类，实现延迟初始化"""
    
    def __getattr__(self, name):
        logger_instance = _get_or_create_battle_logger()
        return getattr(logger_instance, name)
    
    def __call__(self, *args, **kwargs):
        logger_instance = _get_or_create_battle_logger()
        return logger_instance(*args, **kwargs)


# 全局日志对象（使用代理实现延迟初始化）
logger = _LoggerProxy()
sls_logger = _SLSLoggerProxy()
battle_logger = _BattleLoggerProxy()

# 导出所有公共接口
__all__ = [
    # 核心类
    'LoggerConfig',
    'LogLevel', 
    'RotationConfig',
    'LoggerConfigManager',
    'BaseLogger',
    'LoggerFactory',
    'SLSLogger',
    'SLSConfig', 
    'BattleLogger',
    'BattleConfig',
    
    # 全局日志对象
    'logger',
    'sls_logger', 
    'battle_logger',
    
    # 便捷函数
    'get_logger',
    'initialize_logging',
    'set_global_log_level',
    'get_logger_factory',
    
    # 工厂实例
    'logger_factory',
]
