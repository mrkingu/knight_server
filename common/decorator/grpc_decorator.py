"""
gRPC装饰器模块

该模块提供gRPC相关的装饰器，用于简化gRPC服务的开发。
支持服务类标记、方法标记和远程调用简化。

主要功能：
- @grpc_service: 标记gRPC服务类
- @grpc_method: 标记gRPC方法
- @grpc_call: 简化gRPC远程调用
- gRPC客户端连接管理
- 自动错误处理和重试
"""

import asyncio
import functools
import inspect
import time
from typing import Callable, Any, Dict, Optional, Type, List, Union
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger


class GrpcServiceType(Enum):
    """gRPC服务类型枚举"""
    UNARY = "unary"
    SERVER_STREAMING = "server_streaming"
    CLIENT_STREAMING = "client_streaming"
    BIDIRECTIONAL_STREAMING = "bidirectional_streaming"


@dataclass
class GrpcMethodInfo:
    """gRPC方法信息"""
    method_name: str
    service_type: GrpcServiceType
    request_type: Optional[Type] = None
    response_type: Optional[Type] = None
    timeout: float = 30.0
    retry_count: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GrpcServiceInfo:
    """gRPC服务信息"""
    service_name: str
    service_class: Type
    methods: Dict[str, GrpcMethodInfo] = field(default_factory=dict)
    host: str = "localhost"
    port: int = 50051
    metadata: Dict[str, Any] = field(default_factory=dict)


class GrpcServiceRegistry:
    """gRPC服务注册表"""
    
    def __init__(self):
        self._services: Dict[str, GrpcServiceInfo] = {}
        self._clients: Dict[str, Any] = {}
    
    def register_service(self, service_info: GrpcServiceInfo):
        """注册gRPC服务"""
        self._services[service_info.service_name] = service_info
        logger.info("gRPC服务注册成功", service_name=service_info.service_name)
    
    def get_service(self, service_name: str) -> Optional[GrpcServiceInfo]:
        """获取gRPC服务信息"""
        return self._services.get(service_name)
    
    def get_client(self, service_name: str) -> Optional[Any]:
        """获取gRPC客户端"""
        return self._clients.get(service_name)
    
    def set_client(self, service_name: str, client: Any):
        """设置gRPC客户端"""
        self._clients[service_name] = client
    
    def list_services(self) -> List[str]:
        """列出所有注册的服务"""
        return list(self._services.keys())


# 全局服务注册表
_grpc_registry = GrpcServiceRegistry()


def grpc_service(name: Optional[str] = None, 
                host: str = "localhost", 
                port: int = 50051,
                **kwargs) -> Callable:
    """
    标记gRPC服务类的装饰器
    
    Args:
        name: 服务名称，默认使用类名
        host: 服务主机地址
        port: 服务端口
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的类
        
    使用示例：
    ```python
    @grpc_service(name="UserService", port=50051)
    class UserService:
        @grpc_method
        async def get_user_info(self, request):
            pass
    ```
    """
    def decorator(cls: Type) -> Type:
        # 获取服务名称
        service_name = name or cls.__name__
        
        # 创建服务信息
        service_info = GrpcServiceInfo(
            service_name=service_name,
            service_class=cls,
            host=host,
            port=port,
            metadata=kwargs
        )
        
        # 扫描类中的gRPC方法
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if hasattr(attr, '_grpc_method_info'):
                method_info = attr._grpc_method_info
                service_info.methods[method_info.method_name] = method_info
        
        # 注册服务
        _grpc_registry.register_service(service_info)
        
        # 在类上添加服务信息
        cls._grpc_service_info = service_info
        
        logger.info("gRPC服务类装饰完成", 
                   service_name=service_name,
                   method_count=len(service_info.methods))
        
        return cls
    
    return decorator


