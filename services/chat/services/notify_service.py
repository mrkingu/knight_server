"""
Chat通知服务

该模块实现了Chat服务的通知功能，继承自BaseNotify，
负责处理聊天相关的消息推送、通知管理、实时通信等功能。

主要功能：
- 私聊消息推送
- 群聊消息推送
- 频道消息推送
- 系统消息推送
- 用户状态变更通知
- 消息状态更新通知
- 批量消息推送
- 推送统计和分析

技术特点：
- 支持多种推送方式（WebSocket、HTTP、gRPC）
- 消息队列管理
- 推送失败重试机制
- 消息优先级处理
- 实时连接管理
- 推送性能监控
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum

from services.base import BaseNotify, NotifyMessage, NotifyTarget, NotifyType, MessagePriority
from common.logger import logger


class ChatNotifyType(Enum):
    """聊天通知类型枚举"""
    PRIVATE_MESSAGE = "private_message"        # 私聊消息
    GROUP_MESSAGE = "group_message"            # 群聊消息
    CHANNEL_MESSAGE = "channel_message"        # 频道消息
    SYSTEM_MESSAGE = "system_message"          # 系统消息
    USER_ONLINE = "user_online"                # 用户上线
    USER_OFFLINE = "user_offline"              # 用户离线
    MESSAGE_READ = "message_read"              # 消息已读
    MESSAGE_RECALLED = "message_recalled"      # 消息撤回
    TYPING_STATUS = "typing_status"            # 输入状态
    FRIEND_REQUEST = "friend_request"          # 好友请求
    CHANNEL_INVITE = "channel_invite"          # 频道邀请


@dataclass
class ChatNotifyData:
    """聊天通知数据结构"""
    notify_type: ChatNotifyType
    sender_id: str
    receiver_id: str
    content: str
    message_id: Optional[str] = None
    channel_id: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None
    timestamp: float = 0.0


class ChatNotifyService(BaseNotify):
    """
    Chat通知服务
    
    负责处理Chat服务相关的所有通知功能，包括消息推送、
    状态通知、系统消息等。
    """
    
    def __init__(self):
        """初始化Chat通知服务"""
        super().__init__()
        
        # 在线用户连接管理
        self.online_connections: Dict[str, Set[str]] = {}  # user_id -> connection_ids
        self.connection_info: Dict[str, Dict[str, Any]] = {}  # connection_id -> info
        
        # 消息队列
        self.message_queue: Dict[str, List[NotifyMessage]] = {}  # user_id -> messages
        self.offline_messages: Dict[str, List[NotifyMessage]] = {}  # user_id -> messages
        
        # 推送统计
        self.push_stats = {
            'total_notifications': 0,
            'private_messages': 0,
            'group_messages': 0,
            'channel_messages': 0,
            'system_messages': 0,
            'online_pushes': 0,
            'offline_queued': 0,
            'failed_pushes': 0,
            'retry_pushes': 0
        }
        
        # 用户状态
        self.user_status: Dict[str, Dict[str, Any]] = {}
        
        # 消息过滤器
        self.message_filters: Dict[str, List[str]] = {}  # user_id -> blocked_users
        
        self.logger.info("Chat通知服务初始化完成")
    
    async def initialize(self):
        """初始化通知服务"""
        try:
            # 调用父类初始化
            await super().initialize()
            
            # 启动定时任务
            asyncio.create_task(self._process_message_queue())
            asyncio.create_task(self._cleanup_expired_connections())
            asyncio.create_task(self._retry_failed_messages())
            
            self.logger.info("Chat通知服务初始化成功")
            
        except Exception as e:
            self.logger.error("Chat通知服务初始化失败", error=str(e))
            raise
    
    async def notify_private_message(self, sender_id: str, receiver_id: str,
                                   message_id: str, content: str,
                                   message_type: str = "text") -> bool:
        """
        推送私聊消息通知
        
        Args:
            sender_id: 发送者ID
            receiver_id: 接收者ID
            message_id: 消息ID
            content: 消息内容
            message_type: 消息类型
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 检查消息过滤
            if await self._is_message_filtered(sender_id, receiver_id):
                self.logger.info("消息被过滤", 
                               sender_id=sender_id,
                               receiver_id=receiver_id)
                return True
            
            # 创建通知数据
            notify_data = ChatNotifyData(
                notify_type=ChatNotifyType.PRIVATE_MESSAGE,
                sender_id=sender_id,
                receiver_id=receiver_id,
                content=content,
                message_id=message_id,
                extra_data={'message_type': message_type},
                timestamp=time.time()
            )
            
            # 创建通知消息
            message = NotifyMessage(
                message_id=f"pm_{message_id}",
                target=NotifyTarget(
                    target_type="user",
                    target_id=receiver_id
                ),
                notify_type=NotifyType.REAL_TIME,
                priority=MessagePriority.HIGH,
                content=asdict(notify_data),
                created_time=time.time(),
                expire_time=time.time() + 3600  # 1小时过期
            )
            
            # 发送通知
            success = await self._send_notification(message)
            
            if success:
                self.push_stats['total_notifications'] += 1
                self.push_stats['private_messages'] += 1
                
                self.logger.info("私聊消息通知推送成功", 
                               sender_id=sender_id,
                               receiver_id=receiver_id,
                               message_id=message_id)
            else:
                self.push_stats['failed_pushes'] += 1
                self.logger.warning("私聊消息通知推送失败", 
                                  sender_id=sender_id,
                                  receiver_id=receiver_id,
                                  message_id=message_id)
            
            return success
            
        except Exception as e:
            self.logger.error("推送私聊消息通知失败", 
                            sender_id=sender_id,
                            receiver_id=receiver_id,
                            error=str(e))
            return False
    
    async def notify_channel_message(self, sender_id: str, channel_id: str,
                                   message_id: str, content: str,
                                   message_type: str = "text") -> bool:
        """
        推送频道消息通知
        
        Args:
            sender_id: 发送者ID
            channel_id: 频道ID
            message_id: 消息ID
            content: 消息内容
            message_type: 消息类型
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 获取频道成员列表
            channel_members = await self._get_channel_members(channel_id)
            
            if not channel_members:
                self.logger.warning("频道成员为空", channel_id=channel_id)
                return False
            
            # 创建通知数据
            notify_data = ChatNotifyData(
                notify_type=ChatNotifyType.CHANNEL_MESSAGE,
                sender_id=sender_id,
                receiver_id="",  # 频道消息没有特定接收者
                content=content,
                message_id=message_id,
                channel_id=channel_id,
                extra_data={'message_type': message_type},
                timestamp=time.time()
            )
            
            # 批量发送通知
            success_count = 0
            
            for member_id in channel_members:
                # 跳过发送者
                if member_id == sender_id:
                    continue
                
                # 检查消息过滤
                if await self._is_message_filtered(sender_id, member_id):
                    continue
                
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"cm_{message_id}_{member_id}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=member_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.NORMAL,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + 3600
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            total_members = len(channel_members) - 1  # 排除发送者
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['channel_messages'] += success_count
                
                self.logger.info("频道消息通知推送完成", 
                               sender_id=sender_id,
                               channel_id=channel_id,
                               message_id=message_id,
                               success_count=success_count,
                               total_members=total_members)
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送频道消息通知失败", 
                            sender_id=sender_id,
                            channel_id=channel_id,
                            error=str(e))
            return False
    
    async def notify_user_status(self, user_id: str, status: str, 
                               notify_friends: bool = True) -> bool:
        """
        推送用户状态变更通知
        
        Args:
            user_id: 用户ID
            status: 状态（online/offline）
            notify_friends: 是否通知好友
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 确定通知类型
            if status == "online":
                notify_type = ChatNotifyType.USER_ONLINE
            elif status == "offline":
                notify_type = ChatNotifyType.USER_OFFLINE
            else:
                self.logger.warning("未知用户状态", user_id=user_id, status=status)
                return False
            
            # 更新用户状态
            if user_id not in self.user_status:
                self.user_status[user_id] = {}
            
            self.user_status[user_id]['status'] = status
            self.user_status[user_id]['last_update'] = time.time()
            
            # 如果不通知好友，直接返回
            if not notify_friends:
                return True
            
            # 获取好友列表
            friends = await self._get_user_friends(user_id)
            
            if not friends:
                self.logger.info("用户无好友", user_id=user_id)
                return True
            
            # 创建通知数据
            notify_data = ChatNotifyData(
                notify_type=notify_type,
                sender_id=user_id,
                receiver_id="",
                content=f"用户{status}",
                extra_data={'status': status},
                timestamp=time.time()
            )
            
            # 批量发送通知
            success_count = 0
            
            for friend_id in friends:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"status_{user_id}_{friend_id}_{int(time.time())}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=friend_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.LOW,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + 300  # 5分钟过期
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                
                self.logger.info("用户状态通知推送完成", 
                               user_id=user_id,
                               status=status,
                               success_count=success_count,
                               total_friends=len(friends))
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送用户状态通知失败", 
                            user_id=user_id,
                            status=status,
                            error=str(e))
            return False
    
    async def notify_message_read(self, reader_id: str, message_id: str, 
                                sender_id: str) -> bool:
        """
        推送消息已读通知
        
        Args:
            reader_id: 阅读者ID
            message_id: 消息ID
            sender_id: 原发送者ID
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = ChatNotifyData(
                notify_type=ChatNotifyType.MESSAGE_READ,
                sender_id=reader_id,
                receiver_id=sender_id,
                content=f"消息已读",
                message_id=message_id,
                timestamp=time.time()
            )
            
            # 创建通知消息
            message = NotifyMessage(
                message_id=f"read_{message_id}",
                target=NotifyTarget(
                    target_type="user",
                    target_id=sender_id
                ),
                notify_type=NotifyType.REAL_TIME,
                priority=MessagePriority.LOW,
                content=asdict(notify_data),
                created_time=time.time(),
                expire_time=time.time() + 300
            )
            
            # 发送通知
            success = await self._send_notification(message)
            
            if success:
                self.push_stats['total_notifications'] += 1
                
                self.logger.info("消息已读通知推送成功", 
                               reader_id=reader_id,
                               message_id=message_id,
                               sender_id=sender_id)
            
            return success
            
        except Exception as e:
            self.logger.error("推送消息已读通知失败", 
                            reader_id=reader_id,
                            message_id=message_id,
                            error=str(e))
            return False
    
    async def notify_system_message(self, target_users: List[str], 
                                  content: str, message_type: str = "system") -> bool:
        """
        推送系统消息
        
        Args:
            target_users: 目标用户列表
            content: 消息内容
            message_type: 消息类型
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = ChatNotifyData(
                notify_type=ChatNotifyType.SYSTEM_MESSAGE,
                sender_id="system",
                receiver_id="",
                content=content,
                extra_data={'message_type': message_type},
                timestamp=time.time()
            )
            
            # 批量发送通知
            success_count = 0
            
            for user_id in target_users:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"sys_{user_id}_{int(time.time())}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=user_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.HIGH,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + 86400  # 24小时过期
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['system_messages'] += success_count
                
                self.logger.info("系统消息通知推送完成", 
                               content=content,
                               success_count=success_count,
                               total_users=len(target_users))
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送系统消息通知失败", 
                            content=content,
                            error=str(e))
            return False
    
    async def add_user_connection(self, user_id: str, connection_id: str, 
                                connection_type: str = "websocket") -> bool:
        """
        添加用户连接
        
        Args:
            user_id: 用户ID
            connection_id: 连接ID
            connection_type: 连接类型
            
        Returns:
            bool: 添加是否成功
        """
        try:
            # 添加到在线连接
            if user_id not in self.online_connections:
                self.online_connections[user_id] = set()
            
            self.online_connections[user_id].add(connection_id)
            
            # 记录连接信息
            self.connection_info[connection_id] = {
                'user_id': user_id,
                'connection_type': connection_type,
                'connected_time': time.time(),
                'last_activity': time.time()
            }
            
            # 处理离线消息
            await self._deliver_offline_messages(user_id)
            
            self.logger.info("用户连接添加成功", 
                           user_id=user_id,
                           connection_id=connection_id,
                           connection_type=connection_type)
            
            return True
            
        except Exception as e:
            self.logger.error("添加用户连接失败", 
                            user_id=user_id,
                            connection_id=connection_id,
                            error=str(e))
            return False
    
    async def remove_user_connection(self, user_id: str, connection_id: str) -> bool:
        """
        移除用户连接
        
        Args:
            user_id: 用户ID
            connection_id: 连接ID
            
        Returns:
            bool: 移除是否成功
        """
        try:
            # 从在线连接移除
            if user_id in self.online_connections:
                self.online_connections[user_id].discard(connection_id)
                
                # 如果用户没有其他连接，移除整个记录
                if not self.online_connections[user_id]:
                    del self.online_connections[user_id]
            
            # 移除连接信息
            if connection_id in self.connection_info:
                del self.connection_info[connection_id]
            
            self.logger.info("用户连接移除成功", 
                           user_id=user_id,
                           connection_id=connection_id)
            
            return True
            
        except Exception as e:
            self.logger.error("移除用户连接失败", 
                            user_id=user_id,
                            connection_id=connection_id,
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
        return user_id in self.online_connections and len(self.online_connections[user_id]) > 0
    
    async def _send_notification(self, message: NotifyMessage) -> bool:
        """发送通知消息"""
        try:
            user_id = message.target.target_id
            
            # 检查用户是否在线
            if await self.is_user_online(user_id):
                # 用户在线，直接推送
                success = await self._push_to_user(user_id, message)
                
                if success:
                    self.push_stats['online_pushes'] += 1
                else:
                    # 推送失败，加入队列
                    await self._queue_message(user_id, message)
                    self.push_stats['offline_queued'] += 1
                
                return success
            else:
                # 用户离线，加入离线消息队列
                await self._queue_offline_message(user_id, message)
                self.push_stats['offline_queued'] += 1
                return True
                
        except Exception as e:
            self.logger.error("发送通知消息失败", 
                            message_id=message.message_id,
                            error=str(e))
            return False
    
    async def _push_to_user(self, user_id: str, message: NotifyMessage) -> bool:
        """推送消息到用户"""
        try:
            connections = self.online_connections.get(user_id, set())
            
            if not connections:
                return False
            
            # 向所有连接推送消息
            success_count = 0
            
            for connection_id in connections:
                try:
                    # 这里应该根据连接类型推送消息
                    # 由于是模拟实现，直接标记为成功
                    await self._push_to_connection(connection_id, message)
                    success_count += 1
                    
                    # 更新连接活动时间
                    if connection_id in self.connection_info:
                        self.connection_info[connection_id]['last_activity'] = time.time()
                        
                except Exception as e:
                    self.logger.error("推送到连接失败", 
                                    connection_id=connection_id,
                                    error=str(e))
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送到用户失败", 
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def _push_to_connection(self, connection_id: str, message: NotifyMessage):
        """推送消息到特定连接"""
        try:
            connection_info = self.connection_info.get(connection_id)
            
            if not connection_info:
                raise Exception(f"连接信息不存在: {connection_id}")
            
            # 根据连接类型推送消息
            connection_type = connection_info['connection_type']
            
            if connection_type == "websocket":
                # WebSocket推送
                await self._push_websocket(connection_id, message)
            elif connection_type == "http":
                # HTTP推送
                await self._push_http(connection_id, message)
            elif connection_type == "grpc":
                # gRPC推送
                await self._push_grpc(connection_id, message)
            else:
                raise Exception(f"不支持的连接类型: {connection_type}")
                
        except Exception as e:
            self.logger.error("推送到连接失败", 
                            connection_id=connection_id,
                            error=str(e))
            raise
    
    async def _push_websocket(self, connection_id: str, message: NotifyMessage):
        """WebSocket推送"""
        # 模拟WebSocket推送
        self.logger.debug("WebSocket推送", 
                         connection_id=connection_id,
                         message_id=message.message_id)
    
    async def _push_http(self, connection_id: str, message: NotifyMessage):
        """HTTP推送"""
        # 模拟HTTP推送
        self.logger.debug("HTTP推送", 
                         connection_id=connection_id,
                         message_id=message.message_id)
    
    async def _push_grpc(self, connection_id: str, message: NotifyMessage):
        """gRPC推送"""
        # 模拟gRPC推送
        self.logger.debug("gRPC推送", 
                         connection_id=connection_id,
                         message_id=message.message_id)
    
    async def _queue_message(self, user_id: str, message: NotifyMessage):
        """将消息加入队列"""
        try:
            if user_id not in self.message_queue:
                self.message_queue[user_id] = []
            
            self.message_queue[user_id].append(message)
            
            # 限制队列长度
            if len(self.message_queue[user_id]) > 100:
                self.message_queue[user_id] = self.message_queue[user_id][-100:]
                
        except Exception as e:
            self.logger.error("消息入队失败", 
                            user_id=user_id,
                            error=str(e))
    
    async def _queue_offline_message(self, user_id: str, message: NotifyMessage):
        """将消息加入离线消息队列"""
        try:
            if user_id not in self.offline_messages:
                self.offline_messages[user_id] = []
            
            self.offline_messages[user_id].append(message)
            
            # 限制离线消息数量
            if len(self.offline_messages[user_id]) > 1000:
                self.offline_messages[user_id] = self.offline_messages[user_id][-1000:]
                
        except Exception as e:
            self.logger.error("离线消息入队失败", 
                            user_id=user_id,
                            error=str(e))
    
    async def _deliver_offline_messages(self, user_id: str):
        """投递离线消息"""
        try:
            if user_id not in self.offline_messages:
                return
            
            messages = self.offline_messages[user_id]
            
            if not messages:
                return
            
            # 投递离线消息
            delivered_count = 0
            
            for message in messages:
                # 检查消息是否过期
                if time.time() > message.expire_time:
                    continue
                
                # 推送消息
                if await self._push_to_user(user_id, message):
                    delivered_count += 1
            
            # 清空离线消息
            del self.offline_messages[user_id]
            
            if delivered_count > 0:
                self.logger.info("离线消息投递完成", 
                               user_id=user_id,
                               delivered_count=delivered_count,
                               total_messages=len(messages))
                
        except Exception as e:
            self.logger.error("投递离线消息失败", 
                            user_id=user_id,
                            error=str(e))
    
    async def _is_message_filtered(self, sender_id: str, receiver_id: str) -> bool:
        """检查消息是否被过滤"""
        try:
            # 检查接收者是否屏蔽了发送者
            blocked_users = self.message_filters.get(receiver_id, [])
            return sender_id in blocked_users
            
        except Exception as e:
            self.logger.error("检查消息过滤失败", error=str(e))
            return False
    
    async def _get_channel_members(self, channel_id: str) -> List[str]:
        """获取频道成员列表"""
        try:
            # 这里应该调用频道服务获取成员列表
            # 模拟返回一些成员
            return ["user1", "user2", "user3"]
            
        except Exception as e:
            self.logger.error("获取频道成员失败", 
                            channel_id=channel_id,
                            error=str(e))
            return []
    
    async def _get_user_friends(self, user_id: str) -> List[str]:
        """获取用户好友列表"""
        try:
            # 这里应该调用用户服务获取好友列表
            # 模拟返回一些好友
            return ["friend1", "friend2", "friend3"]
            
        except Exception as e:
            self.logger.error("获取用户好友失败", 
                            user_id=user_id,
                            error=str(e))
            return []
    
    async def _process_message_queue(self):
        """处理消息队列"""
        while True:
            try:
                await asyncio.sleep(1)  # 1秒处理一次
                
                for user_id, messages in list(self.message_queue.items()):
                    if not messages:
                        continue
                    
                    # 如果用户在线，尝试推送消息
                    if await self.is_user_online(user_id):
                        processed_messages = []
                        
                        for message in messages:
                            # 检查消息是否过期
                            if time.time() > message.expire_time:
                                processed_messages.append(message)
                                continue
                            
                            # 推送消息
                            if await self._push_to_user(user_id, message):
                                processed_messages.append(message)
                                self.push_stats['online_pushes'] += 1
                            else:
                                # 推送失败，转移到离线消息
                                await self._queue_offline_message(user_id, message)
                                processed_messages.append(message)
                        
                        # 移除已处理的消息
                        for message in processed_messages:
                            messages.remove(message)
                        
                        # 如果队列为空，删除队列
                        if not messages:
                            del self.message_queue[user_id]
                            
            except Exception as e:
                self.logger.error("处理消息队列异常", error=str(e))
    
    async def _cleanup_expired_connections(self):
        """清理过期连接"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                expired_connections = []
                
                for connection_id, info in self.connection_info.items():
                    # 10分钟未活跃的连接视为过期
                    if current_time - info['last_activity'] > 600:
                        expired_connections.append(connection_id)
                
                for connection_id in expired_connections:
                    user_id = self.connection_info[connection_id]['user_id']
                    await self.remove_user_connection(user_id, connection_id)
                
                if expired_connections:
                    self.logger.info("清理过期连接", count=len(expired_connections))
                    
            except Exception as e:
                self.logger.error("清理过期连接异常", error=str(e))
    
    async def _retry_failed_messages(self):
        """重试失败消息"""
        while True:
            try:
                await asyncio.sleep(30)  # 30秒重试一次
                
                # 这里可以实现失败消息的重试逻辑
                # 由于是模拟实现，暂时跳过
                
            except Exception as e:
                self.logger.error("重试失败消息异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取通知服务统计信息"""
        return {
            'push_stats': self.push_stats.copy(),
            'connection_info': {
                'online_users': len(self.online_connections),
                'total_connections': len(self.connection_info),
                'queued_messages': sum(len(msgs) for msgs in self.message_queue.values()),
                'offline_messages': sum(len(msgs) for msgs in self.offline_messages.values())
            },
            'user_info': {
                'total_users': len(self.user_status),
                'filtered_users': len(self.message_filters)
            }
        }
    
    async def cleanup(self):
        """清理通知服务资源"""
        try:
            # 清理所有数据
            self.online_connections.clear()
            self.connection_info.clear()
            self.message_queue.clear()
            self.offline_messages.clear()
            self.user_status.clear()
            self.message_filters.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Chat通知服务清理完成")
            
        except Exception as e:
            self.logger.error("Chat通知服务清理失败", error=str(e))