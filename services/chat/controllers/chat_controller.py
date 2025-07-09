"""
Chat控制器

该模块实现了聊天功能的控制器，继承自BaseController，
负责处理私聊、群聊、消息发送、消息历史等聊天相关的业务逻辑。

主要功能：
- 处理私聊消息发送和接收
- 处理群聊消息发送和接收
- 获取聊天历史记录
- 用户在线状态管理
- 消息状态管理（已读、未读）
- 消息撤回功能
- 表情和富文本消息支持

装饰器支持：
- @handler 绑定消息协议号到处理方法
- 参数自动验证和解析
- 响应消息自动构建

技术特点：
- 使用MVC架构模式
- 异步处理提高性能
- 完善的异常处理
- 详细的日志记录
- 支持消息过滤和验证
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

from services.base import BaseController, ControllerException, ValidationException
from common.logger import logger
from common.decorator.handler_decorator import handler, controller


@dataclass
class ChatMessage:
    """聊天消息数据结构"""
    message_id: str
    sender_id: str
    receiver_id: str
    content: str
    message_type: str = "text"  # text, image, voice, video, file
    timestamp: float = 0.0
    status: str = "sent"  # sent, delivered, read
    chat_type: str = "private"  # private, group


@dataclass
class ChatHistory:
    """聊天历史数据结构"""
    chat_id: str
    messages: List[ChatMessage]
    total_count: int
    has_more: bool = False


@controller(name="ChatController")
class ChatController(BaseController):
    """
    Chat控制器
    
    负责处理所有聊天相关的请求，包括私聊、群聊、消息历史等功能。
    与ChatService和FilterService协作完成业务逻辑处理。
    """
    
    def __init__(self):
        """初始化Chat控制器"""
        super().__init__()
        
        # 服务依赖
        self.chat_service = None
        self.filter_service = None
        
        # 消息缓存
        self.recent_messages: Dict[str, List[ChatMessage]] = {}
        self.message_cache_ttl = 300  # 5分钟
        
        # 用户会话管理
        self.user_sessions: Dict[str, Dict[str, Any]] = {}
        
        # 统计信息
        self.message_stats = {
            'total_sent': 0,
            'total_received': 0,
            'private_messages': 0,
            'group_messages': 0,
            'filtered_messages': 0
        }
        
        self.logger.info("Chat控制器初始化完成")
    
    async def initialize(self):
        """初始化控制器"""
        try:
            # 获取服务依赖
            self.chat_service = self.get_service('chat_service')
            self.filter_service = self.get_service('filter_service')
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_cache())
            
            self.logger.info("Chat控制器初始化成功")
            
        except Exception as e:
            self.logger.error("Chat控制器初始化失败", error=str(e))
            raise ControllerException(f"Chat控制器初始化失败: {e}")
    
    @handler(message_id=6001)
    async def send_private_message(self, request, context):
        """
        发送私聊消息
        
        Args:
            request: 包含sender_id, receiver_id, content, message_type的请求
            context: 请求上下文
            
        Returns:
            响应消息包含message_id和发送状态
        """
        try:
            # 参数验证
            if not hasattr(request, 'sender_id') or not request.sender_id:
                raise ValidationException("发送者ID不能为空")
            if not hasattr(request, 'receiver_id') or not request.receiver_id:
                raise ValidationException("接收者ID不能为空")
            if not hasattr(request, 'content') or not request.content:
                raise ValidationException("消息内容不能为空")
            
            # 内容过滤
            filtered_content = await self.filter_service.filter_content(
                request.content, 
                request.sender_id
            )
            
            if filtered_content != request.content:
                self.message_stats['filtered_messages'] += 1
                self.logger.info("消息内容被过滤", 
                               sender_id=request.sender_id,
                               original_length=len(request.content),
                               filtered_length=len(filtered_content))
            
            # 创建消息对象
            message = ChatMessage(
                message_id=f"msg_{int(time.time() * 1000000)}",
                sender_id=request.sender_id,
                receiver_id=request.receiver_id,
                content=filtered_content,
                message_type=getattr(request, 'message_type', 'text'),
                timestamp=time.time(),
                chat_type="private"
            )
            
            # 发送消息
            success = await self.chat_service.send_private_message(message)
            
            if success:
                self.message_stats['total_sent'] += 1
                self.message_stats['private_messages'] += 1
                
                # 更新缓存
                await self._update_message_cache(message)
                
                self.logger.info("私聊消息发送成功", 
                               message_id=message.message_id,
                               sender_id=request.sender_id,
                               receiver_id=request.receiver_id)
                
                return {
                    'message_id': message.message_id,
                    'status': 'success',
                    'timestamp': message.timestamp
                }
            else:
                self.logger.error("私聊消息发送失败", 
                                sender_id=request.sender_id,
                                receiver_id=request.receiver_id)
                
                return {
                    'message_id': message.message_id,
                    'status': 'failed',
                    'error': '消息发送失败'
                }
                
        except ValidationException as e:
            self.logger.warning("私聊消息参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("发送私聊消息异常", error=str(e))
            raise ControllerException(f"发送私聊消息失败: {e}")
    
    @handler(message_id=6002)
    async def get_chat_history(self, request, context):
        """
        获取聊天历史记录
        
        Args:
            request: 包含user_id, chat_id, page, page_size的请求
            context: 请求上下文
            
        Returns:
            包含历史消息列表的响应
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'chat_id') or not request.chat_id:
                raise ValidationException("聊天ID不能为空")
            
            page = getattr(request, 'page', 1)
            page_size = getattr(request, 'page_size', 20)
            
            # 获取历史记录
            history = await self.chat_service.get_chat_history(
                request.user_id,
                request.chat_id,
                page,
                page_size
            )
            
            self.logger.info("获取聊天历史成功", 
                           user_id=request.user_id,
                           chat_id=request.chat_id,
                           message_count=len(history.messages))
            
            return {
                'chat_id': history.chat_id,
                'messages': [
                    {
                        'message_id': msg.message_id,
                        'sender_id': msg.sender_id,
                        'receiver_id': msg.receiver_id,
                        'content': msg.content,
                        'message_type': msg.message_type,
                        'timestamp': msg.timestamp,
                        'status': msg.status
                    }
                    for msg in history.messages
                ],
                'total_count': history.total_count,
                'has_more': history.has_more
            }
            
        except ValidationException as e:
            self.logger.warning("获取聊天历史参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取聊天历史异常", error=str(e))
            raise ControllerException(f"获取聊天历史失败: {e}")
    
    @handler(message_id=6003)
    async def mark_message_read(self, request, context):
        """
        标记消息为已读
        
        Args:
            request: 包含user_id, message_id的请求
            context: 请求上下文
            
        Returns:
            标记结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'message_id') or not request.message_id:
                raise ValidationException("消息ID不能为空")
            
            # 标记已读
            success = await self.chat_service.mark_message_read(
                request.user_id,
                request.message_id
            )
            
            if success:
                self.logger.info("消息标记已读成功", 
                               user_id=request.user_id,
                               message_id=request.message_id)
                
                return {
                    'status': 'success',
                    'message_id': request.message_id
                }
            else:
                self.logger.error("消息标记已读失败", 
                                user_id=request.user_id,
                                message_id=request.message_id)
                
                return {
                    'status': 'failed',
                    'error': '标记已读失败'
                }
                
        except ValidationException as e:
            self.logger.warning("标记消息已读参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("标记消息已读异常", error=str(e))
            raise ControllerException(f"标记消息已读失败: {e}")
    
    @handler(message_id=6004)
    async def recall_message(self, request, context):
        """
        撤回消息
        
        Args:
            request: 包含user_id, message_id的请求
            context: 请求上下文
            
        Returns:
            撤回结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'message_id') or not request.message_id:
                raise ValidationException("消息ID不能为空")
            
            # 撤回消息
            success = await self.chat_service.recall_message(
                request.user_id,
                request.message_id
            )
            
            if success:
                self.logger.info("消息撤回成功", 
                               user_id=request.user_id,
                               message_id=request.message_id)
                
                return {
                    'status': 'success',
                    'message_id': request.message_id
                }
            else:
                self.logger.error("消息撤回失败", 
                                user_id=request.user_id,
                                message_id=request.message_id)
                
                return {
                    'status': 'failed',
                    'error': '消息撤回失败'
                }
                
        except ValidationException as e:
            self.logger.warning("撤回消息参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("撤回消息异常", error=str(e))
            raise ControllerException(f"撤回消息失败: {e}")
    
    async def _update_message_cache(self, message: ChatMessage):
        """更新消息缓存"""
        try:
            cache_key = f"{message.sender_id}:{message.receiver_id}"
            
            if cache_key not in self.recent_messages:
                self.recent_messages[cache_key] = []
            
            self.recent_messages[cache_key].append(message)
            
            # 保持缓存大小限制
            if len(self.recent_messages[cache_key]) > 100:
                self.recent_messages[cache_key] = self.recent_messages[cache_key][-100:]
                
        except Exception as e:
            self.logger.error("更新消息缓存失败", error=str(e))
    
    async def _cleanup_expired_cache(self):
        """清理过期缓存"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                expired_keys = []
                
                for cache_key, messages in self.recent_messages.items():
                    # 移除过期消息
                    valid_messages = [
                        msg for msg in messages 
                        if current_time - msg.timestamp <= self.message_cache_ttl
                    ]
                    
                    if valid_messages:
                        self.recent_messages[cache_key] = valid_messages
                    else:
                        expired_keys.append(cache_key)
                
                # 删除空的缓存键
                for key in expired_keys:
                    del self.recent_messages[key]
                
                if expired_keys:
                    self.logger.info("清理过期消息缓存", expired_count=len(expired_keys))
                    
            except Exception as e:
                self.logger.error("清理消息缓存异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            'message_stats': self.message_stats.copy(),
            'cache_info': {
                'cached_conversations': len(self.recent_messages),
                'total_cached_messages': sum(len(msgs) for msgs in self.recent_messages.values())
            },
            'active_sessions': len(self.user_sessions)
        }
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            # 清理缓存
            self.recent_messages.clear()
            self.user_sessions.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Chat控制器清理完成")
            
        except Exception as e:
            self.logger.error("Chat控制器清理失败", error=str(e))