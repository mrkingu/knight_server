"""
统一请求处理器

该模块负责处理所有WebSocket消息，包括Protocol Buffers解码、请求分发、
响应编码、异常处理等功能。是网关的核心消息处理中心。

主要功能：
- 处理所有WebSocket消息
- Protocol Buffers解码
- 请求分发到对应控制器
- 响应结果编码返回
- 异常统一处理
- 请求链路追踪
"""

import asyncio
import time
import traceback
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass
import json

from common.logger import logger
from common.proto import ProtoCodec, decode_message, encode_message, MessageHeader, extract_msg_id
from common.monitor import get_monitor
from .config import GatewayConfig
from .websocket_manager import WebSocketManager, get_websocket_manager
from .session_manager import SessionManager, get_session_manager
from .route_manager import RouteManager, get_route_manager, RouteType


@dataclass
class RequestContext:
    """请求上下文"""
    connection_id: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    client_ip: str = ""
    user_agent: str = ""
    request_id: str = ""
    protocol_id: int = 0
    request_time: float = 0.0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
        if not self.request_time:
            self.request_time = time.time()


@dataclass
class ResponseResult:
    """响应结果"""
    success: bool
    data: Any = None
    error_code: int = 0
    error_message: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class GateHandler:
    """网关处理器"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化网关处理器
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.websocket_manager: Optional[WebSocketManager] = None
        self.session_manager: Optional[SessionManager] = None
        self.route_manager: Optional[RouteManager] = None
        self.proto_codec = ProtoCodec()
        self.monitor = get_monitor()
        
        # 请求统计
        self._total_requests = 0
        self._success_requests = 0
        self._error_requests = 0
        self._total_response_time = 0.0
        
        logger.info("网关处理器初始化完成")
        
    async def initialize(self):
        """初始化处理器"""
        # 获取管理器实例
        self.websocket_manager = get_websocket_manager()
        self.session_manager = get_session_manager()
        self.route_manager = get_route_manager()
        
        if not all([self.websocket_manager, self.session_manager, self.route_manager]):
            raise RuntimeError("管理器未初始化")
            
        logger.info("网关处理器初始化完成")
        
    async def handle_websocket_message(self, connection_id: str, message_data: bytes) -> bool:
        """
        处理WebSocket消息
        
        Args:
            connection_id: 连接ID
            message_data: 消息数据
            
        Returns:
            bool: 是否处理成功
        """
        start_time = time.time()
        context = None
        
        try:
            # 获取连接信息
            connection_info = self.websocket_manager.get_connection_info(connection_id)
            if not connection_info:
                logger.warning("连接不存在", connection_id=connection_id)
                return False
                
            # 创建请求上下文
            context = RequestContext(
                connection_id=connection_id,
                client_ip=connection_info.client_ip,
                user_agent=connection_info.user_agent,
                request_id=f"{connection_id}_{int(time.time())}"
            )
            
            # 获取会话信息
            session_info = await self.session_manager.get_session_by_connection(connection_id)
            if session_info:
                context.session_id = session_info.session_id
                context.user_id = session_info.user_id
                
            # 解码消息
            decoded_message = await self._decode_message(message_data, context)
            if not decoded_message:
                return False
                
            # 提取协议ID
            context.protocol_id = decoded_message.get('protocol_id', 0)
            
            # 更新统计
            self._total_requests += 1
            
            # 处理请求
            response = await self._handle_request(decoded_message, context)
            
            # 发送响应
            await self._send_response(connection_id, response, context)
            
            # 更新成功统计
            self._success_requests += 1
            
            # 更新路由统计
            duration = time.time() - start_time
            self._total_response_time += duration
            if self.route_manager:
                await self.route_manager.add_route_stat(context.protocol_id, True, duration)
                
            return True
            
        except Exception as e:
            # 更新错误统计
            self._error_requests += 1
            
            # 更新路由统计
            duration = time.time() - start_time
            if self.route_manager and context:
                await self.route_manager.add_route_stat(context.protocol_id, False, duration)
                
            logger.error("处理WebSocket消息失败", 
                        connection_id=connection_id,
                        error=str(e),
                        traceback=traceback.format_exc())
            
            # 发送错误响应
            await self._send_error_response(connection_id, str(e), context)
            
            return False
            
    async def handle_websocket_connect(self, connection_id: str, websocket: Any, 
                                     client_ip: str = "", user_agent: str = "") -> bool:
        """
        处理WebSocket连接
        
        Args:
            connection_id: 连接ID
            websocket: WebSocket对象
            client_ip: 客户端IP
            user_agent: 用户代理
            
        Returns:
            bool: 是否处理成功
        """
        try:
            # 添加连接到WebSocket管理器
            success = await self.websocket_manager.add_connection(
                connection_id=connection_id,
                websocket=websocket,
                client_ip=client_ip,
                user_agent=user_agent
            )
            
            if success:
                logger.info("WebSocket连接成功", 
                           connection_id=connection_id,
                           client_ip=client_ip)
                
                # 发送连接成功消息
                welcome_message = {
                    "type": "welcome",
                    "connection_id": connection_id,
                    "timestamp": time.time()
                }
                await self.websocket_manager.send_message(connection_id, welcome_message)
                
            return success
            
        except Exception as e:
            logger.error("处理WebSocket连接失败", 
                        connection_id=connection_id,
                        error=str(e))
            return False
            
    async def handle_websocket_disconnect(self, connection_id: str) -> bool:
        """
        处理WebSocket断开
        
        Args:
            connection_id: 连接ID
            
        Returns:
            bool: 是否处理成功
        """
        try:
            # 解绑会话
            await self.session_manager.unbind_connection(connection_id)
            
            # 移除连接
            success = await self.websocket_manager.remove_connection(connection_id)
            
            if success:
                logger.info("WebSocket断开成功", connection_id=connection_id)
                
            return success
            
        except Exception as e:
            logger.error("处理WebSocket断开失败", 
                        connection_id=connection_id,
                        error=str(e))
            return False
            
    async def handle_authentication(self, connection_id: str, auth_data: Dict[str, Any]) -> bool:
        """
        处理认证请求
        
        Args:
            connection_id: 连接ID
            auth_data: 认证数据
            
        Returns:
            bool: 是否认证成功
        """
        try:
            # 获取认证信息
            token = auth_data.get('token')
            username = auth_data.get('username')
            password = auth_data.get('password')
            
            # 验证Token或用户名密码
            session_info = None
            if token:
                # Token认证
                session_info = await self.session_manager.verify_token(token)
            elif username and password:
                # 用户名密码认证
                # TODO: 实现用户名密码认证逻辑
                pass
                
            if session_info:
                # 绑定会话到连接
                await self.session_manager.bind_connection(session_info.session_id, connection_id)
                await self.websocket_manager.bind_user(connection_id, session_info.user_id)
                
                logger.info("认证成功", 
                           connection_id=connection_id,
                           user_id=session_info.user_id)
                
                # 发送认证成功消息
                auth_success_message = {
                    "type": "auth_success",
                    "session_id": session_info.session_id,
                    "user_id": session_info.user_id,
                    "username": session_info.username,
                    "timestamp": time.time()
                }
                await self.websocket_manager.send_message(connection_id, auth_success_message)
                
                return True
            else:
                logger.warning("认证失败", connection_id=connection_id)
                
                # 发送认证失败消息
                auth_failed_message = {
                    "type": "auth_failed",
                    "error": "Invalid credentials",
                    "timestamp": time.time()
                }
                await self.websocket_manager.send_message(connection_id, auth_failed_message)
                
                return False
                
        except Exception as e:
            logger.error("处理认证请求失败", 
                        connection_id=connection_id,
                        error=str(e))
            return False
            
    async def broadcast_message(self, message: Any, user_ids: Optional[list] = None) -> int:
        """
        广播消息
        
        Args:
            message: 消息内容
            user_ids: 目标用户ID列表，为None时广播给所有用户
            
        Returns:
            int: 成功发送的连接数
        """
        try:
            if user_ids:
                # 发送给指定用户
                total_sent = 0
                for user_id in user_ids:
                    sent_count = await self.websocket_manager.send_to_user(user_id, message)
                    total_sent += sent_count
                return total_sent
            else:
                # 广播给所有用户
                return await self.websocket_manager.broadcast_message(message)
                
        except Exception as e:
            logger.error("广播消息失败", error=str(e))
            return 0
            
    async def send_notification(self, user_id: str, notification: Dict[str, Any]) -> bool:
        """
        发送通知
        
        Args:
            user_id: 用户ID
            notification: 通知内容
            
        Returns:
            bool: 是否发送成功
        """
        try:
            # 添加通知类型
            notification["type"] = "notification"
            notification["timestamp"] = time.time()
            
            # 发送给用户
            sent_count = await self.websocket_manager.send_to_user(user_id, notification)
            
            logger.info("通知发送完成", 
                       user_id=user_id,
                       sent_count=sent_count)
            
            return sent_count > 0
            
        except Exception as e:
            logger.error("发送通知失败", 
                        user_id=user_id,
                        error=str(e))
            return False
            
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        avg_response_time = 0.0
        if self._total_requests > 0:
            avg_response_time = self._total_response_time / self._total_requests
            
        success_rate = 0.0
        if self._total_requests > 0:
            success_rate = self._success_requests / self._total_requests
            
        return {
            "total_requests": self._total_requests,
            "success_requests": self._success_requests,
            "error_requests": self._error_requests,
            "success_rate": success_rate,
            "average_response_time": avg_response_time
        }
        
    async def _decode_message(self, message_data: bytes, context: RequestContext) -> Optional[Dict[str, Any]]:
        """
        解码消息
        
        Args:
            message_data: 消息数据
            context: 请求上下文
            
        Returns:
            Dict[str, Any]: 解码后的消息
        """
        try:
            # 尝试Protocol Buffers解码
            try:
                # 提取消息ID
                msg_id = extract_msg_id(message_data)
                context.protocol_id = msg_id
                
                # 解码消息
                decoded_message = decode_message(message_data)
                if decoded_message:
                    return {
                        "protocol_id": msg_id,
                        "data": decoded_message
                    }
            except Exception as pb_error:
                logger.debug("Protocol Buffers解码失败，尝试JSON解码", error=str(pb_error))
                
            # 尝试JSON解码
            try:
                json_str = message_data.decode('utf-8')
                json_data = json.loads(json_str)
                return {
                    "protocol_id": json_data.get("protocol_id", 0),
                    "data": json_data
                }
            except Exception as json_error:
                logger.debug("JSON解码失败", error=str(json_error))
                
            # 尝试文本解码
            try:
                text_data = message_data.decode('utf-8')
                return {
                    "protocol_id": 0,
                    "data": {"text": text_data}
                }
            except Exception as text_error:
                logger.debug("文本解码失败", error=str(text_error))
                
            logger.error("消息解码失败", 
                        connection_id=context.connection_id,
                        message_size=len(message_data))
            return None
            
        except Exception as e:
            logger.error("解码消息异常", 
                        connection_id=context.connection_id,
                        error=str(e))
            return None
            
    async def _handle_request(self, message: Dict[str, Any], context: RequestContext) -> ResponseResult:
        """
        处理请求
        
        Args:
            message: 消息内容
            context: 请求上下文
            
        Returns:
            ResponseResult: 响应结果
        """
        try:
            protocol_id = context.protocol_id
            
            # 查找路由处理器
            handler = await self.route_manager.find_handler(protocol_id)
            if not handler:
                return ResponseResult(
                    success=False,
                    error_code=404,
                    error_message=f"未找到协议处理器: {protocol_id}"
                )
                
            # 检查权限
            if context.user_id:
                session_info = await self.session_manager.get_session(context.session_id)
                if session_info:
                    user_permissions = session_info.permissions
                    if not await self.route_manager.check_permission(protocol_id, user_permissions):
                        return ResponseResult(
                            success=False,
                            error_code=403,
                            error_message="权限不足"
                        )
                        
            # 更新会话活动时间
            if context.session_id:
                await self.session_manager.update_session_activity(context.session_id)
                
            # 调用处理器
            result = await handler(message["data"], context)
            
            # 包装响应结果
            if isinstance(result, ResponseResult):
                return result
            elif isinstance(result, dict):
                return ResponseResult(success=True, data=result)
            else:
                return ResponseResult(success=True, data={"result": result})
                
        except Exception as e:
            logger.error("处理请求异常", 
                        protocol_id=context.protocol_id,
                        connection_id=context.connection_id,
                        error=str(e),
                        traceback=traceback.format_exc())
            
            return ResponseResult(
                success=False,
                error_code=500,
                error_message=f"服务器内部错误: {str(e)}"
            )
            
    async def _send_response(self, connection_id: str, response: ResponseResult, context: RequestContext):
        """
        发送响应
        
        Args:
            connection_id: 连接ID
            response: 响应结果
            context: 请求上下文
        """
        try:
            # 构造响应消息
            response_message = {
                "type": "response",
                "protocol_id": context.protocol_id,
                "request_id": context.request_id,
                "success": response.success,
                "timestamp": time.time()
            }
            
            if response.success:
                response_message["data"] = response.data
            else:
                response_message["error"] = {
                    "code": response.error_code,
                    "message": response.error_message
                }
                
            # 添加元数据
            if response.metadata:
                response_message["metadata"] = response.metadata
                
            # 发送响应
            await self.websocket_manager.send_message(connection_id, response_message)
            
        except Exception as e:
            logger.error("发送响应失败", 
                        connection_id=connection_id,
                        error=str(e))
            
    async def _send_error_response(self, connection_id: str, error_message: str, context: Optional[RequestContext] = None):
        """
        发送错误响应
        
        Args:
            connection_id: 连接ID
            error_message: 错误消息
            context: 请求上下文
        """
        try:
            error_response = {
                "type": "error",
                "error": error_message,
                "timestamp": time.time()
            }
            
            if context:
                error_response["protocol_id"] = context.protocol_id
                error_response["request_id"] = context.request_id
                
            await self.websocket_manager.send_message(connection_id, error_response)
            
        except Exception as e:
            logger.error("发送错误响应失败", 
                        connection_id=connection_id,
                        error=str(e))


# 全局处理器实例
_gate_handler: Optional[GateHandler] = None


def get_gate_handler() -> Optional[GateHandler]:
    """获取网关处理器实例"""
    return _gate_handler


def create_gate_handler(config: GatewayConfig) -> GateHandler:
    """创建网关处理器"""
    global _gate_handler
    _gate_handler = GateHandler(config)
    return _gate_handler