def grpc_method(service_type: GrpcServiceType = GrpcServiceType.UNARY,
               request_type: Optional[Type] = None,
               response_type: Optional[Type] = None,
               timeout: float = 30.0,
               retry_count: int = 3,
               **kwargs) -> Callable:
    """
    标记gRPC方法的装饰器
    
    Args:
        service_type: 服务类型
        request_type: 请求类型
        response_type: 响应类型
        timeout: 超时时间(秒)
        retry_count: 重试次数
        **kwargs: 其他元数据
        
    Returns:
        Callable: 装饰后的方法
        
    使用示例：
    ```python
    @grpc_method(
        service_type=GrpcServiceType.UNARY,
        request_type=UserRequest,
        response_type=UserResponse,
        timeout=10.0
    )
    async def get_user_info(self, request: UserRequest) -> UserResponse:
        pass
    ```
    """
    def decorator(func: Callable) -> Callable:
        # 创建方法信息
        method_info = GrpcMethodInfo(
            method_name=func.__name__,
            service_type=service_type,
            request_type=request_type,
            response_type=response_type,
            timeout=timeout,
            retry_count=retry_count,
            metadata=kwargs
        )
        
        # 在方法上添加信息
        func._grpc_method_info = method_info
        
        # 包装方法以添加gRPC相关功能
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                # 调用原始方法
                result = await func(*args, **kwargs)
                
                # 记录成功调用
                latency = time.time() - start_time
                logger.debug("gRPC方法调用成功",
                           method=func.__name__,
                           latency=latency)
                
                return result
                
            except Exception as e:
                # 记录错误调用
                latency = time.time() - start_time
                logger.error("gRPC方法调用失败",
                           method=func.__name__,
                           error=str(e),
                           latency=latency)
                raise
        
        return wrapper
    
    return decorator


def grpc_call(service_name: str,
             method_name: str,
             timeout: Optional[float] = None,
             retry_count: int = 3,
             **kwargs) -> Callable:
    """
    简化gRPC远程调用的装饰器
    
    Args:
        service_name: 服务名称
        method_name: 方法名称
        timeout: 超时时间(秒)
        retry_count: 重试次数
        **kwargs: 其他调用参数
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @grpc_call(service_name="UserService", method_name="get_user_info")
    async def get_user_info(request: UserRequest) -> UserResponse:
        pass  # 此函数体会被替换为gRPC调用
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取服务信息
            service_info = _grpc_registry.get_service(service_name)
            if not service_info:
                raise ValueError(f"未找到gRPC服务: {service_name}")
            
            # 获取方法信息
            method_info = service_info.methods.get(method_name)
            if not method_info:
                raise ValueError(f"未找到gRPC方法: {service_name}.{method_name}")
            
            # 获取或创建客户端
            client = await _get_or_create_client(service_info)
            
            # 执行gRPC调用
            return await _execute_grpc_call(
                client=client,
                method_info=method_info,
                args=args,
                kwargs=kwargs,
                timeout=timeout or method_info.timeout,
                retry_count=retry_count
            )
        
        return wrapper
    
    return decorator


def grpc_stream(service_name: str,
               method_name: str,
               **kwargs) -> Callable:
    """
    gRPC流式调用装饰器
    
    Args:
        service_name: 服务名称
        method_name: 方法名称
        **kwargs: 其他调用参数
        
    Returns:
        Callable: 装饰后的函数
        
    使用示例：
    ```python
    @grpc_stream(service_name="ChatService", method_name="chat_stream")
    async def chat_stream(request_iterator):
        async for response in grpc_call:
            yield response
    ```
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取服务信息
            service_info = _grpc_registry.get_service(service_name)
            if not service_info:
                raise ValueError(f"未找到gRPC服务: {service_name}")
            
            # 获取方法信息
            method_info = service_info.methods.get(method_name)
            if not method_info:
                raise ValueError(f"未找到gRPC方法: {service_name}.{method_name}")
            
            # 获取或创建客户端
            client = await _get_or_create_client(service_info)
            
            # 执行流式调用
            return await _execute_grpc_stream(
                client=client,
                method_info=method_info,
                args=args,
                kwargs=kwargs
            )
        
        return wrapper
    
    return decorator


async def _get_or_create_client(service_info: GrpcServiceInfo) -> Any:
    """获取或创建gRPC客户端"""
    client = _grpc_registry.get_client(service_info.service_name)
    
    if client is None:
        # 创建新的客户端连接
        try:
            # 这里应该根据实际的gRPC客户端库创建连接
            # 暂时使用模拟实现
            client = _create_mock_grpc_client(service_info)
            _grpc_registry.set_client(service_info.service_name, client)
            
            logger.info("gRPC客户端创建成功",
                       service_name=service_info.service_name,
                       host=service_info.host,
                       port=service_info.port)
        except Exception as e:
            logger.error("gRPC客户端创建失败",
                        service_name=service_info.service_name,
                        error=str(e))
            raise
    
    return client


