"""
gRPC拦截器模块

提供多种类型的拦截器，支持认证、日志、追踪、性能监控、异常处理等功能。
拦截器支持链式调用，可以灵活组合不同的功能。
"""

import asyncio
import time
import json
import uuid
from typing import Any, Dict, List, Optional, Callable, Union, Awaitable
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

try:
    import grpc
    from grpc import aio as grpc_aio
    from grpc_interceptor import ExceptionToStatusInterceptor
    from grpc_interceptor.server import AsyncServerInterceptor
    from grpc_interceptor.client import AsyncClientInterceptor
except ImportError:
    # 如果grpc未安装，创建模拟基类
    grpc = None
    grpc_aio = None
    
    class AsyncServerInterceptor:
        pass
    
    class AsyncClientInterceptor:
        pass
    
    class ExceptionToStatusInterceptor:
        pass

from ..logger import logger
from .exceptions import (
    GrpcAuthenticationError,
    GrpcException,
    handle_grpc_exception_async
)


@dataclass
class RequestContext:
    """请求上下文信息"""
    
    # 基本信息
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    
    # 时间信息
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    
    # 请求信息
    method_name: Optional[str] = None
    service_name: Optional[str] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    
    # 响应信息
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    response_size: Optional[int] = None
    
    # 自定义属性
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> float:
        """请求持续时间"""
        if self.end_time is None:
            return time.time() - self.start_time
        return self.end_time - self.start_time
    
    def set_error(self, error: Exception) -> None:
        """设置错误信息"""
        self.status_code = getattr(error, 'code', -1)
        self.error_message = str(error)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "method_name": self.method_name,
            "service_name": self.service_name,
            "client_ip": self.client_ip,
            "user_agent": self.user_agent,
            "status_code": self.status_code,
            "error_message": self.error_message,
            "response_size": self.response_size,
            "attributes": self.attributes
        }


