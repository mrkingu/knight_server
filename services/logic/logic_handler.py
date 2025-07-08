"""
Logic消息处理器

该模块实现了Logic服务的统一消息处理器，继承自BaseHandler，
负责消息的接收、解码、路由、异常处理、性能统计等功能。

主要功能：
- 继承自BaseHandler提供完整的消息处理基础功能
- 统一接收和分发Logic相关的消息
- 根据消息类型自动路由到对应的Controller
- 处理异常和错误返回
- 记录请求日志和性能指标
- 支持消息验证和安全检查

消息处理流程：
1. 接收原始消息数据
2. 解码和验证消息
3. 根据消息ID路由到对应的控制器
4. 调用控制器处理业务逻辑
5. 编码响应消息
6. 返回处理结果

支持的消息类型：
- 用户相关消息 (登录、登出、用户信息等)
- 游戏相关消息 (游戏状态、房间管理等)
- 物品相关消息 (背包、装备、道具等)
- 任务相关消息 (任务列表、完成任务等)
- 排行榜相关消息 (排行榜查询、更新等)
"""

import asyncio
import time
import traceback
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from services.base import BaseHandler, RequestContext, ResponseContext, MessageType
from common.logger import logger
from common.decorator import get_handler_registry

# 导入协议相关
try:
    from common.proto import ProtoCodec
    PROTO_AVAILABLE = True
except ImportError:
    logger.warning("协议模块不可用，使用模拟模式")
    PROTO_AVAILABLE = False
    
    class ProtoCodec:
        @staticmethod
        def decode(data: bytes) -> dict:
            return {"message_id": 1001, "data": {}}
        
        @staticmethod
        def encode(data: dict) -> bytes:
            return b"mock_response"


@dataclass
class LogicMessageContext(RequestContext):
    """Logic消息上下文"""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    game_room_id: Optional[str] = None
    message_category: Optional[str] = None  # user, game, item, task, leaderboard
    require_auth: bool = True
    cache_key: Optional[str] = None


