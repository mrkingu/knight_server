"""
配置表异常模块

定义配置表相关的异常类。
"""

from typing import Optional, Any


class TableError(Exception):
    """配置表基础异常"""
    
    def __init__(self, message: str, error_code: Optional[int] = None):
        """
        初始化异常
        
        Args:
            message: 异常消息
            error_code: 错误代码
        """
        super().__init__(message)
        self.error_code = error_code


class ConfigNotFoundError(TableError):
    """配置未找到异常"""
    
    def __init__(self, config_type: str, config_id: Any):
        """
        初始化异常
        
        Args:
            config_type: 配置类型
            config_id: 配置ID
        """
        message = f"配置未找到: {config_type}[{config_id}]"
        super().__init__(message, error_code=404)
        self.config_type = config_type
        self.config_id = config_id


class ConfigLoadError(TableError):
    """配置加载异常"""
    
    def __init__(self, file_path: str, reason: str):
        """
        初始化异常
        
        Args:
            file_path: 文件路径
            reason: 失败原因
        """
        message = f"配置加载失败: {file_path} - {reason}"
        super().__init__(message, error_code=500)
        self.file_path = file_path
        self.reason = reason


class ConfigValidationError(TableError):
    """配置验证异常"""
    
    def __init__(self, config_type: str, config_id: Any, validation_errors: list):
        """
        初始化异常
        
        Args:
            config_type: 配置类型
            config_id: 配置ID
            validation_errors: 验证错误列表
        """
        message = f"配置验证失败: {config_type}[{config_id}] - {validation_errors}"
        super().__init__(message, error_code=400)
        self.config_type = config_type
        self.config_id = config_id
        self.validation_errors = validation_errors


class ConfigTypeError(TableError):
    """配置类型异常"""
    
    def __init__(self, config_type: str):
        """
        初始化异常
        
        Args:
            config_type: 配置类型
        """
        message = f"未知的配置类型: {config_type}"
        super().__init__(message, error_code=400)
        self.config_type = config_type


class HotReloadError(TableError):
    """热更新异常"""
    
    def __init__(self, file_path: str, reason: str):
        """
        初始化异常
        
        Args:
            file_path: 文件路径
            reason: 失败原因
        """
        message = f"热更新失败: {file_path} - {reason}"
        super().__init__(message, error_code=500)
        self.file_path = file_path
        self.reason = reason


class CacheError(TableError):
    """缓存异常"""
    
    def __init__(self, operation: str, reason: str):
        """
        初始化异常
        
        Args:
            operation: 操作类型
            reason: 失败原因
        """
        message = f"缓存操作失败: {operation} - {reason}"
        super().__init__(message, error_code=500)
        self.operation = operation
        self.reason = reason


class ConfigManagerError(TableError):
    """配置管理器异常"""
    
    def __init__(self, reason: str):
        """
        初始化异常
        
        Args:
            reason: 失败原因
        """
        message = f"配置管理器错误: {reason}"
        super().__init__(message, error_code=500)
        self.reason = reason


class SchemaValidationError(TableError):
    """模式验证异常"""
    
    def __init__(self, file_path: str, schema_errors: list):
        """
        初始化异常
        
        Args:
            file_path: 文件路径
            schema_errors: 模式验证错误列表
        """
        message = f"模式验证失败: {file_path} - {schema_errors}"
        super().__init__(message, error_code=400)
        self.file_path = file_path
        self.schema_errors = schema_errors