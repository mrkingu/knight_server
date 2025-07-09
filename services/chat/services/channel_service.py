"""
Channel业务服务

该模块实现了频道功能的业务服务层，继承自BaseService，
负责处理频道创建、管理、成员管理、消息发送、权限控制等核心业务逻辑。

主要功能：
- 频道创建和删除
- 频道成员管理（加入、离开、踢出、封禁）
- 频道消息发送和存储
- 频道权限管理（角色权限、操作权限）
- 频道设置管理
- 频道统计和分析
- 频道事件处理

技术特点：
- 使用异步处理提高性能
- 支持分布式事务处理
- 完善的缓存机制
- 详细的日志记录
- 支持大规模频道管理
- 高并发消息处理
"""

import asyncio
import time
import json
import uuid
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum

from services.base import BaseService, ServiceException, transactional, cached, retry
from common.logger import logger


class ChannelRole(Enum):
    """频道角色枚举"""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


@dataclass
class ChannelInfo:
    """频道信息数据结构"""
    channel_id: str
    name: str
    description: str
    owner_id: str
    member_count: int
    max_members: int
    created_time: float
    is_private: bool = False
    is_active: bool = True
    settings: Optional[Dict[str, Any]] = None


@dataclass
class ChannelMember:
    """频道成员数据结构"""
    user_id: str
    channel_id: str
    role: str = ChannelRole.MEMBER.value
    joined_time: float = 0.0
    is_muted: bool = False
    last_active_time: float = 0.0
    permissions: Optional[Set[str]] = None


@dataclass
class ChannelMessage:
    """频道消息数据结构"""
    message_id: str
    channel_id: str
    sender_id: str
    content: str
    message_type: str = "text"
    timestamp: float = 0.0
    reply_to: Optional[str] = None
    is_pinned: bool = False
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class ChannelSettings:
    """频道设置数据结构"""
    allow_member_invite: bool = True
    allow_member_message: bool = True
    message_rate_limit: int = 10
    auto_delete_messages: bool = False
    message_retention_days: int = 30