@dataclass
class LogicHandlerStatistics:
    """Logic处理器统计信息"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    user_requests: int = 0
    game_requests: int = 0
    item_requests: int = 0
    task_requests: int = 0
    leaderboard_requests: int = 0
    avg_response_time: float = 0.0
    max_response_time: float = 0.0
    min_response_time: float = float('inf')
    active_sessions: int = 0
    request_history: List[dict] = field(default_factory=list)


class LogicHandler(BaseHandler):
    """Logic消息处理器
    
    负责处理所有Logic服务相关的消息请求，包括用户管理、
    游戏状态、物品系统、任务系统、排行榜等功能。
    """
    
    def __init__(self):
        """初始化Logic消息处理器"""
        super().__init__(
            enable_tracing=True,
            enable_metrics=True,
            enable_validation=True,
            max_message_size=1024 * 1024,  # 1MB
            request_timeout=30.0
        )
        
        # Logic特有的统计信息
        self.logic_stats = LogicHandlerStatistics()
        
        # 消息路由映射
        self.message_routes: Dict[int, str] = {}
        
        # 控制器映射
        self.controller_mapping: Dict[str, str] = {
            'user': 'user',
            'game': 'game', 
            'item': 'item',
            'task': 'game',  # 任务由game控制器处理
            'leaderboard': 'game',  # 排行榜由game控制器处理
        }
        
        # 消息分类映射
        self.message_category_mapping: Dict[int, str] = {
            # 用户相关消息 (1000-1999)
            1001: 'user',  # 登录请求
            1002: 'user',  # 登出请求
            1003: 'user',  # 获取用户信息
            1004: 'user',  # 更新用户信息
            1005: 'user',  # 用户状态查询
            
            # 游戏相关消息 (2000-2999)
            2001: 'game',  # 创建游戏房间
            2002: 'game',  # 加入游戏房间
            2003: 'game',  # 离开游戏房间
            2004: 'game',  # 游戏状态同步
            2005: 'game',  # 游戏操作
            
            # 物品相关消息 (3000-3999)
            3001: 'item',  # 获取背包
            3002: 'item',  # 使用物品
            3003: 'item',  # 装备物品
            3004: 'item',  # 卸载装备
            3005: 'item',  # 物品交易
            
            # 任务相关消息 (4000-4999)
            4001: 'task',  # 获取任务列表
            4002: 'task',  # 接受任务
            4003: 'task',  # 完成任务
            4004: 'task',  # 任务进度更新
            4005: 'task',  # 任务奖励领取
            
            # 排行榜相关消息 (5000-5999)
            5001: 'leaderboard',  # 获取排行榜
            5002: 'leaderboard',  # 更新排行榜
            5003: 'leaderboard',  # 排行榜奖励
        }
        
        # 需要认证的消息
        self.auth_required_messages: set = {
            1002, 1003, 1004, 1005,  # 用户相关 (除了登录)
            2001, 2002, 2003, 2004, 2005,  # 游戏相关
            3001, 3002, 3003, 3004, 3005,  # 物品相关
            4001, 4002, 4003, 4004, 4005,  # 任务相关
            5001, 5002, 5003  # 排行榜相关
        }
        
        # 缓存配置
        self.cache_enabled_messages: set = {
            1003, 1005,  # 用户信息查询
            3001,  # 背包查询
            4001,  # 任务列表
            5001   # 排行榜查询
        }
        
        self.logger.info("Logic消息处理器初始化完成")
    
    async def initialize(self):
        """初始化Logic消息处理器"""
        try:
            # 调用基础处理器的初始化
            await super().initialize()
            
            # 构建消息路由表
            await self._build_message_routes()
            
            # 初始化协议编解码器
            await self._initialize_proto_codec()
            
            # 初始化性能监控
            await self._initialize_performance_monitor()
            
            self.logger.info("Logic消息处理器初始化完成")
            
        except Exception as e:
            self.logger.error("Logic消息处理器初始化失败", error=str(e))
            raise
    
    async def _build_message_routes(self):
        """构建消息路由表"""
        try:
            # 基于消息分类映射构建路由表
            for message_id, category in self.message_category_mapping.items():
                controller_name = self.controller_mapping.get(category)
                if controller_name:
                    self.message_routes[message_id] = controller_name
            
            self.logger.info("消息路由表构建完成", 
                           route_count=len(self.message_routes))
            
        except Exception as e:
            self.logger.error("消息路由表构建失败", error=str(e))
            raise
    
    async def _initialize_proto_codec(self):
        """初始化协议编解码器"""
        try:
            if PROTO_AVAILABLE:
                # 初始化协议编解码器
                pass
            
            self.logger.info("协议编解码器初始化完成")
            
        except Exception as e:
            self.logger.error("协议编解码器初始化失败", error=str(e))
            raise
    
    async def _initialize_performance_monitor(self):
        """初始化性能监控"""
        try:
            # 启动性能监控任务
            asyncio.create_task(self._performance_monitor_task())
            
            self.logger.info("性能监控初始化完成")
            
        except Exception as e:
            self.logger.error("性能监控初始化失败", error=str(e))
    
    async def _performance_monitor_task(self):
        """性能监控任务"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟统计一次
                
                # 计算平均响应时间
                if self.logic_stats.total_requests > 0:
                    self.logic_stats.avg_response_time = sum(
                        req.get('response_time', 0) 
                        for req in self.logic_stats.request_history[-100:]
                    ) / min(len(self.logic_stats.request_history), 100)
                
                # 清理旧的请求历史
                if len(self.logic_stats.request_history) > 1000:
                    self.logic_stats.request_history = self.logic_stats.request_history[-500:]
                
                # 记录统计信息
                self.logger.info("Logic处理器性能统计",
                               total_requests=self.logic_stats.total_requests,
                               success_rate=self.logic_stats.successful_requests / max(self.logic_stats.total_requests, 1),
                               avg_response_time=self.logic_stats.avg_response_time,
                               active_sessions=self.logic_stats.active_sessions)
                
            except Exception as e:
                self.logger.error("性能监控任务异常", error=str(e))
                await asyncio.sleep(60)
    
    async def handle_message(self, message_data: bytes, context: dict = None) -> Optional[bytes]:
        """处理Logic消息"""
        request_start_time = time.time()
        logic_context = None
        
        try:
            # 更新统计信息
            self.logic_stats.total_requests += 1
            
            # 创建Logic消息上下文
            logic_context = await self._create_logic_context(message_data, context)
            
            # 消息预处理
            await self._preprocess_message(logic_context)
            
            # 调用基础处理器的消息处理
            response = await super().handle_message(message_data, context)
            
            # 消息后处理
            await self._postprocess_message(logic_context, response)
            
            # 更新成功统计
            self.logic_stats.successful_requests += 1
            
            return response
            
        except Exception as e:
            self.logger.error("Logic消息处理失败", 
                            error=str(e),
                            traceback=traceback.format_exc(),
                            context=logic_context)
            
            # 更新失败统计
            self.logic_stats.failed_requests += 1
            
            # 生成错误响应
            return await self._generate_error_response(logic_context, e)
            
        finally:
            # 记录请求信息
            await self._record_request_info(logic_context, request_start_time)
    
    async def _create_logic_context(self, message_data: bytes, context: dict = None) -> LogicMessageContext:
        """创建Logic消息上下文"""
        try:
            # 解码消息获取基本信息
            if PROTO_AVAILABLE:
                decoded_message = ProtoCodec.decode(message_data)
            else:
                decoded_message = {"message_id": 1001, "data": {}}
            
            message_id = decoded_message.get("message_id", 0)
            message_category = self.message_category_mapping.get(message_id, 'unknown')
            
            # 创建Logic上下文
            logic_context = LogicMessageContext(
                trace_id=f"logic_{time.time()}_{message_id}",
                message_id=message_id,
                message_data=message_data,
                message_size=len(message_data),
                client_ip=context.get('client_ip', '127.0.0.1') if context else '127.0.0.1',
                user_id=context.get('user_id') if context else None,
                session_id=context.get('session_id') if context else None,
                game_room_id=context.get('game_room_id') if context else None,
                message_category=message_category,
                require_auth=message_id in self.auth_required_messages,
                cache_key=f"logic_{message_id}_{context.get('user_id', '')}" if context else None
            )
            
            return logic_context
            
        except Exception as e:
            self.logger.error("创建Logic上下文失败", error=str(e))
            raise
    
    async def _preprocess_message(self, context: LogicMessageContext):
        """消息预处理"""
        try:
            # 检查认证
            if context.require_auth and not context.user_id:
                raise ValueError("需要用户认证")
            
            # 检查会话
            if context.require_auth and not context.session_id:
                raise ValueError("需要有效会话")
            
            # 更新分类统计
            if context.message_category == 'user':
                self.logic_stats.user_requests += 1
            elif context.message_category == 'game':
                self.logic_stats.game_requests += 1
            elif context.message_category == 'item':
                self.logic_stats.item_requests += 1
            elif context.message_category == 'task':
                self.logic_stats.task_requests += 1
            elif context.message_category == 'leaderboard':
                self.logic_stats.leaderboard_requests += 1
            
            self.logger.debug("消息预处理完成", 
                            message_id=context.message_id,
                            category=context.message_category,
                            user_id=context.user_id)
            
        except Exception as e:
            self.logger.error("消息预处理失败", error=str(e))
            raise
    
    async def _postprocess_message(self, context: LogicMessageContext, response: Optional[bytes]):
        """消息后处理"""
        try:
            # 缓存处理
            if context.message_id in self.cache_enabled_messages and response:
                await self._cache_response(context, response)
            
            # 通知处理
            await self._handle_notifications(context, response)
            
            self.logger.debug("消息后处理完成", 
                            message_id=context.message_id,
                            response_size=len(response) if response else 0)
            
        except Exception as e:
            self.logger.error("消息后处理失败", error=str(e))
            # 后处理失败不影响主流程
    
    async def _cache_response(self, context: LogicMessageContext, response: bytes):
        """缓存响应"""
        try:
            if context.cache_key:
                # 这里应该实现缓存逻辑
                pass
            
        except Exception as e:
            self.logger.error("缓存响应失败", error=str(e))
    
    async def _handle_notifications(self, context: LogicMessageContext, response: Optional[bytes]):
        """处理通知"""
        try:
            # 根据消息类型发送相应的通知
            if context.message_category == 'game' and context.game_room_id:
                # 游戏相关通知
                pass
            elif context.message_category == 'user' and context.user_id:
                # 用户相关通知
                pass
            
        except Exception as e:
            self.logger.error("通知处理失败", error=str(e))
    
    async def _generate_error_response(self, context: Optional[LogicMessageContext], error: Exception) -> bytes:
        """生成错误响应"""
        try:
            error_response = {
                "status": "error",
                "code": 500,
                "message": str(error),
                "trace_id": context.trace_id if context else "unknown"
            }
            
            if PROTO_AVAILABLE:
                return ProtoCodec.encode(error_response)
            else:
                return b"error_response"
                
        except Exception as e:
            self.logger.error("生成错误响应失败", error=str(e))
            return b"internal_error"
    
    async def _record_request_info(self, context: Optional[LogicMessageContext], start_time: float):
        """记录请求信息"""
        try:
            if not context:
                return
            
            response_time = time.time() - start_time
            
            # 更新响应时间统计
            self.logic_stats.max_response_time = max(self.logic_stats.max_response_time, response_time)
            self.logic_stats.min_response_time = min(self.logic_stats.min_response_time, response_time)
            
            # 记录请求历史
            request_info = {
                'trace_id': context.trace_id,
                'message_id': context.message_id,
                'category': context.message_category,
                'user_id': context.user_id,
                'response_time': response_time,
                'timestamp': time.time()
            }
            
            self.logic_stats.request_history.append(request_info)
            
            # 记录详细日志
            self.logger.info("Logic请求处理完成",
                           trace_id=context.trace_id,
                           message_id=context.message_id,
                           category=context.message_category,
                           user_id=context.user_id,
                           response_time=response_time)
            
        except Exception as e:
            self.logger.error("记录请求信息失败", error=str(e))
    
    async def _route_message(self, context: RequestContext, message: Any) -> Any:
        """路由消息到对应的控制器"""
        try:
            # 获取消息ID
            message_id = getattr(message, 'message_id', context.message_id)
            
            # 查找对应的控制器
            controller_name = self.message_routes.get(message_id)
            if not controller_name:
                raise ValueError(f"未找到消息ID {message_id} 对应的控制器")
            
            # 获取控制器
            controller = self._controllers.get(controller_name)
            if not controller:
                raise ValueError(f"控制器 {controller_name} 未注册")
            
            # 调用控制器处理消息
            return await controller.handle_message(message, context)
            
        except Exception as e:
            self.logger.error("消息路由失败", 
                            message_id=getattr(message, 'message_id', 'unknown'),
                            error=str(e))
            raise
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取处理器统计信息"""
        return {
            'total_requests': self.logic_stats.total_requests,
            'successful_requests': self.logic_stats.successful_requests,
            'failed_requests': self.logic_stats.failed_requests,
            'success_rate': self.logic_stats.successful_requests / max(self.logic_stats.total_requests, 1),
            'user_requests': self.logic_stats.user_requests,
            'game_requests': self.logic_stats.game_requests,
            'item_requests': self.logic_stats.item_requests,
            'task_requests': self.logic_stats.task_requests,
            'leaderboard_requests': self.logic_stats.leaderboard_requests,
            'avg_response_time': self.logic_stats.avg_response_time,
            'max_response_time': self.logic_stats.max_response_time,
            'min_response_time': self.logic_stats.min_response_time if self.logic_stats.min_response_time != float('inf') else 0,
            'active_sessions': self.logic_stats.active_sessions,
            'message_routes': len(self.message_routes)
        }
    
    def get_route_info(self) -> Dict[str, Any]:
        """获取路由信息"""
        return {
            'message_routes': self.message_routes,
            'message_categories': self.message_category_mapping,
            'auth_required_messages': list(self.auth_required_messages),
            'cache_enabled_messages': list(self.cache_enabled_messages)
        }


def create_logic_handler() -> LogicHandler:
    """
    创建Logic消息处理器实例
    
    Returns:
        LogicHandler实例
    """
    try:
        handler = LogicHandler()
        logger.info("Logic消息处理器创建成功")
        return handler
        
    except Exception as e:
        logger.error("创建Logic消息处理器失败", error=str(e))
        raise


# 便于测试的工厂函数
async def create_and_initialize_logic_handler() -> LogicHandler:
    """
    创建并初始化Logic消息处理器
    
    Returns:
        已初始化的LogicHandler实例
    """
    handler = create_logic_handler()
    await handler.initialize()
    return handler