class BaseInterceptor(ABC):
    """
    拦截器基类
    
    定义拦截器的通用接口和基础功能。
    """
    
    def __init__(self, name: Optional[str] = None):
        """
        初始化拦截器
        
        Args:
            name: 拦截器名称
        """
        self.name = name or self.__class__.__name__
        self.enabled = True
        self.stats = {
            "processed_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_processing_time": 0.0
        }
    
    async def process_request(self, context: RequestContext, request: Any) -> Any:
        """
        处理请求
        
        Args:
            context: 请求上下文
            request: 请求对象
            
        Returns:
            Any: 处理后的请求对象
        """
        if not self.enabled:
            return request
        
        start_time = time.time()
        try:
            result = await self._process_request(context, request)
            self.stats["successful_requests"] += 1
            return result
        except Exception as e:
            self.stats["failed_requests"] += 1
            logger.error(f"拦截器 {self.name} 处理请求失败: {e}")
            raise
        finally:
            processing_time = time.time() - start_time
            self.stats["processed_requests"] += 1
            self.stats["total_processing_time"] += processing_time
    
    async def process_response(self, context: RequestContext, response: Any) -> Any:
        """
        处理响应
        
        Args:
            context: 请求上下文
            response: 响应对象
            
        Returns:
            Any: 处理后的响应对象
        """
        if not self.enabled:
            return response
        
        start_time = time.time()
        try:
            result = await self._process_response(context, response)
            return result
        except Exception as e:
            logger.error(f"拦截器 {self.name} 处理响应失败: {e}")
            raise
        finally:
            processing_time = time.time() - start_time
            self.stats["total_processing_time"] += processing_time
    
    @abstractmethod
    async def _process_request(self, context: RequestContext, request: Any) -> Any:
        """
        子类实现的请求处理逻辑
        
        Args:
            context: 请求上下文
            request: 请求对象
            
        Returns:
            Any: 处理后的请求对象
        """
        pass
    
    @abstractmethod
    async def _process_response(self, context: RequestContext, response: Any) -> Any:
        """
        子类实现的响应处理逻辑
        
        Args:
            context: 请求上下文
            response: 响应对象
            
        Returns:
            Any: 处理后的响应对象
        """
        pass
    
    def enable(self) -> None:
        """启用拦截器"""
        self.enabled = True
        logger.info(f"拦截器 {self.name} 已启用")
    
    def disable(self) -> None:
        """禁用拦截器"""
        self.enabled = False
        logger.info(f"拦截器 {self.name} 已禁用")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取拦截器统计信息"""
        avg_processing_time = 0.0
        if self.stats["processed_requests"] > 0:
            avg_processing_time = self.stats["total_processing_time"] / self.stats["processed_requests"]
        
        return {
            "name": self.name,
            "enabled": self.enabled,
            "processed_requests": self.stats["processed_requests"],
            "successful_requests": self.stats["successful_requests"],
            "failed_requests": self.stats["failed_requests"],
            "success_rate": self.stats["successful_requests"] / max(self.stats["processed_requests"], 1),
            "avg_processing_time": avg_processing_time,
            "total_processing_time": self.stats["total_processing_time"]
        }


class AuthInterceptor(BaseInterceptor):
    """
    认证拦截器
    
    验证JWT token和用户权限。
    """
    
    def __init__(
        self, 
        name: Optional[str] = None,
        jwt_secret: str = "default_secret",
        required_permissions: Optional[List[str]] = None,
        auth_header: str = "authorization",
        auth_metadata_key: str = "authorization"
    ):
        """
        初始化认证拦截器
        
        Args:
            name: 拦截器名称
            jwt_secret: JWT密钥
            required_permissions: 必需的权限列表
            auth_header: 认证头名称
            auth_metadata_key: 认证元数据键名
        """
        super().__init__(name)
        self.jwt_secret = jwt_secret
        self.required_permissions = required_permissions or []
        self.auth_header = auth_header
        self.auth_metadata_key = auth_metadata_key
    
    async def _process_request(self, context: RequestContext, request: Any) -> Any:
        """处理认证"""
        # 从请求中提取认证信息
        auth_token = await self._extract_auth_token(request)
        
        if not auth_token:
            raise GrpcAuthenticationError("缺少认证token")
        
        # 验证token
        user_info = await self._validate_token(auth_token)
        
        # 设置用户信息到上下文
        context.user_id = user_info.get("user_id")
        context.attributes["user_info"] = user_info
        
        # 检查权限
        if self.required_permissions:
            await self._check_permissions(user_info, self.required_permissions)
        
        logger.debug(f"用户认证成功: {context.user_id}")
        return request
    
    async def _process_response(self, context: RequestContext, response: Any) -> Any:
        """处理响应（认证拦截器通常不需要处理响应）"""
        return response
    
    async def _extract_auth_token(self, request: Any) -> Optional[str]:
        """
        从请求中提取认证token
        
        Args:
            request: 请求对象
            
        Returns:
            Optional[str]: 认证token
        """
        # 这里应该根据实际的gRPC请求格式来提取token
        # 示例实现
        if hasattr(request, 'metadata'):
            for key, value in request.metadata:
                if key.lower() == self.auth_header.lower():
                    if value.startswith("Bearer "):
                        return value[7:]
                    return value
        
        return None
    
    async def _validate_token(self, token: str) -> Dict[str, Any]:
        """
        验证JWT token
        
        Args:
            token: JWT token
            
        Returns:
            Dict[str, Any]: 用户信息
            
        Raises:
            GrpcAuthenticationError: token无效
        """
        try:
            # 这里应该使用实际的JWT库来验证token
            # 示例实现
            import jwt
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return payload
        except Exception as e:
            raise GrpcAuthenticationError(f"token验证失败: {e}")
    
    async def _check_permissions(self, user_info: Dict[str, Any], required_permissions: List[str]) -> None:
        """
        检查用户权限
        
        Args:
            user_info: 用户信息
            required_permissions: 必需的权限列表
            
        Raises:
            GrpcAuthenticationError: 权限不足
        """
        user_permissions = user_info.get("permissions", [])
        
        for permission in required_permissions:
            if permission not in user_permissions:
                raise GrpcAuthenticationError(f"权限不足，需要权限: {permission}")


class LoggingInterceptor(BaseInterceptor):
    """
    日志拦截器
    
    记录请求和响应日志。
    """
    
    def __init__(
        self, 
        name: Optional[str] = None,
        log_requests: bool = True,
        log_responses: bool = True,
        log_errors: bool = True,
        max_body_size: int = 1024
    ):
        """
        初始化日志拦截器
        
        Args:
            name: 拦截器名称
            log_requests: 是否记录请求日志
            log_responses: 是否记录响应日志
            log_errors: 是否记录错误日志
            max_body_size: 最大日志主体大小
        """
        super().__init__(name)
        self.log_requests = log_requests
        self.log_responses = log_responses
        self.log_errors = log_errors
        self.max_body_size = max_body_size
    
    async def _process_request(self, context: RequestContext, request: Any) -> Any:
        """记录请求日志"""
        if self.log_requests:
            request_info = {
                "request_id": context.request_id,
                "method": context.method_name,
                "service": context.service_name,
                "client_ip": context.client_ip,
                "user_id": context.user_id,
                "timestamp": context.start_time
            }
            
            # 记录请求体（如果需要且不太大）
            if hasattr(request, '__dict__') and len(str(request)) <= self.max_body_size:
                request_info["request_body"] = str(request)[:self.max_body_size]
            
            logger.info(f"gRPC请求: {json.dumps(request_info, ensure_ascii=False)}")
        
        return request
    
    async def _process_response(self, context: RequestContext, response: Any) -> Any:
        """记录响应日志"""
        if self.log_responses:
            response_info = {
                "request_id": context.request_id,
                "duration": context.duration,
                "status_code": context.status_code,
                "response_size": context.response_size,
                "timestamp": time.time()
            }
            
            # 记录响应体（如果需要且不太大）
            if hasattr(response, '__dict__') and len(str(response)) <= self.max_body_size:
                response_info["response_body"] = str(response)[:self.max_body_size]
            
            if context.error_message:
                response_info["error"] = context.error_message
                if self.log_errors:
                    logger.error(f"gRPC响应错误: {json.dumps(response_info, ensure_ascii=False)}")
                else:
                    logger.info(f"gRPC响应: {json.dumps(response_info, ensure_ascii=False)}")
            else:
                logger.info(f"gRPC响应: {json.dumps(response_info, ensure_ascii=False)}")
        
        return response


class TracingInterceptor(BaseInterceptor):
    """
    链路追踪拦截器
    
    支持分布式链路追踪。
    """
    
    def __init__(
        self, 
        name: Optional[str] = None,
        tracer_name: str = "grpc_tracer",
        trace_header: str = "x-trace-id",
        span_header: str = "x-span-id"
    ):
        """
        初始化追踪拦截器
        
        Args:
            name: 拦截器名称
            tracer_name: 追踪器名称
            trace_header: 追踪ID头名称
            span_header: 跨度ID头名称
        """
        super().__init__(name)
        self.tracer_name = tracer_name
        self.trace_header = trace_header
        self.span_header = span_header
    
    async def _process_request(self, context: RequestContext, request: Any) -> Any:
        """开始追踪"""
        # 提取或生成trace_id
        context.trace_id = await self._extract_trace_id(request) or str(uuid.uuid4())
        context.span_id = str(uuid.uuid4())
        
        # 记录追踪开始
        span_info = {
            "trace_id": context.trace_id,
            "span_id": context.span_id,
            "operation_name": f"{context.service_name}.{context.method_name}",
            "start_time": context.start_time,
            "tags": {
                "service.name": context.service_name,
                "rpc.method": context.method_name,
                "rpc.system": "grpc",
                "user_id": context.user_id
            }
        }
        
        logger.debug(f"开始追踪: {json.dumps(span_info, ensure_ascii=False)}")
        return request
    
    async def _process_response(self, context: RequestContext, response: Any) -> Any:
        """结束追踪"""
        context.end_time = time.time()
        
        # 记录追踪结束
        span_info = {
            "trace_id": context.trace_id,
            "span_id": context.span_id,
            "duration": context.duration,
            "status_code": context.status_code,
            "error": context.error_message is not None,
            "end_time": context.end_time
        }
        
        logger.debug(f"结束追踪: {json.dumps(span_info, ensure_ascii=False)}")
        return response
    
    async def _extract_trace_id(self, request: Any) -> Optional[str]:
        """
        从请求中提取trace_id
        
        Args:
            request: 请求对象
            
        Returns:
            Optional[str]: trace_id
        """
        if hasattr(request, 'metadata'):
            for key, value in request.metadata:
                if key.lower() == self.trace_header.lower():
                    return value
        
        return None


class MetricsInterceptor(BaseInterceptor):
    """
    性能监控拦截器
    
    收集性能指标和统计信息。
    """
    
    def __init__(
        self, 
        name: Optional[str] = None,
        collect_histograms: bool = True,
        collect_counters: bool = True
    ):
        """
        初始化性能监控拦截器
        
        Args:
            name: 拦截器名称
            collect_histograms: 是否收集直方图指标
            collect_counters: 是否收集计数器指标
        """
        super().__init__(name)
        self.collect_histograms = collect_histograms
        self.collect_counters = collect_counters
        
        # 指标存储
        self.method_metrics: Dict[str, Dict[str, Any]] = {}
        self.global_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_duration": 0.0,
            "min_duration": float('inf'),
            "max_duration": 0.0
        }
    
    async def _process_request(self, context: RequestContext, request: Any) -> Any:
        """开始性能监控"""
        method_key = f"{context.service_name}.{context.method_name}"
        
        # 初始化方法指标
        if method_key not in self.method_metrics:
            self.method_metrics[method_key] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_duration": 0.0,
                "min_duration": float('inf'),
                "max_duration": 0.0,
                "duration_histogram": []
            }
        
        # 增加请求计数
        if self.collect_counters:
            self.method_metrics[method_key]["total_requests"] += 1
            self.global_metrics["total_requests"] += 1
        
        return request
    
    async def _process_response(self, context: RequestContext, response: Any) -> Any:
        """收集性能指标"""
        method_key = f"{context.service_name}.{context.method_name}"
        duration = context.duration
        
        method_stats = self.method_metrics[method_key]
        
        # 更新指标
        if context.error_message:
            method_stats["failed_requests"] += 1
            self.global_metrics["failed_requests"] += 1
        else:
            method_stats["successful_requests"] += 1
            self.global_metrics["successful_requests"] += 1
        
        # 更新持续时间统计
        method_stats["total_duration"] += duration
        method_stats["min_duration"] = min(method_stats["min_duration"], duration)
        method_stats["max_duration"] = max(method_stats["max_duration"], duration)
        
        self.global_metrics["total_duration"] += duration
        self.global_metrics["min_duration"] = min(self.global_metrics["min_duration"], duration)
        self.global_metrics["max_duration"] = max(self.global_metrics["max_duration"], duration)
        
        # 收集直方图数据
        if self.collect_histograms:
            method_stats["duration_histogram"].append(duration)
            # 保持直方图大小在合理范围内
            if len(method_stats["duration_histogram"]) > 1000:
                method_stats["duration_histogram"] = method_stats["duration_histogram"][-1000:]
        
        return response
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        获取性能指标
        
        Returns:
            Dict[str, Any]: 性能指标数据
        """
        # 计算全局平均值
        global_avg_duration = 0.0
        if self.global_metrics["successful_requests"] > 0:
            global_avg_duration = self.global_metrics["total_duration"] / self.global_metrics["successful_requests"]
        
        # 计算方法级别的平均值
        method_stats = {}
        for method, stats in self.method_metrics.items():
            avg_duration = 0.0
            if stats["successful_requests"] > 0:
                avg_duration = stats["total_duration"] / stats["successful_requests"]
            
            success_rate = 0.0
            if stats["total_requests"] > 0:
                success_rate = stats["successful_requests"] / stats["total_requests"]
            
            method_stats[method] = {
                **stats,
                "avg_duration": avg_duration,
                "success_rate": success_rate
            }
            
            # 移除直方图数据以减少输出大小
            if "duration_histogram" in method_stats[method]:
                del method_stats[method]["duration_histogram"]
        
        return {
            "global": {
                **self.global_metrics,
                "avg_duration": global_avg_duration,
                "success_rate": self.global_metrics["successful_requests"] / max(self.global_metrics["total_requests"], 1)
            },
            "methods": method_stats
        }


