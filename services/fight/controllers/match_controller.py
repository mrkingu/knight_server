"""
Match控制器

该模块实现了匹配功能的控制器，继承自BaseController，
负责处理战斗匹配、匹配队列管理、匹配确认、自定义匹配等匹配相关的业务逻辑。

主要功能：
- 处理匹配队列的加入和退出
- 管理匹配状态和进度
- 处理匹配确认和拒绝
- 支持自定义匹配房间
- 邀请匹配功能
- 匹配历史记录
- 匹配算法优化
- 匹配统计分析

装饰器支持：
- @handler 绑定消息协议号到处理方法
- 参数自动验证和解析
- 响应消息自动构建

技术特点：
- 使用MVC架构模式
- 异步处理提高性能
- 完善的异常处理
- 详细的日志记录
- 支持多种匹配模式
"""

import asyncio
import time
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum
import uuid

from services.base import BaseController, ControllerException, ValidationException
from common.logger import logger
from common.decorator.handler_decorator import handler, controller


class MatchType(Enum):
    """匹配类型枚举"""
    RANKED = "ranked"          # 排位匹配
    CASUAL = "casual"          # 休闲匹配
    CUSTOM = "custom"          # 自定义匹配
    TOURNAMENT = "tournament"  # 锦标赛匹配
    PRIVATE = "private"        # 私人匹配


class MatchStatus(Enum):
    """匹配状态枚举"""
    WAITING = "waiting"        # 等待中
    FOUND = "found"           # 找到匹配
    CONFIRMING = "confirming"  # 确认中
    CONFIRMED = "confirmed"    # 已确认
    REJECTED = "rejected"      # 被拒绝
    TIMEOUT = "timeout"        # 超时
    CANCELLED = "cancelled"    # 已取消


@dataclass
class MatchRequest:
    """匹配请求数据结构"""
    request_id: str
    user_id: str
    character_id: str
    match_type: MatchType
    rating: int
    preferences: Dict[str, Any]
    created_time: float
    timeout: float
    status: MatchStatus = MatchStatus.WAITING


@dataclass
class MatchResult:
    """匹配结果数据结构"""
    match_id: str
    participants: List[str]
    match_type: MatchType
    created_time: float
    battle_id: Optional[str] = None
    status: str = "pending"


@dataclass
class CustomMatch:
    """自定义匹配数据结构"""
    room_id: str
    creator_id: str
    room_name: str
    max_players: int
    current_players: int
    password: Optional[str] = None
    settings: Dict[str, Any] = None
    created_time: float = 0.0
    is_private: bool = False