async def _execute_grpc_call(client: Any,
                           method_info: GrpcMethodInfo,
                           args: tuple,
                           kwargs: dict,
                           timeout: float,
                           retry_count: int) -> Any:
    """执行gRPC调用"""
    last_exception = None
    
    for attempt in range(retry_count + 1):
        try:
            start_time = time.time()
            
            # 执行实际的gRPC调用
            # 这里应该根据实际的gRPC客户端库实现
            result = await _mock_grpc_call(client, method_info, args, kwargs, timeout)
            
            # 记录成功调用
            latency = time.time() - start_time
            logger.debug("gRPC调用成功",
                        method=method_info.method_name,
                        attempt=attempt + 1,
                        latency=latency)
            
            return result
            
        except Exception as e:
            last_exception = e
            latency = time.time() - start_time
            
            if attempt < retry_count:
                logger.warning("gRPC调用失败，准备重试",
                             method=method_info.method_name,
                             attempt=attempt + 1,
                             error=str(e),
                             latency=latency)
                
                # 指数退避重试
                await asyncio.sleep(0.1 * (2 ** attempt))
            else:
                logger.error("gRPC调用最终失败",
                           method=method_info.method_name,
                           total_attempts=attempt + 1,
                           error=str(e),
                           latency=latency)
    
    # 抛出最后一个异常
    raise last_exception


async def _execute_grpc_stream(client: Any,
                             method_info: GrpcMethodInfo,
                             args: tuple,
                             kwargs: dict) -> Any:
    """执行gRPC流式调用"""
    try:
        # 执行实际的gRPC流式调用
        # 这里应该根据实际的gRPC客户端库实现
        return await _mock_grpc_stream(client, method_info, args, kwargs)
    except Exception as e:
        logger.error("gRPC流式调用失败",
                    method=method_info.method_name,
                    error=str(e))
        raise


def _create_mock_grpc_client(service_info: GrpcServiceInfo) -> Any:
    """创建模拟gRPC客户端"""
    class MockGrpcClient:
        def __init__(self, service_info: GrpcServiceInfo):
            self.service_info = service_info
            self.connected = True
        
        async def call(self, method_name: str, *args, **kwargs):
            # 模拟gRPC调用
            await asyncio.sleep(0.01)  # 模拟网络延迟
            return {"result": "success", "method": method_name}
        
        async def stream(self, method_name: str, *args, **kwargs):
            # 模拟gRPC流式调用
            for i in range(3):
                await asyncio.sleep(0.01)
                yield {"data": f"stream_item_{i}", "method": method_name}
    
    return MockGrpcClient(service_info)


async def _mock_grpc_call(client: Any, method_info: GrpcMethodInfo, 
                        args: tuple, kwargs: dict, timeout: float) -> Any:
    """模拟gRPC调用"""
    if hasattr(client, 'call'):
        return await client.call(method_info.method_name, *args, **kwargs)
    else:
        # 基础模拟实现
        await asyncio.sleep(0.01)
        return {"result": "mock_success", "method": method_info.method_name}


async def _mock_grpc_stream(client: Any, method_info: GrpcMethodInfo,
                          args: tuple, kwargs: dict) -> Any:
    """模拟gRPC流式调用"""
    if hasattr(client, 'stream'):
        async for item in client.stream(method_info.method_name, *args, **kwargs):
            yield item
    else:
        # 基础模拟实现
        for i in range(3):
            await asyncio.sleep(0.01)
            yield {"data": f"mock_stream_{i}", "method": method_info.method_name}


def get_grpc_registry() -> GrpcServiceRegistry:
    """获取gRPC服务注册表"""
    return _grpc_registry


def list_grpc_services() -> List[str]:
    """列出所有注册的gRPC服务"""
    return _grpc_registry.list_services()


def get_grpc_service_info(service_name: str) -> Optional[GrpcServiceInfo]:
    """获取gRPC服务信息"""
    return _grpc_registry.get_service(service_name)