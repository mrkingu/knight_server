"""
基础消息处理器类模块

该模块提供了统一的消息处理入口，负责消息的接收、解码、路由、
异常处理、请求追踪、性能统计、消息验证、响应编码等功能。

主要功能：
- 统一的消息接收入口
- 消息解码（调用proto模块）
- 根据消息ID自动路由到对应的Controller
- 异常统一处理
- 请求追踪（trace_id）
- 性能统计（请求耗时）
- 消息验证（签名、时间戳等）
- 响应编码和发送

使用示例：
```python
from services.base.base_handler import BaseHandler

class GameHandler(BaseHandler):
    def __init__(self):
        super().__init__()
        # 注册控制器
        self.register_controller("user", UserController())
        self.register_controller("game", GameController())
    
    async def handle_custom_message(self, message_data: bytes, context: dict):
        # 自定义消息处理逻辑
        return await super().handle_message(message_data, context)

# 使用
handler = GameHandler()
result = await handler.handle_message(message_data, context)
```
"""

import asyncio
import time
import uuid
import traceback
from typing import Dict, List, Optional, Any, Callable, Type, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager

from common.logger import logger
try:
    from common.proto import ProtoCodec, decode_message, encode_message, ProtoException
    from common.proto.header import MessageHeader, decode_header, encode_header
except ImportError:
    # Mock proto classes if not available
    class ProtoCodec:
        def __init__(self):
            pass
    
    class ProtoException(Exception):
        pass
    
    class MessageHeader:
        def __init__(self, msg_id=0, timestamp=0):
            self.msg_id = msg_id
            self.timestamp = timestamp
    
    def decode_message(data, codec):
        return {"mock": "message"}
    
    def encode_message(data, codec):
        return b"mock_encoded"
    
    def decode_header(data):
        return MessageHeader()
    
    def encode_header(header):
        return b"mock_header"

from common.decorator.handler_decorator import get_handler_registry, dispatch_message
try:
    from common.security import SecurityManager, validate_signature, validate_timestamp
except ImportError:
    class SecurityManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
    
    def validate_signature(data, signature):
        return True
    
    def validate_timestamp(timestamp):
        return True

try:
    from common.monitor import MonitorManager, record_request_metrics
except ImportError:
    class MonitorManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
    
    async def record_request_metrics(*args, **kwargs):
        pass


class MessageType(Enum):
    """消息类型枚举"""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    HEARTBEAT = "heartbeat"


@dataclass
class RequestContext:
    """请求上下文"""
    # 基本信息
    trace_id: str
    message_id: int
    message_type: MessageType
    timestamp: float
    
    # 客户端信息
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    
    # 消息信息
    raw_data: Optional[bytes] = None
    decoded_message: Optional[Any] = None
    message_size: int = 0
    
    # 性能统计
    start_time: float = field(default_factory=time.time)
    decode_time: float = 0.0
    process_time: float = 0.0
    encode_time: float = 0.0
    total_time: float = 0.0
    
    # 路由信息
    controller_name: Optional[str] = None
    handler_name: Optional[str] = None
    
    # 安全信息
    signature: Optional[str] = None
    validated: bool = False
    
    # 其他元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseContext:
    """响应上下文"""
    # 基本信息
    trace_id: str
    message_id: int
    status_code: int = 200
    
    # 响应数据
    response_data: Optional[Any] = None
    encoded_data: Optional[bytes] = None
    
    # 性能统计
    encode_time: float = 0.0
    send_time: float = 0.0
    
    # 错误信息
    error_code: Optional[int] = None
    error_message: Optional[str] = None
    
    # 其他元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerStatistics:
    """处理器统计信息"""
    total_requests: int = 0
    success_requests: int = 0
    failed_requests: int = 0
    
    total_latency: float = 0.0
    min_latency: float = float('inf')
    max_latency: float = 0.0
    avg_latency: float = 0.0
    
    total_throughput: int = 0
    current_qps: float = 0.0
    
    last_request_time: float = 0.0
    last_reset_time: float = field(default_factory=time.time)


