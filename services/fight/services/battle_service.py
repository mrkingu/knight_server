"""
Battle业务服务

该模块实现了战斗功能的业务服务层，继承自BaseService，
负责处理战斗创建、战斗逻辑、战斗状态管理、战斗结算等核心业务逻辑。

主要功能：
- 战斗创建和初始化
- 战斗状态管理和同步
- 战斗动作处理和验证
- 战斗逻辑计算和处理
- 战斗结算和奖励分发
- 战斗数据持久化
- 战斗回放生成
- 战斗性能监控

技术特点：
- 使用异步处理提高性能
- 支持分布式事务处理
- 完善的状态机管理
- 详细的日志记录
- 支持实时战斗同步
- 高精度时间控制
"""

import asyncio
import time
import json
import uuid
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum
import random

from services.base import BaseService, ServiceException, transactional, cached, retry
from common.logger import logger


class BattleStatus(Enum):
    """战斗状态枚举"""
    WAITING = "waiting"
    PREPARING = "preparing"
    FIGHTING = "fighting"
    PAUSED = "paused"
    FINISHED = "finished"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class ActionType(Enum):
    """动作类型枚举"""
    MOVE = "move"
    ATTACK = "attack"
    SKILL = "skill"
    DEFEND = "defend"
    ITEM = "item"
    SURRENDER = "surrender"
    CHAT = "chat"


@dataclass
class BattleAction:
    """战斗动作数据结构"""
    action_id: str
    battle_id: str
    user_id: str
    action_type: ActionType
    target_id: Optional[str] = None
    skill_id: Optional[str] = None
    position: Optional[Dict[str, float]] = None
    timestamp: float = 0.0
    extra_data: Optional[Dict[str, Any]] = None


@dataclass
class BattleState:
    """战斗状态数据结构"""
    battle_id: str
    status: BattleStatus
    participants: List[str]
    current_turn: Optional[str] = None
    turn_number: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    winner: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


@dataclass
class BattleParticipant:
    """战斗参与者数据结构"""
    user_id: str
    character_id: str
    team: int
    position: Dict[str, float]
    health: int
    max_health: int
    mana: int
    max_mana: int
    status_effects: List[Dict[str, Any]]
    is_alive: bool = True
    last_action_time: float = 0.0


@dataclass
class BattleResult:
    """战斗结果数据结构"""
    battle_id: str
    winner: Optional[str]
    loser: Optional[str]
    duration: float
    actions_count: int
    damage_dealt: Dict[str, int]
    healing_done: Dict[str, int]
    skills_used: Dict[str, int]
    mvp: Optional[str] = None


