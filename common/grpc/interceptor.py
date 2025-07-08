"""
gRPC拦截器模块

该模块实现了完整的gRPC拦截器机制，包含认证、日志、追踪、性能、异常处理等拦截器。
支持拦截器链式调用和自定义拦截器扩展。
"""

import asyncio
import time
import uuid
import json
from typing import Dict, List, Optional, Any, Callable, Union, Tuple
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

try:
    import grpc
    import grpc.aio
    from grpc import StatusCode
    GRPC_AVAILABLE = True
except ImportError:
    # 模拟grpc模块
    GRPC_AVAILABLE = False
    
    class StatusCode:
        OK = 'OK'
        UNAUTHENTICATED = 'UNAUTHENTICATED'
        PERMISSION_DENIED = 'PERMISSION_DENIED'
        INTERNAL = 'INTERNAL'
        UNAVAILABLE = 'UNAVAILABLE'
        DEADLINE_EXCEEDED = 'DEADLINE_EXCEEDED'
    
    class grpc:
        @staticmethod
        def unary_unary(func):
            return func
        
        @staticmethod
        def unary_stream(func):
            return func
        
        @staticmethod
        def stream_unary(func):
            return func
        
        @staticmethod
        def stream_stream(func):
            return func

from .exceptions import (
    GrpcAuthenticationError,
    GrpcAuthorizationError,
    BaseGrpcException,
    handle_async_grpc_exception
)


@dataclass
class InterceptorContext:
    """拦截器上下文"""
    # 请求信息
    method_name: str = ""                   # 方法名
    request: Any = None                     # 请求对象
    response: Any = None                    # 响应对象
    
    # 元数据
    metadata: Dict[str, str] = field(default_factory=dict)  # 元数据
    headers: Dict[str, str] = field(default_factory=dict)   # 请求头
    
    # 追踪信息
    trace_id: Optional[str] = None          # 追踪ID
    span_id: Optional[str] = None           # 跨度ID
    user_id: Optional[str] = None           # 用户ID
    
    # 时间信息
    start_time: float = field(default_factory=time.time)  # 开始时间
    end_time: Optional[float] = None        # 结束时间
    
    # 错误信息
    error: Optional[Exception] = None       # 异常
    status_code: Optional[str] = None       # 状态码
    
    # 自定义属性
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> float:
        """获取执行时间(秒)"""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    @property
    def is_successful(self) -> bool:
        """是否成功"""
        return self.error is None and self.status_code in [None, StatusCode.OK]
    
    def set_attribute(self, key: str, value: Any):
        """设置自定义属性"""
        self.attributes[key] = value
    
    def get_attribute(self, key: str, default: Any = None) -> Any:
        """获取自定义属性"""
        return self.attributes.get(key, default)


class BaseInterceptor(ABC):
    """基础拦截器抽象类"""
    
    def __init__(self, name: str):
        self.name = name
        self.enabled = True
    
    @abstractmethod
    async def before_call(self, context: InterceptorContext) -> Optional[InterceptorContext]:
        """
        调用前处理
        
        Args:
            context: 拦截器上下文
            
        Returns:
            Optional[InterceptorContext]: 修改后的上下文，返回None表示中断调用
        """
        pass
    
    @abstractmethod
    async def after_call(self, context: InterceptorContext) -> InterceptorContext:
        """
        调用后处理
        
        Args:
            context: 拦截器上下文
            
        Returns:
            InterceptorContext: 修改后的上下文
        """
        pass
    
    async def on_error(self, context: InterceptorContext) -> InterceptorContext:
        """
        错误处理
        
        Args:
            context: 拦截器上下文
            
        Returns:
            InterceptorContext: 修改后的上下文
        """
        return context
    
    def disable(self):
        """禁用拦截器"""
        self.enabled = False
    
    def enable(self):
        """启用拦截器"""
        self.enabled = True


