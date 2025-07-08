"""
游戏控制器

该模块负责处理游戏相关的请求，主要转发游戏逻辑请求到logic服务，
包括游戏状态、玩家操作、游戏房间等功能。

主要功能：
- 转发游戏逻辑请求到logic服务
- 游戏状态管理
- 玩家操作处理
- 游戏房间管理
- 游戏数据同步
"""

import time
from typing import Dict, Any, List, Optional

from common.logger import logger
from ..route_manager import route, RouteType
from ..gate_handler import RequestContext
from .base_controller import BaseController, ControllerResponse


class GameController(BaseController):
    """游戏控制器"""
    
    def __init__(self, config, proxy_service):
        """
        初始化游戏控制器
        
        Args:
            config: 网关配置
            proxy_service: 代理服务
        """
        super().__init__(config)
        self.proxy_service = proxy_service
        self.target_service = "logic_service"
        
        # 设置需要权限的方法
        self.add_required_permission("game:play")
        
        logger.info("游戏控制器初始化完成")
        
    @route(protocol_id=2001, description="获取游戏状态", group_name="game")
    async def handle_protocol_2001(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取游戏状态请求
        
        Args:
            data: 请求数据 {}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "get_game_state",
                "data": data
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_game_state",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取游戏状态失败")
                )
                
        except Exception as e:
            logger.error("获取游戏状态失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取游戏状态失败")
            
    @route(protocol_id=2002, description="创建游戏房间", group_name="game")
    async def handle_protocol_2002(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理创建游戏房间请求
        
        Args:
            data: 请求数据 {"room_name": str, "max_players": int, "game_type": str}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_name = data.get("room_name", "").strip()
            max_players = data.get("max_players", 4)
            game_type = data.get("game_type", "").strip()
            
            if not room_name:
                return self.validation_error_response("room_name", "房间名称不能为空")
                
            if not game_type:
                return self.validation_error_response("game_type", "游戏类型不能为空")
                
            if max_players < 2 or max_players > 8:
                return self.validation_error_response("max_players", "玩家数量必须在2-8之间")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "create_room",
                "data": {
                    "room_name": room_name,
                    "max_players": max_players,
                    "game_type": game_type,
                    "creator_id": context.user_id
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="create_room",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "创建房间失败")
                )
                
        except Exception as e:
            logger.error("创建游戏房间失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("创建游戏房间失败")
            
    @route(protocol_id=2003, description="加入游戏房间", group_name="game")
    async def handle_protocol_2003(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理加入游戏房间请求
        
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
                "action": "join_room",
                "data": {
                    "room_id": room_id,
                    "password": password,
                    "player_id": context.user_id
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="join_room",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "加入房间失败")
                )
                
        except Exception as e:
            logger.error("加入游戏房间失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("加入游戏房间失败")
            
    @route(protocol_id=2004, description="离开游戏房间", group_name="game")
    async def handle_protocol_2004(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理离开游戏房间请求
        
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
                "action": "leave_room",
                "data": {
                    "room_id": room_id,
                    "player_id": context.user_id
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="leave_room",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "离开房间失败")
                )
                
        except Exception as e:
            logger.error("离开游戏房间失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("离开游戏房间失败")
            
    @route(protocol_id=2005, description="获取房间列表", group_name="game")
    async def handle_protocol_2005(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取房间列表请求
        
        Args:
            data: 请求数据 {"page": int, "page_size": int, "game_type": str}
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
            game_type = data.get("game_type", "").strip()
            
            if page < 1:
                page = 1
            if page_size < 1 or page_size > 100:
                page_size = 20
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "get_room_list",
                "data": {
                    "page": page,
                    "page_size": page_size,
                    "game_type": game_type
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_room_list",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取房间列表失败")
                )
                
        except Exception as e:
            logger.error("获取房间列表失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取房间列表失败")
            
    @route(protocol_id=2006, description="游戏操作", group_name="game")
    async def handle_protocol_2006(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理游戏操作请求
        
        Args:
            data: 请求数据 {"room_id": str, "action": str, "params": dict}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 验证参数
            room_id = data.get("room_id", "").strip()
            action = data.get("action", "").strip()
            params = data.get("params", {})
            
            if not room_id:
                return self.validation_error_response("room_id", "房间ID不能为空")
                
            if not action:
                return self.validation_error_response("action", "操作类型不能为空")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "game_action",
                "data": {
                    "room_id": room_id,
                    "action": action,
                    "params": params,
                    "player_id": context.user_id,
                    "timestamp": time.time()
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="game_action",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "游戏操作失败")
                )
                
        except Exception as e:
            logger.error("游戏操作失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("游戏操作失败")
            
    @route(protocol_id=2007, description="获取游戏历史", group_name="game")
    async def handle_protocol_2007(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取游戏历史请求
        
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
                "action": "get_game_history",
                "data": {
                    "page": page,
                    "page_size": page_size,
                    "player_id": context.user_id
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_game_history",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取游戏历史失败")
                )
                
        except Exception as e:
            logger.error("获取游戏历史失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取游戏历史失败")
            
    @route(protocol_id=2008, description="获取玩家统计", group_name="game")
    async def handle_protocol_2008(self, data: Dict[str, Any], context: RequestContext) -> ControllerResponse:
        """
        处理获取玩家统计请求
        
        Args:
            data: 请求数据 {}
            context: 请求上下文
            
        Returns:
            ControllerResponse: 响应结果
        """
        try:
            if not context.user_id:
                return self.error_response(401, "用户未登录")
                
            # 构造转发请求
            request_data = {
                "user_id": context.user_id,
                "action": "get_player_stats",
                "data": {
                    "player_id": context.user_id
                }
            }
            
            # 转发到logic服务
            result = await self.proxy_service.forward_request(
                service_name=self.target_service,
                method_name="get_player_stats",
                request_data=request_data,
                context=context
            )
            
            if result.get("success"):
                return self.success_response(result.get("data", {}))
            else:
                return self.error_response(
                    result.get("error_code", 500),
                    result.get("error_message", "获取玩家统计失败")
                )
                
        except Exception as e:
            logger.error("获取玩家统计失败", 
                        user_id=context.user_id,
                        error=str(e))
            return self.server_error_response("获取玩家统计失败")
            
    async def get_supported_protocols(self) -> List[int]:
        """获取支持的协议列表"""
        return [2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008]
        
    async def get_controller_info(self) -> Dict[str, Any]:
        """获取控制器信息"""
        return {
            "name": "GameController",
            "description": "游戏控制器",
            "version": "1.0.0",
            "target_service": self.target_service,
            "supported_protocols": await self.get_supported_protocols(),
            "required_permissions": list(self.required_permissions)
        }