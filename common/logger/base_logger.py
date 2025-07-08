"""
基础日志模块

该模块提供基础日志类，封装loguru功能，提供统一的日志接口、
上下文信息管理、性能监控等功能。
"""

import sys
import time
import json
import random
import threading
import multiprocessing
from typing import Any, Dict, Optional, Callable, Union
from functools import wraps
from contextlib import contextmanager
from pathlib import Path

try:
    from loguru import logger as loguru_logger
    LOGURU_AVAILABLE = True
except ImportError:
    # 如果loguru不可用，创建一个简单的模拟对象
    LOGURU_AVAILABLE = False
    
    class MockLogger:
        def __init__(self):
            self.handlers = []
            
        def add(self, *args, **kwargs):
            return len(self.handlers)
            
        def remove(self, handler_id=None):
            pass
            
        def configure(self, **kwargs):
            pass
            
        def bind(self, **kwargs):
            return self
            
        def opt(self, **kwargs):
            return self
            
        def catch(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
            
        def trace(self, message, *args, **kwargs):
            self._log("TRACE", message, *args, **kwargs)
            
        def debug(self, message, *args, **kwargs):
            self._log("DEBUG", message, *args, **kwargs)
            
        def info(self, message, *args, **kwargs):
            self._log("INFO", message, *args, **kwargs)
            
        def success(self, message, *args, **kwargs):
            self._log("SUCCESS", message, *args, **kwargs)
            
        def warning(self, message, *args, **kwargs):
            self._log("WARNING", message, *args, **kwargs)
            
        def error(self, message, *args, **kwargs):
            self._log("ERROR", message, *args, **kwargs)
            
        def critical(self, message, *args, **kwargs):
            self._log("CRITICAL", message, *args, **kwargs)
            
        def _log(self, level, message, *args, **kwargs):
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"{timestamp} | {level: <8} | {message}")
    
    loguru_logger = MockLogger()

from .logger_config import LoggerConfig, LogLevel