class AuthInterceptor(BaseInterceptor):
    """认证拦截器"""
    
    def __init__(
        self,
        token_validator: Optional[Callable[[str], Tuple[bool, Optional[str]]]] = None,
        excluded_methods: Optional[List[str]] = None
    ):
        """
        初始化认证拦截器
        
        Args:
            token_validator: token验证函数，返回(is_valid, user_id)
            excluded_methods: 排除的方法列表
        """
        super().__init__("auth")
        self._token_validator = token_validator or self._default_token_validator
        self._excluded_methods = set(excluded_methods or [])
    
    def _default_token_validator(self, token: str) -> Tuple[bool, Optional[str]]:
        """默认token验证器"""
        # 简单的JWT模拟验证
        if token and token.startswith("Bearer "):
            # 在实际应用中，这里应该验证JWT token
            return True, "default_user"
        return False, None
    
    async def before_call(self, context: InterceptorContext) -> Optional[InterceptorContext]:
        """执行认证检查"""
        if context.method_name in self._excluded_methods:
            return context
        
        # 获取认证token
        token = context.headers.get("authorization") or context.metadata.get("authorization")
        
        if not token:
            context.error = GrpcAuthenticationError(
                message="缺少认证token",
                auth_type="bearer"
            )
            context.status_code = StatusCode.UNAUTHENTICATED
            return None
        
        # 验证token
        try:
            is_valid, user_id = self._token_validator(token)
            if not is_valid:
                context.error = GrpcAuthenticationError(
                    message="无效的认证token",
                    auth_type="bearer"
                )
                context.status_code = StatusCode.UNAUTHENTICATED
                return None
            
            # 设置用户信息
            context.user_id = user_id
            context.set_attribute("authenticated", True)
            context.set_attribute("auth_method", "bearer")
            
            return context
            
        except Exception as e:
            context.error = GrpcAuthenticationError(
                message=f"认证验证失败: {str(e)}",
                auth_type="bearer",
                cause=e
            )
            context.status_code = StatusCode.UNAUTHENTICATED
            return None
    
    async def after_call(self, context: InterceptorContext) -> InterceptorContext:
        """认证后处理"""
        return context


