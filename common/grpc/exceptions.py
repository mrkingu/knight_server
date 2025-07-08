"""
gRPC自定义异常模块

该模块定义了gRPC通信中使用的所有自定义异常类，提供详细的错误信息和错误码。
支持异常链、错误诊断和监控集成。
"""

from typing import Optional, Dict, Any, List
from enum import IntEnum


class GrpcErrorCode(IntEnum):
    """gRPC错误码枚举"""
    # 连接相关错误 (1000-1099)
    CONNECTION_ERROR = 1001
    CONNECTION_TIMEOUT = 1002
    CONNECTION_REFUSED = 1003
    CONNECTION_LOST = 1004
    
    # 连接池相关错误 (1100-1199)
    POOL_EXHAUSTED = 1101
    POOL_CLOSED = 1102
    POOL_INVALID_STATE = 1103
    
    # 服务相关错误 (1200-1299)
    SERVICE_UNAVAILABLE = 1201
    SERVICE_NOT_FOUND = 1202
    SERVICE_TIMEOUT = 1203
    SERVICE_OVERLOADED = 1204
    
    # 认证相关错误 (1300-1399)
    AUTHENTICATION_FAILED = 1301
    AUTHORIZATION_FAILED = 1302
    TOKEN_EXPIRED = 1303
    TOKEN_INVALID = 1304
    
    # 请求相关错误 (1400-1499)
    REQUEST_TIMEOUT = 1401
    REQUEST_TOO_LARGE = 1402
    REQUEST_INVALID = 1403
    REQUEST_RATE_LIMITED = 1404
    
    # 健康检查错误 (1500-1599)
    HEALTH_CHECK_FAILED = 1501
    HEALTH_CHECK_TIMEOUT = 1502
    
    # 负载均衡错误 (1600-1699)
    NO_AVAILABLE_NODES = 1601
    LOAD_BALANCER_ERROR = 1602
    
    # 配置错误 (1700-1799)
    CONFIG_ERROR = 1701
    CONFIG_MISSING = 1702


