"""
gRPC自定义异常模块

定义gRPC通信过程中可能出现的各种异常类型，提供详细的错误信息和错误码。
所有gRPC相关的异常都继承自GrpcException基类，便于统一处理。
"""

from typing import Optional, Dict, Any
from enum import IntEnum


class GrpcErrorCode(IntEnum):
    """gRPC错误码枚举"""
    
    # 连接相关错误 (1000-1099)
    CONNECTION_ERROR = 1001
    CONNECTION_TIMEOUT = 1002
    CONNECTION_REFUSED = 1003
    CONNECTION_LOST = 1004
    
    # 认证相关错误 (1100-1199)
    AUTHENTICATION_ERROR = 1101
    AUTHORIZATION_ERROR = 1102
    TOKEN_EXPIRED = 1103
    TOKEN_INVALID = 1104
    
    # 服务相关错误 (1200-1299)
    SERVICE_UNAVAILABLE = 1201
    SERVICE_NOT_FOUND = 1202
    METHOD_NOT_FOUND = 1203
    SERVICE_TIMEOUT = 1204
    
    # 连接池相关错误 (1300-1399)
    POOL_EXHAUSTED = 1301
    POOL_CLOSED = 1302
    POOL_TIMEOUT = 1303
    
    # 负载均衡相关错误 (1400-1499)
    NO_AVAILABLE_SERVERS = 1401
    LOAD_BALANCER_ERROR = 1402
    
    # 健康检查相关错误 (1500-1599)
    HEALTH_CHECK_FAILED = 1501
    HEALTH_CHECK_TIMEOUT = 1502
    
    # 配置相关错误 (1600-1699)
    CONFIGURATION_ERROR = 1601
    INVALID_CONFIG = 1602
    
    # 序列化相关错误 (1700-1799)
    SERIALIZATION_ERROR = 1701
    DESERIALIZATION_ERROR = 1702
    
    # 其他错误 (1900-1999)
    UNKNOWN_ERROR = 1901
    INTERNAL_ERROR = 1902


