"""
Logic通知服务

该模块实现了Logic服务的通知功能，继承自BaseNotify，
负责向客户端推送各种游戏相关的通知消息。

主要功能：
- 用户状态变化通知
- 游戏房间状态通知
- 任务进度更新通知
- 物品变化通知
- 排行榜更新通知
- 系统公告通知

通知类型：
- 单播通知（发送给特定用户）
- 组播通知（发送给游戏房间内的玩家）
- 广播通知（发送给所有在线用户）
"""

import asyncio
import time
import json
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field
from enum import Enum
import uuid

from services.base import BaseNotify, NotifyConfig, NotifyMessage, NotifyTarget
from services.base import NotifyTask, NotifyStatistics, NotifyType, MessagePriority
from common.logger import logger

# 尝试导入协议模块
try:
    from common.proto import ProtoCodec
    PROTO_AVAILABLE = True
except ImportError:
    logger.warning("协议模块不可用，使用模拟模式")
    PROTO_AVAILABLE = False
    
    class ProtoCodec:
        @staticmethod
        def encode(data: dict) -> bytes:
            return json.dumps(data).encode('utf-8')


class LogicNotifyType(Enum):
    """Logic通知类型"""
    # 用户相关通知
    USER_STATUS_CHANGE = "user_status_change"
    USER_LEVEL_UP = "user_level_up"
    USER_FRIEND_ONLINE = "user_friend_online"
    
    # 游戏相关通知
    GAME_ROOM_INVITE = "game_room_invite"
    GAME_ROOM_PLAYER_JOIN = "game_room_player_join"
    GAME_ROOM_PLAYER_LEAVE = "game_room_player_leave"
    GAME_ROOM_STATE_CHANGE = "game_room_state_change"
    GAME_RESULT = "game_result"
    
    # 任务相关通知
    TASK_PROGRESS_UPDATE = "task_progress_update"
    TASK_COMPLETED = "task_completed"
    TASK_REWARD_AVAILABLE = "task_reward_available"
    TASK_REFRESH = "task_refresh"
    
    # 物品相关通知
    ITEM_RECEIVED = "item_received"
    ITEM_USED = "item_used"
    ITEM_EQUIPPED = "item_equipped"
    ITEM_TRADE_REQUEST = "item_trade_request"
    ITEM_SYNTHESIS_COMPLETE = "item_synthesis_complete"
    
    # 排行榜相关通知
    LEADERBOARD_RANK_CHANGE = "leaderboard_rank_change"
    LEADERBOARD_SEASON_END = "leaderboard_season_end"
    LEADERBOARD_REWARD = "leaderboard_reward"
    
    # 系统通知
    SYSTEM_ANNOUNCEMENT = "system_announcement"
    SYSTEM_MAINTENANCE = "system_maintenance"
    SYSTEM_UPDATE = "system_update"


@dataclass
class LogicNotifyConfig(NotifyConfig):
    """Logic通知服务配置"""
    # 通知队列配置
    max_queue_size: int = 10000
    batch_size: int = 100
    process_interval: float = 0.1  # 100ms
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # 消息过期配置
    message_expire_time: int = 3600  # 1小时
    
    # 用户通知限制
    max_user_notifications: int = 100
    notification_rate_limit: int = 10  # 每秒最多10条
    
    # 房间通知配置
    max_room_notifications: int = 1000
    
    # 系统通知配置
    enable_system_notifications: bool = True
    system_notification_ttl: int = 86400  # 24小时


