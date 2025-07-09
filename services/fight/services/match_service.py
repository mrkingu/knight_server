"""
Match业务服务

该模块实现了匹配功能的业务服务层，继承自BaseService，
负责处理匹配算法、匹配队列管理、匹配状态跟踪、匹配历史记录等核心业务逻辑。

主要功能：
- 匹配算法实现和优化
- 匹配队列管理和调度
- 匹配状态跟踪和同步
- 匹配历史记录管理
- 邀请系统管理
- 匹配偏好设置
- 匹配数据分析
- 匹配性能监控

技术特点：
- 使用异步处理提高性能
- 支持多种匹配算法
- 完善的状态机管理
- 详细的日志记录
- 支持实时匹配通知
- 高效的匹配调度
"""

import asyncio
import time
import json
import uuid
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import heapq

from services.base import BaseService, ServiceException, transactional, cached, retry
from common.logger import logger


class MatchType(Enum):
    """匹配类型枚举"""
    RANKED = "ranked"
    CASUAL = "casual"
    CUSTOM = "custom"
    TOURNAMENT = "tournament"
    PRIVATE = "private"


class MatchStatus(Enum):
    """匹配状态枚举"""
    WAITING = "waiting"
    FOUND = "found"
    CONFIRMING = "confirming"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


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
    priority: int = 0
    status: MatchStatus = MatchStatus.WAITING


@dataclass
class MatchPair:
    """匹配对数据结构"""
    match_id: str
    participants: List[str]
    match_type: MatchType
    average_rating: float
    created_time: float
    confirmation_deadline: float
    status: str = "pending"


@dataclass
class MatchHistory:
    """匹配历史数据结构"""
    match_id: str
    user_id: str
    opponent_id: str
    match_type: MatchType
    result: str  # win/lose/draw
    rating_change: int
    duration: float
    created_time: float


@dataclass
class MatchInvite:
    """匹配邀请数据结构"""
    invite_id: str
    from_user_id: str
    to_user_id: str
    room_id: str
    created_time: float
    expires_time: float
    status: str = "pending"