class GrpcException(Exception):
    """
    gRPC异常基类
    
    所有gRPC模块的异常都应该继承自此类，提供统一的异常处理接口。
    """
    
    def __init__(
        self, 
        message: str, 
        error_code: GrpcErrorCode = GrpcErrorCode.UNKNOWN_ERROR,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化gRPC异常
        
        Args:
            message: 错误消息
            error_code: 错误码
            details: 错误详情字典
            cause: 原始异常（如果有）
        """
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
        
    def __str__(self) -> str:
        """返回格式化的错误信息"""
        error_info = f"[{self.error_code.name}:{self.error_code.value}] {self.args[0]}"
        
        if self.details:
            details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            error_info += f" ({details_str})"
            
        if self.cause:
            error_info += f" <- 原因: {self.cause}"
            
        return error_info
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式，便于序列化和日志记录
        
        Returns:
            Dict[str, Any]: 异常信息字典
        """
        return {
            "error_code": self.error_code.value,
            "error_name": self.error_code.name,
            "message": str(self.args[0]) if self.args else "",
            "details": self.details,
            "cause": str(self.cause) if self.cause else None
        }


class GrpcConnectionError(GrpcException):
    """gRPC连接异常"""
    
    def __init__(
        self, 
        message: str, 
        host: Optional[str] = None,
        port: Optional[int] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化连接异常
        
        Args:
            message: 错误消息
            host: 主机地址
            port: 端口号
            cause: 原始异常
        """
        details = {}
        if host:
            details["host"] = host
        if port:
            details["port"] = port
            
        super().__init__(
            message, 
            GrpcErrorCode.CONNECTION_ERROR, 
            details, 
            cause
        )


class GrpcTimeoutError(GrpcException):
    """gRPC超时异常"""
    
    def __init__(
        self, 
        message: str, 
        timeout: Optional[float] = None,
        operation: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化超时异常
        
        Args:
            message: 错误消息
            timeout: 超时时间（秒）
            operation: 超时的操作名称
            cause: 原始异常
        """
        details = {}
        if timeout is not None:
            details["timeout"] = timeout
        if operation:
            details["operation"] = operation
            
        super().__init__(
            message, 
            GrpcErrorCode.CONNECTION_TIMEOUT, 
            details, 
            cause
        )


class GrpcServiceUnavailableError(GrpcException):
    """gRPC服务不可用异常"""
    
    def __init__(
        self, 
        message: str, 
        service_name: Optional[str] = None,
        available_servers: Optional[int] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化服务不可用异常
        
        Args:
            message: 错误消息
            service_name: 服务名称
            available_servers: 可用服务器数量
            cause: 原始异常
        """
        details = {}
        if service_name:
            details["service_name"] = service_name
        if available_servers is not None:
            details["available_servers"] = available_servers
            
        super().__init__(
            message, 
            GrpcErrorCode.SERVICE_UNAVAILABLE, 
            details, 
            cause
        )


class GrpcPoolExhaustedError(GrpcException):
    """gRPC连接池耗尽异常"""
    
    def __init__(
        self, 
        message: str, 
        pool_size: Optional[int] = None,
        active_connections: Optional[int] = None,
        waiting_requests: Optional[int] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化连接池耗尽异常
        
        Args:
            message: 错误消息
            pool_size: 连接池大小
            active_connections: 活跃连接数
            waiting_requests: 等待中的请求数
            cause: 原始异常
        """
        details = {}
        if pool_size is not None:
            details["pool_size"] = pool_size
        if active_connections is not None:
            details["active_connections"] = active_connections
        if waiting_requests is not None:
            details["waiting_requests"] = waiting_requests
            
        super().__init__(
            message, 
            GrpcErrorCode.POOL_EXHAUSTED, 
            details, 
            cause
        )


class GrpcAuthenticationError(GrpcException):
    """gRPC认证失败异常"""
    
    def __init__(
        self, 
        message: str, 
        auth_type: Optional[str] = None,
        user_id: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化认证失败异常
        
        Args:
            message: 错误消息
            auth_type: 认证类型
            user_id: 用户ID
            cause: 原始异常
        """
        details = {}
        if auth_type:
            details["auth_type"] = auth_type
        if user_id:
            details["user_id"] = user_id
            
        super().__init__(
            message, 
            GrpcErrorCode.AUTHENTICATION_ERROR, 
            details, 
            cause
        )


class GrpcConfigurationError(GrpcException):
    """gRPC配置错误异常"""
    
    def __init__(
        self, 
        message: str, 
        config_key: Optional[str] = None,
        config_value: Optional[Any] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化配置错误异常
        
        Args:
            message: 错误消息
            config_key: 配置键名
            config_value: 配置值
            cause: 原始异常
        """
        details = {}
        if config_key:
            details["config_key"] = config_key
        if config_value is not None:
            details["config_value"] = str(config_value)
            
        super().__init__(
            message, 
            GrpcErrorCode.CONFIGURATION_ERROR, 
            details, 
            cause
        )


class GrpcHealthCheckError(GrpcException):
    """gRPC健康检查异常"""
    
    def __init__(
        self, 
        message: str, 
        service_name: Optional[str] = None,
        check_type: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化健康检查异常
        
        Args:
            message: 错误消息
            service_name: 服务名称
            check_type: 检查类型
            cause: 原始异常
        """
        details = {}
        if service_name:
            details["service_name"] = service_name
        if check_type:
            details["check_type"] = check_type
            
        super().__init__(
            message, 
            GrpcErrorCode.HEALTH_CHECK_FAILED, 
            details, 
            cause
        )


class GrpcSerializationError(GrpcException):
    """gRPC序列化异常"""
    
    def __init__(
        self, 
        message: str, 
        data_type: Optional[str] = None,
        operation: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化序列化异常
        
        Args:
            message: 错误消息
            data_type: 数据类型
            operation: 操作类型（serialize/deserialize）
            cause: 原始异常
        """
        details = {}
        if data_type:
            details["data_type"] = data_type
        if operation:
            details["operation"] = operation
            
        error_code = (
            GrpcErrorCode.SERIALIZATION_ERROR 
            if operation == "serialize" 
            else GrpcErrorCode.DESERIALIZATION_ERROR
        )
        
        super().__init__(
            message, 
            error_code, 
            details, 
            cause
        )


def handle_grpc_exception(func):
    """
    gRPC异常处理装饰器
    
    自动捕获并转换标准异常为gRPC异常，提供统一的异常处理机制。
    
    Usage:
        @handle_grpc_exception
        def some_grpc_method():
            # 方法实现
            pass
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GrpcException:
            # 已经是gRPC异常，直接重新抛出
            raise
        except ConnectionError as e:
            raise GrpcConnectionError(f"连接失败: {e}", cause=e)
        except TimeoutError as e:
            raise GrpcTimeoutError(f"操作超时: {e}", cause=e)
        except Exception as e:
            raise GrpcException(f"未知错误: {e}", cause=e)
    
    return wrapper


async def handle_grpc_exception_async(func):
    """
    异步gRPC异常处理装饰器
    
    自动捕获并转换标准异常为gRPC异常，支持异步方法。
    
    Usage:
        @handle_grpc_exception_async
        async def some_async_grpc_method():
            # 异步方法实现
            pass
    """
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except GrpcException:
            # 已经是gRPC异常，直接重新抛出
            raise
        except ConnectionError as e:
            raise GrpcConnectionError(f"连接失败: {e}", cause=e)
        except TimeoutError as e:
            raise GrpcTimeoutError(f"操作超时: {e}", cause=e)
        except Exception as e:
            raise GrpcException(f"未知错误: {e}", cause=e)
    
    return wrapper