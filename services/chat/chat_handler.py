"""
Chat消息处理器

该模块实现了Chat服务的统一消息处理器，继承自BaseHandler，
负责消息的接收、解码、路由、异常处理、性能统计等功能。

主要功能：
- 继承自BaseHandler提供完整的消息处理基础功能
- 统一接收和分发Chat相关的消息
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
- 私聊消息 (发送、接收、历史记录)
- 频道消息 (创建、加入、离开、发送消息)
- 系统消息 (公告、通知)
- 用户状态消息 (上线、离线、状态变更)
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
            return {"message_id": 6001, "data": {}}
        
        @staticmethod
        def encode(data: dict) -> bytes:
            return b"mock_response"


@dataclass
class ChatMessageContext(RequestContext):
    """Chat消息上下文"""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    channel_id: Optional[str] = None
    target_user_id: Optional[str] = None
    message_category: Optional[str] = None  # private, channel, system
    require_auth: bool = True
    cache_key: Optional[str] = None
    message_type: Optional[str] = None  # text, image, file, emoji


@dataclass
class ChatHandlerStatistics:
    """Chat处理器统计信息"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    private_messages: int = 0
    channel_messages: int = 0
    system_messages: int = 0
    filtered_messages: int = 0
    avg_response_time: float = 0.0
    max_response_time: float = 0.0
    min_response_time: float = float('inf')
    active_users: int = 0
    active_channels: int = 0
    request_history: List[dict] = field(default_factory=list)


