"""
简单的 Logger 模拟实现

当无法安装 loguru 时，提供基本的日志功能。
"""

import time
import sys
from typing import Any


class MockLogger:
    """模拟的 Logger 类"""
    
    def __init__(self):
        self.level = "INFO"
    
    def _log(self, level: str, message: str, *args, **kwargs):
        """输出日志消息"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted_msg = f"[{timestamp}] {level}: {message}"
        print(formatted_msg, file=sys.stderr)
    
    def debug(self, message: str, *args, **kwargs):
        """调试日志"""
        if self.level in ["DEBUG"]:
            self._log("DEBUG", message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        """信息日志"""
        if self.level in ["DEBUG", "INFO"]:
            self._log("INFO", message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        """警告日志"""
        if self.level in ["DEBUG", "INFO", "WARNING"]:
            self._log("WARNING", message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        """错误日志"""
        if self.level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            self._log("ERROR", message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        """严重错误日志"""
        self._log("CRITICAL", message, *args, **kwargs)
    
    def remove(self, *args, **kwargs):
        """移除处理器 (兼容 loguru)"""
        pass
    
    def add(self, *args, **kwargs):
        """添加处理器 (兼容 loguru)"""
        pass


# 创建全局 logger 实例
logger = MockLogger()