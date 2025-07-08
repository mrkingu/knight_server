"""
通知服务

该模块负责主动推送消息到客户端，支持各种类型的通知推送，
包括系统通知、游戏通知、聊天通知等。

主要功能：
- 主动推送消息到客户端
- 支持多种通知类型
- 批量推送支持
- 通知历史记录
- 通知模板管理
"""

import asyncio
import time
import json
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger
from common.db.redis_manager import get_redis_manager
from ..config import GatewayConfig
from ..websocket_manager import get_websocket_manager
from ..session_manager import get_session_manager


class NotificationType(Enum):
    """通知类型枚举"""
    SYSTEM = "system"        # 系统通知
    GAME = "game"           # 游戏通知
    CHAT = "chat"           # 聊天通知
    FRIEND = "friend"       # 好友通知
    ANNOUNCEMENT = "announcement"  # 公告通知
    MAINTENANCE = "maintenance"    # 维护通知


class NotificationPriority(Enum):
    """通知优先级枚举"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationMessage:
    """通知消息"""
    message_id: str
    notification_type: NotificationType
    priority: NotificationPriority
    title: str
    content: str
    target_users: Set[str] = field(default_factory=set)
    target_groups: Set[str] = field(default_factory=set)
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    expire_at: Optional[float] = None
    sent_count: int = 0
    read_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "message_id": self.message_id,
            "type": self.notification_type.value,
            "priority": self.priority.value,
            "title": self.title,
            "content": self.content,
            "data": self.data,
            "created_at": self.created_at,
            "expire_at": self.expire_at
        }
        
    def is_expired(self) -> bool:
        """检查是否过期"""
        if self.expire_at is None:
            return False
        return time.time() > self.expire_at


@dataclass
class NotificationTemplate:
    """通知模板"""
    template_id: str
    template_name: str
    notification_type: NotificationType
    title_template: str
    content_template: str
    default_data: Dict[str, Any] = field(default_factory=dict)
    
    def format_message(self, data: Dict[str, Any]) -> Dict[str, str]:
        """格式化消息"""
        merged_data = {**self.default_data, **data}
        
        try:
            title = self.title_template.format(**merged_data)
            content = self.content_template.format(**merged_data)
            return {"title": title, "content": content}
        except KeyError as e:
            logger.error("模板格式化失败", 
                        template_id=self.template_id,
                        error=str(e))
            return {"title": self.title_template, "content": self.content_template}


class NotifyService:
    """通知服务"""
    
    def __init__(self, config: GatewayConfig):
        """
        初始化通知服务
        
        Args:
            config: 网关配置
        """
        self.config = config
        self.websocket_manager = None
        self.session_manager = None
        self.redis_manager = None
        
        # 消息队列
        self.message_queue: asyncio.Queue = asyncio.Queue()
        self.processing_task: Optional[asyncio.Task] = None
        
        # 通知历史
        self.notification_history: Dict[str, NotificationMessage] = {}
        
        # 用户通知
        self.user_notifications: Dict[str, List[str]] = {}  # user_id -> [message_ids]
        
        # 通知模板
        self.notification_templates: Dict[str, NotificationTemplate] = {}
        
        # 统计信息
        self._total_sent = 0
        self._total_read = 0
        self._total_failed = 0
        
        logger.info("通知服务初始化完成")
        
    async def initialize(self):
        """初始化通知服务"""
        # 获取管理器实例
        self.websocket_manager = get_websocket_manager()
        self.session_manager = get_session_manager()
        self.redis_manager = get_redis_manager()
        
        # 初始化通知模板
        await self._init_notification_templates()
        
        logger.info("通知服务初始化完成")
        
    async def start(self):
        """启动通知服务"""
        # 启动消息处理任务
        self.processing_task = asyncio.create_task(self._process_message_queue())
        
        logger.info("通知服务启动完成")
        
    async def stop(self):
        """停止通知服务"""
        # 停止消息处理任务
        if self.processing_task:
            self.processing_task.cancel()
            
        logger.info("通知服务停止完成")
        
    async def send_notification(self, 
                              notification_type: NotificationType,
                              title: str,
                              content: str,
                              target_users: Optional[Set[str]] = None,
                              target_groups: Optional[Set[str]] = None,
                              data: Optional[Dict[str, Any]] = None,
                              priority: NotificationPriority = NotificationPriority.NORMAL,
                              expire_seconds: Optional[int] = None) -> str:
        """
        发送通知
        
        Args:
            notification_type: 通知类型
            title: 标题
            content: 内容
            target_users: 目标用户
            target_groups: 目标群组
            data: 附加数据
            priority: 优先级
            expire_seconds: 过期时间(秒)
            
        Returns:
            str: 消息ID
        """
        try:
            # 生成消息ID
            message_id = f"notify_{int(time.time() * 1000)}"
            
            # 计算过期时间
            expire_at = None
            if expire_seconds:
                expire_at = time.time() + expire_seconds
                
            # 创建通知消息
            notification = NotificationMessage(
                message_id=message_id,
                notification_type=notification_type,
                priority=priority,
                title=title,
                content=content,
                target_users=target_users or set(),
                target_groups=target_groups or set(),
                data=data or {},
                expire_at=expire_at
            )
            
            # 保存到历史记录
            self.notification_history[message_id] = notification
            
            # 添加到消息队列
            await self.message_queue.put(notification)
            
            logger.info("通知已加入队列", 
                       message_id=message_id,
                       notification_type=notification_type.value,
                       target_users=len(target_users or []),
                       target_groups=len(target_groups or []))
            
            return message_id
            
        except Exception as e:
            logger.error("发送通知失败", error=str(e))
            raise
            
    async def send_notification_by_template(self,
                                          template_id: str,
                                          template_data: Dict[str, Any],
                                          target_users: Optional[Set[str]] = None,
                                          target_groups: Optional[Set[str]] = None,
                                          priority: NotificationPriority = NotificationPriority.NORMAL,
                                          expire_seconds: Optional[int] = None) -> str:
        """
        使用模板发送通知
        
        Args:
            template_id: 模板ID
            template_data: 模板数据
            target_users: 目标用户
            target_groups: 目标群组
            priority: 优先级
            expire_seconds: 过期时间(秒)
            
        Returns:
            str: 消息ID
        """
        template = self.notification_templates.get(template_id)
        if not template:
            raise ValueError(f"通知模板不存在: {template_id}")
            
        # 格式化消息
        formatted_message = template.format_message(template_data)
        
        # 发送通知
        return await self.send_notification(
            notification_type=template.notification_type,
            title=formatted_message["title"],
            content=formatted_message["content"],
            target_users=target_users,
            target_groups=target_groups,
            data=template_data,
            priority=priority,
            expire_seconds=expire_seconds
        )
        
    async def send_system_notification(self,
                                     title: str,
                                     content: str,
                                     target_users: Optional[Set[str]] = None,
                                     data: Optional[Dict[str, Any]] = None) -> str:
        """
        发送系统通知
        
        Args:
            title: 标题
            content: 内容
            target_users: 目标用户，None表示全体用户
            data: 附加数据
            
        Returns:
            str: 消息ID
        """
        return await self.send_notification(
            notification_type=NotificationType.SYSTEM,
            title=title,
            content=content,
            target_users=target_users,
            data=data,
            priority=NotificationPriority.HIGH
        )
        
    async def send_game_notification(self,
                                   title: str,
                                   content: str,
                                   target_users: Set[str],
                                   data: Optional[Dict[str, Any]] = None) -> str:
        """
        发送游戏通知
        
        Args:
            title: 标题
            content: 内容
            target_users: 目标用户
            data: 附加数据
            
        Returns:
            str: 消息ID
        """
        return await self.send_notification(
            notification_type=NotificationType.GAME,
            title=title,
            content=content,
            target_users=target_users,
            data=data,
            priority=NotificationPriority.NORMAL
        )
        
    async def send_chat_notification(self,
                                   title: str,
                                   content: str,
                                   target_users: Set[str],
                                   data: Optional[Dict[str, Any]] = None) -> str:
        """
        发送聊天通知
        
        Args:
            title: 标题
            content: 内容
            target_users: 目标用户
            data: 附加数据
            
        Returns:
            str: 消息ID
        """
        return await self.send_notification(
            notification_type=NotificationType.CHAT,
            title=title,
            content=content,
            target_users=target_users,
            data=data,
            priority=NotificationPriority.NORMAL
        )
        
    async def broadcast_announcement(self,
                                   title: str,
                                   content: str,
                                   data: Optional[Dict[str, Any]] = None,
                                   expire_seconds: int = 3600) -> str:
        """
        广播公告
        
        Args:
            title: 标题
            content: 内容
            data: 附加数据
            expire_seconds: 过期时间(秒)
            
        Returns:
            str: 消息ID
        """
        return await self.send_notification(
            notification_type=NotificationType.ANNOUNCEMENT,
            title=title,
            content=content,
            data=data,
            priority=NotificationPriority.HIGH,
            expire_seconds=expire_seconds
        )
        
    async def get_user_notifications(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取用户通知
        
        Args:
            user_id: 用户ID
            limit: 限制数量
            
        Returns:
            List[Dict[str, Any]]: 通知列表
        """
        message_ids = self.user_notifications.get(user_id, [])
        notifications = []
        
        for message_id in message_ids[-limit:]:
            notification = self.notification_history.get(message_id)
            if notification and not notification.is_expired():
                notifications.append(notification.to_dict())
                
        return notifications
        
    async def mark_notification_read(self, user_id: str, message_id: str) -> bool:
        """
        标记通知已读
        
        Args:
            user_id: 用户ID
            message_id: 消息ID
            
        Returns:
            bool: 是否成功
        """
        try:
            notification = self.notification_history.get(message_id)
            if notification:
                notification.read_count += 1
                self._total_read += 1
                
                # 保存到Redis
                await self._save_notification_to_redis(notification)
                
                logger.info("通知已读", 
                           user_id=user_id,
                           message_id=message_id)
                
                return True
                
        except Exception as e:
            logger.error("标记通知已读失败", 
                        user_id=user_id,
                        message_id=message_id,
                        error=str(e))
            
        return False
        
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_sent": self._total_sent,
            "total_read": self._total_read,
            "total_failed": self._total_failed,
            "queue_size": self.message_queue.qsize(),
            "active_notifications": len(self.notification_history),
            "templates": len(self.notification_templates)
        }
        
    async def _process_message_queue(self):
        """处理消息队列"""
        while True:
            try:
                # 获取消息
                notification = await self.message_queue.get()
                
                # 检查是否过期
                if notification.is_expired():
                    logger.info("通知已过期，跳过发送", 
                               message_id=notification.message_id)
                    continue
                    
                # 处理通知
                await self._process_notification(notification)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("处理消息队列失败", error=str(e))
                
    async def _process_notification(self, notification: NotificationMessage):
        """
        处理单个通知
        
        Args:
            notification: 通知消息
        """
        try:
            # 获取目标用户
            target_users = set()
            
            # 添加指定用户
            target_users.update(notification.target_users)
            
            # 处理群组用户
            for group in notification.target_groups:
                group_users = await self._get_group_users(group)
                target_users.update(group_users)
                
            # 如果没有指定用户，发送给所有在线用户
            if not target_users:
                target_users = await self._get_online_users()
                
            # 发送通知
            success_count = 0
            failed_count = 0
            
            for user_id in target_users:
                try:
                    success = await self._send_notification_to_user(user_id, notification)
                    if success:
                        success_count += 1
                        
                        # 添加到用户通知列表
                        if user_id not in self.user_notifications:
                            self.user_notifications[user_id] = []
                        self.user_notifications[user_id].append(notification.message_id)
                        
                    else:
                        failed_count += 1
                        
                except Exception as e:
                    logger.error("发送通知给用户失败", 
                               user_id=user_id,
                               message_id=notification.message_id,
                               error=str(e))
                    failed_count += 1
                    
            # 更新统计
            notification.sent_count = success_count
            self._total_sent += success_count
            self._total_failed += failed_count
            
            # 保存到Redis
            await self._save_notification_to_redis(notification)
            
            logger.info("通知发送完成", 
                       message_id=notification.message_id,
                       success_count=success_count,
                       failed_count=failed_count)
            
        except Exception as e:
            logger.error("处理通知失败", 
                        message_id=notification.message_id,
                        error=str(e))
            
    async def _send_notification_to_user(self, user_id: str, notification: NotificationMessage) -> bool:
        """
        发送通知给用户
        
        Args:
            user_id: 用户ID
            notification: 通知消息
            
        Returns:
            bool: 是否成功
        """
        try:
            # 构造通知消息
            message = {
                "type": "notification",
                "notification": notification.to_dict()
            }
            
            # 发送给用户的所有连接
            sent_count = await self.websocket_manager.send_to_user(user_id, message)
            
            return sent_count > 0
            
        except Exception as e:
            logger.error("发送通知给用户失败", 
                        user_id=user_id,
                        error=str(e))
            return False
            
    async def _get_group_users(self, group: str) -> Set[str]:
        """
        获取群组用户
        
        Args:
            group: 群组名称
            
        Returns:
            Set[str]: 用户ID集合
        """
        # 这里应该从数据库或缓存中获取群组用户
        # 暂时返回空集合
        return set()
        
    async def _get_online_users(self) -> Set[str]:
        """
        获取在线用户
        
        Returns:
            Set[str]: 在线用户ID集合
        """
        online_users = set()
        
        # 从WebSocket管理器获取在线用户
        stats = self.websocket_manager.get_statistics()
        
        # 遍历所有连接获取用户ID
        for connection_id, connection_info in self.websocket_manager._connections.items():
            if connection_info.user_id:
                online_users.add(connection_info.user_id)
                
        return online_users
        
    async def _init_notification_templates(self):
        """初始化通知模板"""
        templates = [
            NotificationTemplate(
                template_id="user_login",
                template_name="用户登录通知",
                notification_type=NotificationType.SYSTEM,
                title_template="欢迎 {username}",
                content_template="欢迎您登录游戏系统！"
            ),
            NotificationTemplate(
                template_id="game_start",
                template_name="游戏开始通知",
                notification_type=NotificationType.GAME,
                title_template="游戏开始",
                content_template="房间 {room_name} 的游戏即将开始！"
            ),
            NotificationTemplate(
                template_id="new_message",
                template_name="新消息通知",
                notification_type=NotificationType.CHAT,
                title_template="新消息",
                content_template="{sender} 发送了一条新消息"
            ),
            NotificationTemplate(
                template_id="system_maintenance",
                template_name="系统维护通知",
                notification_type=NotificationType.MAINTENANCE,
                title_template="系统维护通知",
                content_template="系统将在 {maintenance_time} 进行维护，预计持续 {duration} 分钟"
            )
        ]
        
        for template in templates:
            self.notification_templates[template.template_id] = template
            
    async def _save_notification_to_redis(self, notification: NotificationMessage):
        """保存通知到Redis"""
        if not self.redis_manager:
            return
            
        try:
            key = f"notification:{notification.message_id}"
            data = json.dumps({
                "message_id": notification.message_id,
                "notification_type": notification.notification_type.value,
                "priority": notification.priority.value,
                "title": notification.title,
                "content": notification.content,
                "data": notification.data,
                "created_at": notification.created_at,
                "expire_at": notification.expire_at,
                "sent_count": notification.sent_count,
                "read_count": notification.read_count
            })
            
            # 设置过期时间
            expire_seconds = 86400  # 24小时
            if notification.expire_at:
                expire_seconds = int(notification.expire_at - time.time())
                
            if expire_seconds > 0:
                await self.redis_manager.set(key, data, expire=expire_seconds)
                
        except Exception as e:
            logger.error("保存通知到Redis失败", 
                        message_id=notification.message_id,
                        error=str(e))