class BaseHandler:
    """
    基础消息处理器类
    
    负责所有消息的统一处理，包括：
    - 消息接收和解码
    - 路由到对应的控制器
    - 异常处理
    - 性能统计
    - 请求追踪
    - 消息验证
    - 响应编码
    """
    
    def __init__(self, 
                 enable_tracing: bool = True,
                 enable_metrics: bool = True,
                 enable_validation: bool = True,
                 max_message_size: int = 1024 * 1024,  # 1MB
                 request_timeout: float = 30.0):
        """
        初始化基础处理器
        
        Args:
            enable_tracing: 是否启用请求追踪
            enable_metrics: 是否启用性能统计
            enable_validation: 是否启用消息验证
            max_message_size: 最大消息大小
            request_timeout: 请求超时时间
        """
        self.logger = logger
        
        # 配置
        self.enable_tracing = enable_tracing
        self.enable_metrics = enable_metrics
        self.enable_validation = enable_validation
        self.max_message_size = max_message_size
        self.request_timeout = request_timeout
        
        # 核心组件
        self._proto_codec = ProtoCodec()
        self._security_manager = SecurityManager()
        self._monitor_manager = MonitorManager() if enable_metrics else None
        self._handler_registry = get_handler_registry()
        
        # 控制器注册表
        self._controllers: Dict[str, Any] = {}
        
        # 路由表：消息ID -> (控制器名, 处理器名)
        self._routing_table: Dict[int, Tuple[str, str]] = {}
        
        # 中间件
        self._before_middlewares: List[Callable] = []
        self._after_middlewares: List[Callable] = []
        self._error_middlewares: List[Callable] = []
        
        # 统计信息
        self._statistics = HandlerStatistics()
        self._request_contexts: Dict[str, RequestContext] = {}
        
        # 限流器
        self._rate_limiters: Dict[str, Any] = {}
        
        self.logger.info("基础消息处理器初始化完成")
    
    async def initialize(self):
        """初始化处理器"""
        try:
            # 初始化安全管理器
            await self._security_manager.initialize()
            
            # 初始化监控管理器
            if self._monitor_manager:
                await self._monitor_manager.initialize()
            
            # 构建路由表
            await self._build_routing_table()
            
            self.logger.info("基础消息处理器初始化完成")
            
        except Exception as e:
            self.logger.error("基础消息处理器初始化失败", error=str(e))
            raise
    
    async def handle_message(self, message_data: bytes, context: dict = None) -> Optional[bytes]:
        """
        处理消息的主入口
        
        Args:
            message_data: 原始消息数据
            context: 上下文信息（如客户端信息、连接信息等）
            
        Returns:
            Optional[bytes]: 响应数据，如果为None表示无需响应
        """
        # 生成追踪ID
        trace_id = str(uuid.uuid4()) if self.enable_tracing else ""
        
        # 创建请求上下文
        request_context = RequestContext(
            trace_id=trace_id,
            message_id=0,  # 将在解码后设置
            message_type=MessageType.REQUEST,
            timestamp=time.time(),
            raw_data=message_data,
            message_size=len(message_data)
        )
        
        # 从context中提取信息
        if context:
            request_context.client_id = context.get("client_id")
            request_context.user_id = context.get("user_id")
            request_context.session_id = context.get("session_id")
            request_context.ip_address = context.get("ip_address")
            request_context.metadata.update(context.get("metadata", {}))
        
        # 记录请求上下文
        if self.enable_tracing:
            self._request_contexts[trace_id] = request_context
        
        try:
            # 前置处理
            await self._before_process(request_context)
            
            # 解码消息
            decoded_message = await self._decode_message(request_context)
            
            # 验证消息
            if self.enable_validation:
                await self._validate_message(request_context, decoded_message)
            
            # 路由消息
            result = await self._route_message(request_context, decoded_message)
            
            # 编码响应
            response_data = await self._encode_response(request_context, result)
            
            # 后置处理
            await self._after_process(request_context, response_data)
            
            # 更新统计信息
            await self._update_statistics(request_context, True)
            
            return response_data
            
        except Exception as e:
            # 错误处理
            await self._handle_error(request_context, e)
            
            # 更新统计信息
            await self._update_statistics(request_context, False)
            
            # 生成错误响应
            return await self._generate_error_response(request_context, e)
            
        finally:
            # 清理上下文
            if self.enable_tracing and trace_id in self._request_contexts:
                del self._request_contexts[trace_id]
    
    async def _decode_message(self, context: RequestContext) -> Any:
        """
        解码消息
        
        Args:
            context: 请求上下文
            
        Returns:
            Any: 解码后的消息对象
        """
        start_time = time.time()
        
        try:
            # 检查消息大小
            if context.message_size > self.max_message_size:
                raise ValueError(f"消息大小超过限制: {context.message_size} > {self.max_message_size}")
            
            # 解码消息头
            header = decode_header(context.raw_data)
            context.message_id = header.msg_id
            context.timestamp = header.timestamp
            
            # 解码消息体
            decoded_message = decode_message(context.raw_data, self._proto_codec)
            context.decoded_message = decoded_message
            
            # 记录解码时间
            context.decode_time = time.time() - start_time
            
            self.logger.debug("消息解码成功",
                            trace_id=context.trace_id,
                            message_id=context.message_id,
                            decode_time=context.decode_time)
            
            return decoded_message
            
        except Exception as e:
            self.logger.error("消息解码失败",
                            trace_id=context.trace_id,
                            error=str(e),
                            message_size=context.message_size)
            raise
    
    async def _validate_message(self, context: RequestContext, message: Any):
        """
        验证消息
        
        Args:
            context: 请求上下文
            message: 解码后的消息
        """
        try:
            # 验证时间戳
            if not validate_timestamp(context.timestamp):
                raise ValueError("消息时间戳无效或过期")
            
            # 验证签名
            if hasattr(message, 'signature') and message.signature:
                context.signature = message.signature
                if not validate_signature(context.raw_data, message.signature):
                    raise ValueError("消息签名验证失败")
            
            # 验证用户权限
            if context.user_id and hasattr(message, 'user_id'):
                if message.user_id != context.user_id:
                    raise ValueError("用户ID不匹配")
            
            # 验证会话
            if context.session_id and hasattr(message, 'session_id'):
                if message.session_id != context.session_id:
                    raise ValueError("会话ID不匹配")
            
            context.validated = True
            
            self.logger.debug("消息验证成功",
                            trace_id=context.trace_id,
                            message_id=context.message_id)
            
        except Exception as e:
            self.logger.error("消息验证失败",
                            trace_id=context.trace_id,
                            message_id=context.message_id,
                            error=str(e))
            raise
    
    async def _route_message(self, context: RequestContext, message: Any) -> Any:
        """
        路由消息到对应的控制器
        
        Args:
            context: 请求上下文
            message: 解码后的消息
            
        Returns:
            Any: 处理结果
        """
        start_time = time.time()
        
        try:
            # 查找路由
            route_info = self._handler_registry.get_route(context.message_id)
            if not route_info:
                raise ValueError(f"未找到消息ID {context.message_id} 的路由")
            
            context.controller_name = route_info.controller_name
            context.handler_name = route_info.handler_name
            
            # 获取控制器
            controller = self._controllers.get(route_info.controller_name)
            if not controller:
                raise ValueError(f"未找到控制器: {route_info.controller_name}")
            
            # 调用处理器方法
            result = await dispatch_message(context.message_id, controller, message, context)
            
            # 记录处理时间
            context.process_time = time.time() - start_time
            
            self.logger.debug("消息路由成功",
                            trace_id=context.trace_id,
                            message_id=context.message_id,
                            controller_name=context.controller_name,
                            handler_name=context.handler_name,
                            process_time=context.process_time)
            
            return result
            
        except Exception as e:
            self.logger.error("消息路由失败",
                            trace_id=context.trace_id,
                            message_id=context.message_id,
                            error=str(e))
            raise
    
    async def _encode_response(self, context: RequestContext, result: Any) -> Optional[bytes]:
        """
        编码响应
        
        Args:
            context: 请求上下文
            result: 处理结果
            
        Returns:
            Optional[bytes]: 编码后的响应数据
        """
        if result is None:
            return None
        
        start_time = time.time()
        
        try:
            # 编码响应消息
            encoded_data = encode_message(result, self._proto_codec)
            
            # 记录编码时间
            context.encode_time = time.time() - start_time
            
            self.logger.debug("响应编码成功",
                            trace_id=context.trace_id,
                            message_id=context.message_id,
                            encode_time=context.encode_time,
                            response_size=len(encoded_data))
            
            return encoded_data
            
        except Exception as e:
            self.logger.error("响应编码失败",
                            trace_id=context.trace_id,
                            message_id=context.message_id,
                            error=str(e))
            raise
    
    async def _before_process(self, context: RequestContext):
        """前置处理"""
        for middleware in self._before_middlewares:
            try:
                await middleware(context)
            except Exception as e:
                self.logger.error("前置中间件执行失败",
                                trace_id=context.trace_id,
                                middleware=middleware.__name__,
                                error=str(e))
                raise
    
    async def _after_process(self, context: RequestContext, response_data: Optional[bytes]):
        """后置处理"""
        for middleware in self._after_middlewares:
            try:
                await middleware(context, response_data)
            except Exception as e:
                self.logger.error("后置中间件执行失败",
                                trace_id=context.trace_id,
                                middleware=middleware.__name__,
                                error=str(e))
    
    async def _handle_error(self, context: RequestContext, error: Exception):
        """错误处理"""
        # 记录错误日志
        self.logger.error("消息处理失败",
                        trace_id=context.trace_id,
                        message_id=context.message_id,
                        controller_name=context.controller_name,
                        handler_name=context.handler_name,
                        error=str(error),
                        traceback=traceback.format_exc())
        
        # 执行错误中间件
        for middleware in self._error_middlewares:
            try:
                await middleware(context, error)
            except Exception as e:
                self.logger.error("错误中间件执行失败",
                                trace_id=context.trace_id,
                                middleware=middleware.__name__,
                                error=str(e))
    
    async def _generate_error_response(self, context: RequestContext, error: Exception) -> Optional[bytes]:
        """生成错误响应"""
        try:
            # 创建错误响应对象
            error_response = {
                "error_code": getattr(error, 'error_code', 500),
                "error_message": str(error),
                "trace_id": context.trace_id,
                "timestamp": time.time()
            }
            
            # 编码错误响应
            return encode_message(error_response, self._proto_codec)
            
        except Exception as e:
            self.logger.error("生成错误响应失败",
                            trace_id=context.trace_id,
                            error=str(e))
            return None
    
    async def _update_statistics(self, context: RequestContext, success: bool):
        """更新统计信息"""
        if not self.enable_metrics:
            return
        
        try:
            # 计算总耗时
            context.total_time = time.time() - context.start_time
            
            # 更新统计信息
            self._statistics.total_requests += 1
            self._statistics.total_latency += context.total_time
            self._statistics.last_request_time = context.start_time
            
            if success:
                self._statistics.success_requests += 1
            else:
                self._statistics.failed_requests += 1
            
            # 更新延迟统计
            self._statistics.min_latency = min(self._statistics.min_latency, context.total_time)
            self._statistics.max_latency = max(self._statistics.max_latency, context.total_time)
            self._statistics.avg_latency = self._statistics.total_latency / self._statistics.total_requests
            
            # 记录监控指标
            if self._monitor_manager:
                await record_request_metrics(
                    message_id=context.message_id,
                    latency=context.total_time,
                    success=success,
                    controller_name=context.controller_name,
                    handler_name=context.handler_name
                )
            
        except Exception as e:
            self.logger.error("更新统计信息失败", error=str(e))
    
    async def _build_routing_table(self):
        """构建路由表"""
        try:
            routes = self._handler_registry.list_routes()
            for route_key, handler_name in routes.items():
                if isinstance(route_key, int):
                    route_info = self._handler_registry.get_route(route_key)
                    if route_info:
                        self._routing_table[route_key] = (
                            route_info.controller_name,
                            route_info.handler_name
                        )
            
            self.logger.info("路由表构建完成", routes_count=len(self._routing_table))
            
        except Exception as e:
            self.logger.error("路由表构建失败", error=str(e))
            raise
    
    def register_controller(self, name: str, controller: Any):
        """
        注册控制器
        
        Args:
            name: 控制器名称
            controller: 控制器实例
        """
        self._controllers[name] = controller
        self.logger.info("控制器注册成功", name=name)
    
    def unregister_controller(self, name: str):
        """
        注销控制器
        
        Args:
            name: 控制器名称
        """
        if name in self._controllers:
            del self._controllers[name]
            self.logger.info("控制器注销成功", name=name)
    
    def add_before_middleware(self, middleware: Callable):
        """添加前置中间件"""
        self._before_middlewares.append(middleware)
    
    def add_after_middleware(self, middleware: Callable):
        """添加后置中间件"""
        self._after_middlewares.append(middleware)
    
    def add_error_middleware(self, middleware: Callable):
        """添加错误中间件"""
        self._error_middlewares.append(middleware)
    
    def get_statistics(self) -> HandlerStatistics:
        """获取统计信息"""
        return self._statistics
    
    def reset_statistics(self):
        """重置统计信息"""
        self._statistics = HandlerStatistics()
    
    def get_request_context(self, trace_id: str) -> Optional[RequestContext]:
        """获取请求上下文"""
        return self._request_contexts.get(trace_id)
    
    @property
    def controllers(self) -> Dict[str, Any]:
        """获取已注册的控制器"""
        return self._controllers.copy()
    
    @property
    def routing_table(self) -> Dict[int, Tuple[str, str]]:
        """获取路由表"""
        return self._routing_table.copy()