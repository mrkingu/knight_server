"""
服务注册发现模块异常定义

该模块定义了服务注册发现相关的异常类，提供详细的错误信息和诊断功能。
"""

from typing import Optional, Dict, Any
from enum import Enum


class RegistryErrorCode(Enum):
    """注册中心错误码"""
    # 连接相关
    CONNECTION_FAILED = "REGISTRY_CONNECTION_FAILED"
    CONNECTION_TIMEOUT = "REGISTRY_CONNECTION_TIMEOUT"
    CONNECTION_LOST = "REGISTRY_CONNECTION_LOST"
    
    # 服务注册相关
    REGISTRATION_FAILED = "REGISTRATION_FAILED"
    DEREGISTRATION_FAILED = "DEREGISTRATION_FAILED"
    SERVICE_ALREADY_EXISTS = "SERVICE_ALREADY_EXISTS"
    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    
    # 服务发现相关
    DISCOVERY_FAILED = "DISCOVERY_FAILED"
    NO_HEALTHY_SERVICES = "NO_HEALTHY_SERVICES"
    
    # 健康检查相关
    HEALTH_CHECK_FAILED = "HEALTH_CHECK_FAILED"
    HEALTH_CHECK_TIMEOUT = "HEALTH_CHECK_TIMEOUT"
    
    # 负载均衡相关
    LOAD_BALANCER_ERROR = "LOAD_BALANCER_ERROR"
    NO_AVAILABLE_NODES = "NO_AVAILABLE_NODES"
    
    # 配置相关
    INVALID_CONFIG = "INVALID_CONFIG"
    MISSING_CONFIG = "MISSING_CONFIG"
    
    # 适配器相关
    ADAPTER_NOT_SUPPORTED = "ADAPTER_NOT_SUPPORTED"
    ADAPTER_INITIALIZATION_FAILED = "ADAPTER_INITIALIZATION_FAILED"


class BaseRegistryException(Exception):
    """注册中心基础异常类"""
    
    def __init__(
        self, 
        message: str,
        error_code: RegistryErrorCode,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化异常
        
        Args:
            message: 错误消息
            error_code: 错误码
            details: 错误详细信息
            cause: 引起异常的原始异常
        """
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
        
    def __str__(self) -> str:
        """返回格式化的错误信息"""
        msg = f"[{self.error_code.value}] {self.args[0]}"
        if self.details:
            msg += f" - 详细信息: {self.details}"
        if self.cause:
            msg += f" - 原因: {self.cause}"
        return msg
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error_code": self.error_code.value,
            "message": self.args[0],
            "details": self.details,
            "cause": str(self.cause) if self.cause else None
        }


class RegistryConnectionError(BaseRegistryException):
    """注册中心连接异常"""
    
    def __init__(
        self,
        message: str,
        endpoint: Optional[str] = None,
        timeout: Optional[float] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if endpoint:
            details["endpoint"] = endpoint
        if timeout:
            details["timeout"] = timeout
            
        super().__init__(
            message,
            RegistryErrorCode.CONNECTION_FAILED,
            details=details,
            cause=cause
        )


class RegistryTimeoutError(BaseRegistryException):
    """注册中心超时异常"""
    
    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        timeout: Optional[float] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if operation:
            details["operation"] = operation
        if timeout:
            details["timeout"] = timeout
            
        super().__init__(
            message,
            RegistryErrorCode.CONNECTION_TIMEOUT,
            details=details,
            cause=cause
        )


class ServiceRegistrationError(BaseRegistryException):
    """服务注册异常"""
    
    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        service_id: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if service_name:
            details["service_name"] = service_name
        if service_id:
            details["service_id"] = service_id
            
        super().__init__(
            message,
            RegistryErrorCode.REGISTRATION_FAILED,
            details=details,
            cause=cause
        )


class ServiceDiscoveryError(BaseRegistryException):
    """服务发现异常"""
    
    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        tags: Optional[list] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if service_name:
            details["service_name"] = service_name
        if tags:
            details["tags"] = tags
            
        super().__init__(
            message,
            RegistryErrorCode.DISCOVERY_FAILED,
            details=details,
            cause=cause
        )


class HealthCheckError(BaseRegistryException):
    """健康检查异常"""
    
    def __init__(
        self,
        message: str,
        service_id: Optional[str] = None,
        check_type: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if service_id:
            details["service_id"] = service_id
        if check_type:
            details["check_type"] = check_type
            
        super().__init__(
            message,
            RegistryErrorCode.HEALTH_CHECK_FAILED,
            details=details,
            cause=cause
        )


class LoadBalancerError(BaseRegistryException):
    """负载均衡异常"""
    
    def __init__(
        self,
        message: str,
        strategy: Optional[str] = None,
        available_nodes: Optional[int] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if strategy:
            details["strategy"] = strategy
        if available_nodes is not None:
            details["available_nodes"] = available_nodes
            
        super().__init__(
            message,
            RegistryErrorCode.LOAD_BALANCER_ERROR,
            details=details,
            cause=cause
        )


class RegistryConfigError(BaseRegistryException):
    """注册中心配置异常"""
    
    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        config_value: Optional[Any] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if config_key:
            details["config_key"] = config_key
        if config_value is not None:
            details["config_value"] = str(config_value)
            
        super().__init__(
            message,
            RegistryErrorCode.INVALID_CONFIG,
            details=details,
            cause=cause
        )


def handle_registry_exception(func):
    """
    注册中心异常处理装饰器
    
    自动捕获并转换异常为注册中心异常类型
    """
    import functools
    try:
        from loguru import logger
    except ImportError:
        from ..logger.mock_logger import logger
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BaseRegistryException:
            # 重新抛出注册中心异常
            raise
        except Exception as e:
            logger.error(f"注册中心操作异常: {func.__name__} - {e}")
            raise BaseRegistryException(
                f"注册中心操作失败: {func.__name__}",
                RegistryErrorCode.CONNECTION_FAILED,
                cause=e
            )
    
    return wrapper


def handle_async_registry_exception(func):
    """
    异步注册中心异常处理装饰器
    
    自动捕获并转换异常为注册中心异常类型
    """
    import functools
    import asyncio
    try:
        from loguru import logger
    except ImportError:
        from ..logger.mock_logger import logger
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except BaseRegistryException:
            # 重新抛出注册中心异常
            raise
        except asyncio.TimeoutError as e:
            logger.error(f"注册中心超时: {func.__name__} - {e}")
            raise RegistryTimeoutError(
                f"注册中心操作超时: {func.__name__}",
                operation=func.__name__,
                cause=e
            )
        except Exception as e:
            logger.error(f"注册中心操作异常: {func.__name__} - {e}")
            raise BaseRegistryException(
                f"注册中心操作失败: {func.__name__}",
                RegistryErrorCode.CONNECTION_FAILED,
                cause=e
            )
    
    return wrapper