@controller(name="MatchController")
class MatchController(BaseController):
    """
    Match控制器
    
    负责处理所有匹配相关的请求，包括匹配队列管理、匹配确认、
    自定义匹配等功能。
    """
    
    def __init__(self):
        """初始化Match控制器"""
        super().__init__()
        
        # 服务依赖
        self.match_service = None
        self.battle_service = None
        
        # 匹配请求队列
        self.match_queue: Dict[str, MatchRequest] = {}  # request_id -> MatchRequest
        
        # 用户匹配映射
        self.user_matches: Dict[str, str] = {}  # user_id -> request_id
        
        # 匹配结果缓存
        self.match_results: Dict[str, MatchResult] = {}  # match_id -> MatchResult
        
        # 自定义匹配房间
        self.custom_rooms: Dict[str, CustomMatch] = {}  # room_id -> CustomMatch
        
        # 匹配确认状态
        self.confirmation_states: Dict[str, Dict[str, bool]] = {}  # match_id -> user_id -> confirmed
        
        # 匹配统计
        self.match_stats = {
            'total_requests': 0,
            'successful_matches': 0,
            'cancelled_matches': 0,
            'timeout_matches': 0,
            'avg_wait_time': 0.0,
            'custom_rooms_created': 0,
            'invites_sent': 0
        }
        
        # 等待时间记录
        self.wait_times: List[float] = []
        self.max_wait_records = 1000
        
        self.logger.info("Match控制器初始化完成")
    
    async def initialize(self):
        """初始化控制器"""
        try:
            # 获取服务依赖
            self.match_service = self.get_service('match_service')
            self.battle_service = self.get_service('battle_service')
            
            # 启动定时任务
            asyncio.create_task(self._process_match_queue())
            asyncio.create_task(self._cleanup_expired_matches())
            asyncio.create_task(self._update_match_statistics())
            
            self.logger.info("Match控制器初始化成功")
            
        except Exception as e:
            self.logger.error("Match控制器初始化失败", error=str(e))
            raise ControllerException(f"Match控制器初始化失败: {e}")
    
    @handler(message_id=8001)
    async def join_match_queue(self, request, context):
        """
        加入匹配队列
        
        Args:
            request: 包含match_type, character_id, rating, preferences的请求
            context: 请求上下文
            
        Returns:
            匹配队列加入结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'match_type') or not request.match_type:
                raise ValidationException("匹配类型不能为空")
            if not hasattr(request, 'character_id') or not request.character_id:
                raise ValidationException("角色ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            user_id = request.user_id
            
            # 检查用户是否已在队列中
            if user_id in self.user_matches:
                existing_request_id = self.user_matches[user_id]
                existing_request = self.match_queue.get(existing_request_id)
                
                if existing_request and existing_request.status == MatchStatus.WAITING:
                    self.logger.warning("用户已在匹配队列中", user_id=user_id)
                    return {
                        'status': 'already_in_queue',
                        'request_id': existing_request_id,
                        'wait_time': time.time() - existing_request.created_time
                    }
            
            # 创建匹配请求
            request_id = f"match_{uuid.uuid4().hex[:12]}"
            
            match_request = MatchRequest(
                request_id=request_id,
                user_id=user_id,
                character_id=request.character_id,
                match_type=MatchType(request.match_type),
                rating=getattr(request, 'rating', 1000),
                preferences=getattr(request, 'preferences', {}),
                created_time=time.time(),
                timeout=time.time() + 300,  # 5分钟超时
                status=MatchStatus.WAITING
            )
            
            # 添加到队列
            self.match_queue[request_id] = match_request
            self.user_matches[user_id] = request_id
            
            # 尝试立即匹配
            await self._try_match(match_request)
            
            # 更新统计
            self.match_stats['total_requests'] += 1
            
            self.logger.info("用户加入匹配队列成功", 
                           user_id=user_id,
                           request_id=request_id,
                           match_type=request.match_type)
            
            return {
                'status': 'success',
                'request_id': request_id,
                'match_type': request.match_type,
                'estimated_wait_time': self.match_stats['avg_wait_time']
            }
            
        except ValidationException as e:
            self.logger.warning("加入匹配队列参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("加入匹配队列异常", error=str(e))
            raise ControllerException(f"加入匹配队列失败: {e}")
    
    @handler(message_id=8002)
    async def leave_match_queue(self, request, context):
        """
        离开匹配队列
        
        Args:
            request: 包含user_id的请求
            context: 请求上下文
            
        Returns:
            离开队列结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            user_id = request.user_id
            
            # 检查用户是否在队列中
            if user_id not in self.user_matches:
                self.logger.warning("用户不在匹配队列中", user_id=user_id)
                return {
                    'status': 'not_in_queue',
                    'message': '用户不在匹配队列中'
                }
            
            request_id = self.user_matches[user_id]
            match_request = self.match_queue.get(request_id)
            
            if match_request:
                # 记录等待时间
                wait_time = time.time() - match_request.created_time
                self.wait_times.append(wait_time)
                
                # 更新状态
                match_request.status = MatchStatus.CANCELLED
                
                # 移除队列
                del self.match_queue[request_id]
                del self.user_matches[user_id]
                
                # 更新统计
                self.match_stats['cancelled_matches'] += 1
                
                self.logger.info("用户离开匹配队列成功", 
                               user_id=user_id,
                               request_id=request_id,
                               wait_time=wait_time)
                
                return {
                    'status': 'success',
                    'request_id': request_id,
                    'wait_time': wait_time
                }
            else:
                self.logger.warning("匹配请求不存在", 
                                  user_id=user_id,
                                  request_id=request_id)
                return {
                    'status': 'request_not_found',
                    'message': '匹配请求不存在'
                }
                
        except ValidationException as e:
            self.logger.warning("离开匹配队列参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("离开匹配队列异常", error=str(e))
            raise ControllerException(f"离开匹配队列失败: {e}")
    
    @handler(message_id=8003)
    async def get_match_status(self, request, context):
        """
        获取匹配状态
        
        Args:
            request: 包含user_id的请求
            context: 请求上下文
            
        Returns:
            匹配状态信息
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            user_id = request.user_id
            
            # 检查用户是否在队列中
            if user_id not in self.user_matches:
                return {
                    'status': 'not_in_queue',
                    'message': '用户不在匹配队列中'
                }
            
            request_id = self.user_matches[user_id]
            match_request = self.match_queue.get(request_id)
            
            if match_request:
                wait_time = time.time() - match_request.created_time
                
                self.logger.info("获取匹配状态成功", 
                               user_id=user_id,
                               request_id=request_id,
                               status=match_request.status.value)
                
                return {
                    'status': 'success',
                    'request_id': request_id,
                    'match_status': match_request.status.value,
                    'wait_time': wait_time,
                    'match_type': match_request.match_type.value,
                    'estimated_remaining_time': max(0, match_request.timeout - time.time())
                }
            else:
                return {
                    'status': 'request_not_found',
                    'message': '匹配请求不存在'
                }
                
        except ValidationException as e:
            self.logger.warning("获取匹配状态参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取匹配状态异常", error=str(e))
            raise ControllerException(f"获取匹配状态失败: {e}")
    
    @handler(message_id=8004)
    async def confirm_match(self, request, context):
        """
        确认匹配
        
        Args:
            request: 包含match_id, user_id的请求
            context: 请求上下文
            
        Returns:
            匹配确认结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'match_id') or not request.match_id:
                raise ValidationException("匹配ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            match_id = request.match_id
            user_id = request.user_id
            
            # 检查匹配结果是否存在
            match_result = self.match_results.get(match_id)
            if not match_result:
                raise ValidationException("匹配结果不存在")
            
            # 检查用户是否在匹配中
            if user_id not in match_result.participants:
                raise ValidationException("用户不在此匹配中")
            
            # 初始化确认状态
            if match_id not in self.confirmation_states:
                self.confirmation_states[match_id] = {}
            
            # 确认匹配
            self.confirmation_states[match_id][user_id] = True
            
            # 检查是否所有用户都已确认
            all_confirmed = all(
                self.confirmation_states[match_id].get(participant, False)
                for participant in match_result.participants
            )
            
            if all_confirmed:
                # 所有用户都已确认，创建战斗
                battle_id = await self._create_battle(match_result)
                
                if battle_id:
                    match_result.battle_id = battle_id
                    match_result.status = "confirmed"
                    
                    # 清理匹配队列
                    await self._cleanup_match_queue(match_result.participants)
                    
                    # 更新统计
                    self.match_stats['successful_matches'] += 1
                    
                    self.logger.info("匹配确认完成，战斗创建成功", 
                                   match_id=match_id,
                                   battle_id=battle_id,
                                   participants=match_result.participants)
                    
                    return {
                        'status': 'all_confirmed',
                        'match_id': match_id,
                        'battle_id': battle_id,
                        'participants': match_result.participants
                    }
                else:
                    self.logger.error("创建战斗失败", match_id=match_id)
                    return {
                        'status': 'battle_creation_failed',
                        'error': '创建战斗失败'
                    }
            else:
                # 等待其他用户确认
                confirmed_count = sum(
                    1 for confirmed in self.confirmation_states[match_id].values()
                    if confirmed
                )
                total_count = len(match_result.participants)
                
                self.logger.info("用户确认匹配", 
                               match_id=match_id,
                               user_id=user_id,
                               confirmed_count=confirmed_count,
                               total_count=total_count)
                
                return {
                    'status': 'confirmed',
                    'match_id': match_id,
                    'confirmed_count': confirmed_count,
                    'total_count': total_count
                }
                
        except ValidationException as e:
            self.logger.warning("确认匹配参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("确认匹配异常", error=str(e))
            raise ControllerException(f"确认匹配失败: {e}")
    
    @handler(message_id=8005)
    async def reject_match(self, request, context):
        """
        拒绝匹配
        
        Args:
            request: 包含match_id, user_id的请求
            context: 请求上下文
            
        Returns:
            匹配拒绝结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'match_id') or not request.match_id:
                raise ValidationException("匹配ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            match_id = request.match_id
            user_id = request.user_id
            
            # 检查匹配结果是否存在
            match_result = self.match_results.get(match_id)
            if not match_result:
                raise ValidationException("匹配结果不存在")
            
            # 检查用户是否在匹配中
            if user_id not in match_result.participants:
                raise ValidationException("用户不在此匹配中")
            
            # 拒绝匹配
            match_result.status = "rejected"
            
            # 清理确认状态
            if match_id in self.confirmation_states:
                del self.confirmation_states[match_id]
            
            # 将其他用户重新加入队列
            await self._requeue_participants(match_result.participants, user_id)
            
            # 清理匹配结果
            del self.match_results[match_id]
            
            self.logger.info("用户拒绝匹配", 
                           match_id=match_id,
                           user_id=user_id,
                           participants=match_result.participants)
            
            return {
                'status': 'success',
                'match_id': match_id,
                'message': '匹配已拒绝'
            }
            
        except ValidationException as e:
            self.logger.warning("拒绝匹配参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("拒绝匹配异常", error=str(e))
            raise ControllerException(f"拒绝匹配失败: {e}")
    
    @handler(message_id=8006)
    async def create_custom_match(self, request, context):
        """
        创建自定义匹配
        
        Args:
            request: 包含room_name, max_players, password, settings的请求
            context: 请求上下文
            
        Returns:
            自定义匹配创建结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'room_name') or not request.room_name:
                raise ValidationException("房间名称不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            user_id = request.user_id
            room_name = request.room_name
            max_players = getattr(request, 'max_players', 8)
            password = getattr(request, 'password', None)
            settings = getattr(request, 'settings', {})
            is_private = getattr(request, 'is_private', False)
            
            # 生成房间ID
            room_id = f"room_{uuid.uuid4().hex[:12]}"
            
            # 创建自定义匹配
            custom_match = CustomMatch(
                room_id=room_id,
                creator_id=user_id,
                room_name=room_name,
                max_players=max_players,
                current_players=1,
                password=password,
                settings=settings,
                created_time=time.time(),
                is_private=is_private
            )
            
            # 保存房间
            self.custom_rooms[room_id] = custom_match
            
            # 更新统计
            self.match_stats['custom_rooms_created'] += 1
            
            self.logger.info("自定义匹配创建成功", 
                           room_id=room_id,
                           creator_id=user_id,
                           room_name=room_name,
                           max_players=max_players)
            
            return {
                'status': 'success',
                'room_id': room_id,
                'room_name': room_name,
                'max_players': max_players,
                'current_players': 1,
                'is_private': is_private
            }
            
        except ValidationException as e:
            self.logger.warning("创建自定义匹配参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("创建自定义匹配异常", error=str(e))
            raise ControllerException(f"创建自定义匹配失败: {e}")
    
    @handler(message_id=8007)
    async def send_match_invite(self, request, context):
        """
        发送匹配邀请
        
        Args:
            request: 包含target_user_id, room_id的请求
            context: 请求上下文
            
        Returns:
            邀请发送结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'target_user_id') or not request.target_user_id:
                raise ValidationException("目标用户ID不能为空")
            if not hasattr(request, 'room_id') or not request.room_id:
                raise ValidationException("房间ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            target_user_id = request.target_user_id
            room_id = request.room_id
            user_id = request.user_id
            
            # 检查房间是否存在
            room = self.custom_rooms.get(room_id)
            if not room:
                raise ValidationException("房间不存在")
            
            # 检查是否有邀请权限
            if room.creator_id != user_id:
                raise ValidationException("只有房间创建者可以发送邀请")
            
            # 发送邀请
            invite_success = await self.match_service.send_invite(
                room_id, user_id, target_user_id
            )
            
            if invite_success:
                # 更新统计
                self.match_stats['invites_sent'] += 1
                
                self.logger.info("匹配邀请发送成功", 
                               room_id=room_id,
                               from_user=user_id,
                               to_user=target_user_id)
                
                return {
                    'status': 'success',
                    'room_id': room_id,
                    'target_user_id': target_user_id,
                    'message': '邀请发送成功'
                }
            else:
                self.logger.error("匹配邀请发送失败", 
                                room_id=room_id,
                                from_user=user_id,
                                to_user=target_user_id)
                
                return {
                    'status': 'failed',
                    'error': '邀请发送失败'
                }
                
        except ValidationException as e:
            self.logger.warning("发送匹配邀请参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("发送匹配邀请异常", error=str(e))
            raise ControllerException(f"发送匹配邀请失败: {e}")
    
    @handler(message_id=8008)
    async def get_match_history(self, request, context):
        """
        获取匹配历史
        
        Args:
            request: 包含user_id, page, page_size的请求
            context: 请求上下文
            
        Returns:
            匹配历史记录
        """
        try:
            # 参数验证
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            user_id = request.user_id
            page = getattr(request, 'page', 1)
            page_size = getattr(request, 'page_size', 20)
            
            # 获取匹配历史
            history = await self.match_service.get_match_history(
                user_id, page, page_size
            )
            
            self.logger.info("获取匹配历史成功", 
                           user_id=user_id,
                           page=page,
                           record_count=len(history))
            
            return {
                'status': 'success',
                'user_id': user_id,
                'page': page,
                'page_size': page_size,
                'history': history
            }
            
        except ValidationException as e:
            self.logger.warning("获取匹配历史参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取匹配历史异常", error=str(e))
            raise ControllerException(f"获取匹配历史失败: {e}")
    
    async def _try_match(self, match_request: MatchRequest):
        """尝试匹配"""
        try:
            # 寻找匹配的对手
            opponent = await self._find_opponent(match_request)
            
            if opponent:
                # 创建匹配结果
                match_id = f"match_{uuid.uuid4().hex[:12]}"
                
                match_result = MatchResult(
                    match_id=match_id,
                    participants=[match_request.user_id, opponent.user_id],
                    match_type=match_request.match_type,
                    created_time=time.time(),
                    status="pending"
                )
                
                # 保存匹配结果
                self.match_results[match_id] = match_result
                
                # 更新匹配请求状态
                match_request.status = MatchStatus.FOUND
                opponent.status = MatchStatus.FOUND
                
                # 通知用户找到匹配
                await self._notify_match_found(match_result)
                
                self.logger.info("找到匹配", 
                               match_id=match_id,
                               participants=match_result.participants)
                
        except Exception as e:
            self.logger.error("尝试匹配失败", 
                            request_id=match_request.request_id,
                            error=str(e))
    
    async def _find_opponent(self, match_request: MatchRequest) -> Optional[MatchRequest]:
        """寻找对手"""
        try:
            rating_range = 100  # 评分范围
            
            for request_id, opponent in self.match_queue.items():
                if (opponent.request_id != match_request.request_id and
                    opponent.status == MatchStatus.WAITING and
                    opponent.match_type == match_request.match_type and
                    abs(opponent.rating - match_request.rating) <= rating_range):
                    
                    return opponent
            
            return None
            
        except Exception as e:
            self.logger.error("寻找对手失败", error=str(e))
            return None
    
    async def _notify_match_found(self, match_result: MatchResult):
        """通知用户找到匹配"""
        try:
            # 这里应该通过通知服务通知用户
            # 由于是模拟实现，只记录日志
            self.logger.info("通知用户找到匹配", 
                           match_id=match_result.match_id,
                           participants=match_result.participants)
            
        except Exception as e:
            self.logger.error("通知匹配找到失败", error=str(e))
    
    async def _create_battle(self, match_result: MatchResult) -> Optional[str]:
        """创建战斗"""
        try:
            # 调用战斗服务创建战斗
            battle_id = await self.battle_service.create_battle(
                participants=match_result.participants,
                match_type=match_result.match_type.value
            )
            
            return battle_id
            
        except Exception as e:
            self.logger.error("创建战斗失败", 
                            match_id=match_result.match_id,
                            error=str(e))
            return None
    
    async def _cleanup_match_queue(self, participants: List[str]):
        """清理匹配队列"""
        try:
            for user_id in participants:
                if user_id in self.user_matches:
                    request_id = self.user_matches[user_id]
                    
                    # 记录等待时间
                    if request_id in self.match_queue:
                        match_request = self.match_queue[request_id]
                        wait_time = time.time() - match_request.created_time
                        self.wait_times.append(wait_time)
                        
                        # 删除队列记录
                        del self.match_queue[request_id]
                    
                    # 删除用户映射
                    del self.user_matches[user_id]
                    
        except Exception as e:
            self.logger.error("清理匹配队列失败", error=str(e))
    
    async def _requeue_participants(self, participants: List[str], excluding_user: str):
        """重新将参与者加入队列"""
        try:
            for user_id in participants:
                if user_id != excluding_user and user_id in self.user_matches:
                    request_id = self.user_matches[user_id]
                    
                    if request_id in self.match_queue:
                        match_request = self.match_queue[request_id]
                        match_request.status = MatchStatus.WAITING
                        match_request.created_time = time.time()  # 重置等待时间
                        
                        self.logger.info("用户重新加入匹配队列", 
                                       user_id=user_id,
                                       request_id=request_id)
                        
        except Exception as e:
            self.logger.error("重新加入队列失败", error=str(e))
    
    async def _process_match_queue(self):
        """处理匹配队列"""
        while True:
            try:
                await asyncio.sleep(5)  # 每5秒处理一次
                
                # 处理等待中的匹配请求
                for request_id, match_request in list(self.match_queue.items()):
                    if match_request.status == MatchStatus.WAITING:
                        await self._try_match(match_request)
                        
            except Exception as e:
                self.logger.error("处理匹配队列异常", error=str(e))
    
    async def _cleanup_expired_matches(self):
        """清理过期匹配"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟清理一次
                
                current_time = time.time()
                expired_requests = []
                
                # 清理过期的匹配请求
                for request_id, match_request in self.match_queue.items():
                    if current_time > match_request.timeout:
                        expired_requests.append(request_id)
                
                for request_id in expired_requests:
                    match_request = self.match_queue[request_id]
                    user_id = match_request.user_id
                    
                    # 记录等待时间
                    wait_time = current_time - match_request.created_time
                    self.wait_times.append(wait_time)
                    
                    # 删除过期请求
                    del self.match_queue[request_id]
                    
                    if user_id in self.user_matches:
                        del self.user_matches[user_id]
                    
                    # 更新统计
                    self.match_stats['timeout_matches'] += 1
                    
                    self.logger.info("清理过期匹配请求", 
                                   request_id=request_id,
                                   user_id=user_id,
                                   wait_time=wait_time)
                
                # 清理过期的匹配结果
                expired_results = []
                for match_id, match_result in self.match_results.items():
                    if current_time - match_result.created_time > 300:  # 5分钟过期
                        expired_results.append(match_id)
                
                for match_id in expired_results:
                    del self.match_results[match_id]
                    
                    if match_id in self.confirmation_states:
                        del self.confirmation_states[match_id]
                
                if expired_requests or expired_results:
                    self.logger.info("清理过期匹配数据", 
                                   expired_requests=len(expired_requests),
                                   expired_results=len(expired_results))
                    
            except Exception as e:
                self.logger.error("清理过期匹配异常", error=str(e))
    
    async def _update_match_statistics(self):
        """更新匹配统计"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟更新一次
                
                # 更新平均等待时间
                if self.wait_times:
                    # 保持最近1000条记录
                    if len(self.wait_times) > self.max_wait_records:
                        self.wait_times = self.wait_times[-self.max_wait_records:]
                    
                    self.match_stats['avg_wait_time'] = sum(self.wait_times) / len(self.wait_times)
                    
            except Exception as e:
                self.logger.error("更新匹配统计异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            'match_stats': self.match_stats.copy(),
            'queue_info': {
                'waiting_players': len(self.match_queue),
                'custom_rooms': len(self.custom_rooms),
                'pending_matches': len(self.match_results),
                'confirming_matches': len(self.confirmation_states)
            },
            'performance': {
                'avg_wait_time': self.match_stats['avg_wait_time'],
                'success_rate': (self.match_stats['successful_matches'] / 
                               max(1, self.match_stats['total_requests'])) * 100
            }
        }
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            # 清理所有数据
            self.match_queue.clear()
            self.user_matches.clear()
            self.match_results.clear()
            self.custom_rooms.clear()
            self.confirmation_states.clear()
            self.wait_times.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Match控制器清理完成")
            
        except Exception as e:
            self.logger.error("Match控制器清理失败", error=str(e))