class LogicNotifyService(BaseNotify):
    """Logic通知服务
    
    负责处理Logic服务相关的所有通知推送。
    """
    
    def __init__(self, config: Optional[LogicNotifyConfig] = None):
        """
        初始化Logic通知服务
        
        Args:
            config: 通知服务配置
        """
        super().__init__(config=config)
        
        self.logic_config = config or LogicNotifyConfig()
        
        # 用户连接管理
        self.user_connections: Dict[str, Set[str]] = {}  # user_id -> {connection_id}
        self.connection_users: Dict[str, str] = {}  # connection_id -> user_id
        
        # 游戏房间用户映射
        self.room_users: Dict[str, Set[str]] = {}  # room_id -> {user_id}
        self.user_rooms: Dict[str, str] = {}  # user_id -> room_id
        
        # 通知统计
        self.notification_stats = {
            "total_sent": 0,
            "total_failed": 0,
            "user_notifications": 0,
            "room_notifications": 0,
            "system_notifications": 0,
            "by_type": {}
        }
        
        # 用户通知限制
        self.user_notification_count: Dict[str, int] = {}
        self.user_notification_reset_time: Dict[str, float] = {}
        
        # 离线通知存储
        self.offline_notifications: Dict[str, List[Dict[str, Any]]] = {}
        
        self.logger.info("Logic通知服务初始化完成")
    
    async def initialize(self):
        """初始化通知服务"""
        try:
            await super().initialize()
            
            # 启动通知处理任务
            asyncio.create_task(self._process_notification_queue())
            asyncio.create_task(self._cleanup_expired_notifications())
            asyncio.create_task(self._reset_user_notification_limits())
            
            self.logger.info("Logic通知服务初始化完成")
            
        except Exception as e:
            self.logger.error("Logic通知服务初始化失败", error=str(e))
            raise
    
    async def register_user_connection(self, user_id: str, connection_id: str):
        """
        注册用户连接
        
        Args:
            user_id: 用户ID
            connection_id: 连接ID
        """
        try:
            # 添加用户连接
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            self.user_connections[user_id].add(connection_id)
            
            # 添加连接用户映射
            self.connection_users[connection_id] = user_id
            
            # 发送离线通知
            await self._send_offline_notifications(user_id, connection_id)
            
            self.logger.info("用户连接注册成功", 
                           user_id=user_id,
                           connection_id=connection_id)
            
        except Exception as e:
            self.logger.error("注册用户连接失败", error=str(e))
    
    async def unregister_user_connection(self, connection_id: str):
        """
        注销用户连接
        
        Args:
            connection_id: 连接ID
        """
        try:
            user_id = self.connection_users.get(connection_id)
            if user_id:
                # 移除连接
                if user_id in self.user_connections:
                    self.user_connections[user_id].discard(connection_id)
                    if not self.user_connections[user_id]:
                        del self.user_connections[user_id]
                
                # 移除连接用户映射
                del self.connection_users[connection_id]
                
                self.logger.info("用户连接注销成功", 
                               user_id=user_id,
                               connection_id=connection_id)
            
        except Exception as e:
            self.logger.error("注销用户连接失败", error=str(e))
    
    async def join_room(self, user_id: str, room_id: str):
        """
        用户加入房间
        
        Args:
            user_id: 用户ID
            room_id: 房间ID
        """
        try:
            # 添加房间用户映射
            if room_id not in self.room_users:
                self.room_users[room_id] = set()
            self.room_users[room_id].add(user_id)
            
            # 添加用户房间映射
            self.user_rooms[user_id] = room_id
            
            self.logger.info("用户加入房间成功", 
                           user_id=user_id,
                           room_id=room_id)
            
        except Exception as e:
            self.logger.error("用户加入房间失败", error=str(e))
    
    async def leave_room(self, user_id: str, room_id: str):
        """
        用户离开房间
        
        Args:
            user_id: 用户ID
            room_id: 房间ID
        """
        try:
            # 移除房间用户映射
            if room_id in self.room_users:
                self.room_users[room_id].discard(user_id)
                if not self.room_users[room_id]:
                    del self.room_users[room_id]
            
            # 移除用户房间映射
            if user_id in self.user_rooms:
                del self.user_rooms[user_id]
            
            self.logger.info("用户离开房间成功", 
                           user_id=user_id,
                           room_id=room_id)
            
        except Exception as e:
            self.logger.error("用户离开房间失败", error=str(e))
    
    async def notify_user_status_change(self, user_id: str, old_status: str, new_status: str):
        """
        通知用户状态变化
        
        Args:
            user_id: 用户ID
            old_status: 旧状态
            new_status: 新状态
        """
        try:
            notification = {
                "type": LogicNotifyType.USER_STATUS_CHANGE.value,
                "user_id": user_id,
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": time.time()
            }
            
            # 通知用户好友
            await self._notify_user_friends(user_id, notification)
            
            self.logger.info("用户状态变化通知发送成功", 
                           user_id=user_id,
                           old_status=old_status,
                           new_status=new_status)
            
        except Exception as e:
            self.logger.error("用户状态变化通知发送失败", error=str(e))
    
    async def notify_user_level_up(self, user_id: str, old_level: int, new_level: int):
        """
        通知用户升级
        
        Args:
            user_id: 用户ID
            old_level: 旧等级
            new_level: 新等级
        """
        try:
            notification = {
                "type": LogicNotifyType.USER_LEVEL_UP.value,
                "user_id": user_id,
                "old_level": old_level,
                "new_level": new_level,
                "timestamp": time.time()
            }
            
            # 通知用户本人
            await self._send_user_notification(user_id, notification, MessagePriority.HIGH)
            
            self.logger.info("用户升级通知发送成功", 
                           user_id=user_id,
                           old_level=old_level,
                           new_level=new_level)
            
        except Exception as e:
            self.logger.error("用户升级通知发送失败", error=str(e))
    
    async def notify_room_player_join(self, room_id: str, user_id: str, user_info: Dict[str, Any]):
        """
        通知房间玩家加入
        
        Args:
            room_id: 房间ID
            user_id: 用户ID
            user_info: 用户信息
        """
        try:
            notification = {
                "type": LogicNotifyType.GAME_ROOM_PLAYER_JOIN.value,
                "room_id": room_id,
                "user_id": user_id,
                "user_info": user_info,
                "timestamp": time.time()
            }
            
            # 通知房间内其他玩家
            await self._send_room_notification(room_id, notification, exclude_user=user_id)
            
            self.logger.info("房间玩家加入通知发送成功", 
                           room_id=room_id,
                           user_id=user_id)
            
        except Exception as e:
            self.logger.error("房间玩家加入通知发送失败", error=str(e))
    
    async def notify_room_player_leave(self, room_id: str, user_id: str, leave_reason: str):
        """
        通知房间玩家离开
        
        Args:
            room_id: 房间ID
            user_id: 用户ID
            leave_reason: 离开原因
        """
        try:
            notification = {
                "type": LogicNotifyType.GAME_ROOM_PLAYER_LEAVE.value,
                "room_id": room_id,
                "user_id": user_id,
                "leave_reason": leave_reason,
                "timestamp": time.time()
            }
            
            # 通知房间内其他玩家
            await self._send_room_notification(room_id, notification, exclude_user=user_id)
            
            self.logger.info("房间玩家离开通知发送成功", 
                           room_id=room_id,
                           user_id=user_id)
            
        except Exception as e:
            self.logger.error("房间玩家离开通知发送失败", error=str(e))
    
    async def notify_game_state_change(self, room_id: str, game_state: Dict[str, Any]):
        """
        通知游戏状态变化
        
        Args:
            room_id: 房间ID
            game_state: 游戏状态
        """
        try:
            notification = {
                "type": LogicNotifyType.GAME_ROOM_STATE_CHANGE.value,
                "room_id": room_id,
                "game_state": game_state,
                "timestamp": time.time()
            }
            
            # 通知房间内所有玩家
            await self._send_room_notification(room_id, notification)
            
            self.logger.info("游戏状态变化通知发送成功", room_id=room_id)
            
        except Exception as e:
            self.logger.error("游戏状态变化通知发送失败", error=str(e))
    
    async def notify_task_progress_update(self, user_id: str, task_id: str, progress: Dict[str, Any]):
        """
        通知任务进度更新
        
        Args:
            user_id: 用户ID
            task_id: 任务ID
            progress: 进度信息
        """
        try:
            notification = {
                "type": LogicNotifyType.TASK_PROGRESS_UPDATE.value,
                "user_id": user_id,
                "task_id": task_id,
                "progress": progress,
                "timestamp": time.time()
            }
            
            # 通知用户本人
            await self._send_user_notification(user_id, notification, MessagePriority.NORMAL)
            
            self.logger.info("任务进度更新通知发送成功", 
                           user_id=user_id,
                           task_id=task_id)
            
        except Exception as e:
            self.logger.error("任务进度更新通知发送失败", error=str(e))
    
    async def notify_task_completed(self, user_id: str, task_id: str, rewards: List[Dict[str, Any]]):
        """
        通知任务完成
        
        Args:
            user_id: 用户ID
            task_id: 任务ID
            rewards: 奖励信息
        """
        try:
            notification = {
                "type": LogicNotifyType.TASK_COMPLETED.value,
                "user_id": user_id,
                "task_id": task_id,
                "rewards": rewards,
                "timestamp": time.time()
            }
            
            # 通知用户本人
            await self._send_user_notification(user_id, notification, MessagePriority.HIGH)
            
            self.logger.info("任务完成通知发送成功", 
                           user_id=user_id,
                           task_id=task_id)
            
        except Exception as e:
            self.logger.error("任务完成通知发送失败", error=str(e))
    
    async def notify_item_received(self, user_id: str, items: List[Dict[str, Any]]):
        """
        通知物品获得
        
        Args:
            user_id: 用户ID
            items: 物品列表
        """
        try:
            notification = {
                "type": LogicNotifyType.ITEM_RECEIVED.value,
                "user_id": user_id,
                "items": items,
                "timestamp": time.time()
            }
            
            # 通知用户本人
            await self._send_user_notification(user_id, notification, MessagePriority.NORMAL)
            
            self.logger.info("物品获得通知发送成功", 
                           user_id=user_id,
                           item_count=len(items))
            
        except Exception as e:
            self.logger.error("物品获得通知发送失败", error=str(e))
    
    async def notify_item_trade_request(self, user_id: str, trade_id: str, from_user_id: str, trade_info: Dict[str, Any]):
        """
        通知物品交易请求
        
        Args:
            user_id: 用户ID
            trade_id: 交易ID
            from_user_id: 发起交易的用户ID
            trade_info: 交易信息
        """
        try:
            notification = {
                "type": LogicNotifyType.ITEM_TRADE_REQUEST.value,
                "user_id": user_id,
                "trade_id": trade_id,
                "from_user_id": from_user_id,
                "trade_info": trade_info,
                "timestamp": time.time()
            }
            
            # 通知目标用户
            await self._send_user_notification(user_id, notification, MessagePriority.HIGH)
            
            self.logger.info("物品交易请求通知发送成功", 
                           user_id=user_id,
                           trade_id=trade_id)
            
        except Exception as e:
            self.logger.error("物品交易请求通知发送失败", error=str(e))
    
    async def notify_leaderboard_rank_change(self, user_id: str, leaderboard_type: str, old_rank: int, new_rank: int):
        """
        通知排行榜排名变化
        
        Args:
            user_id: 用户ID
            leaderboard_type: 排行榜类型
            old_rank: 旧排名
            new_rank: 新排名
        """
        try:
            notification = {
                "type": LogicNotifyType.LEADERBOARD_RANK_CHANGE.value,
                "user_id": user_id,
                "leaderboard_type": leaderboard_type,
                "old_rank": old_rank,
                "new_rank": new_rank,
                "timestamp": time.time()
            }
            
            # 通知用户本人
            await self._send_user_notification(user_id, notification, MessagePriority.NORMAL)
            
            self.logger.info("排行榜排名变化通知发送成功", 
                           user_id=user_id,
                           leaderboard_type=leaderboard_type)
            
        except Exception as e:
            self.logger.error("排行榜排名变化通知发送失败", error=str(e))
    
    async def notify_system_announcement(self, title: str, content: str, target_users: Optional[List[str]] = None):
        """
        发送系统公告
        
        Args:
            title: 公告标题
            content: 公告内容
            target_users: 目标用户列表，如果为None则广播给所有用户
        """
        try:
            notification = {
                "type": LogicNotifyType.SYSTEM_ANNOUNCEMENT.value,
                "title": title,
                "content": content,
                "timestamp": time.time()
            }
            
            if target_users:
                # 发送给指定用户
                for user_id in target_users:
                    await self._send_user_notification(user_id, notification, MessagePriority.HIGH)
            else:
                # 广播给所有在线用户
                await self._broadcast_notification(notification)
            
            self.logger.info("系统公告发送成功", 
                           title=title,
                           target_count=len(target_users) if target_users else "all")
            
        except Exception as e:
            self.logger.error("系统公告发送失败", error=str(e))
    
    async def _send_user_notification(self, user_id: str, notification: Dict[str, Any], priority: MessagePriority = MessagePriority.NORMAL):
        """发送用户通知"""
        try:
            # 检查用户通知限制
            if await self._check_user_notification_limit(user_id):
                self.logger.warning("用户通知限制", user_id=user_id)
                return
            
            # 获取用户连接
            connections = self.user_connections.get(user_id, set())
            
            if connections:
                # 用户在线，直接发送
                for connection_id in connections:
                    await self._send_to_connection(connection_id, notification)
                
                # 更新统计
                self.notification_stats["user_notifications"] += 1
                self.notification_stats["total_sent"] += 1
                
                # 更新用户通知计数
                self.user_notification_count[user_id] = self.user_notification_count.get(user_id, 0) + 1
                
            else:
                # 用户离线，存储通知
                await self._store_offline_notification(user_id, notification)
            
            # 更新按类型统计
            notify_type = notification.get("type", "unknown")
            self.notification_stats["by_type"][notify_type] = self.notification_stats["by_type"].get(notify_type, 0) + 1
            
        except Exception as e:
            self.logger.error("发送用户通知失败", error=str(e))
            self.notification_stats["total_failed"] += 1
    
    async def _send_room_notification(self, room_id: str, notification: Dict[str, Any], exclude_user: Optional[str] = None):
        """发送房间通知"""
        try:
            users = self.room_users.get(room_id, set())
            
            sent_count = 0
            for user_id in users:
                if exclude_user and user_id == exclude_user:
                    continue
                
                await self._send_user_notification(user_id, notification, MessagePriority.NORMAL)
                sent_count += 1
            
            # 更新统计
            self.notification_stats["room_notifications"] += sent_count
            
        except Exception as e:
            self.logger.error("发送房间通知失败", error=str(e))
    
    async def _broadcast_notification(self, notification: Dict[str, Any]):
        """广播通知"""
        try:
            sent_count = 0
            for user_id in self.user_connections:
                await self._send_user_notification(user_id, notification, MessagePriority.NORMAL)
                sent_count += 1
            
            # 更新统计
            self.notification_stats["system_notifications"] += sent_count
            
        except Exception as e:
            self.logger.error("广播通知失败", error=str(e))
    
    async def _send_to_connection(self, connection_id: str, notification: Dict[str, Any]):
        """发送到连接"""
        try:
            # 编码通知消息
            if PROTO_AVAILABLE:
                message_data = ProtoCodec.encode(notification)
            else:
                message_data = json.dumps(notification).encode('utf-8')
            
            # 这里应该调用实际的连接发送方法
            # 现在只是记录日志
            self.logger.debug("发送通知到连接", 
                            connection_id=connection_id,
                            type=notification.get("type"))
            
        except Exception as e:
            self.logger.error("发送到连接失败", error=str(e))
            raise
    
    async def _store_offline_notification(self, user_id: str, notification: Dict[str, Any]):
        """存储离线通知"""
        try:
            if user_id not in self.offline_notifications:
                self.offline_notifications[user_id] = []
            
            # 添加过期时间
            notification["expire_time"] = time.time() + self.logic_config.message_expire_time
            
            self.offline_notifications[user_id].append(notification)
            
            # 限制离线通知数量
            if len(self.offline_notifications[user_id]) > self.logic_config.max_user_notifications:
                self.offline_notifications[user_id] = self.offline_notifications[user_id][-self.logic_config.max_user_notifications:]
            
        except Exception as e:
            self.logger.error("存储离线通知失败", error=str(e))
    
    async def _send_offline_notifications(self, user_id: str, connection_id: str):
        """发送离线通知"""
        try:
            notifications = self.offline_notifications.get(user_id, [])
            
            if not notifications:
                return
            
            current_time = time.time()
            valid_notifications = []
            
            # 过滤过期通知
            for notification in notifications:
                if current_time < notification.get("expire_time", 0):
                    valid_notifications.append(notification)
            
            # 发送有效通知
            for notification in valid_notifications:
                await self._send_to_connection(connection_id, notification)
            
            # 清理已发送的离线通知
            self.offline_notifications[user_id] = []
            
            if valid_notifications:
                self.logger.info("离线通知发送成功", 
                               user_id=user_id,
                               count=len(valid_notifications))
            
        except Exception as e:
            self.logger.error("发送离线通知失败", error=str(e))
    
    async def _check_user_notification_limit(self, user_id: str) -> bool:
        """检查用户通知限制"""
        try:
            current_time = time.time()
            
            # 检查是否需要重置计数
            reset_time = self.user_notification_reset_time.get(user_id, 0)
            if current_time >= reset_time:
                self.user_notification_count[user_id] = 0
                self.user_notification_reset_time[user_id] = current_time + 60  # 每分钟重置
                return False
            
            # 检查是否超过限制
            count = self.user_notification_count.get(user_id, 0)
            return count >= self.logic_config.notification_rate_limit
            
        except Exception as e:
            self.logger.error("检查用户通知限制失败", error=str(e))
            return False
    
    async def _notify_user_friends(self, user_id: str, notification: Dict[str, Any]):
        """通知用户好友"""
        try:
            # 这里应该获取用户好友列表
            # 现在只是占位符实现
            friends = []  # 从用户服务获取好友列表
            
            for friend_id in friends:
                await self._send_user_notification(friend_id, notification, MessagePriority.LOW)
            
        except Exception as e:
            self.logger.error("通知用户好友失败", error=str(e))
    
    async def _process_notification_queue(self):
        """处理通知队列"""
        while True:
            try:
                await asyncio.sleep(self.logic_config.process_interval)
                
                # 这里应该处理通知队列
                # 现在只是占位符实现
                
            except Exception as e:
                self.logger.error("处理通知队列异常", error=str(e))
                await asyncio.sleep(1)
    
    async def _cleanup_expired_notifications(self):
        """清理过期通知"""
        while True:
            try:
                await asyncio.sleep(3600)  # 每小时清理一次
                
                current_time = time.time()
                
                # 清理过期的离线通知
                for user_id, notifications in self.offline_notifications.items():
                    valid_notifications = [
                        notification for notification in notifications
                        if current_time < notification.get("expire_time", 0)
                    ]
                    self.offline_notifications[user_id] = valid_notifications
                
            except Exception as e:
                self.logger.error("清理过期通知异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _reset_user_notification_limits(self):
        """重置用户通知限制"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟重置一次
                
                current_time = time.time()
                
                # 重置过期的计数
                for user_id in list(self.user_notification_reset_time.keys()):
                    if current_time >= self.user_notification_reset_time[user_id]:
                        self.user_notification_count[user_id] = 0
                        del self.user_notification_reset_time[user_id]
                
            except Exception as e:
                self.logger.error("重置用户通知限制异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理通知服务资源"""
        try:
            await super().cleanup()
            
            # 清理连接信息
            self.user_connections.clear()
            self.connection_users.clear()
            
            # 清理房间信息
            self.room_users.clear()
            self.user_rooms.clear()
            
            # 清理离线通知
            self.offline_notifications.clear()
            
            # 清理限制信息
            self.user_notification_count.clear()
            self.user_notification_reset_time.clear()
            
            self.logger.info("Logic通知服务资源清理完成")
            
        except Exception as e:
            self.logger.error("Logic通知服务资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取通知统计信息"""
        return {
            **self.notification_stats,
            "service_name": self.__class__.__name__,
            "connected_users": len(self.user_connections),
            "active_rooms": len(self.room_users),
            "offline_notifications": sum(len(notifications) for notifications in self.offline_notifications.values()),
            "notification_limits": len(self.user_notification_count)
        }


def create_logic_notify_service(config: Optional[LogicNotifyConfig] = None) -> LogicNotifyService:
    """
    创建Logic通知服务实例
    
    Args:
        config: 通知服务配置
        
    Returns:
        LogicNotifyService实例
    """
    try:
        service = LogicNotifyService(config)
        logger.info("Logic通知服务创建成功")
        return service
        
    except Exception as e:
        logger.error("创建Logic通知服务失败", error=str(e))
        raise