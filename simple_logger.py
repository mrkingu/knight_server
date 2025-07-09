"""
Simple logger implementation for testing purposes
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

class SimpleLogger:
    def __init__(self, name: str = "logger"):
        self.name = name
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        # Create console handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def info(self, message: str, **kwargs):
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if extra_info else message
        self.logger.info(full_message)
    
    def error(self, message: str, **kwargs):
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if extra_info else message
        self.logger.error(full_message)
    
    def warning(self, message: str, **kwargs):
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if extra_info else message
        self.logger.warning(full_message)
    
    def debug(self, message: str, **kwargs):
        extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items())
        full_message = f"{message} {extra_info}" if extra_info else message
        self.logger.debug(full_message)

# Global logger instance
logger = SimpleLogger()