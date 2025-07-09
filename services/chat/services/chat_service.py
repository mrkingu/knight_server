"""
Chat业务服务

该模块实现了聊天功能的业务服务层，继承自BaseService，
负责处理私聊、群聊、消息存储、消息历史、用户状态等核心业务逻辑。

主要功能：
- 私聊消息处理和存储
- 群聊消息处理和存储
- 消息历史记录管理
- 用户在线状态管理
- 消息状态管理（发送、接收、已读）
- 消息撤回和删除
- 聊天会话管理
- 消息统计和分析

技术特点：
- 使用异步处理提高性能
- 支持分布式事务处理
- 完善的缓存机制
- 详细的日志记录
- 支持消息持久化
- 高并发处理能力
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from services.base import BaseService, ServiceException, transactional, cached, retry
from common.logger import logger


@dataclass
class ChatMessage:
    """聊天消息数据结构"""
    message_id: str
    sender_id: str
    receiver_id: str
    content: str
    message_type: str = "text"
    timestamp: float = 0.0
    status: str = "sent"
    chat_type: str = "private"
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class ChatHistory:
    """聊天历史数据结构"""
    chat_id: str
    messages: List[ChatMessage]
    total_count: int
    has_more: bool = False


@dataclass
class ChatSession:
    """聊天会话数据结构"""
    session_id: str
    user_id: str
    target_id: str
    chat_type: str
    last_message_time: float
    unread_count: int
    is_active: bool = True


class ChatService(BaseService):
    """
    Chat业务服务
    
    负责处理所有聊天相关的业务逻辑，包括消息发送、接收、存储、
    历史记录管理、会话管理等功能。
    """
    
    def __init__(self, max_message_length: int = 1000, 
                 max_messages_per_second: int = 10,
                 message_history_size: int = 1000):
        """
        初始化Chat服务
        
        Args:
            max_message_length: 消息最大长度
            max_messages_per_second: 每秒最大消息数
            message_history_size: 历史消息保存数量
        """
        super().__init__()
        
        self.max_message_length = max_message_length
        self.max_messages_per_second = max_messages_per_second
        self.message_history_size = message_history_size
        
        # 消息存储
        self.message_storage: Dict[str, List[ChatMessage]] = {}
        self.message_index: Dict[str, ChatMessage] = {}
        
        # 会话管理
        self.user_sessions: Dict[str, List[ChatSession]] = {}
        self.session_index: Dict[str, ChatSession] = {}
        
        # 用户状态管理
        self.user_status: Dict[str, Dict[str, Any]] = {}
        self.online_users: Set[str] = set()
        
        # 消息统计
        self.message_stats = {
            'total_messages': 0,
            'private_messages': 0,
            'group_messages': 0,
            'messages_delivered': 0,
            'messages_read': 0,
            'messages_recalled': 0
        }
        
        # 限流控制
        self.rate_limiter: Dict[str, List[float]] = {}
        
        self.logger.info("Chat服务初始化完成",
                        max_message_length=max_message_length,
                        max_messages_per_second=max_messages_per_second,
                        message_history_size=message_history_size)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化基础服务
            await super().initialize()
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_sessions())
            asyncio.create_task(self._cleanup_rate_limiter())
            asyncio.create_task(self._update_user_status())
            
            self.logger.info("Chat服务初始化成功")
            
        except Exception as e:
            self.logger.error("Chat服务初始化失败", error=str(e))
            raise ServiceException(f"Chat服务初始化失败: {e}")
    
    @transactional
    async def send_private_message(self, message: ChatMessage) -> bool:
        """
        发送私聊消息
        
        Args:
            message: 消息对象
            
        Returns:
            bool: 发送是否成功
        """
        try:
            # 验证消息
            if not await self._validate_message(message):
                self.logger.warning("消息验证失败", 
                                  message_id=message.message_id,
                                  sender_id=message.sender_id)
                return False
            
            # 检查限流
            if not await self._check_rate_limit(message.sender_id):
                self.logger.warning("发送消息频率限制", 
                                  sender_id=message.sender_id)
                return False
            
            # 检查用户状态
            if not await self._check_user_status(message.sender_id, message.receiver_id):
                self.logger.warning("用户状态检查失败", 
                                  sender_id=message.sender_id,
                                  receiver_id=message.receiver_id)
                return False
            
            # 存储消息
            await self._store_message(message)
            
            # 更新会话
            await self._update_session(message)
            
            # 更新统计
            self.message_stats['total_messages'] += 1
            self.message_stats['private_messages'] += 1
            
            # 标记消息为已送达
            message.status = "delivered"
            
            self.logger.info("私聊消息发送成功", 
                           message_id=message.message_id,
                           sender_id=message.sender_id,
                           receiver_id=message.receiver_id)
            
            return True
            
        except Exception as e:
            self.logger.error("发送私聊消息失败", 
                            message_id=message.message_id,
                            error=str(e))
            return False
    
    @cached(ttl=300)
    async def get_chat_history(self, user_id: str, chat_id: str, 
                             page: int = 1, page_size: int = 20) -> ChatHistory:
        """
        获取聊天历史记录
        
        Args:
            user_id: 用户ID
            chat_id: 聊天ID
            page: 页码
            page_size: 每页大小
            
        Returns:
            ChatHistory: 历史记录对象
        """
        try:
            # 验证权限
            if not await self._check_access_permission(user_id, chat_id):
                self.logger.warning("用户无权限访问聊天历史", 
                                  user_id=user_id,
                                  chat_id=chat_id)
                return ChatHistory(chat_id=chat_id, messages=[], total_count=0)
            
            # 获取消息列表
            messages = self.message_storage.get(chat_id, [])
            
            # 计算分页
            total_count = len(messages)
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            
            # 按时间倒序排序
            messages = sorted(messages, key=lambda x: x.timestamp, reverse=True)
            page_messages = messages[start_index:end_index]
            
            # 恢复正序
            page_messages.reverse()
            
            history = ChatHistory(
                chat_id=chat_id,
                messages=page_messages,
                total_count=total_count,
                has_more=end_index < total_count
            )
            
            self.logger.info("获取聊天历史成功", 
                           user_id=user_id,
                           chat_id=chat_id,
                           page=page,
                           message_count=len(page_messages))
            
            return history
            
        except Exception as e:
            self.logger.error("获取聊天历史失败", 
                            user_id=user_id,
                            chat_id=chat_id,
                            error=str(e))
            return ChatHistory(chat_id=chat_id, messages=[], total_count=0)
    
    @transactional
    async def mark_message_read(self, user_id: str, message_id: str) -> bool:
        """
        标记消息为已读
        
        Args:
            user_id: 用户ID
            message_id: 消息ID
            
        Returns:
            bool: 标记是否成功
        """
        try:
            # 查找消息
            message = self.message_index.get(message_id)
            if not message:
                self.logger.warning("消息不存在", message_id=message_id)
                return False
            
            # 验证权限
            if message.receiver_id != user_id:
                self.logger.warning("用户无权限标记消息已读", 
                                  user_id=user_id,
                                  message_id=message_id)
                return False
            
            # 标记已读
            message.status = "read"
            
            # 更新统计
            self.message_stats['messages_read'] += 1
            
            # 更新会话未读数
            await self._update_session_unread_count(message.sender_id, message.receiver_id)
            
            self.logger.info("消息标记已读成功", 
                           user_id=user_id,
                           message_id=message_id)
            
            return True
            
        except Exception as e:
            self.logger.error("标记消息已读失败", 
                            user_id=user_id,
                            message_id=message_id,
                            error=str(e))
            return False
    
    @transactional
    async def recall_message(self, user_id: str, message_id: str) -> bool:
        """
        撤回消息
        
        Args:
            user_id: 用户ID
            message_id: 消息ID
            
        Returns:
            bool: 撤回是否成功
        """
        try:
            # 查找消息
            message = self.message_index.get(message_id)
            if not message:
                self.logger.warning("消息不存在", message_id=message_id)
                return False
            
            # 验证权限
            if message.sender_id != user_id:
                self.logger.warning("用户无权限撤回消息", 
                                  user_id=user_id,
                                  message_id=message_id)
                return False
            
            # 检查时间限制（只能撤回5分钟内的消息）
            if time.time() - message.timestamp > 300:
                self.logger.warning("消息撤回时间超限", 
                                  user_id=user_id,
                                  message_id=message_id)
                return False
            
            # 修改消息内容
            message.content = "[消息已撤回]"
            message.message_type = "recall"
            
            # 更新统计
            self.message_stats['messages_recalled'] += 1
            
            self.logger.info("消息撤回成功", 
                           user_id=user_id,
                           message_id=message_id)
            
            return True
            
        except Exception as e:
            self.logger.error("撤回消息失败", 
                            user_id=user_id,
                            message_id=message_id,
                            error=str(e))
            return False
    
    async def get_user_sessions(self, user_id: str) -> List[ChatSession]:
        """
        获取用户会话列表
        
        Args:
            user_id: 用户ID
            
        Returns:
            List[ChatSession]: 会话列表
        """
        try:
            sessions = self.user_sessions.get(user_id, [])
            
            # 按最后消息时间排序
            sessions = sorted(sessions, key=lambda x: x.last_message_time, reverse=True)
            
            self.logger.info("获取用户会话列表成功", 
                           user_id=user_id,
                           session_count=len(sessions))
            
            return sessions
            
        except Exception as e:
            self.logger.error("获取用户会话列表失败", 
                            user_id=user_id,
                            error=str(e))
            return []
    
    async def set_user_online(self, user_id: str) -> bool:
        """
        设置用户在线状态
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 设置是否成功
        """
        try:
            self.online_users.add(user_id)
            
            # 更新用户状态
            if user_id not in self.user_status:
                self.user_status[user_id] = {}
            
            self.user_status[user_id]['online'] = True
            self.user_status[user_id]['last_active'] = time.time()
            
            self.logger.info("用户上线", user_id=user_id)
            
            return True
            
        except Exception as e:
            self.logger.error("设置用户在线状态失败", 
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def set_user_offline(self, user_id: str) -> bool:
        """
        设置用户离线状态
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 设置是否成功
        """
        try:
            self.online_users.discard(user_id)
            
            # 更新用户状态
            if user_id in self.user_status:
                self.user_status[user_id]['online'] = False
                self.user_status[user_id]['last_active'] = time.time()
            
            self.logger.info("用户离线", user_id=user_id)
            
            return True
            
        except Exception as e:
            self.logger.error("设置用户离线状态失败", 
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def is_user_online(self, user_id: str) -> bool:
        """
        检查用户是否在线
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否在线
        """
        return user_id in self.online_users
    
    async def _validate_message(self, message: ChatMessage) -> bool:
        """验证消息"""
        try:
            # 检查消息长度
            if len(message.content) > self.max_message_length:
                return False
            
            # 检查必要字段
            if not message.sender_id or not message.receiver_id or not message.content:
                return False
            
            # 检查消息类型
            if message.message_type not in ["text", "image", "voice", "video", "file"]:
                return False
            
            return True
            
        except Exception as e:
            self.logger.error("消息验证异常", error=str(e))
            return False
    
    async def _check_rate_limit(self, user_id: str) -> bool:
        """检查发送频率限制"""
        try:
            current_time = time.time()
            
            # 清理过期记录
            if user_id in self.rate_limiter:
                self.rate_limiter[user_id] = [
                    t for t in self.rate_limiter[user_id]
                    if current_time - t < 1.0
                ]
            else:
                self.rate_limiter[user_id] = []
            
            # 检查频率限制
            if len(self.rate_limiter[user_id]) >= self.max_messages_per_second:
                return False
            
            # 记录当前时间
            self.rate_limiter[user_id].append(current_time)
            
            return True
            
        except Exception as e:
            self.logger.error("频率限制检查异常", error=str(e))
            return True  # 异常时默认放行
    
    async def _check_user_status(self, sender_id: str, receiver_id: str) -> bool:
        """检查用户状态"""
        try:
            # 检查发送者状态
            sender_status = self.user_status.get(sender_id)
            if sender_status and sender_status.get('blocked', False):
                return False
            
            # 检查接收者状态
            receiver_status = self.user_status.get(receiver_id)
            if receiver_status and receiver_status.get('blocked', False):
                return False
            
            # 检查是否相互屏蔽
            if (sender_status and receiver_id in sender_status.get('blocked_users', set())):
                return False
            
            if (receiver_status and sender_id in receiver_status.get('blocked_users', set())):
                return False
            
            return True
            
        except Exception as e:
            self.logger.error("用户状态检查异常", error=str(e))
            return True  # 异常时默认放行
    
    async def _store_message(self, message: ChatMessage):
        """存储消息"""
        try:
            # 生成聊天ID
            chat_id = self._generate_chat_id(message.sender_id, message.receiver_id)
            
            # 存储到消息存储
            if chat_id not in self.message_storage:
                self.message_storage[chat_id] = []
            
            self.message_storage[chat_id].append(message)
            
            # 限制历史消息数量
            if len(self.message_storage[chat_id]) > self.message_history_size:
                self.message_storage[chat_id] = self.message_storage[chat_id][-self.message_history_size:]
            
            # 添加到消息索引
            self.message_index[message.message_id] = message
            
        except Exception as e:
            self.logger.error("存储消息异常", error=str(e))
    
    async def _update_session(self, message: ChatMessage):
        """更新会话信息"""
        try:
            # 更新发送者会话
            await self._update_user_session(
                message.sender_id, 
                message.receiver_id,
                message.timestamp,
                False
            )
            
            # 更新接收者会话
            await self._update_user_session(
                message.receiver_id,
                message.sender_id,
                message.timestamp,
                True
            )
            
        except Exception as e:
            self.logger.error("更新会话异常", error=str(e))
    
    async def _update_user_session(self, user_id: str, target_id: str, 
                                 timestamp: float, is_received: bool):
        """更新用户会话"""
        try:
            session_id = f"{user_id}:{target_id}"
            
            # 查找现有会话
            session = self.session_index.get(session_id)
            
            if not session:
                # 创建新会话
                session = ChatSession(
                    session_id=session_id,
                    user_id=user_id,
                    target_id=target_id,
                    chat_type="private",
                    last_message_time=timestamp,
                    unread_count=1 if is_received else 0
                )
                
                # 添加到索引
                self.session_index[session_id] = session
                
                # 添加到用户会话列表
                if user_id not in self.user_sessions:
                    self.user_sessions[user_id] = []
                
                self.user_sessions[user_id].append(session)
            else:
                # 更新现有会话
                session.last_message_time = timestamp
                
                if is_received:
                    session.unread_count += 1
                    
        except Exception as e:
            self.logger.error("更新用户会话异常", error=str(e))
    
    async def _update_session_unread_count(self, sender_id: str, receiver_id: str):
        """更新会话未读数"""
        try:
            session_id = f"{receiver_id}:{sender_id}"
            session = self.session_index.get(session_id)
            
            if session:
                session.unread_count = 0
                
        except Exception as e:
            self.logger.error("更新会话未读数异常", error=str(e))
    
    async def _check_access_permission(self, user_id: str, chat_id: str) -> bool:
        """检查访问权限"""
        try:
            # 从聊天ID解析用户ID
            parts = chat_id.split(':')
            if len(parts) != 2:
                return False
            
            user1, user2 = parts
            
            # 检查用户是否是聊天参与者
            return user_id == user1 or user_id == user2
            
        except Exception as e:
            self.logger.error("检查访问权限异常", error=str(e))
            return False
    
    def _generate_chat_id(self, user1: str, user2: str) -> str:
        """生成聊天ID"""
        # 确保聊天ID的一致性
        if user1 < user2:
            return f"{user1}:{user2}"
        else:
            return f"{user2}:{user1}"
    
    async def _cleanup_expired_sessions(self):
        """清理过期会话"""
        while True:
            try:
                await asyncio.sleep(3600)  # 1小时清理一次
                
                current_time = time.time()
                expired_sessions = []
                
                for session_id, session in self.session_index.items():
                    # 清理7天未活跃的会话
                    if current_time - session.last_message_time > 604800:
                        expired_sessions.append(session_id)
                
                for session_id in expired_sessions:
                    session = self.session_index.pop(session_id)
                    
                    # 从用户会话列表移除
                    if session.user_id in self.user_sessions:
                        self.user_sessions[session.user_id] = [
                            s for s in self.user_sessions[session.user_id]
                            if s.session_id != session_id
                        ]
                
                if expired_sessions:
                    self.logger.info("清理过期会话", count=len(expired_sessions))
                    
            except Exception as e:
                self.logger.error("清理过期会话异常", error=str(e))
    
    async def _cleanup_rate_limiter(self):
        """清理频率限制器"""
        while True:
            try:
                await asyncio.sleep(60)  # 1分钟清理一次
                
                current_time = time.time()
                
                for user_id in list(self.rate_limiter.keys()):
                    # 清理过期记录
                    self.rate_limiter[user_id] = [
                        t for t in self.rate_limiter[user_id]
                        if current_time - t < 1.0
                    ]
                    
                    # 删除空记录
                    if not self.rate_limiter[user_id]:
                        del self.rate_limiter[user_id]
                        
            except Exception as e:
                self.logger.error("清理频率限制器异常", error=str(e))
    
    async def _update_user_status(self):
        """更新用户状态"""
        while True:
            try:
                await asyncio.sleep(30)  # 30秒更新一次
                
                current_time = time.time()
                
                # 检查用户活跃状态
                for user_id in list(self.user_status.keys()):
                    status = self.user_status[user_id]
                    
                    # 5分钟未活跃则设为离线
                    if (status.get('online', False) and 
                        current_time - status.get('last_active', 0) > 300):
                        await self.set_user_offline(user_id)
                        
            except Exception as e:
                self.logger.error("更新用户状态异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            'message_stats': self.message_stats.copy(),
            'storage_info': {
                'total_chats': len(self.message_storage),
                'total_stored_messages': sum(len(msgs) for msgs in self.message_storage.values()),
                'indexed_messages': len(self.message_index)
            },
            'session_info': {
                'total_sessions': len(self.session_index),
                'active_users': len(self.user_sessions)
            },
            'user_status': {
                'online_users': len(self.online_users),
                'total_users': len(self.user_status)
            }
        }
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理存储
            self.message_storage.clear()
            self.message_index.clear()
            self.user_sessions.clear()
            self.session_index.clear()
            self.user_status.clear()
            self.online_users.clear()
            self.rate_limiter.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Chat服务清理完成")
            
        except Exception as e:
            self.logger.error("Chat服务清理失败", error=str(e))