class ChatHandler(BaseHandler):
    """Chat消息处理器
    
    负责处理所有Chat服务相关的消息请求，包括私聊、频道聊天、
    系统消息等功能。
    """
    
    def __init__(self):
        """初始化Chat消息处理器"""
        super().__init__(
            enable_tracing=True,
            enable_metrics=True,
            enable_validation=True,
            max_message_size=1024 * 1024,  # 1MB
            request_timeout=30.0
        )
        
        # Chat特有的统计信息
        self.chat_stats = ChatHandlerStatistics()
        
        # 消息路由映射
        self.message_routes: Dict[int, str] = {}
        
        # 控制器映射
        self.controller_mapping: Dict[str, str] = {
            'private': 'chat',
            'channel': 'channel',
            'system': 'chat',
            'user_status': 'chat'
        }
        
        # 消息分类映射
        self.message_category_mapping: Dict[int, str] = {
            # 私聊相关消息 (6000-6999)
            6001: 'private',  # 发送私聊消息
            6002: 'private',  # 获取私聊历史
            6003: 'private',  # 删除私聊消息
            6004: 'private',  # 撤回私聊消息
            6005: 'private',  # 标记消息已读
            
            # 频道相关消息 (7000-7999)
            7001: 'channel',  # 创建频道
            7002: 'channel',  # 加入频道
            7003: 'channel',  # 离开频道
            7004: 'channel',  # 发送频道消息
            7005: 'channel',  # 获取频道历史
            7006: 'channel',  # 获取频道列表
            7007: 'channel',  # 获取频道成员
            7008: 'channel',  # 频道管理操作
            
            # 系统消息相关 (8000-8999)
            8001: 'system',  # 系统公告
            8002: 'system',  # 系统通知
            8003: 'system',  # 获取系统消息历史
            
            # 用户状态相关 (9000-9999)
            9001: 'user_status',  # 用户上线
            9002: 'user_status',  # 用户离线
            9003: 'user_status',  # 用户状态变更
            9004: 'user_status',  # 获取用户状态
        }
        
        # 需要认证的消息
        self.auth_required_messages: set = {
            6001, 6002, 6003, 6004, 6005,  # 私聊相关
            7001, 7002, 7003, 7004, 7005, 7006, 7007, 7008,  # 频道相关
            9001, 9002, 9003, 9004  # 用户状态相关
        }
        
        # 缓存配置
        self.cache_enabled_messages: set = {
            6002,  # 私聊历史
            7005,  # 频道历史
            7006,  # 频道列表
            7007,  # 频道成员
            8003,  # 系统消息历史
            9004   # 用户状态
        }
        
        # 消息类型映射
        self.message_type_mapping: Dict[int, str] = {
            6001: 'text',  # 文本消息
            6002: 'history',  # 历史消息
            7004: 'text',  # 频道文本消息
            8001: 'announcement',  # 公告
            8002: 'notification'  # 通知
        }
        
        # 用户活动追踪
        self.user_activity: Dict[str, float] = {}
        
        # 频道活动追踪
        self.channel_activity: Dict[str, float] = {}
        
        self.logger.info("Chat消息处理器初始化完成")
    
    async def initialize(self):
        """初始化Chat消息处理器"""
        try:
            # 调用基础处理器的初始化
            await super().initialize()
            
            # 构建消息路由表
            await self._build_message_routes()
            
            # 初始化协议编解码器
            await self._initialize_proto_codec()
            
            # 初始化性能监控
            await self._initialize_performance_monitor()
            
            # 初始化消息过滤器
            await self._initialize_message_filter()
            
            self.logger.info("Chat消息处理器初始化完成")
            
        except Exception as e:
            self.logger.error("Chat消息处理器初始化失败", error=str(e))
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
    
    async def _initialize_message_filter(self):
        """初始化消息过滤器"""
        try:
            # 初始化敏感词过滤
            # 这里应该加载敏感词库
            
            self.logger.info("消息过滤器初始化完成")
            
        except Exception as e:
            self.logger.error("消息过滤器初始化失败", error=str(e))
    
    async def _performance_monitor_task(self):
        """性能监控任务"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟统计一次
                
                # 计算平均响应时间
                if self.chat_stats.total_requests > 0:
                    self.chat_stats.avg_response_time = sum(
                        req.get('response_time', 0) 
                        for req in self.chat_stats.request_history[-100:]
                    ) / min(len(self.chat_stats.request_history), 100)
                
                # 清理旧的请求历史
                if len(self.chat_stats.request_history) > 1000:
                    self.chat_stats.request_history = self.chat_stats.request_history[-500:]
                
                # 更新活跃用户和频道数
                current_time = time.time()
                
                # 统计活跃用户
                active_users = sum(1 for last_activity in self.user_activity.values() 
                                 if current_time - last_activity < 300)  # 5分钟内活跃
                self.chat_stats.active_users = active_users
                
                # 统计活跃频道
                active_channels = sum(1 for last_activity in self.channel_activity.values()
                                    if current_time - last_activity < 600)  # 10分钟内活跃
                self.chat_stats.active_channels = active_channels
                
                # 记录统计信息
                self.logger.info("Chat处理器性能统计",
                               total_requests=self.chat_stats.total_requests,
                               success_rate=self.chat_stats.successful_requests / max(self.chat_stats.total_requests, 1),
                               avg_response_time=self.chat_stats.avg_response_time,
                               active_users=self.chat_stats.active_users,
                               active_channels=self.chat_stats.active_channels)
                
            except Exception as e:
                self.logger.error("性能监控任务异常", error=str(e))
                await asyncio.sleep(60)
    
    async def handle_message(self, message_data: bytes, context: dict = None) -> Optional[bytes]:
        """处理Chat消息"""
        request_start_time = time.time()
        chat_context = None
        
        try:
            # 更新统计信息
            self.chat_stats.total_requests += 1
            
            # 创建Chat消息上下文
            chat_context = await self._create_chat_context(message_data, context)
            
            # 消息预处理
            await self._preprocess_message(chat_context)
            
            # 调用基础处理器的消息处理
            response = await super().handle_message(message_data, context)
            
            # 消息后处理
            await self._postprocess_message(chat_context, response)
            
            # 更新成功统计
            self.chat_stats.successful_requests += 1
            
            return response
            
        except Exception as e:
            self.logger.error("Chat消息处理失败", 
                            error=str(e),
                            traceback=traceback.format_exc(),
                            context=chat_context)
            
            # 更新失败统计
            self.chat_stats.failed_requests += 1
            
            # 生成错误响应
            return await self._generate_error_response(chat_context, e)
            
        finally:
            # 记录请求信息
            await self._record_request_info(chat_context, request_start_time)
    
    async def _create_chat_context(self, message_data: bytes, context: dict = None) -> ChatMessageContext:
        """创建Chat消息上下文"""
        try:
            # 解码消息获取基本信息
            if PROTO_AVAILABLE:
                decoded_message = ProtoCodec.decode(message_data)
            else:
                decoded_message = {"message_id": 6001, "data": {}}
            
            message_id = decoded_message.get("message_id", 0)
            message_category = self.message_category_mapping.get(message_id, 'unknown')
            message_type = self.message_type_mapping.get(message_id, 'text')
            
            # 从消息数据中提取信息
            data = decoded_message.get("data", {})
            
            # 创建Chat上下文
            chat_context = ChatMessageContext(
                trace_id=f"chat_{time.time()}_{message_id}",
                message_id=message_id,
                message_data=message_data,
                message_size=len(message_data),
                client_ip=context.get('client_ip', '127.0.0.1') if context else '127.0.0.1',
                user_id=context.get('user_id') if context else None,
                session_id=context.get('session_id') if context else None,
                channel_id=data.get('channel_id') if data else None,
                target_user_id=data.get('target_user_id') if data else None,
                message_category=message_category,
                message_type=message_type,
                require_auth=message_id in self.auth_required_messages,
                cache_key=f"chat_{message_id}_{context.get('user_id', '')}" if context else None
            )
            
            return chat_context
            
        except Exception as e:
            self.logger.error("创建Chat上下文失败", error=str(e))
            raise
    
    async def _preprocess_message(self, context: ChatMessageContext):
        """消息预处理"""
        try:
            # 检查认证
            if context.require_auth and not context.user_id:
                raise ValueError("需要用户认证")
            
            # 检查会话
            if context.require_auth and not context.session_id:
                raise ValueError("需要有效会话")
            
            # 更新用户活动
            if context.user_id:
                self.user_activity[context.user_id] = time.time()
            
            # 更新频道活动
            if context.channel_id:
                self.channel_activity[context.channel_id] = time.time()
            
            # 更新分类统计
            if context.message_category == 'private':
                self.chat_stats.private_messages += 1
            elif context.message_category == 'channel':
                self.chat_stats.channel_messages += 1
            elif context.message_category == 'system':
                self.chat_stats.system_messages += 1
            
            self.logger.debug("消息预处理完成", 
                            message_id=context.message_id,
                            category=context.message_category,
                            user_id=context.user_id)
            
        except Exception as e:
            self.logger.error("消息预处理失败", error=str(e))
            raise
    
    async def _postprocess_message(self, context: ChatMessageContext, response: Optional[bytes]):
        """消息后处理"""
        try:
            # 缓存处理
            if context.message_id in self.cache_enabled_messages and response:
                await self._cache_response(context, response)
            
            # 通知处理
            await self._handle_notifications(context, response)
            
            # 消息过滤统计
            if context.message_type == 'text':
                # 这里应该检查是否被过滤
                pass
            
            self.logger.debug("消息后处理完成", 
                            message_id=context.message_id,
                            response_size=len(response) if response else 0)
            
        except Exception as e:
            self.logger.error("消息后处理失败", error=str(e))
            # 后处理失败不影响主流程
    
    async def _cache_response(self, context: ChatMessageContext, response: bytes):
        """缓存响应"""
        try:
            if context.cache_key:
                # 这里应该实现缓存逻辑
                pass
            
        except Exception as e:
            self.logger.error("缓存响应失败", error=str(e))
    
    async def _handle_notifications(self, context: ChatMessageContext, response: Optional[bytes]):
        """处理通知"""
        try:
            # 根据消息类型发送相应的通知
            if context.message_category == 'private' and context.target_user_id:
                # 私聊通知
                pass
            elif context.message_category == 'channel' and context.channel_id:
                # 频道通知
                pass
            elif context.message_category == 'system':
                # 系统通知
                pass
            
        except Exception as e:
            self.logger.error("通知处理失败", error=str(e))
    
    async def _generate_error_response(self, context: Optional[ChatMessageContext], error: Exception) -> bytes:
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
    
    async def _record_request_info(self, context: Optional[ChatMessageContext], start_time: float):
        """记录请求信息"""
        try:
            if not context:
                return
            
            response_time = time.time() - start_time
            
            # 更新响应时间统计
            self.chat_stats.max_response_time = max(self.chat_stats.max_response_time, response_time)
            self.chat_stats.min_response_time = min(self.chat_stats.min_response_time, response_time)
            
            # 记录请求历史
            request_info = {
                'trace_id': context.trace_id,
                'message_id': context.message_id,
                'category': context.message_category,
                'message_type': context.message_type,
                'user_id': context.user_id,
                'channel_id': context.channel_id,
                'response_time': response_time,
                'timestamp': time.time()
            }
            
            self.chat_stats.request_history.append(request_info)
            
            # 记录详细日志
            self.logger.info("Chat请求处理完成",
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
            'total_requests': self.chat_stats.total_requests,
            'successful_requests': self.chat_stats.successful_requests,
            'failed_requests': self.chat_stats.failed_requests,
            'success_rate': self.chat_stats.successful_requests / max(self.chat_stats.total_requests, 1),
            'private_messages': self.chat_stats.private_messages,
            'channel_messages': self.chat_stats.channel_messages,
            'system_messages': self.chat_stats.system_messages,
            'filtered_messages': self.chat_stats.filtered_messages,
            'avg_response_time': self.chat_stats.avg_response_time,
            'max_response_time': self.chat_stats.max_response_time,
            'min_response_time': self.chat_stats.min_response_time if self.chat_stats.min_response_time != float('inf') else 0,
            'active_users': self.chat_stats.active_users,
            'active_channels': self.chat_stats.active_channels,
            'message_routes': len(self.message_routes)
        }
    
    def get_route_info(self) -> Dict[str, Any]:
        """获取路由信息"""
        return {
            'message_routes': self.message_routes,
            'message_categories': self.message_category_mapping,
            'message_types': self.message_type_mapping,
            'auth_required_messages': list(self.auth_required_messages),
            'cache_enabled_messages': list(self.cache_enabled_messages)
        }


def create_chat_handler() -> ChatHandler:
    """
    创建Chat消息处理器实例
    
    Returns:
        ChatHandler实例
    """
    try:
        handler = ChatHandler()
        logger.info("Chat消息处理器创建成功")
        return handler
        
    except Exception as e:
        logger.error("创建Chat消息处理器失败", error=str(e))
        raise


# 便于测试的工厂函数
async def create_and_initialize_chat_handler() -> ChatHandler:
    """
    创建并初始化Chat消息处理器
    
    Returns:
        已初始化的ChatHandler实例
    """
    handler = create_chat_handler()
    await handler.initialize()
    return handler