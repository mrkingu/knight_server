"""
Fight通知服务

该模块实现了Fight服务的通知功能，继承自BaseNotify，
负责处理战斗相关的消息推送、通知管理、实时通信等功能。

主要功能：
- 战斗匹配通知
- 战斗状态更新通知
- 技能释放通知
- 战斗结果通知
- 战斗邀请通知
- 战斗事件推送
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


class FightNotifyType(Enum):
    """战斗通知类型枚举"""
    MATCH_FOUND = "match_found"              # 找到匹配
    MATCH_CANCELLED = "match_cancelled"      # 匹配取消
    BATTLE_STARTED = "battle_started"        # 战斗开始
    BATTLE_ENDED = "battle_ended"            # 战斗结束
    BATTLE_PAUSED = "battle_paused"          # 战斗暂停
    BATTLE_RESUMED = "battle_resumed"        # 战斗恢复
    PLAYER_JOINED = "player_joined"          # 玩家加入
    PLAYER_LEFT = "player_left"              # 玩家离开
    SKILL_CAST = "skill_cast"                # 技能释放
    DAMAGE_DEALT = "damage_dealt"            # 伤害造成
    HEALING_DONE = "healing_done"            # 治疗完成
    STATUS_EFFECT = "status_effect"          # 状态效果
    TURN_CHANGED = "turn_changed"            # 回合变更
    BATTLE_INVITE = "battle_invite"          # 战斗邀请
    ROOM_CREATED = "room_created"            # 房间创建
    ROOM_UPDATED = "room_updated"            # 房间更新
    TOURNAMENT_EVENT = "tournament_event"    # 锦标赛事件


@dataclass
class FightNotifyData:
    """战斗通知数据结构"""
    notify_type: FightNotifyType
    battle_id: Optional[str] = None
    match_id: Optional[str] = None
    user_id: Optional[str] = None
    target_id: Optional[str] = None
    skill_id: Optional[str] = None
    damage: int = 0
    healing: int = 0
    message: str = ""
    extra_data: Optional[Dict[str, Any]] = None
    timestamp: float = 0.0


class FightNotifyService(BaseNotify):
    """
    Fight通知服务
    
    负责处理Fight服务相关的所有通知功能，包括匹配通知、
    战斗状态通知、技能效果通知等。
    """
    
    def __init__(self):
        """初始化Fight通知服务"""
        super().__init__()
        
        # 在线用户连接管理
        self.online_connections: Dict[str, Set[str]] = {}  # user_id -> connection_ids
        self.connection_info: Dict[str, Dict[str, Any]] = {}  # connection_id -> info
        
        # 战斗房间订阅
        self.battle_subscriptions: Dict[str, Set[str]] = {}  # battle_id -> user_ids
        self.user_battles: Dict[str, str] = {}  # user_id -> battle_id
        
        # 匹配队列订阅
        self.match_subscriptions: Dict[str, Set[str]] = {}  # match_type -> user_ids
        
        # 消息队列
        self.message_queue: Dict[str, List[NotifyMessage]] = {}  # user_id -> messages
        self.priority_queue: List[NotifyMessage] = []  # 优先级队列
        
        # 推送统计
        self.push_stats = {
            'total_notifications': 0,
            'match_notifications': 0,
            'battle_notifications': 0,
            'skill_notifications': 0,
            'invite_notifications': 0,
            'online_pushes': 0,
            'offline_queued': 0,
            'failed_pushes': 0,
            'retry_pushes': 0
        }
        
        # 实时战斗状态
        self.battle_states: Dict[str, Dict[str, Any]] = {}  # battle_id -> state
        
        # 推送配置
        self.push_config = {
            'batch_size': 50,
            'retry_attempts': 3,
            'retry_delay': 1.0,
            'priority_threshold': 0.5,
            'compression_enabled': True
        }
        
        self.logger.info("Fight通知服务初始化完成")
    
    async def initialize(self):
        """初始化通知服务"""
        try:
            # 调用父类初始化
            await super().initialize()
            
            # 启动定时任务
            asyncio.create_task(self._process_message_queue())
            asyncio.create_task(self._process_priority_queue())
            asyncio.create_task(self._cleanup_expired_connections())
            asyncio.create_task(self._update_battle_states())
            
            self.logger.info("Fight通知服务初始化成功")
            
        except Exception as e:
            self.logger.error("Fight通知服务初始化失败", error=str(e))
            raise
    
    async def notify_match_found(self, match_id: str, participants: List[str],
                               match_type: str, confirmation_time: int = 30) -> bool:
        """
        推送匹配找到通知
        
        Args:
            match_id: 匹配ID
            participants: 参与者列表
            match_type: 匹配类型
            confirmation_time: 确认时间
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = FightNotifyData(
                notify_type=FightNotifyType.MATCH_FOUND,
                match_id=match_id,
                message=f"找到{match_type}匹配！",
                extra_data={
                    'participants': participants,
                    'match_type': match_type,
                    'confirmation_time': confirmation_time
                },
                timestamp=time.time()
            )
            
            # 批量发送通知
            success_count = 0
            
            for user_id in participants:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"match_{match_id}_{user_id}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=user_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.HIGH,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + confirmation_time
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['match_notifications'] += success_count
                
                self.logger.info("匹配找到通知推送完成", 
                               match_id=match_id,
                               participants=participants,
                               success_count=success_count)
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送匹配找到通知失败", 
                            match_id=match_id,
                            error=str(e))
            return False
    
    async def notify_battle_started(self, battle_id: str, participants: List[str],
                                  battle_settings: Dict[str, Any]) -> bool:
        """
        推送战斗开始通知
        
        Args:
            battle_id: 战斗ID
            participants: 参与者列表
            battle_settings: 战斗设置
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = FightNotifyData(
                notify_type=FightNotifyType.BATTLE_STARTED,
                battle_id=battle_id,
                message="战斗开始！",
                extra_data={
                    'participants': participants,
                    'settings': battle_settings
                },
                timestamp=time.time()
            )
            
            # 订阅战斗事件
            self.battle_subscriptions[battle_id] = set(participants)
            for user_id in participants:
                self.user_battles[user_id] = battle_id
            
            # 批量发送通知
            success_count = 0
            
            for user_id in participants:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"battle_start_{battle_id}_{user_id}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=user_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.HIGH,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + 300
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['battle_notifications'] += success_count
                
                self.logger.info("战斗开始通知推送完成", 
                               battle_id=battle_id,
                               participants=participants,
                               success_count=success_count)
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送战斗开始通知失败", 
                            battle_id=battle_id,
                            error=str(e))
            return False
    
    async def notify_skill_cast(self, battle_id: str, caster_id: str,
                              skill_id: str, target_id: str,
                              damage: int, healing: int,
                              effects: List[Dict[str, Any]]) -> bool:
        """
        推送技能释放通知
        
        Args:
            battle_id: 战斗ID
            caster_id: 释放者ID
            skill_id: 技能ID
            target_id: 目标ID
            damage: 伤害值
            healing: 治疗值
            effects: 效果列表
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = FightNotifyData(
                notify_type=FightNotifyType.SKILL_CAST,
                battle_id=battle_id,
                user_id=caster_id,
                target_id=target_id,
                skill_id=skill_id,
                damage=damage,
                healing=healing,
                message=f"释放技能 {skill_id}",
                extra_data={
                    'effects': effects
                },
                timestamp=time.time()
            )
            
            # 获取战斗订阅者
            subscribers = self.battle_subscriptions.get(battle_id, set())
            
            if not subscribers:
                self.logger.warning("战斗无订阅者", battle_id=battle_id)
                return False
            
            # 批量发送通知
            success_count = 0
            
            for user_id in subscribers:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"skill_{battle_id}_{caster_id}_{int(time.time() * 1000)}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=user_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.NORMAL,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + 60
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['skill_notifications'] += success_count
                
                self.logger.info("技能释放通知推送完成", 
                               battle_id=battle_id,
                               skill_id=skill_id,
                               caster_id=caster_id,
                               success_count=success_count)
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送技能释放通知失败", 
                            battle_id=battle_id,
                            skill_id=skill_id,
                            error=str(e))
            return False
    
    async def notify_battle_ended(self, battle_id: str, winner: Optional[str],
                                loser: Optional[str], result: Dict[str, Any]) -> bool:
        """
        推送战斗结束通知
        
        Args:
            battle_id: 战斗ID
            winner: 胜利者ID
            loser: 失败者ID
            result: 战斗结果
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = FightNotifyData(
                notify_type=FightNotifyType.BATTLE_ENDED,
                battle_id=battle_id,
                user_id=winner,
                message="战斗结束！",
                extra_data={
                    'winner': winner,
                    'loser': loser,
                    'result': result
                },
                timestamp=time.time()
            )
            
            # 获取战斗订阅者
            subscribers = self.battle_subscriptions.get(battle_id, set())
            
            if not subscribers:
                self.logger.warning("战斗无订阅者", battle_id=battle_id)
                return False
            
            # 批量发送通知
            success_count = 0
            
            for user_id in subscribers:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"battle_end_{battle_id}_{user_id}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=user_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.HIGH,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + 600
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            # 清理战斗订阅
            await self._cleanup_battle_subscription(battle_id)
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['battle_notifications'] += success_count
                
                self.logger.info("战斗结束通知推送完成", 
                               battle_id=battle_id,
                               winner=winner,
                               success_count=success_count)
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送战斗结束通知失败", 
                            battle_id=battle_id,
                            error=str(e))
            return False
    
    async def notify_battle_invite(self, from_user_id: str, to_user_id: str,
                                 room_id: str, room_name: str) -> bool:
        """
        推送战斗邀请通知
        
        Args:
            from_user_id: 邀请者ID
            to_user_id: 被邀请者ID
            room_id: 房间ID
            room_name: 房间名称
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = FightNotifyData(
                notify_type=FightNotifyType.BATTLE_INVITE,
                user_id=from_user_id,
                target_id=to_user_id,
                message=f"收到来自 {from_user_id} 的战斗邀请",
                extra_data={
                    'room_id': room_id,
                    'room_name': room_name,
                    'from_user': from_user_id
                },
                timestamp=time.time()
            )
            
            # 创建通知消息
            message = NotifyMessage(
                message_id=f"invite_{room_id}_{to_user_id}",
                target=NotifyTarget(
                    target_type="user",
                    target_id=to_user_id
                ),
                notify_type=NotifyType.REAL_TIME,
                priority=MessagePriority.HIGH,
                content=asdict(notify_data),
                created_time=time.time(),
                expire_time=time.time() + 300  # 5分钟过期
            )
            
            # 发送通知
            success = await self._send_notification(message)
            
            if success:
                self.push_stats['total_notifications'] += 1
                self.push_stats['invite_notifications'] += 1
                
                self.logger.info("战斗邀请通知推送成功", 
                               from_user_id=from_user_id,
                               to_user_id=to_user_id,
                               room_id=room_id)
            
            return success
            
        except Exception as e:
            self.logger.error("推送战斗邀请通知失败", 
                            from_user_id=from_user_id,
                            to_user_id=to_user_id,
                            error=str(e))
            return False
    
    async def notify_turn_changed(self, battle_id: str, current_player: str,
                                turn_number: int, turn_timeout: int) -> bool:
        """
        推送回合变更通知
        
        Args:
            battle_id: 战斗ID
            current_player: 当前玩家ID
            turn_number: 回合数
            turn_timeout: 回合超时时间
            
        Returns:
            bool: 推送是否成功
        """
        try:
            # 创建通知数据
            notify_data = FightNotifyData(
                notify_type=FightNotifyType.TURN_CHANGED,
                battle_id=battle_id,
                user_id=current_player,
                message=f"轮到 {current_player} 行动",
                extra_data={
                    'turn_number': turn_number,
                    'turn_timeout': turn_timeout,
                    'current_player': current_player
                },
                timestamp=time.time()
            )
            
            # 获取战斗订阅者
            subscribers = self.battle_subscriptions.get(battle_id, set())
            
            if not subscribers:
                self.logger.warning("战斗无订阅者", battle_id=battle_id)
                return False
            
            # 批量发送通知
            success_count = 0
            
            for user_id in subscribers:
                # 创建通知消息
                message = NotifyMessage(
                    message_id=f"turn_{battle_id}_{turn_number}_{user_id}",
                    target=NotifyTarget(
                        target_type="user",
                        target_id=user_id
                    ),
                    notify_type=NotifyType.REAL_TIME,
                    priority=MessagePriority.NORMAL,
                    content=asdict(notify_data),
                    created_time=time.time(),
                    expire_time=time.time() + turn_timeout
                )
                
                # 发送通知
                if await self._send_notification(message):
                    success_count += 1
            
            if success_count > 0:
                self.push_stats['total_notifications'] += success_count
                self.push_stats['battle_notifications'] += success_count
                
                self.logger.info("回合变更通知推送完成", 
                               battle_id=battle_id,
                               current_player=current_player,
                               turn_number=turn_number,
                               success_count=success_count)
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error("推送回合变更通知失败", 
                            battle_id=battle_id,
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
    
    async def subscribe_battle(self, battle_id: str, user_id: str) -> bool:
        """
        订阅战斗事件
        
        Args:
            battle_id: 战斗ID
            user_id: 用户ID
            
        Returns:
            bool: 订阅是否成功
        """
        try:
            if battle_id not in self.battle_subscriptions:
                self.battle_subscriptions[battle_id] = set()
            
            self.battle_subscriptions[battle_id].add(user_id)
            self.user_battles[user_id] = battle_id
            
            self.logger.info("战斗订阅成功", 
                           battle_id=battle_id,
                           user_id=user_id)
            
            return True
            
        except Exception as e:
            self.logger.error("战斗订阅失败", 
                            battle_id=battle_id,
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def unsubscribe_battle(self, battle_id: str, user_id: str) -> bool:
        """
        取消订阅战斗事件
        
        Args:
            battle_id: 战斗ID
            user_id: 用户ID
            
        Returns:
            bool: 取消订阅是否成功
        """
        try:
            if battle_id in self.battle_subscriptions:
                self.battle_subscriptions[battle_id].discard(user_id)
                
                if not self.battle_subscriptions[battle_id]:
                    del self.battle_subscriptions[battle_id]
            
            if user_id in self.user_battles:
                del self.user_battles[user_id]
            
            self.logger.info("取消战斗订阅成功", 
                           battle_id=battle_id,
                           user_id=user_id)
            
            return True
            
        except Exception as e:
            self.logger.error("取消战斗订阅失败", 
                            battle_id=battle_id,
                            user_id=user_id,
                            error=str(e))
            return False
    
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
                # 用户离线，加入消息队列
                await self._queue_message(user_id, message)
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
    
    async def _deliver_offline_messages(self, user_id: str):
        """投递离线消息"""
        try:
            if user_id not in self.message_queue:
                return
            
            messages = self.message_queue[user_id]
            
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
            
            # 清空消息队列
            del self.message_queue[user_id]
            
            if delivered_count > 0:
                self.logger.info("离线消息投递完成", 
                               user_id=user_id,
                               delivered_count=delivered_count,
                               total_messages=len(messages))
                
        except Exception as e:
            self.logger.error("投递离线消息失败", 
                            user_id=user_id,
                            error=str(e))
    
    async def _cleanup_battle_subscription(self, battle_id: str):
        """清理战斗订阅"""
        try:
            if battle_id in self.battle_subscriptions:
                subscribers = self.battle_subscriptions[battle_id]
                
                # 清理用户战斗映射
                for user_id in subscribers:
                    if user_id in self.user_battles:
                        del self.user_battles[user_id]
                
                # 删除战斗订阅
                del self.battle_subscriptions[battle_id]
                
                self.logger.info("战斗订阅清理完成", 
                               battle_id=battle_id,
                               subscriber_count=len(subscribers))
                
        except Exception as e:
            self.logger.error("清理战斗订阅失败", 
                            battle_id=battle_id,
                            error=str(e))
    
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
                        
                        # 移除已处理的消息
                        for message in processed_messages:
                            messages.remove(message)
                        
                        # 如果队列为空，删除队列
                        if not messages:
                            del self.message_queue[user_id]
                            
            except Exception as e:
                self.logger.error("处理消息队列异常", error=str(e))
    
    async def _process_priority_queue(self):
        """处理优先级队列"""
        while True:
            try:
                await asyncio.sleep(0.5)  # 0.5秒处理一次
                
                if not self.priority_queue:
                    continue
                
                # 处理高优先级消息
                processed_messages = []
                
                for message in self.priority_queue:
                    # 检查消息是否过期
                    if time.time() > message.expire_time:
                        processed_messages.append(message)
                        continue
                    
                    # 推送消息
                    if await self._send_notification(message):
                        processed_messages.append(message)
                
                # 移除已处理的消息
                for message in processed_messages:
                    self.priority_queue.remove(message)
                    
            except Exception as e:
                self.logger.error("处理优先级队列异常", error=str(e))
    
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
    
    async def _update_battle_states(self):
        """更新战斗状态"""
        while True:
            try:
                await asyncio.sleep(10)  # 10秒更新一次
                
                # 更新战斗状态信息
                for battle_id in self.battle_subscriptions:
                    # 这里应该从战斗服务获取实时状态
                    # 由于是模拟实现，暂时跳过
                    pass
                    
            except Exception as e:
                self.logger.error("更新战斗状态异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取通知服务统计信息"""
        return {
            'push_stats': self.push_stats.copy(),
            'connection_info': {
                'online_users': len(self.online_connections),
                'total_connections': len(self.connection_info),
                'queued_messages': sum(len(msgs) for msgs in self.message_queue.values()),
                'priority_messages': len(self.priority_queue)
            },
            'subscription_info': {
                'battle_subscriptions': len(self.battle_subscriptions),
                'active_battles': len(self.user_battles)
            }
        }
    
    async def cleanup(self):
        """清理通知服务资源"""
        try:
            # 清理所有数据
            self.online_connections.clear()
            self.connection_info.clear()
            self.battle_subscriptions.clear()
            self.user_battles.clear()
            self.match_subscriptions.clear()
            self.message_queue.clear()
            self.priority_queue.clear()
            self.battle_states.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Fight通知服务清理完成")
            
        except Exception as e:
            self.logger.error("Fight通知服务清理失败", error=str(e))