"""
简单日志实现

为了测试服务启动器，提供一个简单的日志接口，
不依赖外部库如loguru，仅使用Python标准库。
"""

import logging
import sys
from typing import Any, Optional


class SimpleLogger:
    """简单日志器实现"""
    
    def __init__(self, name: str = "launcher"):
        self.name = name
        self.logger = logging.getLogger(name)
        
        # 设置默认配置
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)
    
    def debug(self, message: str, *args, **kwargs) -> None:
        """记录DEBUG级别日志"""
        self.logger.debug(message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs) -> None:
        """记录INFO级别日志"""
        self.logger.info(message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs) -> None:
        """记录WARNING级别日志"""
        self.logger.warning(message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs) -> None:
        """记录ERROR级别日志"""
        self.logger.error(message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs) -> None:
        """记录CRITICAL级别日志"""
        self.logger.critical(message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs) -> None:
        """记录异常信息"""
        self.logger.exception(message, *args, **kwargs)


# 创建全局日志实例
logger = SimpleLogger("launcher")


class LoggerFactory:
    """日志工厂类"""
    
# Removed the unused LoggerFactory.initialize method.
    
    @staticmethod
    def get_logger(name: str) -> SimpleLogger:
        """获取日志器"""
        return SimpleLogger(name)


# 为兼容性导出
def get_logger(name: str) -> SimpleLogger:
    """获取日志器"""
    return SimpleLogger(name)


def initialize_logging(service_type: str = "launcher", port: int = 0) -> None:
    """初始化日志"""
    pass