class BattleService(BaseService):
    """
    Battle业务服务
    
    负责处理所有战斗相关的业务逻辑，包括战斗创建、状态管理、
    动作处理、结算等功能。
    """
    
    def __init__(self, max_concurrent_battles: int = 500,
                 battle_timeout: int = 600,
                 max_battle_duration: int = 1800,
                 battle_tick_rate: int = 20,
                 enable_battle_replay: bool = True):
        """
        初始化Battle服务
        
        Args:
            max_concurrent_battles: 最大并发战斗数
            battle_timeout: 战斗超时时间（秒）
            max_battle_duration: 最大战斗时长（秒）
            battle_tick_rate: 战斗tick频率（每秒）
            enable_battle_replay: 是否启用战斗回放
        """
        super().__init__()
        
        self.max_concurrent_battles = max_concurrent_battles
        self.battle_timeout = battle_timeout
        self.max_battle_duration = max_battle_duration
        self.battle_tick_rate = battle_tick_rate
        self.enable_battle_replay = enable_battle_replay
        
        # 战斗存储
        self.battles: Dict[str, BattleState] = {}
        self.battle_participants: Dict[str, List[BattleParticipant]] = {}
        self.battle_actions: Dict[str, List[BattleAction]] = {}
        
        # 战斗回放数据
        self.battle_replays: Dict[str, List[Dict[str, Any]]] = {}
        
        # 战斗统计
        self.battle_stats = {
            'total_battles': 0,
            'active_battles': 0,
            'finished_battles': 0,
            'cancelled_battles': 0,
            'timeout_battles': 0,
            'avg_battle_duration': 0.0,
            'total_actions': 0,
            'total_damage': 0
        }
        
        # 战斗时长记录
        self.battle_durations: List[float] = []
        
        # 战斗锁
        self.battle_locks: Dict[str, asyncio.Lock] = {}
        
        self.logger.info("Battle服务初始化完成",
                        max_concurrent_battles=max_concurrent_battles,
                        battle_timeout=battle_timeout,
                        battle_tick_rate=battle_tick_rate)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化基础服务
            await super().initialize()
            
            # 启动定时任务
            asyncio.create_task(self._battle_tick_loop())
            asyncio.create_task(self._cleanup_finished_battles())
            asyncio.create_task(self._check_battle_timeouts())
            
            self.logger.info("Battle服务初始化成功")
            
        except Exception as e:
            self.logger.error("Battle服务初始化失败", error=str(e))
            raise ServiceException(f"Battle服务初始化失败: {e}")
    
    @transactional
    async def create_battle(self, participants: List[str], 
                          match_type: str = "ranked") -> Optional[str]:
        """
        创建战斗
        
        Args:
            participants: 参与者列表
            match_type: 匹配类型
            
        Returns:
            Optional[str]: 战斗ID，创建失败返回None
        """
        try:
            # 检查并发数限制
            if len(self.battles) >= self.max_concurrent_battles:
                self.logger.warning("战斗数量已达上限", 
                                  current_count=len(self.battles),
                                  max_battles=self.max_concurrent_battles)
                return None
            
            # 验证参与者
            if len(participants) < 2:
                self.logger.warning("参与者数量不足", participants=participants)
                return None
            
            # 生成战斗ID
            battle_id = f"battle_{uuid.uuid4().hex[:12]}"
            
            # 创建战斗状态
            battle_state = BattleState(
                battle_id=battle_id,
                status=BattleStatus.WAITING,
                participants=participants,
                current_turn=None,
                turn_number=0,
                start_time=time.time(),
                end_time=0.0,
                winner=None,
                settings={
                    'match_type': match_type,
                    'max_duration': self.max_battle_duration,
                    'turn_timeout': 30
                }
            )
            
            # 创建战斗参与者
            battle_participants = []
            for i, user_id in enumerate(participants):
                participant = BattleParticipant(
                    user_id=user_id,
                    character_id=f"char_{user_id}",  # 简化实现
                    team=i,
                    position={'x': random.randint(0, 100), 'y': random.randint(0, 100)},
                    health=100,
                    max_health=100,
                    mana=50,
                    max_mana=50,
                    status_effects=[],
                    is_alive=True,
                    last_action_time=time.time()
                )
                battle_participants.append(participant)
            
            # 保存战斗数据
            self.battles[battle_id] = battle_state
            self.battle_participants[battle_id] = battle_participants
            self.battle_actions[battle_id] = []
            
            # 初始化战斗回放
            if self.enable_battle_replay:
                self.battle_replays[battle_id] = []
                await self._record_battle_event(battle_id, "battle_created", {
                    'participants': participants,
                    'match_type': match_type,
                    'timestamp': time.time()
                })
            
            # 创建战斗锁
            self.battle_locks[battle_id] = asyncio.Lock()
            
            # 更新统计
            self.battle_stats['total_battles'] += 1
            self.battle_stats['active_battles'] += 1
            
            self.logger.info("战斗创建成功", 
                           battle_id=battle_id,
                           participants=participants,
                           match_type=match_type)
            
            return battle_id
            
        except Exception as e:
            self.logger.error("创建战斗失败", 
                            participants=participants,
                            error=str(e))
            return None
    
    @transactional
    async def join_battle(self, battle_id: str, user_id: str, 
                        character_id: str) -> bool:
        """
        加入战斗
        
        Args:
            battle_id: 战斗ID
            user_id: 用户ID
            character_id: 角色ID
            
        Returns:
            bool: 是否成功加入
        """
        try:
            # 检查战斗是否存在
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                self.logger.warning("战斗不存在", battle_id=battle_id)
                return False
            
            # 检查用户是否已在战斗中
            if user_id not in battle_state.participants:
                self.logger.warning("用户不在战斗参与者列表中", 
                                  user_id=user_id,
                                  battle_id=battle_id)
                return False
            
            # 获取战斗锁
            async with self.battle_locks[battle_id]:
                # 更新参与者状态
                participants = self.battle_participants[battle_id]
                for participant in participants:
                    if participant.user_id == user_id:
                        participant.character_id = character_id
                        participant.last_action_time = time.time()
                        break
                
                # 检查是否所有参与者都已加入
                if self._all_participants_joined(battle_id):
                    # 开始战斗
                    await self._start_battle(battle_id)
                
                # 记录回放事件
                if self.enable_battle_replay:
                    await self._record_battle_event(battle_id, "player_joined", {
                        'user_id': user_id,
                        'character_id': character_id,
                        'timestamp': time.time()
                    })
                
                self.logger.info("用户加入战斗成功", 
                               user_id=user_id,
                               battle_id=battle_id,
                               character_id=character_id)
                
                return True
                
        except Exception as e:
            self.logger.error("加入战斗失败", 
                            battle_id=battle_id,
                            user_id=user_id,
                            error=str(e))
            return False
    
    @transactional
    async def leave_battle(self, battle_id: str, user_id: str) -> bool:
        """
        离开战斗
        
        Args:
            battle_id: 战斗ID
            user_id: 用户ID
            
        Returns:
            bool: 是否成功离开
        """
        try:
            # 检查战斗是否存在
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                self.logger.warning("战斗不存在", battle_id=battle_id)
                return False
            
            # 获取战斗锁
            async with self.battle_locks[battle_id]:
                # 移除参与者
                battle_state.participants.remove(user_id)
                
                # 更新参与者状态
                participants = self.battle_participants[battle_id]
                for participant in participants:
                    if participant.user_id == user_id:
                        participant.is_alive = False
                        break
                
                # 检查战斗是否应该结束
                if len(battle_state.participants) <= 1:
                    await self._finish_battle(battle_id, "player_left")
                
                # 记录回放事件
                if self.enable_battle_replay:
                    await self._record_battle_event(battle_id, "player_left", {
                        'user_id': user_id,
                        'timestamp': time.time()
                    })
                
                self.logger.info("用户离开战斗成功", 
                               user_id=user_id,
                               battle_id=battle_id)
                
                return True
                
        except Exception as e:
            self.logger.error("离开战斗失败", 
                            battle_id=battle_id,
                            user_id=user_id,
                            error=str(e))
            return False
    
    @transactional
    async def execute_action(self, action: BattleAction) -> Dict[str, Any]:
        """
        执行战斗动作
        
        Args:
            action: 战斗动作
            
        Returns:
            Dict[str, Any]: 动作执行结果
        """
        try:
            battle_id = action.battle_id
            
            # 检查战斗是否存在
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                return {'success': False, 'error': '战斗不存在'}
            
            # 检查战斗状态
            if battle_state.status != BattleStatus.FIGHTING:
                return {'success': False, 'error': '战斗状态不允许操作'}
            
            # 获取战斗锁
            async with self.battle_locks[battle_id]:
                # 验证动作
                if not await self._validate_action(action):
                    return {'success': False, 'error': '动作验证失败'}
                
                # 执行动作
                result = await self._process_action(action)
                
                # 记录动作
                self.battle_actions[battle_id].append(action)
                
                # 更新统计
                self.battle_stats['total_actions'] += 1
                
                # 记录回放事件
                if self.enable_battle_replay:
                    await self._record_battle_event(battle_id, "action_executed", {
                        'action': asdict(action),
                        'result': result,
                        'timestamp': time.time()
                    })
                
                # 检查战斗是否结束
                if result.get('battle_ended', False):
                    await self._finish_battle(battle_id, result.get('end_reason', 'unknown'))
                
                self.logger.info("战斗动作执行成功", 
                               action_id=action.action_id,
                               battle_id=battle_id,
                               user_id=action.user_id,
                               action_type=action.action_type.value)
                
                return result
                
        except Exception as e:
            self.logger.error("执行战斗动作失败", 
                            action_id=action.action_id,
                            battle_id=action.battle_id,
                            error=str(e))
            return {'success': False, 'error': f'动作执行失败: {e}'}
    
    @cached(ttl=60)
    async def get_battle_state(self, battle_id: str) -> Optional[BattleState]:
        """
        获取战斗状态
        
        Args:
            battle_id: 战斗ID
            
        Returns:
            Optional[BattleState]: 战斗状态，不存在返回None
        """
        try:
            battle_state = self.battles.get(battle_id)
            
            if battle_state:
                self.logger.info("获取战斗状态成功", 
                               battle_id=battle_id,
                               status=battle_state.status.value)
            else:
                self.logger.warning("战斗状态不存在", battle_id=battle_id)
            
            return battle_state
            
        except Exception as e:
            self.logger.error("获取战斗状态失败", 
                            battle_id=battle_id,
                            error=str(e))
            return None
    
    async def get_battle_info(self, battle_id: str) -> Optional[Dict[str, Any]]:
        """
        获取战斗详细信息
        
        Args:
            battle_id: 战斗ID
            
        Returns:
            Optional[Dict]: 战斗详细信息
        """
        try:
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                return None
            
            participants = self.battle_participants.get(battle_id, [])
            actions = self.battle_actions.get(battle_id, [])
            
            return {
                'battle_state': asdict(battle_state),
                'participants': [asdict(p) for p in participants],
                'actions_count': len(actions),
                'last_action_time': max([a.timestamp for a in actions]) if actions else battle_state.start_time
            }
            
        except Exception as e:
            self.logger.error("获取战斗详细信息失败", 
                            battle_id=battle_id,
                            error=str(e))
            return None
    
    async def settle_battle(self, battle_id: str) -> Dict[str, Any]:
        """
        战斗结算
        
        Args:
            battle_id: 战斗ID
            
        Returns:
            Dict[str, Any]: 结算结果
        """
        try:
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                return {'success': False, 'error': '战斗不存在'}
            
            if battle_state.status != BattleStatus.FINISHED:
                return {'success': False, 'error': '战斗尚未结束'}
            
            # 计算战斗结果
            result = await self._calculate_battle_result(battle_id)
            
            # 分发奖励
            rewards = await self._distribute_rewards(battle_id, result)
            
            # 更新排名
            await self._update_rankings(battle_id, result)
            
            self.logger.info("战斗结算完成", 
                           battle_id=battle_id,
                           winner=result.winner,
                           duration=result.duration)
            
            return {
                'success': True,
                'battle_id': battle_id,
                'result': asdict(result),
                'rewards': rewards
            }
            
        except Exception as e:
            self.logger.error("战斗结算失败", 
                            battle_id=battle_id,
                            error=str(e))
            return {'success': False, 'error': f'结算失败: {e}'}
    
    async def finish_battle(self, battle_id: str, reason: str) -> bool:
        """
        结束战斗
        
        Args:
            battle_id: 战斗ID
            reason: 结束原因
            
        Returns:
            bool: 是否成功结束
        """
        try:
            return await self._finish_battle(battle_id, reason)
            
        except Exception as e:
            self.logger.error("结束战斗失败", 
                            battle_id=battle_id,
                            error=str(e))
            return False
    
    async def process_battle_tick(self, battle_id: str) -> bool:
        """
        处理战斗tick
        
        Args:
            battle_id: 战斗ID
            
        Returns:
            bool: 处理是否成功
        """
        try:
            battle_state = self.battles.get(battle_id)
            if not battle_state or battle_state.status != BattleStatus.FIGHTING:
                return False
            
            # 获取战斗锁
            async with self.battle_locks[battle_id]:
                # 处理状态效果
                await self._process_status_effects(battle_id)
                
                # 处理持续伤害/治疗
                await self._process_continuous_effects(battle_id)
                
                # 检查胜利条件
                if await self._check_victory_condition(battle_id):
                    await self._finish_battle(battle_id, "victory")
                
                return True
                
        except Exception as e:
            self.logger.error("处理战斗tick失败", 
                            battle_id=battle_id,
                            error=str(e))
            return False
    
    async def _validate_action(self, action: BattleAction) -> bool:
        """验证战斗动作"""
        try:
            # 基础验证
            if not action.user_id or not action.battle_id:
                return False
            
            # 检查用户是否在战斗中
            battle_state = self.battles.get(action.battle_id)
            if not battle_state or action.user_id not in battle_state.participants:
                return False
            
            # 检查参与者状态
            participants = self.battle_participants.get(action.battle_id, [])
            participant = None
            for p in participants:
                if p.user_id == action.user_id:
                    participant = p
                    break
            
            if not participant or not participant.is_alive:
                return False
            
            # 技能动作验证
            if action.action_type == ActionType.SKILL:
                if not action.skill_id or not action.target_id:
                    return False
                
                # 检查魔法值
                if participant.mana < 10:  # 简化的魔法值检查
                    return False
            
            # 攻击动作验证
            if action.action_type == ActionType.ATTACK:
                if not action.target_id:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error("验证战斗动作失败", error=str(e))
            return False
    
    async def _process_action(self, action: BattleAction) -> Dict[str, Any]:
        """处理战斗动作"""
        try:
            battle_id = action.battle_id
            participants = self.battle_participants[battle_id]
            
            # 获取动作执行者
            actor = None
            for p in participants:
                if p.user_id == action.user_id:
                    actor = p
                    break
            
            if not actor:
                return {'success': False, 'error': '找不到动作执行者'}
            
            result = {'success': True}
            
            # 根据动作类型处理
            if action.action_type == ActionType.MOVE:
                result = await self._process_move_action(action, actor)
            elif action.action_type == ActionType.ATTACK:
                result = await self._process_attack_action(action, actor, participants)
            elif action.action_type == ActionType.SKILL:
                result = await self._process_skill_action(action, actor, participants)
            elif action.action_type == ActionType.DEFEND:
                result = await self._process_defend_action(action, actor)
            elif action.action_type == ActionType.ITEM:
                result = await self._process_item_action(action, actor)
            elif action.action_type == ActionType.SURRENDER:
                result = await self._process_surrender_action(action, actor)
                result['battle_ended'] = True
                result['end_reason'] = 'surrender'
            
            # 更新最后动作时间
            actor.last_action_time = time.time()
            
            return result
            
        except Exception as e:
            self.logger.error("处理战斗动作失败", error=str(e))
            return {'success': False, 'error': f'动作处理失败: {e}'}
    
    async def _process_move_action(self, action: BattleAction, 
                                 actor: BattleParticipant) -> Dict[str, Any]:
        """处理移动动作"""
        try:
            if action.position:
                actor.position = action.position
                
                return {
                    'success': True,
                    'action_type': 'move',
                    'new_position': action.position
                }
            else:
                return {'success': False, 'error': '无效的移动位置'}
                
        except Exception as e:
            self.logger.error("处理移动动作失败", error=str(e))
            return {'success': False, 'error': f'移动失败: {e}'}
    
    async def _process_attack_action(self, action: BattleAction, 
                                   actor: BattleParticipant,
                                   participants: List[BattleParticipant]) -> Dict[str, Any]:
        """处理攻击动作"""
        try:
            # 查找目标
            target = None
            for p in participants:
                if p.user_id == action.target_id:
                    target = p
                    break
            
            if not target or not target.is_alive:
                return {'success': False, 'error': '目标不存在或已死亡'}
            
            # 计算伤害
            base_damage = random.randint(15, 25)
            actual_damage = min(base_damage, target.health)
            
            # 应用伤害
            target.health -= actual_damage
            
            # 检查目标是否死亡
            if target.health <= 0:
                target.is_alive = False
                target.health = 0
            
            # 更新统计
            self.battle_stats['total_damage'] += actual_damage
            
            return {
                'success': True,
                'action_type': 'attack',
                'damage': actual_damage,
                'target_health': target.health,
                'target_alive': target.is_alive
            }
            
        except Exception as e:
            self.logger.error("处理攻击动作失败", error=str(e))
            return {'success': False, 'error': f'攻击失败: {e}'}
    
    async def _process_skill_action(self, action: BattleAction, 
                                  actor: BattleParticipant,
                                  participants: List[BattleParticipant]) -> Dict[str, Any]:
        """处理技能动作"""
        try:
            # 查找目标
            target = None
            for p in participants:
                if p.user_id == action.target_id:
                    target = p
                    break
            
            if not target or not target.is_alive:
                return {'success': False, 'error': '目标不存在或已死亡'}
            
            # 消耗魔法值
            mana_cost = 10
            if actor.mana < mana_cost:
                return {'success': False, 'error': '魔法值不足'}
            
            actor.mana -= mana_cost
            
            # 计算技能效果
            skill_damage = random.randint(25, 35)
            actual_damage = min(skill_damage, target.health)
            
            # 应用伤害
            target.health -= actual_damage
            
            # 检查目标是否死亡
            if target.health <= 0:
                target.is_alive = False
                target.health = 0
            
            # 更新统计
            self.battle_stats['total_damage'] += actual_damage
            
            return {
                'success': True,
                'action_type': 'skill',
                'skill_id': action.skill_id,
                'damage': actual_damage,
                'mana_cost': mana_cost,
                'target_health': target.health,
                'target_alive': target.is_alive,
                'cooldown': 5.0  # 5秒冷却
            }
            
        except Exception as e:
            self.logger.error("处理技能动作失败", error=str(e))
            return {'success': False, 'error': f'技能失败: {e}'}
    
    async def _process_defend_action(self, action: BattleAction, 
                                   actor: BattleParticipant) -> Dict[str, Any]:
        """处理防御动作"""
        try:
            # 添加防御状态效果
            defense_effect = {
                'type': 'defense',
                'duration': 3.0,
                'value': 0.5,
                'start_time': time.time()
            }
            
            actor.status_effects.append(defense_effect)
            
            return {
                'success': True,
                'action_type': 'defend',
                'effect': defense_effect
            }
            
        except Exception as e:
            self.logger.error("处理防御动作失败", error=str(e))
            return {'success': False, 'error': f'防御失败: {e}'}
    
    async def _process_item_action(self, action: BattleAction, 
                                 actor: BattleParticipant) -> Dict[str, Any]:
        """处理道具动作"""
        try:
            # 简化的道具处理
            item_id = action.extra_data.get('item_id', 'health_potion')
            
            if item_id == 'health_potion':
                # 恢复生命值
                heal_amount = min(30, actor.max_health - actor.health)
                actor.health += heal_amount
                
                return {
                    'success': True,
                    'action_type': 'item',
                    'item_id': item_id,
                    'heal_amount': heal_amount,
                    'current_health': actor.health
                }
            elif item_id == 'mana_potion':
                # 恢复魔法值
                mana_amount = min(20, actor.max_mana - actor.mana)
                actor.mana += mana_amount
                
                return {
                    'success': True,
                    'action_type': 'item',
                    'item_id': item_id,
                    'mana_amount': mana_amount,
                    'current_mana': actor.mana
                }
            else:
                return {'success': False, 'error': '未知道具'}
                
        except Exception as e:
            self.logger.error("处理道具动作失败", error=str(e))
            return {'success': False, 'error': f'道具使用失败: {e}'}
    
    async def _process_surrender_action(self, action: BattleAction, 
                                      actor: BattleParticipant) -> Dict[str, Any]:
        """处理投降动作"""
        try:
            # 标记为死亡
            actor.is_alive = False
            actor.health = 0
            
            return {
                'success': True,
                'action_type': 'surrender',
                'user_id': actor.user_id
            }
            
        except Exception as e:
            self.logger.error("处理投降动作失败", error=str(e))
            return {'success': False, 'error': f'投降失败: {e}'}
    
    async def _all_participants_joined(self, battle_id: str) -> bool:
        """检查所有参与者是否都已加入"""
        try:
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                return False
            
            participants = self.battle_participants.get(battle_id, [])
            
            # 检查参与者数量
            if len(participants) != len(battle_state.participants):
                return False
            
            # 检查每个参与者是否都已准备
            for participant in participants:
                if participant.character_id.startswith('char_'):
                    # 简化检查，实际应该检查更详细的准备状态
                    continue
                else:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error("检查参与者状态失败", error=str(e))
            return False
    
    async def _start_battle(self, battle_id: str):
        """开始战斗"""
        try:
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                return
            
            # 更新战斗状态
            battle_state.status = BattleStatus.FIGHTING
            battle_state.start_time = time.time()
            battle_state.current_turn = battle_state.participants[0]
            battle_state.turn_number = 1
            
            # 记录回放事件
            if self.enable_battle_replay:
                await self._record_battle_event(battle_id, "battle_started", {
                    'participants': battle_state.participants,
                    'first_turn': battle_state.current_turn,
                    'timestamp': time.time()
                })
            
            self.logger.info("战斗开始", 
                           battle_id=battle_id,
                           participants=battle_state.participants)
            
        except Exception as e:
            self.logger.error("开始战斗失败", 
                            battle_id=battle_id,
                            error=str(e))
    
    async def _finish_battle(self, battle_id: str, reason: str) -> bool:
        """结束战斗"""
        try:
            battle_state = self.battles.get(battle_id)
            if not battle_state:
                return False
            
            # 更新战斗状态
            battle_state.status = BattleStatus.FINISHED
            battle_state.end_time = time.time()
            
            # 确定胜利者
            if reason == "victory":
                battle_state.winner = await self._determine_winner(battle_id)
            elif reason == "surrender":
                battle_state.winner = await self._determine_winner_by_surrender(battle_id)
            
            # 记录战斗时长
            duration = battle_state.end_time - battle_state.start_time
            self.battle_durations.append(duration)
            
            # 更新统计
            self.battle_stats['finished_battles'] += 1
            self.battle_stats['active_battles'] -= 1
            
            if self.battle_durations:
                self.battle_stats['avg_battle_duration'] = sum(self.battle_durations) / len(self.battle_durations)
            
            # 记录回放事件
            if self.enable_battle_replay:
                await self._record_battle_event(battle_id, "battle_finished", {
                    'winner': battle_state.winner,
                    'reason': reason,
                    'duration': duration,
                    'timestamp': time.time()
                })
            
            self.logger.info("战斗结束", 
                           battle_id=battle_id,
                           winner=battle_state.winner,
                           reason=reason,
                           duration=duration)
            
            return True
            
        except Exception as e:
            self.logger.error("结束战斗失败", 
                            battle_id=battle_id,
                            error=str(e))
            return False
    
    async def _determine_winner(self, battle_id: str) -> Optional[str]:
        """确定胜利者"""
        try:
            participants = self.battle_participants.get(battle_id, [])
            
            # 找到存活的参与者
            alive_participants = [p for p in participants if p.is_alive]
            
            if len(alive_participants) == 1:
                return alive_participants[0].user_id
            elif len(alive_participants) == 0:
                # 平局
                return None
            else:
                # 根据剩余生命值确定
                winner = max(alive_participants, key=lambda p: p.health)
                return winner.user_id
                
        except Exception as e:
            self.logger.error("确定胜利者失败", error=str(e))
            return None
    
    async def _determine_winner_by_surrender(self, battle_id: str) -> Optional[str]:
        """根据投降确定胜利者"""
        try:
            participants = self.battle_participants.get(battle_id, [])
            
            # 找到存活的参与者
            alive_participants = [p for p in participants if p.is_alive]
            
            if len(alive_participants) == 1:
                return alive_participants[0].user_id
            else:
                return None
                
        except Exception as e:
            self.logger.error("根据投降确定胜利者失败", error=str(e))
            return None
    
    async def _check_victory_condition(self, battle_id: str) -> bool:
        """检查胜利条件"""
        try:
            participants = self.battle_participants.get(battle_id, [])
            
            # 计算存活参与者数量
            alive_count = sum(1 for p in participants if p.is_alive)
            
            # 如果只有一个或没有存活的参与者，战斗结束
            return alive_count <= 1
            
        except Exception as e:
            self.logger.error("检查胜利条件失败", error=str(e))
            return False
    
    async def _process_status_effects(self, battle_id: str):
        """处理状态效果"""
        try:
            participants = self.battle_participants.get(battle_id, [])
            current_time = time.time()
            
            for participant in participants:
                if not participant.is_alive:
                    continue
                
                # 处理每个状态效果
                expired_effects = []
                
                for effect in participant.status_effects:
                    if current_time - effect['start_time'] >= effect['duration']:
                        expired_effects.append(effect)
                
                # 移除过期效果
                for effect in expired_effects:
                    participant.status_effects.remove(effect)
                    
        except Exception as e:
            self.logger.error("处理状态效果失败", error=str(e))
    
    async def _process_continuous_effects(self, battle_id: str):
        """处理持续效果"""
        try:
            participants = self.battle_participants.get(battle_id, [])
            
            for participant in participants:
                if not participant.is_alive:
                    continue
                
                # 自然恢复魔法值
                if participant.mana < participant.max_mana:
                    participant.mana = min(participant.max_mana, participant.mana + 1)
                    
        except Exception as e:
            self.logger.error("处理持续效果失败", error=str(e))
    
    async def _calculate_battle_result(self, battle_id: str) -> BattleResult:
        """计算战斗结果"""
        try:
            battle_state = self.battles.get(battle_id)
            actions = self.battle_actions.get(battle_id, [])
            
            # 统计数据
            damage_dealt = {}
            healing_done = {}
            skills_used = {}
            
            for action in actions:
                user_id = action.user_id
                
                if user_id not in damage_dealt:
                    damage_dealt[user_id] = 0
                    healing_done[user_id] = 0
                    skills_used[user_id] = 0
                
                if action.action_type == ActionType.ATTACK:
                    damage_dealt[user_id] += 20  # 平均伤害
                elif action.action_type == ActionType.SKILL:
                    damage_dealt[user_id] += 30  # 平均技能伤害
                    skills_used[user_id] += 1
                elif action.action_type == ActionType.ITEM:
                    healing_done[user_id] += 25  # 平均治疗
            
            # 确定MVP
            mvp = max(damage_dealt.items(), key=lambda x: x[1])[0] if damage_dealt else None
            
            # 确定胜负
            winner = battle_state.winner
            loser = None
            if winner and len(battle_state.participants) == 2:
                loser = next(p for p in battle_state.participants if p != winner)
            
            result = BattleResult(
                battle_id=battle_id,
                winner=winner,
                loser=loser,
                duration=battle_state.end_time - battle_state.start_time,
                actions_count=len(actions),
                damage_dealt=damage_dealt,
                healing_done=healing_done,
                skills_used=skills_used,
                mvp=mvp
            )
            
            return result
            
        except Exception as e:
            self.logger.error("计算战斗结果失败", error=str(e))
            return BattleResult(
                battle_id=battle_id,
                winner=None,
                loser=None,
                duration=0,
                actions_count=0,
                damage_dealt={},
                healing_done={},
                skills_used={}
            )
    
    async def _distribute_rewards(self, battle_id: str, 
                                result: BattleResult) -> Dict[str, Any]:
        """分发奖励"""
        try:
            rewards = {}
            
            # 胜利者奖励
            if result.winner:
                rewards[result.winner] = {
                    'experience': 100,
                    'gold': 50,
                    'items': ['victory_token'],
                    'rating_change': 25
                }
            
            # 失败者奖励
            if result.loser:
                rewards[result.loser] = {
                    'experience': 25,
                    'gold': 10,
                    'items': [],
                    'rating_change': -10
                }
            
            # MVP额外奖励
            if result.mvp and result.mvp in rewards:
                rewards[result.mvp]['experience'] += 25
                rewards[result.mvp]['gold'] += 15
                rewards[result.mvp]['items'].append('mvp_medal')
            
            return rewards
            
        except Exception as e:
            self.logger.error("分发奖励失败", error=str(e))
            return {}
    
    async def _update_rankings(self, battle_id: str, result: BattleResult):
        """更新排名"""
        try:
            # 这里应该调用排名服务更新玩家排名
            # 由于是模拟实现，只记录日志
            self.logger.info("更新排名", 
                           battle_id=battle_id,
                           winner=result.winner,
                           loser=result.loser)
            
        except Exception as e:
            self.logger.error("更新排名失败", error=str(e))
    
    async def _record_battle_event(self, battle_id: str, event_type: str, 
                                 event_data: Dict[str, Any]):
        """记录战斗事件"""
        try:
            if battle_id not in self.battle_replays:
                self.battle_replays[battle_id] = []
            
            event = {
                'event_type': event_type,
                'timestamp': time.time(),
                'data': event_data
            }
            
            self.battle_replays[battle_id].append(event)
            
        except Exception as e:
            self.logger.error("记录战斗事件失败", error=str(e))
    
    async def _battle_tick_loop(self):
        """战斗tick循环"""
        while True:
            try:
                await asyncio.sleep(1.0 / self.battle_tick_rate)
                
                # 处理所有活跃战斗
                for battle_id in list(self.battles.keys()):
                    await self.process_battle_tick(battle_id)
                    
            except Exception as e:
                self.logger.error("战斗tick循环异常", error=str(e))
    
    async def _cleanup_finished_battles(self):
        """清理已完成的战斗"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                expired_battles = []
                
                for battle_id, battle_state in self.battles.items():
                    # 清理30分钟前结束的战斗
                    if (battle_state.status == BattleStatus.FINISHED and
                        current_time - battle_state.end_time > 1800):
                        expired_battles.append(battle_id)
                
                for battle_id in expired_battles:
                    # 清理战斗数据
                    del self.battles[battle_id]
                    
                    if battle_id in self.battle_participants:
                        del self.battle_participants[battle_id]
                    
                    if battle_id in self.battle_actions:
                        del self.battle_actions[battle_id]
                    
                    if battle_id in self.battle_replays:
                        del self.battle_replays[battle_id]
                    
                    if battle_id in self.battle_locks:
                        del self.battle_locks[battle_id]
                
                if expired_battles:
                    self.logger.info("清理过期战斗", count=len(expired_battles))
                    
            except Exception as e:
                self.logger.error("清理已完成战斗异常", error=str(e))
    
    async def _check_battle_timeouts(self):
        """检查战斗超时"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                
                current_time = time.time()
                timeout_battles = []
                
                for battle_id, battle_state in self.battles.items():
                    # 检查战斗是否超时
                    if (battle_state.status == BattleStatus.FIGHTING and
                        current_time - battle_state.start_time > self.max_battle_duration):
                        timeout_battles.append(battle_id)
                
                for battle_id in timeout_battles:
                    await self._finish_battle(battle_id, "timeout")
                    self.battle_stats['timeout_battles'] += 1
                
                if timeout_battles:
                    self.logger.info("处理超时战斗", count=len(timeout_battles))
                    
            except Exception as e:
                self.logger.error("检查战斗超时异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            'battle_stats': self.battle_stats.copy(),
            'battle_info': {
                'total_battles': len(self.battles),
                'active_battles': len([b for b in self.battles.values() if b.status == BattleStatus.FIGHTING]),
                'total_participants': sum(len(p) for p in self.battle_participants.values()),
                'total_actions': sum(len(a) for a in self.battle_actions.values())
            },
            'performance': {
                'avg_battle_duration': self.battle_stats['avg_battle_duration'],
                'actions_per_battle': self.battle_stats['total_actions'] / max(1, self.battle_stats['total_battles'])
            }
        }
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理所有数据
            self.battles.clear()
            self.battle_participants.clear()
            self.battle_actions.clear()
            self.battle_replays.clear()
            self.battle_locks.clear()
            self.battle_durations.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Battle服务清理完成")
            
        except Exception as e:
            self.logger.error("Battle服务清理失败", error=str(e))