class ExceptionInterceptor(BaseInterceptor):
    """
    异常处理拦截器
    
    统一处理和转换异常。
    """
    
    def __init__(
        self, 
        name: Optional[str] = None,
        handle_unknown_exceptions: bool = True,
        log_exceptions: bool = True
    ):
        """
        初始化异常处理拦截器
        
        Args:
            name: 拦截器名称
            handle_unknown_exceptions: 是否处理未知异常
            log_exceptions: 是否记录异常日志
        """
        super().__init__(name)
        self.handle_unknown_exceptions = handle_unknown_exceptions
        self.log_exceptions = log_exceptions
    
    async def _process_request(self, context: RequestContext, request: Any) -> Any:
        """请求处理（异常拦截器主要处理响应）"""
        return request
    
    async def _process_response(self, context: RequestContext, response: Any) -> Any:
        """处理异常响应"""
        # 异常处理主要在拦截器链的外层处理
        return response
    
    def handle_exception(self, context: RequestContext, exception: Exception) -> Exception:
        """
        处理异常
        
        Args:
            context: 请求上下文
            exception: 原始异常
            
        Returns:
            Exception: 处理后的异常
        """
        # 记录异常信息到上下文
        context.set_error(exception)
        
        # 记录异常日志
        if self.log_exceptions:
            error_info = {
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "method": context.method_name,
                "user_id": context.user_id,
                "error_type": type(exception).__name__,
                "error_message": str(exception),
                "duration": context.duration
            }
            
            logger.error(f"gRPC异常: {json.dumps(error_info, ensure_ascii=False)}")
        
        # 转换已知异常
        if isinstance(exception, GrpcException):
            return exception
        
        # 处理未知异常
        if self.handle_unknown_exceptions:
            return GrpcException(f"服务器内部错误: {exception}", cause=exception)
        
        return exception


