"""
Battle控制器

该模块实现了战斗功能的控制器，继承自BaseController，
负责处理战斗操作、技能释放、战斗状态管理、战斗结算等战斗相关的业务逻辑。

主要功能：
- 处理战斗操作请求
- 管理技能释放和冷却
- 战斗状态同步
- 战斗结算处理
- 战斗回放管理
- 伤害计算和处理
- 战斗事件处理
- 战斗数据统计

装饰器支持：
- @handler 绑定消息协议号到处理方法
- 参数自动验证和解析
- 响应消息自动构建

技术特点：
- 使用MVC架构模式
- 异步处理提高性能
- 完善的异常处理
- 详细的日志记录
- 支持实时战斗状态同步
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum

from services.base import BaseController, ControllerException, ValidationException
from common.logger import logger
from common.decorator.handler_decorator import handler, controller


class BattleStatus(Enum):
    """战斗状态枚举"""
    WAITING = "waiting"        # 等待中
    PREPARING = "preparing"    # 准备中
    FIGHTING = "fighting"      # 战斗中
    PAUSED = "paused"         # 暂停
    FINISHED = "finished"      # 已结束
    TIMEOUT = "timeout"        # 超时
    CANCELLED = "cancelled"    # 已取消


class ActionType(Enum):
    """战斗动作类型枚举"""
    MOVE = "move"             # 移动
    ATTACK = "attack"         # 攻击
    SKILL = "skill"           # 技能
    DEFEND = "defend"         # 防御
    ITEM = "item"             # 使用道具
    SURRENDER = "surrender"   # 投降
    CHAT = "chat"             # 聊天


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
class SkillCast:
    """技能释放数据结构"""
    skill_id: str
    caster_id: str
    target_id: str
    battle_id: str
    cast_time: float
    cooldown: float
    mana_cost: int
    damage: int
    effect_type: str
    success: bool = True


@controller(name="BattleController")
class BattleController(BaseController):
    """
    Battle控制器
    
    负责处理所有战斗相关的请求，包括战斗操作、技能释放、
    战斗状态管理、战斗结算等功能。
    """
    
    def __init__(self):
        """初始化Battle控制器"""
        super().__init__()
        
        # 服务依赖
        self.battle_service = None
        self.skill_service = None
        
        # 战斗状态缓存
        self.battle_states: Dict[str, BattleState] = {}
        
        # 用户战斗映射
        self.user_battles: Dict[str, str] = {}  # user_id -> battle_id
        
        # 动作队列
        self.action_queues: Dict[str, List[BattleAction]] = {}  # battle_id -> actions
        
        # 技能冷却追踪
        self.skill_cooldowns: Dict[str, Dict[str, float]] = {}  # user_id -> skill_id -> cooldown_end_time
        
        # 战斗统计
        self.battle_stats = {
            'total_battles': 0,
            'active_battles': 0,
            'finished_battles': 0,
            'cancelled_battles': 0,
            'total_actions': 0,
            'total_skills_cast': 0,
            'total_damage_dealt': 0
        }
        
        # 性能监控
        self.processing_times: List[float] = []
        
        self.logger.info("Battle控制器初始化完成")
    
    async def initialize(self):
        """初始化控制器"""
        try:
            # 获取服务依赖
            self.battle_service = self.get_service('battle_service')
            self.skill_service = self.get_service('skill_service')
            
            # 启动定时任务
            asyncio.create_task(self._update_cooldowns())
            asyncio.create_task(self._process_battle_ticks())
            asyncio.create_task(self._cleanup_finished_battles())
            
            self.logger.info("Battle控制器初始化成功")
            
        except Exception as e:
            self.logger.error("Battle控制器初始化失败", error=str(e))
            raise ControllerException(f"Battle控制器初始化失败: {e}")
    
    @handler(message_id=8101)
    async def join_battle(self, request, context):
        """
        加入战斗
        
        Args:
            request: 包含battle_id, user_id, character_id的请求
            context: 请求上下文
            
        Returns:
            战斗加入结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'battle_id') or not request.battle_id:
                raise ValidationException("战斗ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'character_id') or not request.character_id:
                raise ValidationException("角色ID不能为空")
            
            battle_id = request.battle_id
            user_id = request.user_id
            character_id = request.character_id
            
            # 检查用户是否已在其他战斗中
            if user_id in self.user_battles:
                current_battle = self.user_battles[user_id]
                if current_battle != battle_id:
                    raise ValidationException(f"用户已在战斗 {current_battle} 中")
            
            # 加入战斗
            success = await self.battle_service.join_battle(battle_id, user_id, character_id)
            
            if success:
                # 更新用户战斗映射
                self.user_battles[user_id] = battle_id
                
                # 获取战斗状态
                battle_state = await self.battle_service.get_battle_state(battle_id)
                if battle_state:
                    self.battle_states[battle_id] = battle_state
                
                # 初始化动作队列
                if battle_id not in self.action_queues:
                    self.action_queues[battle_id] = []
                
                # 初始化技能冷却
                if user_id not in self.skill_cooldowns:
                    self.skill_cooldowns[user_id] = {}
                
                self.battle_stats['active_battles'] = len(self.battle_states)
                
                self.logger.info("用户加入战斗成功", 
                               user_id=user_id,
                               battle_id=battle_id,
                               character_id=character_id)
                
                return {
                    'status': 'success',
                    'battle_id': battle_id,
                    'battle_state': asdict(battle_state) if battle_state else None
                }
            else:
                self.logger.error("用户加入战斗失败", 
                                user_id=user_id,
                                battle_id=battle_id)
                
                return {
                    'status': 'failed',
                    'error': '加入战斗失败'
                }
                
        except ValidationException as e:
            self.logger.warning("加入战斗参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("加入战斗异常", error=str(e))
            raise ControllerException(f"加入战斗失败: {e}")
    
    @handler(message_id=8102)
    async def battle_action(self, request, context):
        """
        战斗操作
        
        Args:
            request: 包含battle_id, user_id, action_type, target_id等的请求
            context: 请求上下文
            
        Returns:
            战斗操作结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'battle_id') or not request.battle_id:
                raise ValidationException("战斗ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            if not hasattr(request, 'action_type') or not request.action_type:
                raise ValidationException("动作类型不能为空")
            
            battle_id = request.battle_id
            user_id = request.user_id
            
            # 检查用户是否在战斗中
            if user_id not in self.user_battles or self.user_battles[user_id] != battle_id:
                raise ValidationException("用户不在指定战斗中")
            
            # 检查战斗状态
            battle_state = self.battle_states.get(battle_id)
            if not battle_state:
                raise ValidationException("战斗不存在")
            
            if battle_state.status != BattleStatus.FIGHTING:
                raise ValidationException(f"战斗状态不允许操作: {battle_state.status}")
            
            # 创建战斗动作
            action = BattleAction(
                action_id=f"action_{int(time.time() * 1000000)}",
                battle_id=battle_id,
                user_id=user_id,
                action_type=ActionType(request.action_type),
                target_id=getattr(request, 'target_id', None),
                skill_id=getattr(request, 'skill_id', None),
                position=getattr(request, 'position', None),
                timestamp=time.time(),
                extra_data=getattr(request, 'extra_data', None)
            )
            
            # 验证动作
            if not await self._validate_action(action):
                raise ValidationException("动作验证失败")
            
            # 执行动作
            result = await self.battle_service.execute_action(action)
            
            if result.get('success', False):
                # 添加到动作队列
                self.action_queues[battle_id].append(action)
                
                # 更新统计
                self.battle_stats['total_actions'] += 1
                
                # 如果是技能动作，更新技能统计
                if action.action_type == ActionType.SKILL:
                    self.battle_stats['total_skills_cast'] += 1
                    
                    # 更新技能冷却
                    await self._update_skill_cooldown(user_id, action.skill_id)
                
                self.logger.info("战斗动作执行成功", 
                               action_id=action.action_id,
                               battle_id=battle_id,
                               user_id=user_id,
                               action_type=action.action_type.value)
                
                return {
                    'status': 'success',
                    'action_id': action.action_id,
                    'result': result
                }
            else:
                self.logger.error("战斗动作执行失败", 
                                action_id=action.action_id,
                                battle_id=battle_id,
                                error=result.get('error'))
                
                return {
                    'status': 'failed',
                    'error': result.get('error', '动作执行失败')
                }
                
        except ValidationException as e:
            self.logger.warning("战斗动作参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("战斗动作异常", error=str(e))
            raise ControllerException(f"战斗动作失败: {e}")
    
    @handler(message_id=8103)
    async def get_battle_state(self, request, context):
        """
        获取战斗状态
        
        Args:
            request: 包含battle_id的请求
            context: 请求上下文
            
        Returns:
            战斗状态信息
        """
        try:
            # 参数验证
            if not hasattr(request, 'battle_id') or not request.battle_id:
                raise ValidationException("战斗ID不能为空")
            
            battle_id = request.battle_id
            
            # 从缓存获取状态
            battle_state = self.battle_states.get(battle_id)
            
            if not battle_state:
                # 从服务获取
                battle_state = await self.battle_service.get_battle_state(battle_id)
                
                if battle_state:
                    self.battle_states[battle_id] = battle_state
            
            if battle_state:
                # 获取战斗详细信息
                battle_info = await self.battle_service.get_battle_info(battle_id)
                
                self.logger.info("获取战斗状态成功", 
                               battle_id=battle_id,
                               status=battle_state.status.value)
                
                return {
                    'status': 'success',
                    'battle_state': asdict(battle_state),
                    'battle_info': battle_info
                }
            else:
                self.logger.warning("战斗不存在", battle_id=battle_id)
                
                return {
                    'status': 'failed',
                    'error': '战斗不存在'
                }
                
        except ValidationException as e:
            self.logger.warning("获取战斗状态参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取战斗状态异常", error=str(e))
            raise ControllerException(f"获取战斗状态失败: {e}")
    
    @handler(message_id=8104)
    async def leave_battle(self, request, context):
        """
        离开战斗
        
        Args:
            request: 包含battle_id, user_id的请求
            context: 请求上下文
            
        Returns:
            离开战斗结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'battle_id') or not request.battle_id:
                raise ValidationException("战斗ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            battle_id = request.battle_id
            user_id = request.user_id
            
            # 检查用户是否在战斗中
            if user_id not in self.user_battles or self.user_battles[user_id] != battle_id:
                raise ValidationException("用户不在指定战斗中")
            
            # 离开战斗
            success = await self.battle_service.leave_battle(battle_id, user_id)
            
            if success:
                # 清理用户战斗映射
                del self.user_battles[user_id]
                
                # 清理技能冷却
                if user_id in self.skill_cooldowns:
                    del self.skill_cooldowns[user_id]
                
                # 检查战斗是否结束
                battle_state = self.battle_states.get(battle_id)
                if battle_state and len(battle_state.participants) <= 1:
                    # 战斗结束
                    await self._finish_battle(battle_id, "player_left")
                
                self.logger.info("用户离开战斗成功", 
                               user_id=user_id,
                               battle_id=battle_id)
                
                return {
                    'status': 'success',
                    'battle_id': battle_id
                }
            else:
                self.logger.error("用户离开战斗失败", 
                                user_id=user_id,
                                battle_id=battle_id)
                
                return {
                    'status': 'failed',
                    'error': '离开战斗失败'
                }
                
        except ValidationException as e:
            self.logger.warning("离开战斗参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("离开战斗异常", error=str(e))
            raise ControllerException(f"离开战斗失败: {e}")
    
    @handler(message_id=8201)
    async def cast_skill(self, request, context):
        """
        释放技能
        
        Args:
            request: 包含skill_id, target_id, battle_id的请求
            context: 请求上下文
            
        Returns:
            技能释放结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'skill_id') or not request.skill_id:
                raise ValidationException("技能ID不能为空")
            if not hasattr(request, 'target_id') or not request.target_id:
                raise ValidationException("目标ID不能为空")
            if not hasattr(request, 'battle_id') or not request.battle_id:
                raise ValidationException("战斗ID不能为空")
            if not hasattr(request, 'user_id') or not request.user_id:
                raise ValidationException("用户ID不能为空")
            
            skill_id = request.skill_id
            target_id = request.target_id
            battle_id = request.battle_id
            user_id = request.user_id
            
            # 检查用户是否在战斗中
            if user_id not in self.user_battles or self.user_battles[user_id] != battle_id:
                raise ValidationException("用户不在指定战斗中")
            
            # 检查技能冷却
            if await self._is_skill_on_cooldown(user_id, skill_id):
                raise ValidationException("技能正在冷却中")
            
            # 创建技能释放对象
            skill_cast = SkillCast(
                skill_id=skill_id,
                caster_id=user_id,
                target_id=target_id,
                battle_id=battle_id,
                cast_time=time.time(),
                cooldown=0.0,  # 将由技能服务设置
                mana_cost=0,   # 将由技能服务设置
                damage=0,      # 将由技能服务计算
                effect_type="damage"  # 将由技能服务设置
            )
            
            # 释放技能
            result = await self.skill_service.cast_skill(skill_cast)
            
            if result.get('success', False):
                # 更新技能冷却
                await self._update_skill_cooldown(user_id, skill_id)
                
                # 更新统计
                self.battle_stats['total_skills_cast'] += 1
                damage = result.get('damage', 0)
                if damage > 0:
                    self.battle_stats['total_damage_dealt'] += damage
                
                self.logger.info("技能释放成功", 
                               skill_id=skill_id,
                               caster_id=user_id,
                               target_id=target_id,
                               battle_id=battle_id,
                               damage=damage)
                
                return {
                    'status': 'success',
                    'skill_id': skill_id,
                    'damage': damage,
                    'effect': result.get('effect'),
                    'cooldown': result.get('cooldown', 0)
                }
            else:
                self.logger.error("技能释放失败", 
                                skill_id=skill_id,
                                caster_id=user_id,
                                error=result.get('error'))
                
                return {
                    'status': 'failed',
                    'error': result.get('error', '技能释放失败')
                }
                
        except ValidationException as e:
            self.logger.warning("技能释放参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("技能释放异常", error=str(e))
            raise ControllerException(f"技能释放失败: {e}")
    
    @handler(message_id=8301)
    async def settle_battle(self, request, context):
        """
        战斗结算
        
        Args:
            request: 包含battle_id的请求
            context: 请求上下文
            
        Returns:
            战斗结算结果
        """
        try:
            # 参数验证
            if not hasattr(request, 'battle_id') or not request.battle_id:
                raise ValidationException("战斗ID不能为空")
            
            battle_id = request.battle_id
            
            # 检查战斗状态
            battle_state = self.battle_states.get(battle_id)
            if not battle_state:
                raise ValidationException("战斗不存在")
            
            if battle_state.status != BattleStatus.FINISHED:
                raise ValidationException("战斗尚未结束")
            
            # 执行结算
            settlement_result = await self.battle_service.settle_battle(battle_id)
            
            if settlement_result.get('success', False):
                # 更新统计
                self.battle_stats['finished_battles'] += 1
                
                # 清理战斗数据
                await self._cleanup_battle_data(battle_id)
                
                self.logger.info("战斗结算成功", 
                               battle_id=battle_id,
                               winner=settlement_result.get('winner'))
                
                return {
                    'status': 'success',
                    'battle_id': battle_id,
                    'settlement': settlement_result
                }
            else:
                self.logger.error("战斗结算失败", 
                                battle_id=battle_id,
                                error=settlement_result.get('error'))
                
                return {
                    'status': 'failed',
                    'error': settlement_result.get('error', '战斗结算失败')
                }
                
        except ValidationException as e:
            self.logger.warning("战斗结算参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("战斗结算异常", error=str(e))
            raise ControllerException(f"战斗结算失败: {e}")
    
    async def _validate_action(self, action: BattleAction) -> bool:
        """验证战斗动作"""
        try:
            # 基础验证
            if not action.user_id or not action.battle_id:
                return False
            
            # 技能动作验证
            if action.action_type == ActionType.SKILL:
                if not action.skill_id:
                    return False
                
                # 检查技能冷却
                if await self._is_skill_on_cooldown(action.user_id, action.skill_id):
                    return False
                
                # 验证技能是否可用
                if not await self.skill_service.is_skill_available(action.user_id, action.skill_id):
                    return False
            
            # 攻击动作验证
            if action.action_type == ActionType.ATTACK:
                if not action.target_id:
                    return False
            
            # 移动动作验证
            if action.action_type == ActionType.MOVE:
                if not action.position:
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error("验证战斗动作失败", error=str(e))
            return False
    
    async def _is_skill_on_cooldown(self, user_id: str, skill_id: str) -> bool:
        """检查技能是否在冷却中"""
        try:
            if user_id not in self.skill_cooldowns:
                return False
            
            cooldown_end = self.skill_cooldowns[user_id].get(skill_id, 0)
            return time.time() < cooldown_end
            
        except Exception as e:
            self.logger.error("检查技能冷却失败", error=str(e))
            return False
    
    async def _update_skill_cooldown(self, user_id: str, skill_id: str):
        """更新技能冷却"""
        try:
            # 获取技能冷却时间
            cooldown_duration = await self.skill_service.get_skill_cooldown(skill_id)
            
            if user_id not in self.skill_cooldowns:
                self.skill_cooldowns[user_id] = {}
            
            self.skill_cooldowns[user_id][skill_id] = time.time() + cooldown_duration
            
        except Exception as e:
            self.logger.error("更新技能冷却失败", error=str(e))
    
    async def _finish_battle(self, battle_id: str, reason: str):
        """结束战斗"""
        try:
            battle_state = self.battle_states.get(battle_id)
            if not battle_state:
                return
            
            # 更新战斗状态
            battle_state.status = BattleStatus.FINISHED
            battle_state.end_time = time.time()
            
            # 通知战斗服务
            await self.battle_service.finish_battle(battle_id, reason)
            
            self.logger.info("战斗结束", 
                           battle_id=battle_id,
                           reason=reason)
            
        except Exception as e:
            self.logger.error("结束战斗失败", 
                            battle_id=battle_id,
                            error=str(e))
    
    async def _cleanup_battle_data(self, battle_id: str):
        """清理战斗数据"""
        try:
            # 清理战斗状态
            if battle_id in self.battle_states:
                del self.battle_states[battle_id]
            
            # 清理动作队列
            if battle_id in self.action_queues:
                del self.action_queues[battle_id]
            
            # 清理用户战斗映射
            users_to_remove = [
                user_id for user_id, bid in self.user_battles.items()
                if bid == battle_id
            ]
            
            for user_id in users_to_remove:
                del self.user_battles[user_id]
                
                # 清理技能冷却
                if user_id in self.skill_cooldowns:
                    del self.skill_cooldowns[user_id]
            
            self.logger.info("战斗数据清理完成", battle_id=battle_id)
            
        except Exception as e:
            self.logger.error("清理战斗数据失败", 
                            battle_id=battle_id,
                            error=str(e))
    
    async def _update_cooldowns(self):
        """更新技能冷却"""
        while True:
            try:
                await asyncio.sleep(1)  # 每秒更新一次
                
                current_time = time.time()
                
                # 清理过期的技能冷却
                for user_id, cooldowns in list(self.skill_cooldowns.items()):
                    expired_skills = [
                        skill_id for skill_id, cooldown_end in cooldowns.items()
                        if current_time >= cooldown_end
                    ]
                    
                    for skill_id in expired_skills:
                        del cooldowns[skill_id]
                    
                    # 如果用户没有冷却的技能，删除记录
                    if not cooldowns:
                        del self.skill_cooldowns[user_id]
                        
            except Exception as e:
                self.logger.error("更新技能冷却异常", error=str(e))
    
    async def _process_battle_ticks(self):
        """处理战斗tick"""
        while True:
            try:
                await asyncio.sleep(0.05)  # 20Hz tick rate
                
                # 处理所有活跃战斗
                for battle_id, battle_state in self.battle_states.items():
                    if battle_state.status == BattleStatus.FIGHTING:
                        # 处理战斗tick
                        await self.battle_service.process_battle_tick(battle_id)
                        
            except Exception as e:
                self.logger.error("处理战斗tick异常", error=str(e))
    
    async def _cleanup_finished_battles(self):
        """清理已完成的战斗"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                expired_battles = []
                
                for battle_id, battle_state in self.battle_states.items():
                    # 清理30分钟前结束的战斗
                    if (battle_state.status == BattleStatus.FINISHED and
                        current_time - battle_state.end_time > 1800):
                        expired_battles.append(battle_id)
                
                for battle_id in expired_battles:
                    await self._cleanup_battle_data(battle_id)
                
                if expired_battles:
                    self.logger.info("清理过期战斗", count=len(expired_battles))
                    
            except Exception as e:
                self.logger.error("清理已完成战斗异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            'battle_stats': self.battle_stats.copy(),
            'state_info': {
                'active_battles': len(self.battle_states),
                'user_battles': len(self.user_battles),
                'action_queues': len(self.action_queues),
                'skill_cooldowns': len(self.skill_cooldowns)
            },
            'performance': {
                'avg_processing_time': sum(self.processing_times) / len(self.processing_times) if self.processing_times else 0,
                'total_requests': len(self.processing_times)
            }
        }
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            # 清理所有数据
            self.battle_states.clear()
            self.user_battles.clear()
            self.action_queues.clear()
            self.skill_cooldowns.clear()
            self.processing_times.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Battle控制器清理完成")
            
        except Exception as e:
            self.logger.error("Battle控制器清理失败", error=str(e))