"""
处理器装饰器模块

该模块提供处理器相关的装饰器，用于标记消息处理器并自动绑定协议。
支持控制器类、路由方法和自动协议绑定。

主要功能：
- @handler: 标记消息处理器，自动绑定请求和响应协议号
- @controller: 标记控制器类
- @route: 路由装饰器，将消息路由到对应方法
- 自动协议验证和转换
- 处理器统计和监控
"""

import asyncio
import functools
import inspect
import time
from typing import Callable, Any, Dict, Optional, Type, List, Union, get_type_hints
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from common.logger import logger


class HandlerType(Enum):
    """处理器类型枚举"""
    MESSAGE = "message"
    EVENT = "event"
    COMMAND = "command"
    QUERY = "query"


@dataclass
class HandlerInfo:
    """处理器信息"""
    handler_name: str
    handler_type: HandlerType
    request_proto: Optional[Type] = None
    response_proto: Optional[Type] = None
    request_proto_id: Optional[int] = None
    response_proto_id: Optional[int] = None
    timeout: float = 30.0
    max_retries: int = 3
    rate_limit: Optional[int] = None
    cache_ttl: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ControllerInfo:
    """控制器信息"""
    controller_name: str
    controller_class: Type
    handlers: Dict[str, HandlerInfo] = field(default_factory=dict)
    routes: Dict[Union[int, str], str] = field(default_factory=dict)
    middleware: List[Callable] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouteInfo:
    """路由信息"""
    route_key: Union[int, str]
    handler_name: str
    controller_name: str
    method: Callable
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerStatistics:
    """处理器统计信息"""
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency: float = 0.0
    average_latency: float = 0.0
    max_latency: float = 0.0
    min_latency: float = float('inf')
    last_call_time: float = 0.0


class HandlerRegistry:
    """处理器注册表"""
    
    def __init__(self):
        self._controllers: Dict[str, ControllerInfo] = {}
        self._handlers: Dict[str, HandlerInfo] = {}
        self._routes: Dict[Union[int, str], RouteInfo] = {}
        self._statistics: Dict[str, HandlerStatistics] = defaultdict(HandlerStatistics)
        self._middleware: List[Callable] = []
    
    def register_controller(self, controller_info: ControllerInfo):
        """注册控制器"""
        self._controllers[controller_info.controller_name] = controller_info
        logger.info("控制器注册成功",
                   controller_name=controller_info.controller_name,
                   handlers_count=len(controller_info.handlers))
    
    def register_handler(self, handler_info: HandlerInfo):
        """注册处理器"""
        self._handlers[handler_info.handler_name] = handler_info
        logger.info("处理器注册成功",
                   handler_name=handler_info.handler_name,
                   handler_type=handler_info.handler_type.value)
    
    def register_route(self, route_info: RouteInfo):
        """注册路由"""
        self._routes[route_info.route_key] = route_info
        logger.info("路由注册成功",
                   route_key=route_info.route_key,
                   handler_name=route_info.handler_name)
    
    def get_controller(self, controller_name: str) -> Optional[ControllerInfo]:
        """获取控制器信息"""
        return self._controllers.get(controller_name)
    
    def get_handler(self, handler_name: str) -> Optional[HandlerInfo]:
        """获取处理器信息"""
        return self._handlers.get(handler_name)
    
    def get_route(self, route_key: Union[int, str]) -> Optional[RouteInfo]:
        """获取路由信息"""
        return self._routes.get(route_key)
    
    def get_statistics(self, handler_name: str) -> HandlerStatistics:
        """获取处理器统计信息"""
        return self._statistics[handler_name]
    
    def update_statistics(self, handler_name: str, success: bool, latency: float):
        """更新处理器统计信息"""
        stats = self._statistics[handler_name]
        stats.total_calls += 1
        stats.total_latency += latency
        stats.last_call_time = time.time()
        
        if success:
            stats.success_calls += 1
        else:
            stats.failed_calls += 1
        
        # 更新延迟统计
        stats.average_latency = stats.total_latency / stats.total_calls
        stats.max_latency = max(stats.max_latency, latency)
        stats.min_latency = min(stats.min_latency, latency)
    
    def add_global_middleware(self, middleware: Callable):
        """添加全局中间件"""
        self._middleware.append(middleware)
    
    def get_global_middleware(self) -> List[Callable]:
        """获取全局中间件"""
        return self._middleware.copy()
    
    def list_controllers(self) -> List[str]:
        """列出所有控制器"""
        return list(self._controllers.keys())
    
    def list_handlers(self) -> List[str]:
        """列出所有处理器"""
        return list(self._handlers.keys())
    
    def list_routes(self) -> Dict[Union[int, str], str]:
        """列出所有路由"""
        return {k: v.handler_name for k, v in self._routes.items()}


