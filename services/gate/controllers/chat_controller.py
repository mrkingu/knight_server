"""
聊天控制器

该模块负责处理聊天相关的请求，主要转发聊天请求到chat服务，
包括发送消息、获取聊天历史、管理聊天室等功能。

主要功能：
- 转发聊天请求到chat服务
- 消息发送和接收
- 聊天历史管理
- 聊天室管理
- 私聊和群聊支持
"""

import time
from typing import Dict, Any, List, Optional

from common.logger import logger
from ..route_manager import route, RouteType
from ..gate_handler import RequestContext
from .base_controller import BaseController, ControllerResponse


class ChatController(BaseController):
    """聊天控制器"""
    
    def __init__(self, config, proxy_service):
        """
        初始化聊天控制器
        
        Args:
            config: 网关配置
            proxy_service: 代理服务
        """
        super().__init__(config)
        self.proxy_service = proxy_service
        self.target_service = "chat_service"
        
        # 设置需要权限的方法
        self.add_required_permission("chat:send")
        
        logger.info("聊天控制器初始化完成")
        
    @route(protocol_id=3001, description="发送消息", group_name="chat")
    async def handle_protocol_3001(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理发送消息请求
        
        Args:
            data: 请求数据 {"room_id": str, "message": str, "message_type": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_id = data.get("room_id", "").strip()
            message = data.get("message", "").strip()
            message_type = data.get("message_type", "text").strip()
            
            if not room_id:
                return self.validation_error_response("room_id", "房间ID不能为空")
                
            if not message:
                return self.validation_error_response("message", "消息内容不能为空")
                
            if len(message) > 1000:
                return self.validation_error_response("message", "消息内容过长")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "send_message",
                "data": {
                    "room_id": room_id,
                    "message": message,
                    "message_type": message_type,
                    "sender_id": context.user_id,
                    "timestamp": time.time()
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="send_message",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "发送消息失败")
                )
                
        except Exception as e:
            logger.error("发送消息失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("发送消息失败")
            
    @route(protocol_id=3002, description="获取聊天历史", group_name="chat")
    async def handle_protocol_3002(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取聊天历史请求
        
        Args:
            data: 请求数据 {"room_id": str, "page": int, "page_size": int}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_id = data.get("room_id", "").strip()
            page = data.get("page", 1)
            page_size = data.get("page_size", 50)
            
            if not room_id:
                return self.validation_error_response("room_id", "房间ID不能为空")
                
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 100:
                page_size = 50
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "get_chat_history",
                "data": {
                    "room_id": room_id,
                    "page": page,
                    "page_size": page_size,
                    "requester_id": context.user_id
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_chat_history",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取聊天历史失败")
                )
                
        except Exception as e:
            logger.error("获取聊天历史失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取聊天历史失败")
            
    @route(protocol_id=3003, description="创建聊天室", group_name="chat")
    async def handle_protocol_3003(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理创建聊天室请求
        
        Args:
            data: 请求数据 {"room_name": str, "description": str, "is_private": bool}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_name = data.get("room_name", "").strip()
            description = data.get("description", "").strip()
            is_private = data.get("is_private", False)
            
            if not room_name:
                return self.validation_error_response("room_name", "房间名称不能为空")
                
            if len(room_name) > 50:
                return self.validation_error_response("room_name", "房间名称过长")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "create_chat_room",
                "data": {
                    "room_name": room_name,
                    "description": description,
                    "is_private": is_private,
                    "creator_id": context.user_id,
                    "created_at": time.time()
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="create_chat_room",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "创建聊天室失败")
                )
                
        except Exception as e:
            logger.error("创建聊天室失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("创建聊天室失败")
            
    @route(protocol_id=3004, description="加入聊天室", group_name="chat")
    async def handle_protocol_3004(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理加入聊天室请求
        
        Args:
            data: 请求数据 {"room_id": str, "password": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_id = data.get("room_id", "").strip()
            password = data.get("password", "").strip()
            
            if not room_id:
                return self.validation_error_response("room_id", "房间ID不能为空")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "join_chat_room",
                "data": {
                    "room_id": room_id,
                    "password": password,
                    "user_id": context.user_id,
                    "joined_at": time.time()
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="join_chat_room",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "加入聊天室失败")
                )
                
        except Exception as e:
            logger.error("加入聊天室失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("加入聊天室失败")
            
    @route(protocol_id=3005, description="离开聊天室", group_name="chat")
    async def handle_protocol_3005(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理离开聊天室请求
        
        Args:
            data: 请求数据 {"room_id": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_id = data.get("room_id", "").strip()
            
            if not room_id:
                return self.validation_error_response("room_id", "房间ID不能为空")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "leave_chat_room",
                "data": {
                    "room_id": room_id,
                    "user_id": context.user_id,
                    "left_at": time.time()
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="leave_chat_room",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "离开聊天室失败")
                )
                
        except Exception as e:
            logger.error("离开聊天室失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("离开聊天室失败")
            
    @route(protocol_id=3006, description="获取聊天室列表", group_name="chat")
    async def handle_protocol_3006(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取聊天室列表请求
        
        Args:
            data: 请求数据 {"page": int, "page_size": int}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            page = data.get("page", 1)
            page_size = data.get("page_size", 20)
            
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 100:
                page_size = 20
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "get_chat_room_list",
                "data": {
                    "page": page,
                    "page_size": page_size,
                    "requester_id": context.user_id
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_chat_room_list",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取聊天室列表失败")
                )
                
        except Exception as e:
            logger.error("获取聊天室列表失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取聊天室列表失败")
            
    @route(protocol_id=3007, description="发送私聊消息", group_name="chat")
    async def handle_protocol_3007(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理发送私聊消息请求
        
        Args:
            data: 请求数据 {"target_user_id": str, "message": str, "message_type": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            target_user_id = data.get("target_user_id", "").strip()
            message = data.get("message", "").strip()
            message_type = data.get("message_type", "text").strip()
            
            if not target_user_id:
                return self.validation_error_response("target_user_id", "目标用户ID不能为空")
                
            if not message:
                return self.validation_error_response("message", "消息内容不能为空")
                
            if len(message) > 1000:
                return self.validation_error_response("message", "消息内容过长")
                
            if target_user_id == context.user_id:
                return self.validation_error_response("target_user_id", "不能给自己发消息")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "send_private_message",
                "data": {
                    "target_user_id": target_user_id,
                    "message": message,
                    "message_type": message_type,
                    "sender_id": context.user_id,
                    "timestamp": time.time()
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="send_private_message",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "发送私聊消息失败")
                )
                
        except Exception as e:
            logger.error("发送私聊消息失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("发送私聊消息失败")
            
    @route(protocol_id=3008, description="获取私聊历史", group_name="chat")
    async def handle_protocol_3008(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取私聊历史请求
        
        Args:
            data: 请求数据 {"target_user_id": str, "page": int, "page_size": int}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            target_user_id = data.get("target_user_id", "").strip()
            page = data.get("page", 1)
            page_size = data.get("page_size", 50)
            
            if not target_user_id:
                return self.validation_error_response("target_user_id", "目标用户ID不能为空")
                
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 100:
                page_size = 50
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "get_private_chat_history",
                "data": {
                    "target_user_id": target_user_id,
                    "page": page,
                    "page_size": page_size,
                    "requester_id": context.user_id
                }
            }
            
            # 转发到chat服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_private_chat_history",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取私聊历史失败")
                )
                
        except Exception as e:
            logger.error("获取私聊历史失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取私聊历史失败")
            
    async def get_supported_protocols(self) -> List[int]:
        """获取支持的协议列表"""
        return [3001, 3002, 3003, 3004, 3005, 3006, 3007, 3008]
        
    async def get_controller_info(self) -> Dict[str, Any]:
        """获取控制器信息"""
        return {
            "name": "ChatController",
            "description": "聊天控制器",
            "version": "1.0.0",
            "target_service": self.target_service,
            "supported_protocols": await self.get_supported_protocols(),
            "required_permissions": list(self.required_permissions)
        }