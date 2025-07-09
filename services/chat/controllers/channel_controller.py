"""
Channel控制器

该模块实现了频道功能的控制器，继承自BaseController，
负责处理频道创建、管理、成员管理、频道消息等频道相关的业务逻辑。

主要功能：
- 频道创建和删除
- 频道成员管理（加入、离开、踢出）
- 频道消息发送和接收
- 频道权限管理
- 频道设置管理
- 频道统计信息

装饰器支持：
- @handler 绑定消息协议号到处理方法
- 参数自动验证和解析
- 响应消息自动构建

技术特点：
- 使用MVC架构模式
- 异步处理提高性能
- 完善的异常处理
- 详细的日志记录
- 支持权限验证
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass
from datetime import datetime

from services.base import BaseController, ControllerException, ValidationException
from common.logger import logger
from common.decorator.handler_decorator import handler, controller


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


@dataclass
class ChannelMember:
    """频道成员数据结构"""
    user_id: str
    channel_id: str
    role: str = "member"  # owner, admin, member
    joined_time: float = 0.0
    is_muted: bool = False
    last_active_time: float = 0.0


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


@controller(name="ChannelController")
class ChannelController(BaseController):
    """
    Channel控制器
    
    负责处理所有频道相关的请求，包括频道管理、成员管理、消息发送等功能。
    与ChannelService和FilterService协作完成业务逻辑处理。
    """
    
    def __init__(self):
        """初始化Channel控制器"""
        super().__init__()
        
        # 服务依赖
        self.channel_service = None
        self.filter_service = None
        
        # 频道缓存
        self.channel_cache: Dict[str, ChannelInfo] = {}
        self.member_cache: Dict[str, List[ChannelMember]] = {}
        self.cache_ttl = 300  # 5分钟
        
        # 活跃频道追踪
        self.active_channels: Set[str] = set()
        
        # 统计信息
        self.channel_stats = {
            'total_channels': 0,
            'active_channels': 0,
            'total_members': 0,
            'total_messages': 0,
            'channels_created': 0,
            'channels_deleted': 0
        }
        
        self.logger.info("Channel控制器初始化完成")
    
    async def initialize(self):
        """初始化控制器"""
        try:
            # 获取服务依赖
            self.channel_service = self.get_service('channel_service')
            self.filter_service = self.get_service('filter_service')
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_cache())
            asyncio.create_task(self._update_channel_stats())
            
            self.logger.info("Channel控制器初始化成功")
            
        except Exception as e:
            self.logger.error("Channel控制器初始化失败", error=str(e))
            raise ControllerException(f"Channel控制器初始化失败: {e}")
    
    @handler(message_id=7001)
    async def create_channel(self, request, context):
        """
        创建频道
        
        Args:
            request: 包含name, description, owner_id, is_private, max_members的请求
            context: 请求上下文
            
        Returns:
            创建的频道信息
        """
        try:
            # 参数验证
            if not hasattr(request, 'name') or not request.name:
                raise ValidationException("频道名称不能为空")
            if not hasattr(request, 'owner_id') or not request.owner_id:
                raise ValidationException("频道创建者ID不能为空")
            
            # 内容过滤
            filtered_name = await self.filter_service.filter_content(
                request.name,
                request.owner_id
            )
            
            filtered_description = ""
            if hasattr(request, 'description') and request.description:
                filtered_description = await self.filter_service.filter_content(
                    request.description,
                    request.owner_id
                )
            
            # 创建频道
            channel_id = await self.channel_service.create_channel(
                name=filtered_name,
                description=filtered_description,
                owner_id=request.owner_id,
                is_private=getattr(request, 'is_private', False),
                max_members=getattr(request, 'max_members', 100)
            )
            
            if channel_id:
                self.channel_stats['channels_created'] += 1
                self.channel_stats['total_channels'] += 1
                
                # 创建频道信息
                channel_info = ChannelInfo(
                    channel_id=channel_id,
                    name=filtered_name,
                    description=filtered_description,
                    owner_id=request.owner_id,
                    member_count=1,
                    max_members=getattr(request, 'max_members', 100),
                    created_time=time.time(),
                    is_private=getattr(request, 'is_private', False)
                )
                
                # 更新缓存
                self.channel_cache[channel_id] = channel_info
                
                self.logger.info("频道创建成功", 
                               channel_id=channel_id,
                               name=filtered_name,
                               owner_id=request.owner_id)
                
                return {
                    'channel_id': channel_id,
                    'name': filtered_name,
                    'description': filtered_description,
                    'owner_id': request.owner_id,
                    'member_count': 1,
                    'max_members': getattr(request, 'max_members', 100),
                    'created_time': channel_info.created_time,
                    'is_private': getattr(request, 'is_private', False),
                    'status': 'success'
                }
            else:
                self.logger.error("频道创建失败", 
                                name=filtered_name,
                                owner_id=request.owner_id)
                
                return {
                    'status': 'failed',
                    'error': '频道创建失败'
                }
                
        except ValidationException as e:
            self.logger.warning("创建频道参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("创建频道异常", error=str(e))
            raise ControllerException(f"创建频道失败: {e}")
    
    @handler(message_id=7002)
    async def join_channel(self, request, context):
        """
        加入频道
        
        Args:
            request: 包含user_id, channel_id的请求
            context: 请求上下文
            
        Returns:
            加入结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'channel_id') or not request.channel_id:
                raise ValidationException("频道ID不能为空")
            
            # 加入频道
            success = await self.channel_service.join_channel(
                request.user_id,
                request.channel_id
            )
            
            if success:
                self.channel_stats['total_members'] += 1
                
                # 更新缓存
                await self._update_member_cache(request.channel_id, request.user_id)
                
                self.logger.info("用户加入频道成功", 
                               user_id=request.user_id,
                               channel_id=request.channel_id)
                
                return {
                    'status': 'success',
                    'channel_id': request.channel_id,
                    'user_id': request.user_id
                }
            else:
                self.logger.error("用户加入频道失败", 
                                user_id=request.user_id,
                                channel_id=request.channel_id)
                
                return {
                    'status': 'failed',
                    'error': '加入频道失败'
                }
                
        except ValidationException as e:
            self.logger.warning("加入频道参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("加入频道异常", error=str(e))
            raise ControllerException(f"加入频道失败: {e}")
    
    @handler(message_id=7003)
    async def leave_channel(self, request, context):
        """
        离开频道
        
        Args:
            request: 包含user_id, channel_id的请求
            context: 请求上下文
            
        Returns:
            离开结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'channel_id') or not request.channel_id:
                raise ValidationException("频道ID不能为空")
            
            # 离开频道
            success = await self.channel_service.leave_channel(
                request.user_id,
                request.channel_id
            )
            
            if success:
                self.channel_stats['total_members'] -= 1
                
                # 更新缓存
                await self._remove_member_cache(request.channel_id, request.user_id)
                
                self.logger.info("用户离开频道成功", 
                               user_id=request.user_id,
                               channel_id=request.channel_id)
                
                return {
                    'status': 'success',
                    'channel_id': request.channel_id,
                    'user_id': request.user_id
                }
            else:
                self.logger.error("用户离开频道失败", 
                                user_id=request.user_id,
                                channel_id=request.channel_id)
                
                return {
                    'status': 'failed',
                    'error': '离开频道失败'
                }
                
        except ValidationException as e:
            self.logger.warning("离开频道参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("离开频道异常", error=str(e))
            raise ControllerException(f"离开频道失败: {e}")
    
    @handler(message_id=7004)
    async def send_channel_message(self, request, context):
        """
        发送频道消息
        
        Args:
            request: 包含channel_id, sender_id, content, message_type的请求
            context: 请求上下文
            
        Returns:
            消息发送结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'channel_id') or not request.channel_id:
                raise ValidationException("频道ID不能为空")
            if not hasattr(request, 'sender_id') or not request.sender_id:
                raise ValidationException("发送者ID不能为空")
            if not hasattr(request, 'content') or not request.content:
                raise ValidationException("消息内容不能为空")
            
            # 内容过滤
            filtered_content = await self.filter_service.filter_content(
                request.content,
                request.sender_id
            )
            
            # 创建消息对象
            message = ChannelMessage(
                message_id=f"ch_msg_{int(time.time() * 1000000)}",
                channel_id=request.channel_id,
                sender_id=request.sender_id,
                content=filtered_content,
                message_type=getattr(request, 'message_type', 'text'),
                timestamp=time.time(),
                reply_to=getattr(request, 'reply_to', None)
            )
            
            # 发送消息
            success = await self.channel_service.send_message(message)
            
            if success:
                self.channel_stats['total_messages'] += 1
                
                # 更新活跃频道
                self.active_channels.add(request.channel_id)
                
                self.logger.info("频道消息发送成功", 
                               message_id=message.message_id,
                               channel_id=request.channel_id,
                               sender_id=request.sender_id)
                
                return {
                    'message_id': message.message_id,
                    'channel_id': request.channel_id,
                    'timestamp': message.timestamp,
                    'status': 'success'
                }
            else:
                self.logger.error("频道消息发送失败", 
                                channel_id=request.channel_id,
                                sender_id=request.sender_id)
                
                return {
                    'status': 'failed',
                    'error': '消息发送失败'
                }
                
        except ValidationException as e:
            self.logger.warning("发送频道消息参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("发送频道消息异常", error=str(e))
            raise ControllerException(f"发送频道消息失败: {e}")
    
    @handler(message_id=7005)
    async def get_channel_info(self, request, context):
        """
        获取频道信息
        
        Args:
            request: 包含channel_id的请求
            context: 请求上下文
            
        Returns:
            频道详细信息
        """
        try:
            # 参数验证
            if not hasattr(request, 'channel_id') or not request.channel_id:
                raise ValidationException("频道ID不能为空")
            
            # 先从缓存获取
            channel_info = self.channel_cache.get(request.channel_id)
            
            if not channel_info:
                # 从服务获取
                channel_info = await self.channel_service.get_channel_info(request.channel_id)
                
                if channel_info:
                    # 更新缓存
                    self.channel_cache[request.channel_id] = channel_info
            
            if channel_info:
                self.logger.info("获取频道信息成功", 
                               channel_id=request.channel_id,
                               name=channel_info.name)
                
                return {
                    'channel_id': channel_info.channel_id,
                    'name': channel_info.name,
                    'description': channel_info.description,
                    'owner_id': channel_info.owner_id,
                    'member_count': channel_info.member_count,
                    'max_members': channel_info.max_members,
                    'created_time': channel_info.created_time,
                    'is_private': channel_info.is_private,
                    'is_active': channel_info.is_active,
                    'status': 'success'
                }
            else:
                self.logger.error("频道不存在", channel_id=request.channel_id)
                
                return {
                    'status': 'failed',
                    'error': '频道不存在'
                }
                
        except ValidationException as e:
            self.logger.warning("获取频道信息参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取频道信息异常", error=str(e))
            raise ControllerException(f"获取频道信息失败: {e}")
    
    @handler(message_id=7006)
    async def get_channel_members(self, request, context):
        """
        获取频道成员列表
        
        Args:
            request: 包含channel_id, page, page_size的请求
            context: 请求上下文
            
        Returns:
            频道成员列表
        """
        try:
            # 参数验证
            if not hasattr(request, 'channel_id') or not request.channel_id:
                raise ValidationException("频道ID不能为空")
            
            page = getattr(request, 'page', 1)
            page_size = getattr(request, 'page_size', 50)
            
            # 获取成员列表
            members = await self.channel_service.get_channel_members(
                request.channel_id,
                page,
                page_size
            )
            
            self.logger.info("获取频道成员列表成功", 
                           channel_id=request.channel_id,
                           member_count=len(members))
            
            return {
                'channel_id': request.channel_id,
                'members': [
                    {
                        'user_id': member.user_id,
                        'role': member.role,
                        'joined_time': member.joined_time,
                        'is_muted': member.is_muted,
                        'last_active_time': member.last_active_time
                    }
                    for member in members
                ],
                'page': page,
                'page_size': page_size,
                'status': 'success'
            }
            
        except ValidationException as e:
            self.logger.warning("获取频道成员列表参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取频道成员列表异常", error=str(e))
            raise ControllerException(f"获取频道成员列表失败: {e}")
    
    @handler(message_id=7007)
    async def delete_channel(self, request, context):
        """
        删除频道
        
        Args:
            request: 包含channel_id, user_id的请求
            context: 请求上下文
            
        Returns:
            删除结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'channel_id') or not request.channel_id:
                raise ValidationException("频道ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            # 删除频道
            success = await self.channel_service.delete_channel(
                request.channel_id,
                request.user_id
            )
            
            if success:
                self.channel_stats['channels_deleted'] += 1
                self.channel_stats['total_channels'] -= 1
                
                # 清理缓存
                self.channel_cache.pop(request.channel_id, None)
                self.member_cache.pop(request.channel_id, None)
                self.active_channels.discard(request.channel_id)
                
                self.logger.info("频道删除成功", 
                               channel_id=request.channel_id,
                               user_id=request.user_id)
                
                return {
                    'status': 'success',
                    'channel_id': request.channel_id
                }
            else:
                self.logger.error("频道删除失败", 
                                channel_id=request.channel_id,
                                user_id=request.user_id)
                
                return {
                    'status': 'failed',
                    'error': '频道删除失败'
                }
                
        except ValidationException as e:
            self.logger.warning("删除频道参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("删除频道异常", error=str(e))
            raise ControllerException(f"删除频道失败: {e}")
    
    async def _update_member_cache(self, channel_id: str, user_id: str):
        """更新成员缓存"""
        try:
            member = ChannelMember(
                user_id=user_id,
                channel_id=channel_id,
                joined_time=time.time(),
                last_active_time=time.time()
            )
            
            if channel_id not in self.member_cache:
                self.member_cache[channel_id] = []
            
            self.member_cache[channel_id].append(member)
            
        except Exception as e:
            self.logger.error("更新成员缓存失败", error=str(e))
    
    async def _remove_member_cache(self, channel_id: str, user_id: str):
        """移除成员缓存"""
        try:
            if channel_id in self.member_cache:
                self.member_cache[channel_id] = [
                    member for member in self.member_cache[channel_id]
                    if member.user_id != user_id
                ]
                
                if not self.member_cache[channel_id]:
                    del self.member_cache[channel_id]
                    
        except Exception as e:
            self.logger.error("移除成员缓存失败", error=str(e))
    
    async def _cleanup_expired_cache(self):
        """清理过期缓存"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                
                # 清理频道缓存
                expired_channels = [
                    channel_id for channel_id, channel_info in self.channel_cache.items()
                    if current_time - channel_info.created_time > self.cache_ttl
                ]
                
                for channel_id in expired_channels:
                    del self.channel_cache[channel_id]
                
                # 清理成员缓存
                expired_members = [
                    channel_id for channel_id, members in self.member_cache.items()
                    if not members or all(
                        current_time - member.last_active_time > self.cache_ttl
                        for member in members
                    )
                ]
                
                for channel_id in expired_members:
                    del self.member_cache[channel_id]
                
                if expired_channels or expired_members:
                    self.logger.info("清理过期缓存", 
                                   expired_channels=len(expired_channels),
                                   expired_members=len(expired_members))
                    
            except Exception as e:
                self.logger.error("清理缓存异常", error=str(e))
    
    async def _update_channel_stats(self):
        """更新频道统计信息"""
        while True:
            try:
                await asyncio.sleep(60)  # 1分钟更新一次
                
                # 更新活跃频道数
                self.channel_stats['active_channels'] = len(self.active_channels)
                
                # 清理活跃频道（每小时重置一次）
                if int(time.time()) % 3600 == 0:
                    self.active_channels.clear()
                    
            except Exception as e:
                self.logger.error("更新频道统计异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            'channel_stats': self.channel_stats.copy(),
            'cache_info': {
                'cached_channels': len(self.channel_cache),
                'cached_members': len(self.member_cache),
                'active_channels': len(self.active_channels)
            }
        }
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            # 清理缓存
            self.channel_cache.clear()
            self.member_cache.clear()
            self.active_channels.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Channel控制器清理完成")
            
        except Exception as e:
            self.logger.error("Channel控制器清理失败", error=str(e))