class MatchService(BaseService):
    """
    Match业务服务
    
    负责处理所有匹配相关的业务逻辑，包括匹配算法、队列管理、
    状态跟踪、历史记录等功能。
    """
    
    def __init__(self, max_concurrent_matches: int = 1000,
                 match_timeout: int = 30,
                 enable_auto_match: bool = True,
                 match_rating_range: int = 100):
        """
        初始化Match服务
        
        Args:
            max_concurrent_matches: 最大并发匹配数
            match_timeout: 匹配超时时间（秒）
            enable_auto_match: 是否启用自动匹配
            match_rating_range: 匹配评分范围
        """
        super().__init__()
        
        self.max_concurrent_matches = max_concurrent_matches
        self.match_timeout = match_timeout
        self.enable_auto_match = enable_auto_match
        self.match_rating_range = match_rating_range
        
        # 匹配队列 (优先级队列)
        self.match_queues: Dict[MatchType, List[MatchRequest]] = {
            match_type: [] for match_type in MatchType
        }
        
        # 匹配对存储
        self.match_pairs: Dict[str, MatchPair] = {}
        
        # 匹配历史
        self.match_history: Dict[str, List[MatchHistory]] = {}
        
        # 邀请系统
        self.invites: Dict[str, MatchInvite] = {}
        self.user_invites: Dict[str, List[str]] = {}  # user_id -> invite_ids
        
        # 用户匹配状态
        self.user_match_state: Dict[str, Dict[str, Any]] = {}
        
        # 匹配统计
        self.match_stats = {
            'total_requests': 0,
            'successful_matches': 0,
            'cancelled_matches': 0,
            'timeout_matches': 0,
            'avg_wait_time': 0.0,
            'avg_rating_difference': 0.0,
            'match_accuracy': 0.0
        }
        
        # 等待时间记录
        self.wait_times: List[float] = []
        self.rating_differences: List[float] = []
        
        # 匹配算法配置
        self.match_algorithm_config = {
            'rating_weight': 0.7,
            'wait_time_weight': 0.2,
            'preference_weight': 0.1,
            'max_wait_time_expansion': 300,  # 5分钟后扩大匹配范围
            'rating_expansion_rate': 10     # 每秒扩大10分评分范围
        }
        
        self.logger.info("Match服务初始化完成",
                        max_concurrent_matches=max_concurrent_matches,
                        match_timeout=match_timeout,
                        enable_auto_match=enable_auto_match)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化基础服务
            await super().initialize()
            
            # 启动定时任务
            if self.enable_auto_match:
                asyncio.create_task(self._auto_match_loop())
            
            asyncio.create_task(self._cleanup_expired_matches())
            asyncio.create_task(self._cleanup_expired_invites())
            asyncio.create_task(self._update_match_statistics())
            
            self.logger.info("Match服务初始化成功")
            
        except Exception as e:
            self.logger.error("Match服务初始化失败", error=str(e))
            raise ServiceException(f"Match服务初始化失败: {e}")
    
    @transactional
    async def add_match_request(self, user_id: str, character_id: str,
                              match_type: MatchType, rating: int,
                              preferences: Dict[str, Any] = None) -> str:
        """
        添加匹配请求
        
        Args:
            user_id: 用户ID
            character_id: 角色ID
            match_type: 匹配类型
            rating: 用户评分
            preferences: 匹配偏好设置
            
        Returns:
            str: 请求ID
        """
        try:
            # 检查用户是否已在匹配中
            if await self._is_user_in_match(user_id):
                raise ServiceException("用户已在匹配队列中")
            
            # 生成请求ID
            request_id = f"req_{uuid.uuid4().hex[:12]}"
            
            # 创建匹配请求
            match_request = MatchRequest(
                request_id=request_id,
                user_id=user_id,
                character_id=character_id,
                match_type=match_type,
                rating=rating,
                preferences=preferences or {},
                created_time=time.time(),
                timeout=time.time() + self.match_timeout,
                priority=await self._calculate_priority(user_id, rating)
            )
            
            # 添加到队列
            queue = self.match_queues[match_type]
            heapq.heappush(queue, (match_request.priority, match_request.created_time, match_request))
            
            # 更新用户状态
            self.user_match_state[user_id] = {
                'request_id': request_id,
                'status': MatchStatus.WAITING,
                'created_time': match_request.created_time
            }
            
            # 更新统计
            self.match_stats['total_requests'] += 1
            
            self.logger.info("匹配请求添加成功", 
                           request_id=request_id,
                           user_id=user_id,
                           match_type=match_type.value,
                           rating=rating)
            
            return request_id
            
        except Exception as e:
            self.logger.error("添加匹配请求失败", 
                            user_id=user_id,
                            error=str(e))
            raise ServiceException(f"添加匹配请求失败: {e}")
    
    @transactional
    async def cancel_match_request(self, user_id: str) -> bool:
        """
        取消匹配请求
        
        Args:
            user_id: 用户ID
            
        Returns:
            bool: 是否成功取消
        """
        try:
            # 检查用户匹配状态
            user_state = self.user_match_state.get(user_id)
            if not user_state:
                self.logger.warning("用户不在匹配队列中", user_id=user_id)
                return False
            
            request_id = user_state['request_id']
            
            # 从队列中移除
            removed = await self._remove_from_queue(request_id)
            
            if removed:
                # 记录等待时间
                wait_time = time.time() - user_state['created_time']
                self.wait_times.append(wait_time)
                
                # 清理用户状态
                del self.user_match_state[user_id]
                
                # 更新统计
                self.match_stats['cancelled_matches'] += 1
                
                self.logger.info("匹配请求取消成功", 
                               user_id=user_id,
                               request_id=request_id,
                               wait_time=wait_time)
                
                return True
            else:
                self.logger.warning("匹配请求未找到", 
                                  user_id=user_id,
                                  request_id=request_id)
                return False
                
        except Exception as e:
            self.logger.error("取消匹配请求失败", 
                            user_id=user_id,
                            error=str(e))
            return False
    
    @cached(ttl=10)
    async def get_match_status(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        获取匹配状态
        
        Args:
            user_id: 用户ID
            
        Returns:
            Optional[Dict]: 匹配状态信息
        """
        try:
            user_state = self.user_match_state.get(user_id)
            if not user_state:
                return None
            
            wait_time = time.time() - user_state['created_time']
            
            return {
                'request_id': user_state['request_id'],
                'status': user_state['status'].value if hasattr(user_state['status'], 'value') else user_state['status'],
                'wait_time': wait_time,
                'estimated_remaining_time': max(0, self.match_timeout - wait_time)
            }
            
        except Exception as e:
            self.logger.error("获取匹配状态失败", 
                            user_id=user_id,
                            error=str(e))
            return None
    
    @transactional
    async def send_invite(self, room_id: str, from_user_id: str, 
                        to_user_id: str) -> bool:
        """
        发送匹配邀请
        
        Args:
            room_id: 房间ID
            from_user_id: 发送者ID
            to_user_id: 接收者ID
            
        Returns:
            bool: 是否成功发送
        """
        try:
            # 检查用户是否已有邀请
            if await self._has_pending_invite(to_user_id):
                self.logger.warning("用户已有待处理邀请", to_user_id=to_user_id)
                return False
            
            # 生成邀请ID
            invite_id = f"inv_{uuid.uuid4().hex[:12]}"
            
            # 创建邀请
            invite = MatchInvite(
                invite_id=invite_id,
                from_user_id=from_user_id,
                to_user_id=to_user_id,
                room_id=room_id,
                created_time=time.time(),
                expires_time=time.time() + 300,  # 5分钟过期
                status="pending"
            )
            
            # 保存邀请
            self.invites[invite_id] = invite
            
            # 更新用户邀请索引
            if to_user_id not in self.user_invites:
                self.user_invites[to_user_id] = []
            self.user_invites[to_user_id].append(invite_id)
            
            self.logger.info("匹配邀请发送成功", 
                           invite_id=invite_id,
                           from_user_id=from_user_id,
                           to_user_id=to_user_id,
                           room_id=room_id)
            
            return True
            
        except Exception as e:
            self.logger.error("发送匹配邀请失败", 
                            from_user_id=from_user_id,
                            to_user_id=to_user_id,
                            error=str(e))
            return False
    
    @transactional
    async def accept_invite(self, invite_id: str, user_id: str) -> bool:
        """
        接受邀请
        
        Args:
            invite_id: 邀请ID
            user_id: 用户ID
            
        Returns:
            bool: 是否成功接受
        """
        try:
            # 检查邀请是否存在
            invite = self.invites.get(invite_id)
            if not invite:
                self.logger.warning("邀请不存在", invite_id=invite_id)
                return False
            
            # 检查邀请是否属于该用户
            if invite.to_user_id != user_id:
                self.logger.warning("邀请不属于该用户", 
                                  invite_id=invite_id,
                                  user_id=user_id)
                return False
            
            # 检查邀请是否过期
            if time.time() > invite.expires_time:
                self.logger.warning("邀请已过期", invite_id=invite_id)
                return False
            
            # 更新邀请状态
            invite.status = "accepted"
            
            # 清理用户邀请索引
            if user_id in self.user_invites:
                self.user_invites[user_id].remove(invite_id)
                if not self.user_invites[user_id]:
                    del self.user_invites[user_id]
            
            self.logger.info("邀请接受成功", 
                           invite_id=invite_id,
                           user_id=user_id,
                           from_user_id=invite.from_user_id)
            
            return True
            
        except Exception as e:
            self.logger.error("接受邀请失败", 
                            invite_id=invite_id,
                            user_id=user_id,
                            error=str(e))
            return False
    
    async def get_match_history(self, user_id: str, page: int = 1, 
                              page_size: int = 20) -> List[Dict[str, Any]]:
        """
        获取匹配历史
        
        Args:
            user_id: 用户ID
            page: 页码
            page_size: 每页大小
            
        Returns:
            List[Dict]: 匹配历史记录
        """
        try:
            history = self.match_history.get(user_id, [])
            
            # 按时间倒序排序
            history = sorted(history, key=lambda x: x.created_time, reverse=True)
            
            # 分页处理
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            page_history = history[start_index:end_index]
            
            # 转换为字典格式
            result = []
            for record in page_history:
                result.append({
                    'match_id': record.match_id,
                    'opponent_id': record.opponent_id,
                    'match_type': record.match_type.value,
                    'result': record.result,
                    'rating_change': record.rating_change,
                    'duration': record.duration,
                    'created_time': record.created_time
                })
            
            self.logger.info("获取匹配历史成功", 
                           user_id=user_id,
                           page=page,
                           record_count=len(result))
            
            return result
            
        except Exception as e:
            self.logger.error("获取匹配历史失败", 
                            user_id=user_id,
                            error=str(e))
            return []
    
    async def add_match_history(self, match_id: str, participants: List[str],
                              match_type: MatchType, result: Dict[str, Any]):
        """
        添加匹配历史记录
        
        Args:
            match_id: 匹配ID
            participants: 参与者列表
            match_type: 匹配类型
            result: 匹配结果
        """
        try:
            if len(participants) == 2:
                user1, user2 = participants
                
                # 创建历史记录
                history1 = MatchHistory(
                    match_id=match_id,
                    user_id=user1,
                    opponent_id=user2,
                    match_type=match_type,
                    result=result.get('winner') == user1 and 'win' or 'lose',
                    rating_change=result.get('rating_changes', {}).get(user1, 0),
                    duration=result.get('duration', 0),
                    created_time=time.time()
                )
                
                history2 = MatchHistory(
                    match_id=match_id,
                    user_id=user2,
                    opponent_id=user1,
                    match_type=match_type,
                    result=result.get('winner') == user2 and 'win' or 'lose',
                    rating_change=result.get('rating_changes', {}).get(user2, 0),
                    duration=result.get('duration', 0),
                    created_time=time.time()
                )
                
                # 保存历史记录
                if user1 not in self.match_history:
                    self.match_history[user1] = []
                self.match_history[user1].append(history1)
                
                if user2 not in self.match_history:
                    self.match_history[user2] = []
                self.match_history[user2].append(history2)
                
                # 限制历史记录数量
                for user_id in [user1, user2]:
                    if len(self.match_history[user_id]) > 1000:
                        self.match_history[user_id] = self.match_history[user_id][-1000:]
                
                self.logger.info("匹配历史记录添加成功", 
                               match_id=match_id,
                               participants=participants)
                
        except Exception as e:
            self.logger.error("添加匹配历史记录失败", 
                            match_id=match_id,
                            error=str(e))
    
    async def _is_user_in_match(self, user_id: str) -> bool:
        """检查用户是否在匹配中"""
        try:
            return user_id in self.user_match_state
            
        except Exception as e:
            self.logger.error("检查用户匹配状态失败", error=str(e))
            return False
    
    async def _calculate_priority(self, user_id: str, rating: int) -> int:
        """计算匹配优先级"""
        try:
            # 基础优先级
            base_priority = 1000 - rating  # 评分越低优先级越高
            
            # VIP用户优先级加成
            vip_bonus = 0
            
            # 连续匹配失败的用户优先级加成
            failure_bonus = 0
            
            return base_priority + vip_bonus + failure_bonus
            
        except Exception as e:
            self.logger.error("计算匹配优先级失败", error=str(e))
            return 1000
    
    async def _remove_from_queue(self, request_id: str) -> bool:
        """从队列中移除请求"""
        try:
            # 遍历所有队列查找并移除
            for match_type, queue in self.match_queues.items():
                for i, (priority, created_time, request) in enumerate(queue):
                    if request.request_id == request_id:
                        queue.pop(i)
                        heapq.heapify(queue)
                        return True
            
            return False
            
        except Exception as e:
            self.logger.error("从队列移除请求失败", error=str(e))
            return False
    
    async def _has_pending_invite(self, user_id: str) -> bool:
        """检查用户是否有待处理邀请"""
        try:
            invites = self.user_invites.get(user_id, [])
            
            for invite_id in invites:
                invite = self.invites.get(invite_id)
                if invite and invite.status == "pending" and time.time() < invite.expires_time:
                    return True
            
            return False
            
        except Exception as e:
            self.logger.error("检查待处理邀请失败", error=str(e))
            return False
    
    async def _find_match(self, request: MatchRequest) -> Optional[MatchRequest]:
        """查找匹配对手"""
        try:
            queue = self.match_queues[request.match_type]
            current_time = time.time()
            wait_time = current_time - request.created_time
            
            # 动态调整匹配范围
            base_range = self.match_rating_range
            expanded_range = base_range + int(wait_time * self.match_algorithm_config['rating_expansion_rate'])
            
            # 查找合适的对手
            for i, (priority, created_time, opponent) in enumerate(queue):
                if opponent.request_id == request.request_id:
                    continue
                
                # 评分范围检查
                rating_diff = abs(opponent.rating - request.rating)
                if rating_diff > expanded_range:
                    continue
                
                # 偏好匹配检查
                if not await self._check_preferences_match(request, opponent):
                    continue
                
                # 找到合适的对手
                queue.pop(i)
                heapq.heapify(queue)
                
                return opponent
            
            return None
            
        except Exception as e:
            self.logger.error("查找匹配对手失败", error=str(e))
            return None
    
    async def _check_preferences_match(self, request1: MatchRequest, 
                                     request2: MatchRequest) -> bool:
        """检查偏好匹配"""
        try:
            # 简化的偏好匹配检查
            pref1 = request1.preferences
            pref2 = request2.preferences
            
            # 检查地区偏好
            if pref1.get('region') and pref2.get('region'):
                if pref1['region'] != pref2['region']:
                    return False
            
            # 检查游戏模式偏好
            if pref1.get('game_mode') and pref2.get('game_mode'):
                if pref1['game_mode'] != pref2['game_mode']:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error("检查偏好匹配失败", error=str(e))
            return True
    
    async def _create_match_pair(self, request1: MatchRequest, 
                               request2: MatchRequest) -> str:
        """创建匹配对"""
        try:
            # 生成匹配ID
            match_id = f"match_{uuid.uuid4().hex[:12]}"
            
            # 创建匹配对
            match_pair = MatchPair(
                match_id=match_id,
                participants=[request1.user_id, request2.user_id],
                match_type=request1.match_type,
                average_rating=(request1.rating + request2.rating) / 2,
                created_time=time.time(),
                confirmation_deadline=time.time() + 30,  # 30秒确认时间
                status="pending"
            )
            
            # 保存匹配对
            self.match_pairs[match_id] = match_pair
            
            # 更新用户状态
            for user_id in [request1.user_id, request2.user_id]:
                if user_id in self.user_match_state:
                    self.user_match_state[user_id]['status'] = MatchStatus.FOUND
            
            # 记录匹配质量
            rating_diff = abs(request1.rating - request2.rating)
            self.rating_differences.append(rating_diff)
            
            # 记录等待时间
            wait_time1 = time.time() - request1.created_time
            wait_time2 = time.time() - request2.created_time
            avg_wait_time = (wait_time1 + wait_time2) / 2
            self.wait_times.append(avg_wait_time)
            
            self.logger.info("匹配对创建成功", 
                           match_id=match_id,
                           participants=match_pair.participants,
                           rating_diff=rating_diff,
                           avg_wait_time=avg_wait_time)
            
            return match_id
            
        except Exception as e:
            self.logger.error("创建匹配对失败", error=str(e))
            return None
    
    async def _auto_match_loop(self):
        """自动匹配循环"""
        while True:
            try:
                await asyncio.sleep(1)  # 每秒检查一次
                
                # 处理所有匹配类型的队列
                for match_type, queue in self.match_queues.items():
                    if len(queue) < 2:
                        continue
                    
                    # 尝试匹配队列中的玩家
                    matched_pairs = []
                    
                    while len(queue) >= 2:
                        # 取出优先级最高的请求
                        priority, created_time, request = heapq.heappop(queue)
                        
                        # 查找匹配对手
                        opponent = await self._find_match(request)
                        
                        if opponent:
                            # 创建匹配对
                            match_id = await self._create_match_pair(request, opponent)
                            
                            if match_id:
                                matched_pairs.append((request, opponent, match_id))
                                
                                # 更新统计
                                self.match_stats['successful_matches'] += 1
                        else:
                            # 没有找到对手，重新加入队列
                            heapq.heappush(queue, (priority, created_time, request))
                            break
                    
                    # 通知匹配结果
                    for request, opponent, match_id in matched_pairs:
                        await self._notify_match_found(match_id, [request.user_id, opponent.user_id])
                
            except Exception as e:
                self.logger.error("自动匹配循环异常", error=str(e))
    
    async def _notify_match_found(self, match_id: str, participants: List[str]):
        """通知匹配找到"""
        try:
            # 这里应该通过通知服务通知用户
            # 由于是模拟实现，只记录日志
            self.logger.info("通知匹配找到", 
                           match_id=match_id,
                           participants=participants)
            
        except Exception as e:
            self.logger.error("通知匹配找到失败", error=str(e))
    
    async def _cleanup_expired_matches(self):
        """清理过期匹配"""
        while True:
            try:
                await asyncio.sleep(30)  # 每30秒清理一次
                
                current_time = time.time()
                
                # 清理过期的匹配请求
                for match_type, queue in self.match_queues.items():
                    expired_requests = []
                    
                    for i, (priority, created_time, request) in enumerate(queue):
                        if current_time > request.timeout:
                            expired_requests.append(i)
                    
                    # 从后往前移除过期请求
                    for i in reversed(expired_requests):
                        priority, created_time, request = queue.pop(i)
                        
                        # 记录等待时间
                        wait_time = current_time - request.created_time
                        self.wait_times.append(wait_time)
                        
                        # 清理用户状态
                        if request.user_id in self.user_match_state:
                            del self.user_match_state[request.user_id]
                        
                        # 更新统计
                        self.match_stats['timeout_matches'] += 1
                        
                        self.logger.info("清理过期匹配请求", 
                                       request_id=request.request_id,
                                       user_id=request.user_id,
                                       wait_time=wait_time)
                    
                    # 重新构建堆
                    if expired_requests:
                        heapq.heapify(queue)
                
                # 清理过期的匹配对
                expired_pairs = []
                for match_id, pair in self.match_pairs.items():
                    if current_time > pair.confirmation_deadline and pair.status == "pending":
                        expired_pairs.append(match_id)
                
                for match_id in expired_pairs:
                    pair = self.match_pairs[match_id]
                    del self.match_pairs[match_id]
                    
                    # 清理用户状态
                    for user_id in pair.participants:
                        if user_id in self.user_match_state:
                            del self.user_match_state[user_id]
                    
                    self.logger.info("清理过期匹配对", 
                                   match_id=match_id,
                                   participants=pair.participants)
                
            except Exception as e:
                self.logger.error("清理过期匹配异常", error=str(e))
    
    async def _cleanup_expired_invites(self):
        """清理过期邀请"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟清理一次
                
                current_time = time.time()
                expired_invites = []
                
                for invite_id, invite in self.invites.items():
                    if current_time > invite.expires_time:
                        expired_invites.append(invite_id)
                
                for invite_id in expired_invites:
                    invite = self.invites[invite_id]
                    del self.invites[invite_id]
                    
                    # 清理用户邀请索引
                    if invite.to_user_id in self.user_invites:
                        if invite_id in self.user_invites[invite.to_user_id]:
                            self.user_invites[invite.to_user_id].remove(invite_id)
                        
                        if not self.user_invites[invite.to_user_id]:
                            del self.user_invites[invite.to_user_id]
                    
                    self.logger.info("清理过期邀请", 
                                   invite_id=invite_id,
                                   from_user_id=invite.from_user_id,
                                   to_user_id=invite.to_user_id)
                
            except Exception as e:
                self.logger.error("清理过期邀请异常", error=str(e))
    
    async def _update_match_statistics(self):
        """更新匹配统计"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟更新一次
                
                # 更新平均等待时间
                if self.wait_times:
                    # 保持最近1000条记录
                    if len(self.wait_times) > 1000:
                        self.wait_times = self.wait_times[-1000:]
                    
                    self.match_stats['avg_wait_time'] = sum(self.wait_times) / len(self.wait_times)
                
                # 更新平均评分差异
                if self.rating_differences:
                    # 保持最近1000条记录
                    if len(self.rating_differences) > 1000:
                        self.rating_differences = self.rating_differences[-1000:]
                    
                    self.match_stats['avg_rating_difference'] = sum(self.rating_differences) / len(self.rating_differences)
                
                # 计算匹配准确率
                total_matches = self.match_stats['successful_matches'] + self.match_stats['timeout_matches']
                if total_matches > 0:
                    self.match_stats['match_accuracy'] = (self.match_stats['successful_matches'] / total_matches) * 100
                
            except Exception as e:
                self.logger.error("更新匹配统计异常", error=str(e))
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """获取队列状态"""
        return {
            'queues': {
                match_type.value: len(queue)
                for match_type, queue in self.match_queues.items()
            },
            'total_waiting': sum(len(queue) for queue in self.match_queues.values()),
            'active_matches': len(self.match_pairs),
            'pending_invites': len(self.invites)
        }
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            'match_stats': self.match_stats.copy(),
            'queue_status': await self.get_queue_status(),
            'algorithm_config': self.match_algorithm_config.copy()
        }
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理所有数据
            for queue in self.match_queues.values():
                queue.clear()
            
            self.match_pairs.clear()
            self.match_history.clear()
            self.invites.clear()
            self.user_invites.clear()
            self.user_match_state.clear()
            self.wait_times.clear()
            self.rating_differences.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Match服务清理完成")
            
        except Exception as e:
            self.logger.error("Match服务清理失败", error=str(e))