class BaseLogger:
    """
    基础日志类
    
    封装loguru功能，提供统一的日志接口、上下文信息管理、
    性能监控和异常处理功能。
    """
    
    def __init__(self, name: str, config: LoggerConfig):
        """
        初始化基础日志器
        
        Args:
            name: 日志器名称
            config: 日志配置对象
        """
        self.name = name
        self.config = config
        self._context: Dict[str, Any] = {}
        self._handler_ids = []
        self._lock = threading.Lock()
        self._initialized = False
        
        # 初始化日志器
        self._setup_logger()
    
    def _setup_logger(self) -> None:
        """设置日志器"""
        with self._lock:
            if self._initialized:
                return
                
            try:
                # 创建日志目录
                self.config.create_log_directory()
                
                # 移除默认处理器
                if LOGURU_AVAILABLE:
                    loguru_logger.remove()
                
                # 添加控制台输出
                if self.config.enable_console_logging:
                    console_config = {
                        "sink": sys.stdout,
                        "level": self.config.level.value,
                        "format": self.config.format_string,
                        "colorize": self.config.colorize,
                        "enqueue": self.config.enable_async,
                        "backtrace": self.config.backtrace,
                        "diagnose": self.config.diagnose,
                        "catch": self.config.catch_exceptions,
                    }
                    
                    if LOGURU_AVAILABLE:
                        handler_id = loguru_logger.add(**console_config)
                        self._handler_ids.append(handler_id)
                
                # 添加文件输出
                if self.config.enable_file_logging:
                    file_config = self.config.get_loguru_config(self.name)
                    
                    if LOGURU_AVAILABLE:
                        handler_id = loguru_logger.add(**file_config)
                        self._handler_ids.append(handler_id)
                
                # 设置默认上下文
                self._setup_default_context()
                
                self._initialized = True
                
            except Exception as e:
                # 如果设置失败，至少保证基本的日志功能
                print(f"Logger setup failed: {e}")
                if not LOGURU_AVAILABLE:
                    pass  # MockLogger已经可以工作
    
    def _setup_default_context(self) -> None:
        """设置默认上下文信息"""
        self._context.update({
            'service_name': self.config.service_name or 'unknown',
            'service_port': self.config.service_port or 0,
            'process_id': multiprocessing.current_process().pid,
            'thread_id': threading.current_thread().ident,
            'logger_name': self.name,
        })
    
    def bind(self, **kwargs) -> 'BaseLogger':
        """绑定上下文信息"""
        new_logger = BaseLogger(self.name, self.config)
        new_logger._context = {**self._context, **kwargs}
        new_logger._handler_ids = self._handler_ids.copy()
        new_logger._initialized = True
        return new_logger
    
    def with_context(self, **kwargs) -> 'BaseLogger':
        """添加上下文信息（别名方法）"""
        return self.bind(**kwargs)
    
    def _should_sample(self) -> bool:
        """判断是否应该记录日志（用于采样）"""
        if not self.config.enable_sampling:
            return True
        return random.random() <= self.config.sampling_rate
    
    def _format_message(self, message: str, *args, **kwargs) -> str:
        """格式化消息"""
        # 支持参数化消息
        if args:
            try:
                message = message.format(*args)
            except (IndexError, KeyError, ValueError):
                # 如果格式化失败，直接拼接参数
                message = f"{message} {' '.join(map(str, args))}"
        
        return message
    
    def _prepare_extra(self, **kwargs) -> Dict[str, Any]:
        """准备额外的日志字段"""
        extra = {**self._context}
        
        # 添加用户提供的额外字段
        for key, value in kwargs.items():
            if key not in ['exc_info', 'stack_info']:
                extra[key] = value
        
        return extra
    
    def _log(self, level: str, message: str, *args, **kwargs) -> None:
        """内部日志记录方法"""
        if not self._should_sample():
            return
        
        try:
            # 格式化消息
            formatted_message = self._format_message(message, *args)
            
            # 准备上下文数据
            extra = self._prepare_extra(**kwargs)
            
            # 使用loguru记录日志
            if LOGURU_AVAILABLE:
                bound_logger = loguru_logger.bind(**extra)
                getattr(bound_logger, level.lower())(formatted_message)
            else:
                # 使用模拟日志器
                getattr(loguru_logger, level.lower())(formatted_message)
                
        except Exception as e:
            # 如果日志记录失败，使用print作为后备
            print(f"Logging failed: {e}")
            print(f"{level}: {message}")
    
    # 标准日志方法
    def trace(self, message: str, *args, **kwargs) -> None:
        """记录TRACE级别日志"""
        self._log("TRACE", message, *args, **kwargs)
    
    def debug(self, message: str, *args, **kwargs) -> None:
        """记录DEBUG级别日志"""
        self._log("DEBUG", message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs) -> None:
        """记录INFO级别日志"""
        self._log("INFO", message, *args, **kwargs)
    
    def success(self, message: str, *args, **kwargs) -> None:
        """记录SUCCESS级别日志"""
        self._log("SUCCESS", message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs) -> None:
        """记录WARNING级别日志"""
        self._log("WARNING", message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs) -> None:
        """记录ERROR级别日志"""
        self._log("ERROR", message, *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs) -> None:
        """记录CRITICAL级别日志"""
        self._log("CRITICAL", message, *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs) -> None:
        """记录异常信息"""
        import traceback
        exc_info = traceback.format_exc()
        kwargs['exception'] = exc_info
        self.error(message, *args, **kwargs)
    
    # 装饰器方法
    def catch(self, exception=Exception, reraise=False, message="An error occurred"):
        """异常捕获装饰器"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except exception as e:
                    self.exception(f"{message}: {e}")
                    if reraise:
                        raise
                    return None
            return wrapper
        return decorator
    
    def timer(self, message: Optional[str] = None):
        """性能计时装饰器"""
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                func_name = func.__name__
                start_time = time.time()
                
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    log_message = message or f"Function {func_name} completed"
                    self.info(log_message, duration=duration, function=func_name)
                    
                    return result
                except Exception as e:
                    duration = time.time() - start_time
                    self.error(f"Function {func_name} failed after {duration:.3f}s: {e}",
                             duration=duration, function=func_name, error=str(e))
                    raise
            
            # 支持异步函数
            if hasattr(func, '__call__') and hasattr(func, '__await__'):
                @wraps(func)
                async def async_wrapper(*args, **kwargs):
                    func_name = func.__name__
                    start_time = time.time()
                    
                    try:
                        result = await func(*args, **kwargs)
                        duration = time.time() - start_time
                        
                        log_message = message or f"Async function {func_name} completed"
                        self.info(log_message, duration=duration, function=func_name)
                        
                        return result
                    except Exception as e:
                        duration = time.time() - start_time
                        self.error(f"Async function {func_name} failed after {duration:.3f}s: {e}",
                                 duration=duration, function=func_name, error=str(e))
                        raise
                
                return async_wrapper
            
            return wrapper
        return decorator
    
    @contextmanager
    def context(self, **kwargs):
        """上下文管理器，在代码块中添加额外的上下文信息"""
        bound_logger = self.bind(**kwargs)
        yield bound_logger
    
    def set_level(self, level: Union[str, LogLevel]) -> None:
        """动态设置日志级别"""
        if isinstance(level, str):
            level = LogLevel(level.upper())
        
        self.config.level = level
        
        # 重新配置处理器
        if LOGURU_AVAILABLE:
            # 移除现有处理器
            for handler_id in self._handler_ids:
                try:
                    loguru_logger.remove(handler_id)
                except:
                    pass
            
            self._handler_ids.clear()
            self._initialized = False
            
            # 重新设置
            self._setup_logger()
    
    def get_level(self) -> LogLevel:
        """获取当前日志级别"""
        return self.config.level
    
    def is_enabled_for(self, level: Union[str, LogLevel]) -> bool:
        """检查是否为指定级别启用了日志记录"""
        if isinstance(level, str):
            level = LogLevel(level.upper())
        
        level_order = {
            LogLevel.TRACE: 0,
            LogLevel.DEBUG: 1,
            LogLevel.INFO: 2,
            LogLevel.SUCCESS: 2,
            LogLevel.WARNING: 3,
            LogLevel.ERROR: 4,
            LogLevel.CRITICAL: 5,
        }
        
        return level_order.get(level, 0) >= level_order.get(self.config.level, 0)
    
    def flush(self) -> None:
        """刷新日志缓冲区"""
        if LOGURU_AVAILABLE:
            # loguru会自动处理刷新，这里主要是为了接口兼容性
            pass
    
    def close(self) -> None:
        """关闭日志器"""
        if LOGURU_AVAILABLE:
            for handler_id in self._handler_ids:
                try:
                    loguru_logger.remove(handler_id)
                except:
                    pass
        
        self._handler_ids.clear()
        self._initialized = False
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if exc_type is not None:
            self.exception(f"Exception in logger context: {exc_val}")
        return False  # 不抑制异常
    
    def __del__(self):
        """析构函数"""
        try:
            self.close()
        except:
            pass


# 工具函数
def create_logger(name: str, config: Optional[LoggerConfig] = None) -> BaseLogger:
    """创建日志器的便捷函数"""
    if config is None:
        config = LoggerConfig()
    
    return BaseLogger(name, config)


def get_caller_info(skip_frames: int = 2) -> Dict[str, Any]:
    """获取调用者信息"""
    import inspect
    
    frame = inspect.currentframe()
    try:
        for _ in range(skip_frames):
            frame = frame.f_back
            if frame is None:
                break
        
        if frame:
            return {
                'filename': frame.f_code.co_filename,
                'function': frame.f_code.co_name,
                'line': frame.f_lineno,
            }
        return {}
    finally:
        del frame