# 全局处理器注册表
_handler_registry = HandlerRegistry()


def controller(name: Optional[str] = None, 
               middleware: Optional[List[Callable]] = None,
               **kwargs) -> Callable:
    """
    标记控制器类的装饰器
    
    Args:
        name: 控制器名称，默认使用类名
        middleware: 控制器中间件列表
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @controller(name="UserController")
    class UserController:
        @handler(request_proto=LoginRequest, response_proto=LoginResponse)
        async def handle_login(self, request: LoginRequest) -> LoginResponse:
            pass
    ```
    """
    def decorator(cls: Type) -> Type:
        # 获取控制器名称
        controller_name = name or cls.__name__
        
        # 创建控制器信息
        controller_info = ControllerInfo(
            controller_name=controller_name,
            controller_class=cls,
            middleware=middleware or [],
            metadata=kwargs
        )
        
        # 扫描类中的处理器方法
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if hasattr(attr, '_handler_info'):
                handler_info = attr._handler_info
                controller_info.handlers[handler_info.handler_name] = handler_info
            
            if hasattr(attr, '_route_info'):
                route_info = attr._route_info
                route_info.controller_name = controller_name
                controller_info.routes[route_info.route_key] = route_info.handler_name
        
        # 注册控制器
        _handler_registry.register_controller(controller_info)
        
        # 在类上添加控制器信息
        cls._controller_info = controller_info
        
        logger.info("控制器装饰完成",
                   controller_name=controller_name,
                   handlers_count=len(controller_info.handlers))
        
        return cls
    
    return decorator