class InterceptorChain:
    """
    拦截器链
    
    管理多个拦截器的执行顺序。
    """
    
    def __init__(self, interceptors: Optional[List[BaseInterceptor]] = None):
        """
        初始化拦截器链
        
        Args:
            interceptors: 拦截器列表
        """
        self.interceptors = interceptors or []
        self.exception_interceptor: Optional[ExceptionInterceptor] = None
        
        # 查找异常处理拦截器
        for interceptor in self.interceptors:
            if isinstance(interceptor, ExceptionInterceptor):
                self.exception_interceptor = interceptor
                break
    
    def add_interceptor(self, interceptor: BaseInterceptor) -> None:
        """
        添加拦截器
        
        Args:
            interceptor: 拦截器实例
        """
        self.interceptors.append(interceptor)
        
        if isinstance(interceptor, ExceptionInterceptor):
            self.exception_interceptor = interceptor
    
    def remove_interceptor(self, name: str) -> bool:
        """
        移除拦截器
        
        Args:
            name: 拦截器名称
            
        Returns:
            bool: 是否成功移除
        """
        for i, interceptor in enumerate(self.interceptors):
            if interceptor.name == name:
                removed = self.interceptors.pop(i)
                if isinstance(removed, ExceptionInterceptor):
                    self.exception_interceptor = None
                return True
        return False
    
    async def process_request(self, context: RequestContext, request: Any) -> Any:
        """
        处理请求（正向执行所有拦截器）
        
        Args:
            context: 请求上下文
            request: 请求对象
            
        Returns:
            Any: 处理后的请求对象
        """
        current_request = request
        
        try:
            for interceptor in self.interceptors:
                current_request = await interceptor.process_request(context, current_request)
            return current_request
        except Exception as e:
            # 如果有异常处理拦截器，使用它处理异常
            if self.exception_interceptor:
                handled_exception = self.exception_interceptor.handle_exception(context, e)
                raise handled_exception
            raise
    
    async def process_response(self, context: RequestContext, response: Any) -> Any:
        """
        处理响应（反向执行所有拦截器）
        
        Args:
            context: 请求上下文
            response: 响应对象
            
        Returns:
            Any: 处理后的响应对象
        """
        current_response = response
        
        try:
            # 反向执行拦截器
            for interceptor in reversed(self.interceptors):
                current_response = await interceptor.process_response(context, current_response)
            return current_response
        except Exception as e:
            # 如果有异常处理拦截器，使用它处理异常
            if self.exception_interceptor:
                handled_exception = self.exception_interceptor.handle_exception(context, e)
                raise handled_exception
            raise
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取所有拦截器的统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        return {
            interceptor.name: interceptor.get_stats()
            for interceptor in self.interceptors
        }
    
    def enable_all(self) -> None:
        """启用所有拦截器"""
        for interceptor in self.interceptors:
            interceptor.enable()
    
    def disable_all(self) -> None:
        """禁用所有拦截器"""
        for interceptor in self.interceptors:
            interceptor.disable()