class LoggingInterceptor(BaseInterceptor):
    """日志拦截器"""
    
    def __init__(
        self,
        logger=None,
        log_requests: bool = True,
        log_responses: bool = True,
        log_errors: bool = True,
        sensitive_fields: Optional[List[str]] = None
    ):
        """
        初始化日志拦截器
        
        Args:
            logger: 日志器实例
            log_requests: 是否记录请求
            log_responses: 是否记录响应
            log_errors: 是否记录错误
            sensitive_fields: 敏感字段列表（将被脱敏）
        """
        super().__init__("logging")
        
        # 尝试导入logger
        if logger is None:
            try:
                from common.logger import logger as default_logger
                self._logger = default_logger
            except ImportError:
                # 使用简单的打印作为后备
                self._logger = self._simple_logger
        else:
            self._logger = logger
        
        self._log_requests = log_requests
        self._log_responses = log_responses
        self._log_errors = log_errors
        self._sensitive_fields = set(sensitive_fields or ["password", "token", "secret"])
    
    def _simple_logger(self):
        """简单日志器"""
        class SimpleLogger:
            def info(self, msg, **kwargs):
                print(f"INFO: {msg} {kwargs}")
            
            def error(self, msg, **kwargs):
                print(f"ERROR: {msg} {kwargs}")
            
            def debug(self, msg, **kwargs):
                print(f"DEBUG: {msg} {kwargs}")
        
        return SimpleLogger()
    
    def _sanitize_data(self, data: Any) -> Any:
        """脱敏数据"""
        if isinstance(data, dict):
            return {
                key: "***" if key.lower() in self._sensitive_fields else self._sanitize_data(value)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        elif hasattr(data, '__dict__'):
            # 处理protobuf对象
            return {
                key: "***" if key.lower() in self._sensitive_fields else str(value)
                for key, value in data.__dict__.items()
                if not key.startswith('_')
            }
        else:
            return str(data)
    
    async def before_call(self, context: InterceptorContext) -> Optional[InterceptorContext]:
        """记录请求日志"""
        if self._log_requests:
            try:
                sanitized_request = self._sanitize_data(context.request) if context.request else None
                
                self._logger.info(
                    f"gRPC请求开始: {context.method_name}",
                    method=context.method_name,
                    trace_id=context.trace_id,
                    user_id=context.user_id,
                    request_data=sanitized_request,
                    metadata=context.metadata
                )
            except Exception:
                pass  # 忽略日志记录异常
        
        return context
    
    async def after_call(self, context: InterceptorContext) -> InterceptorContext:
        """记录响应日志"""
        if self._log_responses and context.is_successful:
            try:
                sanitized_response = self._sanitize_data(context.response) if context.response else None
                
                self._logger.info(
                    f"gRPC请求完成: {context.method_name}",
                    method=context.method_name,
                    trace_id=context.trace_id,
                    user_id=context.user_id,
                    duration=context.duration,
                    response_data=sanitized_response,
                    status="success"
                )
            except Exception:
                pass  # 忽略日志记录异常
        
        return context
    
    async def on_error(self, context: InterceptorContext) -> InterceptorContext:
        """记录错误日志"""
        if self._log_errors:
            try:
                error_info = {
                    'error_type': type(context.error).__name__ if context.error else 'Unknown',
                    'error_message': str(context.error) if context.error else 'Unknown error',
                    'status_code': context.status_code
                }
                
                if isinstance(context.error, BaseGrpcException):
                    error_info.update(context.error.to_dict())
                
                self._logger.error(
                    f"gRPC请求失败: {context.method_name}",
                    method=context.method_name,
                    trace_id=context.trace_id,
                    user_id=context.user_id,
                    duration=context.duration,
                    error_info=error_info,
                    status="error"
                )
            except Exception:
                pass  # 忽略日志记录异常
        
        return context


class TracingInterceptor(BaseInterceptor):
    """链路追踪拦截器"""
    
    def __init__(self, trace_header: str = "x-trace-id", span_header: str = "x-span-id"):
        """
        初始化追踪拦截器
        
        Args:
            trace_header: 追踪ID header名称
            span_header: 跨度ID header名称
        """
        super().__init__("tracing")
        self._trace_header = trace_header
        self._span_header = span_header
    
    def _generate_trace_id(self) -> str:
        """生成追踪ID"""
        return str(uuid.uuid4())
    
    def _generate_span_id(self) -> str:
        """生成跨度ID"""
        return str(uuid.uuid4())
    
    async def before_call(self, context: InterceptorContext) -> Optional[InterceptorContext]:
        """设置追踪信息"""
        # 从header或metadata中获取现有的trace_id
        trace_id = (
            context.headers.get(self._trace_header) or 
            context.metadata.get(self._trace_header) or
            self._generate_trace_id()
        )
        
        # 生成新的span_id
        span_id = self._generate_span_id()
        
        # 设置追踪信息
        context.trace_id = trace_id
        context.span_id = span_id
        
        # 更新metadata
        context.metadata[self._trace_header] = trace_id
        context.metadata[self._span_header] = span_id
        
        # 设置追踪属性
        context.set_attribute("trace.trace_id", trace_id)
        context.set_attribute("trace.span_id", span_id)
        context.set_attribute("trace.method", context.method_name)
        
        return context
    
    async def after_call(self, context: InterceptorContext) -> InterceptorContext:
        """完成追踪信息"""
        context.set_attribute("trace.duration", context.duration)
        context.set_attribute("trace.status", "success" if context.is_successful else "error")
        
        return context


class MetricsInterceptor(BaseInterceptor):
    """性能指标拦截器"""
    
    def __init__(self, metrics_collector=None):
        """
        初始化性能拦截器
        
        Args:
            metrics_collector: 指标收集器
        """
        super().__init__("metrics")
        
        # 尝试导入监控模块
        if metrics_collector is None:
            try:
                from common.monitor import monitor as default_monitor
                self._metrics = default_monitor
            except ImportError:
                # 使用简单的指标收集器
                self._metrics = self._simple_metrics_collector()
        else:
            self._metrics = metrics_collector
    
    def _simple_metrics_collector(self):
        """简单指标收集器"""
        class SimpleMetrics:
            def __init__(self):
                self.counters = {}
                self.histograms = {}
            
            def increment_counter(self, name, value=1, **tags):
                key = f"{name}_{tags}"
                self.counters[key] = self.counters.get(key, 0) + value
            
            def record_histogram(self, name, value, **tags):
                key = f"{name}_{tags}"
                if key not in self.histograms:
                    self.histograms[key] = []
                self.histograms[key].append(value)
            
            def record_timer(self, name, duration, **tags):
                self.record_histogram(name, duration, **tags)
        
        return SimpleMetrics()
    
    async def before_call(self, context: InterceptorContext) -> Optional[InterceptorContext]:
        """开始性能监控"""
        # 记录请求开始
        self._metrics.increment_counter(
            "grpc_requests_total",
            method=context.method_name,
            status="started"
        )
        
        return context
    
    async def after_call(self, context: InterceptorContext) -> InterceptorContext:
        """记录性能指标"""
        # 记录请求完成
        status = "success" if context.is_successful else "error"
        
        self._metrics.increment_counter(
            "grpc_requests_total",
            method=context.method_name,
            status=status
        )
        
        # 记录响应时间
        self._metrics.record_timer(
            "grpc_request_duration_seconds",
            context.duration,
            method=context.method_name,
            status=status
        )
        
        # 记录用户相关指标
        if context.user_id:
            self._metrics.increment_counter(
                "grpc_user_requests_total",
                user_id=context.user_id,
                method=context.method_name,
                status=status
            )
        
        return context
    
    async def on_error(self, context: InterceptorContext) -> InterceptorContext:
        """记录错误指标"""
        error_type = type(context.error).__name__ if context.error else "Unknown"
        
        self._metrics.increment_counter(
            "grpc_errors_total",
            method=context.method_name,
            error_type=error_type,
            status_code=context.status_code or "UNKNOWN"
        )
        
        return context


class ExceptionInterceptor(BaseInterceptor):
    """异常处理拦截器"""
    
    def __init__(
        self,
        error_handler: Optional[Callable[[Exception, InterceptorContext], Exception]] = None,
        log_errors: bool = True
    ):
        """
        初始化异常拦截器
        
        Args:
            error_handler: 自定义错误处理函数
            log_errors: 是否记录错误日志
        """
        super().__init__("exception")
        self._error_handler = error_handler
        self._log_errors = log_errors
    
    def _default_error_handler(self, error: Exception, context: InterceptorContext) -> Exception:
        """默认错误处理"""
        if isinstance(error, BaseGrpcException):
            return error
        
        # 将标准异常转换为gRPC异常
        if isinstance(error, ValueError):
            return BaseGrpcException(
                message=f"参数错误: {str(error)}",
                error_code=400,
                cause=error
            )
        elif isinstance(error, TimeoutError):
            return BaseGrpcException(
                message=f"请求超时: {str(error)}",
                error_code=408,
                cause=error
            )
        else:
            return BaseGrpcException(
                message=f"内部错误: {str(error)}",
                error_code=500,
                cause=error
            )
    
    async def before_call(self, context: InterceptorContext) -> Optional[InterceptorContext]:
        """异常处理前置检查"""
        return context
    
    async def after_call(self, context: InterceptorContext) -> InterceptorContext:
        """正常完成处理"""
        return context
    
    async def on_error(self, context: InterceptorContext) -> InterceptorContext:
        """异常处理"""
        if context.error:
            # 使用自定义错误处理器或默认处理器
            handler = self._error_handler or self._default_error_handler
            
            try:
                processed_error = handler(context.error, context)
                context.error = processed_error
                
                # 设置相应的状态码
                if isinstance(processed_error, BaseGrpcException):
                    context.status_code = self._map_error_to_status_code(processed_error)
                
            except Exception as e:
                # 如果错误处理器本身抛出异常，使用原始错误
                if self._log_errors:
                    print(f"错误处理器异常: {str(e)}")
        
        return context
    
    def _map_error_to_status_code(self, error: BaseGrpcException) -> str:
        """将gRPC异常映射到状态码"""
        # 简单的映射规则
        error_code = getattr(error, 'error_code', None)
        
        if error_code:
            if error_code in [1301, 1302, 1303, 1304]:  # 认证相关
                return StatusCode.UNAUTHENTICATED
            elif error_code in [1201, 1202]:  # 服务不可用
                return StatusCode.UNAVAILABLE
            elif error_code in [1401, 1402, 1501, 1502]:  # 超时相关
                return StatusCode.DEADLINE_EXCEEDED
            else:
                return StatusCode.INTERNAL
        
        return StatusCode.INTERNAL


class InterceptorChain:
    """拦截器链"""
    
    def __init__(self):
        self._interceptors: List[BaseInterceptor] = []
        self._context_factory: Callable[[], InterceptorContext] = InterceptorContext
    
    def add_interceptor(self, interceptor: BaseInterceptor):
        """添加拦截器"""
        self._interceptors.append(interceptor)
    
    def remove_interceptor(self, name: str) -> bool:
        """移除拦截器"""
        for i, interceptor in enumerate(self._interceptors):
            if interceptor.name == name:
                del self._interceptors[i]
                return True
        return False
    
    def get_interceptor(self, name: str) -> Optional[BaseInterceptor]:
        """获取拦截器"""
        for interceptor in self._interceptors:
            if interceptor.name == name:
                return interceptor
        return None
    
    def clear(self):
        """清空拦截器链"""
        self._interceptors.clear()
    
    @property
    def interceptors(self) -> List[BaseInterceptor]:
        """获取所有拦截器"""
        return self._interceptors.copy()
    
    async def execute(
        self,
        method_name: str,
        request: Any,
        handler: Callable[[Any], Any],
        **kwargs
    ) -> Tuple[Any, InterceptorContext]:
        """
        执行拦截器链
        
        Args:
            method_name: 方法名
            request: 请求对象
            handler: 实际处理函数
            **kwargs: 其他参数
            
        Returns:
            Tuple[Any, InterceptorContext]: (响应, 上下文)
        """
        # 创建上下文
        context = self._context_factory()
        context.method_name = method_name
        context.request = request
        
        # 从kwargs中提取元数据和headers
        context.metadata.update(kwargs.get('metadata', {}))
        context.headers.update(kwargs.get('headers', {}))
        
        try:
            # 执行前置拦截器
            for interceptor in self._interceptors:
                if not interceptor.enabled:
                    continue
                
                result = await interceptor.before_call(context)
                if result is None:
                    # 拦截器中断了调用
                    if context.error:
                        raise context.error
                    else:
                        raise BaseGrpcException(
                            message="请求被拦截器中断",
                            error_code=403
                        )
                context = result
            
            # 执行实际处理函数
            try:
                if asyncio.iscoroutinefunction(handler):
                    response = await handler(request)
                else:
                    response = handler(request)
                
                context.response = response
                context.end_time = time.time()
                
            except Exception as e:
                context.error = e
                context.end_time = time.time()
                
                # 执行错误处理拦截器
                for interceptor in reversed(self._interceptors):
                    if interceptor.enabled:
                        context = await interceptor.on_error(context)
                
                # 重新抛出异常
                raise context.error
            
            # 执行后置拦截器
            for interceptor in reversed(self._interceptors):
                if interceptor.enabled:
                    context = await interceptor.after_call(context)
            
            return context.response, context
            
        except Exception as e:
            context.error = e
            context.end_time = time.time()
            raise


# 默认拦截器链
_default_chain = InterceptorChain()


def get_default_chain() -> InterceptorChain:
    """获取默认拦截器链"""
    return _default_chain


def setup_default_interceptors(
    enable_auth: bool = True,
    enable_logging: bool = True,
    enable_tracing: bool = True,
    enable_metrics: bool = True,
    enable_exception_handling: bool = True,
    **kwargs
):
    """
    设置默认拦截器
    
    Args:
        enable_auth: 启用认证拦截器
        enable_logging: 启用日志拦截器
        enable_tracing: 启用追踪拦截器
        enable_metrics: 启用指标拦截器
        enable_exception_handling: 启用异常处理拦截器
        **kwargs: 各拦截器的配置参数
    """
    chain = get_default_chain()
    chain.clear()
    
    # 按顺序添加拦截器
    if enable_tracing:
        chain.add_interceptor(TracingInterceptor(**kwargs.get('tracing', {})))
    
    if enable_auth:
        chain.add_interceptor(AuthInterceptor(**kwargs.get('auth', {})))
    
    if enable_logging:
        chain.add_interceptor(LoggingInterceptor(**kwargs.get('logging', {})))
    
    if enable_metrics:
        chain.add_interceptor(MetricsInterceptor(**kwargs.get('metrics', {})))
    
    if enable_exception_handling:
        chain.add_interceptor(ExceptionInterceptor(**kwargs.get('exception', {})))


# 装饰器支持
def with_interceptors(interceptor_chain: Optional[InterceptorChain] = None):
    """
    拦截器装饰器
    
    Args:
        interceptor_chain: 拦截器链，为None时使用默认链
    """
    def decorator(func):
        chain = interceptor_chain or get_default_chain()
        
        async def wrapper(*args, **kwargs):
            # 假设第一个参数是request
            request = args[0] if args else None
            method_name = func.__name__
            
            async def handler(req):
                return await func(*args, **kwargs)
            
            response, context = await chain.execute(method_name, request, handler, **kwargs)
            return response
        
        return wrapper
    return decorator


# 导出所有公共接口
__all__ = [
    'InterceptorContext',
    'BaseInterceptor',
    'AuthInterceptor',
    'LoggingInterceptor', 
    'TracingInterceptor',
    'MetricsInterceptor',
    'ExceptionInterceptor',
    'InterceptorChain',
    'get_default_chain',
    'setup_default_interceptors',
    'with_interceptors'
]