class BaseGrpcException(Exception):
    """gRPC基础异常类"""
    
    def __init__(
        self,
        message: str,
        error_code: GrpcErrorCode,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        """
        初始化gRPC异常
        
        Args:
            message: 错误消息
            error_code: 错误码
            details: 错误详情
            cause: 原始异常
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            'error_code': self.error_code.value,
            'error_name': self.error_code.name,
            'message': self.message,
            'details': self.details
        }
        
        if self.cause:
            result['cause'] = {
                'type': type(self.cause).__name__,
                'message': str(self.cause)
            }
        
        return result
    
    def get_diagnostic_info(self) -> Dict[str, Any]:
        """获取诊断信息"""
        info = self.to_dict()
        info['exception_type'] = type(self).__name__
        info['traceback'] = self.__traceback__
        return info


class GrpcConnectionError(BaseGrpcException):
    """gRPC连接异常"""
    
    def __init__(
        self,
        message: str,
        endpoint: Optional[str] = None,
        timeout: Optional[float] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if endpoint:
            details['endpoint'] = endpoint
        if timeout:
            details['timeout'] = timeout
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.CONNECTION_ERROR,
            details=details,
            cause=cause
        )


class GrpcTimeoutError(BaseGrpcException):
    """gRPC超时异常"""
    
    def __init__(
        self,
        message: str,
        timeout: float,
        operation: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        details = {
            'timeout': timeout,
            'timeout_type': 'request' if operation else 'connection'
        }
        if operation:
            details['operation'] = operation
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.REQUEST_TIMEOUT,
            details=details,
            cause=cause
        )


class GrpcServiceUnavailableError(BaseGrpcException):
    """gRPC服务不可用异常"""
    
    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        endpoints: Optional[List[str]] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if service_name:
            details['service_name'] = service_name
        if endpoints:
            details['checked_endpoints'] = endpoints
            details['endpoint_count'] = len(endpoints)
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.SERVICE_UNAVAILABLE,
            details=details,
            cause=cause
        )


class GrpcPoolExhaustedError(BaseGrpcException):
    """gRPC连接池耗尽异常"""
    
    def __init__(
        self,
        message: str,
        pool_size: Optional[int] = None,
        active_connections: Optional[int] = None,
        waiting_requests: Optional[int] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if pool_size is not None:
            details['pool_size'] = pool_size
        if active_connections is not None:
            details['active_connections'] = active_connections
        if waiting_requests is not None:
            details['waiting_requests'] = waiting_requests
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.POOL_EXHAUSTED,
            details=details,
            cause=cause
        )


class GrpcAuthenticationError(BaseGrpcException):
    """gRPC认证失败异常"""
    
    def __init__(
        self,
        message: str,
        auth_type: Optional[str] = None,
        username: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if auth_type:
            details['auth_type'] = auth_type
        if username:
            details['username'] = username
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.AUTHENTICATION_FAILED,
            details=details,
            cause=cause
        )


class GrpcAuthorizationError(BaseGrpcException):
    """gRPC授权失败异常"""
    
    def __init__(
        self,
        message: str,
        resource: Optional[str] = None,
        action: Optional[str] = None,
        username: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if resource:
            details['resource'] = resource
        if action:
            details['action'] = action
        if username:
            details['username'] = username
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.AUTHORIZATION_FAILED,
            details=details,
            cause=cause
        )


class GrpcHealthCheckError(BaseGrpcException):
    """gRPC健康检查异常"""
    
    def __init__(
        self,
        message: str,
        service_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        check_type: Optional[str] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if service_name:
            details['service_name'] = service_name
        if endpoint:
            details['endpoint'] = endpoint
        if check_type:
            details['check_type'] = check_type
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.HEALTH_CHECK_FAILED,
            details=details,
            cause=cause
        )


class GrpcLoadBalancerError(BaseGrpcException):
    """gRPC负载均衡异常"""
    
    def __init__(
        self,
        message: str,
        strategy: Optional[str] = None,
        available_nodes: Optional[int] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if strategy:
            details['strategy'] = strategy
        if available_nodes is not None:
            details['available_nodes'] = available_nodes
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.LOAD_BALANCER_ERROR,
            details=details,
            cause=cause
        )


class GrpcConfigError(BaseGrpcException):
    """gRPC配置异常"""
    
    def __init__(
        self,
        message: str,
        config_key: Optional[str] = None,
        config_value: Optional[Any] = None,
        cause: Optional[Exception] = None
    ):
        details = {}
        if config_key:
            details['config_key'] = config_key
        if config_value is not None:
            details['config_value'] = str(config_value)
            
        super().__init__(
            message=message,
            error_code=GrpcErrorCode.CONFIG_ERROR,
            details=details,
            cause=cause
        )


def handle_grpc_exception(func):
    """
    gRPC异常处理装饰器
    
    将标准异常转换为gRPC自定义异常
    """
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except BaseGrpcException:
            # 已经是gRPC异常，直接抛出
            raise
        except ConnectionError as e:
            raise GrpcConnectionError(
                message=f"连接失败: {str(e)}",
                cause=e
            )
        except TimeoutError as e:
            raise GrpcTimeoutError(
                message=f"操作超时: {str(e)}",
                timeout=0.0,
                cause=e
            )
        except Exception as e:
            raise BaseGrpcException(
                message=f"未知错误: {str(e)}",
                error_code=GrpcErrorCode.CONNECTION_ERROR,
                cause=e
            )
    
    return wrapper


async def handle_async_grpc_exception(func):
    """
    异步gRPC异常处理装饰器
    """
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except BaseGrpcException:
            # 已经是gRPC异常，直接抛出
            raise
        except ConnectionError as e:
            raise GrpcConnectionError(
                message=f"连接失败: {str(e)}",
                cause=e
            )
        except TimeoutError as e:
            raise GrpcTimeoutError(
                message=f"操作超时: {str(e)}",
                timeout=0.0,
                cause=e
            )
        except Exception as e:
            raise BaseGrpcException(
                message=f"未知错误: {str(e)}",
                error_code=GrpcErrorCode.CONNECTION_ERROR,
                cause=e
            )
    
    return wrapper


# 导出所有异常类
__all__ = [
    'GrpcErrorCode',
    'BaseGrpcException',
    'GrpcConnectionError',
    'GrpcTimeoutError', 
    'GrpcServiceUnavailableError',
    'GrpcPoolExhaustedError',
    'GrpcAuthenticationError',
    'GrpcAuthorizationError',
    'GrpcHealthCheckError',
    'GrpcLoadBalancerError',
    'GrpcConfigError',
    'handle_grpc_exception',
    'handle_async_grpc_exception'
]