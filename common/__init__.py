"""
common 模块

该模块提供了common相关的功能实现。
"""

# 导入所有公共模块
from .logger import sls_logger, battle_logger, logger_factory
from .db import BaseDocument, BaseRepository

# 导出所有模块
__all__ = [
    # 日志模块
    "sls_logger",
    "battle_logger", 
    "logger_factory",
    
    # 数据库模块
    "BaseDocument",
    "BaseRepository",
]