def handler(request_proto: Optional[Type] = None,
           response_proto: Optional[Type] = None,
           request_proto_id: Optional[int] = None,
           response_proto_id: Optional[int] = None,
           handler_type: HandlerType = HandlerType.MESSAGE,
           timeout: float = 30.0,
           max_retries: int = 3,
           rate_limit: Optional[int] = None,
           cache_ttl: Optional[int] = None,
           **kwargs) -> Callable:
    """
    标记消息处理器的装饰器
    
    Args:
        request_proto: 请求协议类
        response_proto: 响应协议类
        request_proto_id: 请求协议ID
        response_proto_id: 响应协议ID
        handler_type: 处理器类型
        timeout: 超时时间(秒)
        max_retries: 最大重试次数
        rate_limit: 速率限制(每分钟)
        cache_ttl: 缓存TTL(秒)
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的方法
        
    使用示例：
    ```python
    @handler(
        request_proto=LoginRequest,
        response_proto=LoginResponse,
        timeout=10.0,
        rate_limit=100
    )
    async def handle_login(self, request: LoginRequest) -> LoginResponse:
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        # 自动推断协议类型
        inferred_request_proto = request_proto
        inferred_response_proto = response_proto
        
        if inferred_request_proto is None or inferred_response_proto is None:
            type_hints = get_type_hints(func)
            if inferred_request_proto is None and len(type_hints) > 0:
                # 尝试从参数类型推断请求协议
                sig = inspect.signature(func)
                params = list(sig.parameters.values())
                if len(params) > 1:  # 排除self参数
                    request_proto_inferred = params[1].annotation
                    if request_proto_inferred != inspect.Parameter.empty:
                        inferred_request_proto = request_proto_inferred
            
            if inferred_response_proto is None and 'return' in type_hints:
                inferred_response_proto = type_hints['return']
        
        # 获取协议ID
        req_proto_id = request_proto_id
        resp_proto_id = response_proto_id
        
        if inferred_request_proto and hasattr(inferred_request_proto, 'get_message_id'):
            req_proto_id = inferred_request_proto.get_message_id()
        
        if inferred_response_proto and hasattr(inferred_response_proto, 'get_message_id'):
            resp_proto_id = inferred_response_proto.get_message_id()
        
        # 创建处理器信息
        handler_info = HandlerInfo(
            handler_name=func.__name__,
            handler_type=handler_type,
            request_proto=inferred_request_proto,
            response_proto=inferred_response_proto,
            request_proto_id=req_proto_id,
            response_proto_id=resp_proto_id,
            timeout=timeout,
            max_retries=max_retries,
            rate_limit=rate_limit,
            cache_ttl=cache_ttl,
            metadata=kwargs
        )
        
        # 注册处理器
        _handler_registry.register_handler(handler_info)
        
        # 在方法上添加处理器信息
        func._handler_info = handler_info
        
        # 包装方法以添加处理器功能
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            handler_name = func.__name__
            
            try:
                # 执行前置中间件
                await _execute_middleware(handler_info, "before", args, kwargs)
                
                # 参数验证和转换
                processed_args, processed_kwargs = await _process_handler_args(
                    func, args, kwargs, handler_info
                )
                
                # 调用原始方法
                result = await func(*processed_args, **processed_kwargs)
                
                # 结果验证和转换
                processed_result = await _process_handler_result(result, handler_info)
                
                # 执行后置中间件
                await _execute_middleware(handler_info, "after", processed_result)
                
                # 更新统计信息
                latency = time.time() - start_time
                _handler_registry.update_statistics(handler_name, True, latency)
                
                logger.debug("处理器调用成功",
                           handler_name=handler_name,
                           handler_type=handler_type.value,
                           latency=latency)
                
                return processed_result
                
            except Exception as e:
                # 更新统计信息
                latency = time.time() - start_time
                _handler_registry.update_statistics(handler_name, False, latency)
                
                logger.error("处理器调用失败",
                           handler_name=handler_name,
                           handler_type=handler_type.value,
                           error=str(e),
                           latency=latency)
                
                # 执行错误中间件
                await _execute_middleware(handler_info, "error", e)
                
                raise
        
        return wrapper
    
    return decorator


def route(route_key: Union[int, str], 
          priority: int = 0,
          **kwargs) -> Callable:
    """
    路由装饰器，将消息路由到对应方法
    
    Args:
        route_key: 路由键（协议ID或字符串）
        priority: 路由优先级
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的方法
        
    使用示例：
    ```python
    @route(route_key=1001)
    @handler(request_proto=LoginRequest, response_proto=LoginResponse)
    async def handle_login(self, request: LoginRequest) -> LoginResponse:
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        # 创建路由信息
        route_info = RouteInfo(
            route_key=route_key,
            handler_name=func.__name__,
            controller_name="",  # 将在controller装饰器中设置
            method=func,
            priority=priority,
            metadata=kwargs
        )
        
        # 注册路由
        _handler_registry.register_route(route_info)
        
        # 在方法上添加路由信息
        func._route_info = route_info
        
        logger.info("路由装饰完成",
                   route_key=route_key,
                   handler_name=func.__name__)
        
        return func
    
    return decorator


def middleware(execution_order: str = "before") -> Callable:
    """
    中间件装饰器
    
    Args:
        execution_order: 执行顺序 ("before", "after", "error")
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @middleware(execution_order="before")
    async def auth_middleware(handler_info, *args, **kwargs):
        # 身份验证逻辑
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        # 添加中间件信息
        func._middleware_info = {
            "execution_order": execution_order,
            "middleware_name": func.__name__
        }
        
        # 注册为全局中间件
        _handler_registry.add_global_middleware(func)
        
        logger.info("中间件装饰完成",
                   middleware_name=func.__name__,
                   execution_order=execution_order)
        
        return func
    
    return decorator


async def _execute_middleware(handler_info: HandlerInfo, 
                            execution_order: str, 
                            *args, **kwargs):
    """执行中间件"""
    global_middleware = _handler_registry.get_global_middleware()
    
    for middleware_func in global_middleware:
        if hasattr(middleware_func, '_middleware_info'):
            middleware_info = middleware_func._middleware_info
            if middleware_info["execution_order"] == execution_order:
                try:
                    await middleware_func(handler_info, *args, **kwargs)
                except Exception as e:
                    logger.error("中间件执行失败",
                               middleware_name=middleware_info["middleware_name"],
                               error=str(e))


async def _process_handler_args(func: Callable, args: tuple, kwargs: dict, 
                              handler_info: HandlerInfo) -> tuple:
    """处理处理器参数"""
    # 这里可以添加参数验证、转换和反序列化逻辑
    processed_args = list(args)
    processed_kwargs = kwargs.copy()
    
    # 如果有请求协议，尝试反序列化
    if handler_info.request_proto and len(args) > 1:
        request_data = args[1]
        if isinstance(request_data, bytes):
            # 尝试反序列化
            try:
                if hasattr(handler_info.request_proto, 'deserialize'):
                    processed_args[1] = handler_info.request_proto.deserialize(request_data)
            except Exception as e:
                logger.warning("请求参数反序列化失败",
                             handler_name=handler_info.handler_name,
                             error=str(e))
    
    return tuple(processed_args), processed_kwargs


async def _process_handler_result(result: Any, handler_info: HandlerInfo) -> Any:
    """处理处理器结果"""
    # 这里可以添加结果验证、转换和序列化逻辑
    processed_result = result
    
    # 如果有响应协议，尝试序列化
    if handler_info.response_proto and result is not None:
        try:
            if hasattr(result, 'serialize'):
                processed_result = result.serialize()
        except Exception as e:
            logger.warning("响应结果序列化失败",
                         handler_name=handler_info.handler_name,
                         error=str(e))
    
    return processed_result


def get_handler_registry() -> HandlerRegistry:
    """获取处理器注册表"""
    return _handler_registry


def get_controller_info(controller_name: str) -> Optional[ControllerInfo]:
    """获取控制器信息"""
    return _handler_registry.get_controller(controller_name)


def get_handler_info(handler_name: str) -> Optional[HandlerInfo]:
    """获取处理器信息"""
    return _handler_registry.get_handler(handler_name)


def get_route_info(route_key: Union[int, str]) -> Optional[RouteInfo]:
    """获取路由信息"""
    return _handler_registry.get_route(route_key)


def get_handler_statistics(handler_name: str) -> HandlerStatistics:
    """获取处理器统计信息"""
    return _handler_registry.get_statistics(handler_name)


def list_controllers() -> List[str]:
    """列出所有控制器"""
    return _handler_registry.list_controllers()


def list_handlers() -> List[str]:
    """列出所有处理器"""
    return _handler_registry.list_handlers()


def list_routes() -> Dict[Union[int, str], str]:
    """列出所有路由"""
    return _handler_registry.list_routes()


async def dispatch_message(route_key: Union[int, str], *args, **kwargs) -> Any:
    """
    根据路由键分发消息
    
    Args:
        route_key: 路由键
        *args: 参数
        **kwargs: 关键字参数
        
    Returns:
        Any: 处理结果
    """
    route_info = _handler_registry.get_route(route_key)
    if not route_info:
        raise ValueError(f"未找到路由: {route_key}")
    
    try:
        # 调用处理器方法
        result = await route_info.method(*args, **kwargs)
        
        logger.debug("消息分发成功",
                   route_key=route_key,
                   handler_name=route_info.handler_name)
        
        return result
        
    except Exception as e:
        logger.error("消息分发失败",
                   route_key=route_key,
                   handler_name=route_info.handler_name,
                   error=str(e))
        raise