# 预定义拦截器组合
def create_default_server_interceptors() -> List[BaseInterceptor]:
    """
    创建默认的服务端拦截器链
    
    Returns:
        List[BaseInterceptor]: 拦截器列表
    """
    return [
        TracingInterceptor("server_tracing"),
        LoggingInterceptor("server_logging"),
        MetricsInterceptor("server_metrics"),
        ExceptionInterceptor("server_exception")
    ]


def create_default_client_interceptors() -> List[BaseInterceptor]:
    """
    创建默认的客户端拦截器链
    
    Returns:
        List[BaseInterceptor]: 拦截器列表
    """
    return [
        TracingInterceptor("client_tracing"),
        LoggingInterceptor("client_logging", log_responses=False),
        MetricsInterceptor("client_metrics"),
        ExceptionInterceptor("client_exception")
    ]


def create_auth_interceptors(jwt_secret: str, required_permissions: Optional[List[str]] = None) -> List[BaseInterceptor]:
    """
    创建带认证的拦截器链
    
    Args:
        jwt_secret: JWT密钥
        required_permissions: 必需的权限列表
        
    Returns:
        List[BaseInterceptor]: 拦截器列表
    """
    return [
        AuthInterceptor("auth", jwt_secret=jwt_secret, required_permissions=required_permissions),
        TracingInterceptor("auth_tracing"),
        LoggingInterceptor("auth_logging"),
        MetricsInterceptor("auth_metrics"),
        ExceptionInterceptor("auth_exception")
    ]