class ChannelService(BaseService):
    """
    Channel业务服务
    
    负责处理所有频道相关的业务逻辑，包括频道管理、成员管理、
    消息处理、权限控制等功能。
    """
    
    def __init__(self, max_channels: int = 1000,
                 max_channel_members: int = 1000,
                 default_channel_size: int = 100):
        """
        初始化Channel服务
        
        Args:
            max_channels: 最大频道数量
            max_channel_members: 频道最大成员数
            default_channel_size: 默认频道大小
        """
        super().__init__()
        
        self.max_channels = max_channels
        self.max_channel_members = max_channel_members
        self.default_channel_size = default_channel_size
        
        # 频道存储
        self.channels: Dict[str, ChannelInfo] = {}
        self.channel_members: Dict[str, List[ChannelMember]] = {}
        self.channel_messages: Dict[str, List[ChannelMessage]] = {}
        
        # 用户频道映射
        self.user_channels: Dict[str, Set[str]] = {}
        
        # 频道设置
        self.channel_settings: Dict[str, ChannelSettings] = {}
        
        # 频道统计
        self.channel_stats = {
            'total_channels': 0,
            'active_channels': 0,
            'total_members': 0,
            'total_messages': 0,
            'channels_created': 0,
            'channels_deleted': 0,
            'members_joined': 0,
            'members_left': 0
        }
        
        # 消息限流
        self.message_rate_limits: Dict[str, List[float]] = {}
        
        self.logger.info("Channel服务初始化完成",
                        max_channels=max_channels,
                        max_channel_members=max_channel_members,
                        default_channel_size=default_channel_size)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化基础服务
            await super().initialize()
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_messages())
            asyncio.create_task(self._cleanup_rate_limits())
            asyncio.create_task(self._update_channel_stats())
            
            self.logger.info("Channel服务初始化成功")
            
        except Exception as e:
            self.logger.error("Channel服务初始化失败", error=str(e))
            raise ServiceException(f"Channel服务初始化失败: {e}")
    
    @transactional
    async def create_channel(self, name: str, description: str, owner_id: str,
                           is_private: bool = False, max_members: int = None) -> Optional[str]:
        """
        创建频道
        
        Args:
            name: 频道名称
            description: 频道描述
            owner_id: 创建者ID
            is_private: 是否私有频道
            max_members: 最大成员数
            
        Returns:
            Optional[str]: 频道ID，创建失败返回None
        """
        try:
            # 检查频道数量限制
            if len(self.channels) >= self.max_channels:
                self.logger.warning("频道数量已达上限", 
                                  current_count=len(self.channels),
                                  max_channels=self.max_channels)
                return None
            
            # 检查用户创建的频道数量
            user_channel_count = sum(
                1 for channel in self.channels.values()
                if channel.owner_id == owner_id
            )
            if user_channel_count >= 10:  # 每个用户最多创建10个频道
                self.logger.warning("用户创建频道数量已达上限", 
                                  user_id=owner_id,
                                  channel_count=user_channel_count)
                return None
            
            # 生成频道ID
            channel_id = f"ch_{uuid.uuid4().hex[:12]}"
            
            # 创建频道信息
            channel_info = ChannelInfo(
                channel_id=channel_id,
                name=name,
                description=description,
                owner_id=owner_id,
                member_count=1,
                max_members=max_members or self.default_channel_size,
                created_time=time.time(),
                is_private=is_private,
                is_active=True
            )
            
            # 存储频道信息
            self.channels[channel_id] = channel_info
            
            # 创建频道成员列表
            self.channel_members[channel_id] = []
            
            # 创建频道消息列表
            self.channel_messages[channel_id] = []
            
            # 创建频道设置
            self.channel_settings[channel_id] = ChannelSettings()
            
            # 添加创建者为频道所有者
            await self._add_member_to_channel(channel_id, owner_id, ChannelRole.OWNER)
            
            # 更新统计
            self.channel_stats['total_channels'] += 1
            self.channel_stats['channels_created'] += 1
            
            self.logger.info("频道创建成功", 
                           channel_id=channel_id,
                           name=name,
                           owner_id=owner_id)
            
            return channel_id
            
        except Exception as e:
            self.logger.error("创建频道失败", 
                            name=name,
                            owner_id=owner_id,
                            error=str(e))
            return None
    
    @transactional
    async def join_channel(self, user_id: str, channel_id: str) -> bool:
        """
        加入频道
        
        Args:
            user_id: 用户ID
            channel_id: 频道ID
            
        Returns:
            bool: 加入是否成功
        """
        try:
            # 检查频道是否存在
            channel = self.channels.get(channel_id)
            if not channel:
                self.logger.warning("频道不存在", channel_id=channel_id)
                return False
            
            # 检查频道是否活跃
            if not channel.is_active:
                self.logger.warning("频道已停用", channel_id=channel_id)
                return False
            
            # 检查用户是否已在频道中
            if await self._is_member_in_channel(channel_id, user_id):
                self.logger.warning("用户已在频道中", 
                                  user_id=user_id,
                                  channel_id=channel_id)
                return False
            
            # 检查成员数量限制
            if channel.member_count >= channel.max_members:
                self.logger.warning("频道成员数量已达上限", 
                                  channel_id=channel_id,
                                  member_count=channel.member_count,
                                  max_members=channel.max_members)
                return False
            
            # 检查私有频道权限
            if channel.is_private:
                # 私有频道需要邀请才能加入
                # 这里简化处理，实际应该有邀请机制
                self.logger.warning("私有频道需要邀请才能加入", 
                                  channel_id=channel_id,
                                  user_id=user_id)
                return False
            
            # 添加成员到频道
            await self._add_member_to_channel(channel_id, user_id, ChannelRole.MEMBER)
            
            # 更新频道成员数量
            channel.member_count += 1
            
            # 更新统计
            self.channel_stats['total_members'] += 1
            self.channel_stats['members_joined'] += 1
            
            self.logger.info("用户加入频道成功", 
                           user_id=user_id,
                           channel_id=channel_id)
            
            return True
            
        except Exception as e:
            self.logger.error("用户加入频道失败", 
                            user_id=user_id,
                            channel_id=channel_id,
                            error=str(e))
            return False
    
    @transactional
    async def leave_channel(self, user_id: str, channel_id: str) -> bool:
        """
        离开频道
        
        Args:
            user_id: 用户ID
            channel_id: 频道ID
            
        Returns:
            bool: 离开是否成功
        """
        try:
            # 检查频道是否存在
            channel = self.channels.get(channel_id)
            if not channel:
                self.logger.warning("频道不存在", channel_id=channel_id)
                return False
            
            # 检查用户是否在频道中
            if not await self._is_member_in_channel(channel_id, user_id):
                self.logger.warning("用户不在频道中", 
                                  user_id=user_id,
                                  channel_id=channel_id)
                return False
            
            # 获取成员信息
            member = await self._get_member_info(channel_id, user_id)
            
            # 检查是否为频道所有者
            if member and member.role == ChannelRole.OWNER.value:
                # 所有者离开需要转让或删除频道
                await self._handle_owner_leave(channel_id, user_id)
            else:
                # 普通成员离开
                await self._remove_member_from_channel(channel_id, user_id)
            
            # 更新频道成员数量
            channel.member_count -= 1
            
            # 更新统计
            self.channel_stats['total_members'] -= 1
            self.channel_stats['members_left'] += 1
            
            self.logger.info("用户离开频道成功", 
                           user_id=user_id,
                           channel_id=channel_id)
            
            return True
            
        except Exception as e:
            self.logger.error("用户离开频道失败", 
                            user_id=user_id,
                            channel_id=channel_id,
                            error=str(e))
            return False
    
    @transactional
    async def send_message(self, message: ChannelMessage) -> bool:
        """
        发送频道消息
        
        Args:
            message: 消息对象
            
        Returns:
            bool: 发送是否成功
        """
        try:
            # 检查频道是否存在
            channel = self.channels.get(message.channel_id)
            if not channel:
                self.logger.warning("频道不存在", channel_id=message.channel_id)
                return False
            
            # 检查频道是否活跃
            if not channel.is_active:
                self.logger.warning("频道已停用", channel_id=message.channel_id)
                return False
            
            # 检查用户是否在频道中
            if not await self._is_member_in_channel(message.channel_id, message.sender_id):
                self.logger.warning("用户不在频道中", 
                                  user_id=message.sender_id,
                                  channel_id=message.channel_id)
                return False
            
            # 检查用户权限
            if not await self._check_message_permission(message.channel_id, message.sender_id):
                self.logger.warning("用户无发送消息权限", 
                                  user_id=message.sender_id,
                                  channel_id=message.channel_id)
                return False
            
            # 检查频率限制
            if not await self._check_message_rate_limit(message.channel_id, message.sender_id):
                self.logger.warning("消息发送频率超限", 
                                  user_id=message.sender_id,
                                  channel_id=message.channel_id)
                return False
            
            # 存储消息
            await self._store_channel_message(message)
            
            # 更新成员活跃时间
            await self._update_member_activity(message.channel_id, message.sender_id)
            
            # 更新统计
            self.channel_stats['total_messages'] += 1
            
            self.logger.info("频道消息发送成功", 
                           message_id=message.message_id,
                           channel_id=message.channel_id,
                           sender_id=message.sender_id)
            
            return True
            
        except Exception as e:
            self.logger.error("发送频道消息失败", 
                            message_id=message.message_id,
                            channel_id=message.channel_id,
                            error=str(e))
            return False
    
    @cached(ttl=300)
    async def get_channel_info(self, channel_id: str) -> Optional[ChannelInfo]:
        """
        获取频道信息
        
        Args:
            channel_id: 频道ID
            
        Returns:
            Optional[ChannelInfo]: 频道信息，不存在返回None
        """
        try:
            channel = self.channels.get(channel_id)
            
            if channel:
                self.logger.info("获取频道信息成功", 
                               channel_id=channel_id,
                               name=channel.name)
            else:
                self.logger.warning("频道不存在", channel_id=channel_id)
            
            return channel
            
        except Exception as e:
            self.logger.error("获取频道信息失败", 
                            channel_id=channel_id,
                            error=str(e))
            return None
    
    @cached(ttl=300)
    async def get_channel_members(self, channel_id: str, 
                                page: int = 1, page_size: int = 50) -> List[ChannelMember]:
        """
        获取频道成员列表
        
        Args:
            channel_id: 频道ID
            page: 页码
            page_size: 每页大小
            
        Returns:
            List[ChannelMember]: 成员列表
        """
        try:
            members = self.channel_members.get(channel_id, [])
            
            # 按角色和加入时间排序
            members = sorted(members, key=lambda x: (
                0 if x.role == ChannelRole.OWNER.value else
                1 if x.role == ChannelRole.ADMIN.value else 2,
                x.joined_time
            ))
            
            # 分页处理
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            page_members = members[start_index:end_index]
            
            self.logger.info("获取频道成员列表成功", 
                           channel_id=channel_id,
                           page=page,
                           member_count=len(page_members))
            
            return page_members
            
        except Exception as e:
            self.logger.error("获取频道成员列表失败", 
                            channel_id=channel_id,
                            error=str(e))
            return []
    
    @transactional
    async def delete_channel(self, channel_id: str, user_id: str) -> bool:
        """
        删除频道
        
        Args:
            channel_id: 频道ID
            user_id: 操作用户ID
            
        Returns:
            bool: 删除是否成功
        """
        try:
            # 检查频道是否存在
            channel = self.channels.get(channel_id)
            if not channel:
                self.logger.warning("频道不存在", channel_id=channel_id)
                return False
            
            # 检查权限（只有所有者可以删除频道）
            if channel.owner_id != user_id:
                self.logger.warning("用户无权限删除频道", 
                                  user_id=user_id,
                                  channel_id=channel_id)
                return False
            
            # 删除频道数据
            del self.channels[channel_id]
            
            # 删除成员数据
            if channel_id in self.channel_members:
                members = self.channel_members[channel_id]
                for member in members:
                    # 从用户频道映射中移除
                    if member.user_id in self.user_channels:
                        self.user_channels[member.user_id].discard(channel_id)
                
                del self.channel_members[channel_id]
            
            # 删除消息数据
            if channel_id in self.channel_messages:
                del self.channel_messages[channel_id]
            
            # 删除设置数据
            if channel_id in self.channel_settings:
                del self.channel_settings[channel_id]
            
            # 清理频率限制
            if channel_id in self.message_rate_limits:
                del self.message_rate_limits[channel_id]
            
            # 更新统计
            self.channel_stats['total_channels'] -= 1
            self.channel_stats['channels_deleted'] += 1
            self.channel_stats['total_members'] -= channel.member_count
            
            self.logger.info("频道删除成功", 
                           channel_id=channel_id,
                           user_id=user_id)
            
            return True
            
        except Exception as e:
            self.logger.error("删除频道失败", 
                            channel_id=channel_id,
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def _add_member_to_channel(self, channel_id: str, user_id: str, role: ChannelRole):
        """添加成员到频道"""
        try:
            member = ChannelMember(
                user_id=user_id,
                channel_id=channel_id,
                role=role.value,
                joined_time=time.time(),
                last_active_time=time.time()
            )
            
            # 添加到频道成员列表
            if channel_id not in self.channel_members:
                self.channel_members[channel_id] = []
            
            self.channel_members[channel_id].append(member)
            
            # 更新用户频道映射
            if user_id not in self.user_channels:
                self.user_channels[user_id] = set()
            
            self.user_channels[user_id].add(channel_id)
            
        except Exception as e:
            self.logger.error("添加成员到频道失败", error=str(e))
    
    async def _remove_member_from_channel(self, channel_id: str, user_id: str):
        """从频道移除成员"""
        try:
            # 从频道成员列表移除
            if channel_id in self.channel_members:
                self.channel_members[channel_id] = [
                    member for member in self.channel_members[channel_id]
                    if member.user_id != user_id
                ]
            
            # 从用户频道映射移除
            if user_id in self.user_channels:
                self.user_channels[user_id].discard(channel_id)
                
                if not self.user_channels[user_id]:
                    del self.user_channels[user_id]
            
        except Exception as e:
            self.logger.error("从频道移除成员失败", error=str(e))
    
    async def _is_member_in_channel(self, channel_id: str, user_id: str) -> bool:
        """检查用户是否在频道中"""
        try:
            members = self.channel_members.get(channel_id, [])
            return any(member.user_id == user_id for member in members)
        except Exception as e:
            self.logger.error("检查用户频道成员身份失败", error=str(e))
            return False
    
    async def _get_member_info(self, channel_id: str, user_id: str) -> Optional[ChannelMember]:
        """获取成员信息"""
        try:
            members = self.channel_members.get(channel_id, [])
            for member in members:
                if member.user_id == user_id:
                    return member
            return None
        except Exception as e:
            self.logger.error("获取成员信息失败", error=str(e))
            return None
    
    async def _check_message_permission(self, channel_id: str, user_id: str) -> bool:
        """检查消息发送权限"""
        try:
            member = await self._get_member_info(channel_id, user_id)
            if not member:
                return False
            
            # 检查是否被禁言
            if member.is_muted:
                return False
            
            # 检查频道设置
            settings = self.channel_settings.get(channel_id)
            if settings and not settings.allow_member_message:
                # 只有管理员和所有者可以发送消息
                return member.role in [ChannelRole.OWNER.value, ChannelRole.ADMIN.value]
            
            return True
            
        except Exception as e:
            self.logger.error("检查消息权限失败", error=str(e))
            return False
    
    async def _check_message_rate_limit(self, channel_id: str, user_id: str) -> bool:
        """检查消息发送频率限制"""
        try:
            current_time = time.time()
            rate_key = f"{channel_id}:{user_id}"
            
            # 获取频道设置
            settings = self.channel_settings.get(channel_id)
            rate_limit = settings.message_rate_limit if settings else 10
            
            # 清理过期记录
            if rate_key in self.message_rate_limits:
                self.message_rate_limits[rate_key] = [
                    t for t in self.message_rate_limits[rate_key]
                    if current_time - t < 60  # 1分钟内
                ]
            else:
                self.message_rate_limits[rate_key] = []
            
            # 检查频率限制
            if len(self.message_rate_limits[rate_key]) >= rate_limit:
                return False
            
            # 记录当前时间
            self.message_rate_limits[rate_key].append(current_time)
            
            return True
            
        except Exception as e:
            self.logger.error("检查消息频率限制失败", error=str(e))
            return True  # 异常时默认放行
    
    async def _store_channel_message(self, message: ChannelMessage):
        """存储频道消息"""
        try:
            if message.channel_id not in self.channel_messages:
                self.channel_messages[message.channel_id] = []
            
            self.channel_messages[message.channel_id].append(message)
            
            # 限制消息数量
            max_messages = 10000
            if len(self.channel_messages[message.channel_id]) > max_messages:
                self.channel_messages[message.channel_id] = \
                    self.channel_messages[message.channel_id][-max_messages:]
            
        except Exception as e:
            self.logger.error("存储频道消息失败", error=str(e))
    
    async def _update_member_activity(self, channel_id: str, user_id: str):
        """更新成员活跃时间"""
        try:
            member = await self._get_member_info(channel_id, user_id)
            if member:
                member.last_active_time = time.time()
                
        except Exception as e:
            self.logger.error("更新成员活跃时间失败", error=str(e))
    
    async def _handle_owner_leave(self, channel_id: str, owner_id: str):
        """处理所有者离开频道"""
        try:
            members = self.channel_members.get(channel_id, [])
            
            # 查找管理员
            admins = [m for m in members if m.role == ChannelRole.ADMIN.value]
            
            if admins:
                # 将第一个管理员提升为所有者
                new_owner = admins[0]
                new_owner.role = ChannelRole.OWNER.value
                
                # 更新频道所有者
                channel = self.channels.get(channel_id)
                if channel:
                    channel.owner_id = new_owner.user_id
                
                self.logger.info("频道所有者转让", 
                               channel_id=channel_id,
                               old_owner=owner_id,
                               new_owner=new_owner.user_id)
            else:
                # 没有管理员，删除频道
                await self.delete_channel(channel_id, owner_id)
                return
            
            # 移除原所有者
            await self._remove_member_from_channel(channel_id, owner_id)
            
        except Exception as e:
            self.logger.error("处理所有者离开频道失败", error=str(e))
    
    async def _cleanup_expired_messages(self):
        """清理过期消息"""
        while True:
            try:
                await asyncio.sleep(3600)  # 1小时清理一次
                
                current_time = time.time()
                
                for channel_id, messages in self.channel_messages.items():
                    settings = self.channel_settings.get(channel_id)
                    
                    if settings and settings.auto_delete_messages:
                        retention_seconds = settings.message_retention_days * 24 * 3600
                        
                        # 移除过期消息
                        valid_messages = [
                            msg for msg in messages
                            if current_time - msg.timestamp <= retention_seconds
                        ]
                        
                        if len(valid_messages) != len(messages):
                            self.channel_messages[channel_id] = valid_messages
                            
                            self.logger.info("清理过期消息", 
                                           channel_id=channel_id,
                                           removed_count=len(messages) - len(valid_messages))
                            
            except Exception as e:
                self.logger.error("清理过期消息异常", error=str(e))
    
    async def _cleanup_rate_limits(self):
        """清理频率限制记录"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                
                for rate_key in list(self.message_rate_limits.keys()):
                    # 清理过期记录
                    self.message_rate_limits[rate_key] = [
                        t for t in self.message_rate_limits[rate_key]
                        if current_time - t < 60
                    ]
                    
                    # 删除空记录
                    if not self.message_rate_limits[rate_key]:
                        del self.message_rate_limits[rate_key]
                        
            except Exception as e:
                self.logger.error("清理频率限制记录异常", error=str(e))
    
    async def _update_channel_stats(self):
        """更新频道统计信息"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟更新一次
                
                # 统计活跃频道
                current_time = time.time()
                active_count = 0
                
                for channel_id, messages in self.channel_messages.items():
                    # 5分钟内有消息的频道算作活跃
                    if messages and current_time - messages[-1].timestamp <= 300:
                        active_count += 1
                
                self.channel_stats['active_channels'] = active_count
                
            except Exception as e:
                self.logger.error("更新频道统计异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            'channel_stats': self.channel_stats.copy(),
            'storage_info': {
                'total_channels': len(self.channels),
                'total_members': sum(len(members) for members in self.channel_members.values()),
                'total_messages': sum(len(messages) for messages in self.channel_messages.values())
            },
            'user_info': {
                'users_with_channels': len(self.user_channels)
            }
        }
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理所有数据
            self.channels.clear()
            self.channel_members.clear()
            self.channel_messages.clear()
            self.user_channels.clear()
            self.channel_settings.clear()
            self.message_rate_limits.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Channel服务清理完成")
            
        except Exception as e:
            self.logger.error("Channel服务清理失败", error=str(e))