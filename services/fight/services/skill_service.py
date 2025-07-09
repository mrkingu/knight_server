"""
Skill业务服务

该模块实现了技能系统的业务服务层，继承自BaseService，
负责处理技能释放、技能冷却、技能升级、技能组合等核心业务逻辑。

主要功能：
- 技能释放和验证
- 技能冷却管理
- 技能升级系统
- 技能组合和连招
- 技能效果计算
- 技能数据管理
- 技能统计分析
- 技能配置管理

技术特点：
- 使用异步处理提高性能
- 支持复杂技能效果计算
- 完善的技能状态管理
- 详细的日志记录
- 支持技能热更新
- 高精度时间控制
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, asdict
from enum import Enum
import random
import math

from services.base import BaseService, ServiceException, cached, monitored
from common.logger import logger


class SkillType(Enum):
    """技能类型枚举"""
    ACTIVE = "active"      # 主动技能
    PASSIVE = "passive"    # 被动技能
    COMBO = "combo"        # 组合技能
    ULTIMATE = "ultimate"  # 终极技能


class SkillElement(Enum):
    """技能元素枚举"""
    NONE = "none"
    FIRE = "fire"
    WATER = "water"
    EARTH = "earth"
    AIR = "air"
    LIGHT = "light"
    DARK = "dark"


class SkillTargetType(Enum):
    """技能目标类型枚举"""
    SELF = "self"
    ENEMY = "enemy"
    ALLY = "ally"
    AREA = "area"
    ALL = "all"


@dataclass
class SkillDefinition:
    """技能定义数据结构"""
    skill_id: str
    name: str
    description: str
    skill_type: SkillType
    element: SkillElement
    target_type: SkillTargetType
    cooldown: float
    mana_cost: int
    cast_time: float
    range: float
    damage: int
    healing: int
    effects: List[Dict[str, Any]]
    level_requirements: Dict[int, Dict[str, Any]]
    max_level: int = 10


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
    healing: int
    effect_type: str
    success: bool = True
    effects_applied: List[Dict[str, Any]] = None


@dataclass
class UserSkill:
    """用户技能数据结构"""
    user_id: str
    skill_id: str
    level: int
    experience: int
    last_used: float
    cooldown_end: float
    is_equipped: bool = False
    slot_position: int = 0


@dataclass
class SkillCombo:
    """技能组合数据结构"""
    combo_id: str
    name: str
    skill_sequence: List[str]
    timing_window: float
    bonus_damage: int
    bonus_effects: List[Dict[str, Any]]
    required_level: int


class SkillService(BaseService):
    """
    Skill业务服务
    
    负责处理所有技能相关的业务逻辑，包括技能释放、冷却管理、
    升级系统、组合技能等功能。
    """
    
    def __init__(self, max_skills_per_character: int = 8,
                 skill_cooldown_precision: float = 0.1,
                 enable_skill_combo: bool = True):
        """
        初始化Skill服务
        
        Args:
            max_skills_per_character: 每个角色最大技能数
            skill_cooldown_precision: 技能冷却精度（秒）
            enable_skill_combo: 是否启用技能组合
        """
        super().__init__()
        
        self.max_skills_per_character = max_skills_per_character
        self.skill_cooldown_precision = skill_cooldown_precision
        self.enable_skill_combo = enable_skill_combo
        
        # 技能定义库
        self.skill_definitions: Dict[str, SkillDefinition] = {}
        
        # 用户技能数据
        self.user_skills: Dict[str, List[UserSkill]] = {}  # user_id -> skills
        
        # 技能冷却追踪
        self.skill_cooldowns: Dict[str, Dict[str, float]] = {}  # user_id -> skill_id -> cooldown_end
        
        # 技能组合定义
        self.skill_combos: Dict[str, SkillCombo] = {}
        
        # 技能组合状态追踪
        self.combo_states: Dict[str, Dict[str, Any]] = {}  # user_id -> combo_state
        
        # 技能使用历史
        self.skill_usage_history: Dict[str, List[Dict[str, Any]]] = {}
        
        # 技能统计
        self.skill_stats = {
            'total_casts': 0,
            'successful_casts': 0,
            'failed_casts': 0,
            'total_damage': 0,
            'total_healing': 0,
            'combo_executions': 0,
            'skill_upgrades': 0
        }
        
        # 技能效果计算器
        self.effect_calculators: Dict[str, callable] = {}
        
        self.logger.info("Skill服务初始化完成",
                        max_skills_per_character=max_skills_per_character,
                        skill_cooldown_precision=skill_cooldown_precision,
                        enable_skill_combo=enable_skill_combo)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化基础服务
            await super().initialize()
            
            # 加载技能定义
            await self._load_skill_definitions()
            
            # 加载技能组合
            if self.enable_skill_combo:
                await self._load_skill_combos()
            
            # 初始化效果计算器
            await self._initialize_effect_calculators()
            
            # 启动定时任务
            asyncio.create_task(self._cooldown_update_loop())
            asyncio.create_task(self._cleanup_expired_combos())
            
            self.logger.info("Skill服务初始化成功")
            
        except Exception as e:
            self.logger.error("Skill服务初始化失败", error=str(e))
            raise ServiceException(f"Skill服务初始化失败: {e}")
    
    @monitored
    async def cast_skill(self, skill_cast: SkillCast) -> Dict[str, Any]:
        """
        释放技能
        
        Args:
            skill_cast: 技能释放对象
            
        Returns:
            Dict[str, Any]: 技能释放结果
        """
        try:
            # 验证技能释放
            validation_result = await self._validate_skill_cast(skill_cast)
            if not validation_result['valid']:
                self.skill_stats['failed_casts'] += 1
                return {
                    'success': False,
                    'error': validation_result['error']
                }
            
            # 获取技能定义
            skill_def = self.skill_definitions.get(skill_cast.skill_id)
            if not skill_def:
                self.skill_stats['failed_casts'] += 1
                return {
                    'success': False,
                    'error': '技能不存在'
                }
            
            # 获取用户技能信息
            user_skill = await self._get_user_skill(skill_cast.caster_id, skill_cast.skill_id)
            if not user_skill:
                self.skill_stats['failed_casts'] += 1
                return {
                    'success': False,
                    'error': '用户未学习该技能'
                }
            
            # 计算技能效果
            effect_result = await self._calculate_skill_effects(skill_cast, skill_def, user_skill)
            
            # 应用技能冷却
            await self._apply_skill_cooldown(skill_cast.caster_id, skill_cast.skill_id, skill_def.cooldown)
            
            # 记录技能使用
            await self._record_skill_usage(skill_cast, effect_result)
            
            # 检查技能组合
            combo_result = None
            if self.enable_skill_combo:
                combo_result = await self._check_skill_combo(skill_cast.caster_id, skill_cast.skill_id)
            
            # 更新统计
            self.skill_stats['total_casts'] += 1
            self.skill_stats['successful_casts'] += 1
            self.skill_stats['total_damage'] += effect_result.get('damage', 0)
            self.skill_stats['total_healing'] += effect_result.get('healing', 0)
            
            if combo_result and combo_result.get('executed'):
                self.skill_stats['combo_executions'] += 1
            
            self.logger.info("技能释放成功", 
                           skill_id=skill_cast.skill_id,
                           caster_id=skill_cast.caster_id,
                           target_id=skill_cast.target_id,
                           damage=effect_result.get('damage', 0),
                           healing=effect_result.get('healing', 0))
            
            return {
                'success': True,
                'skill_id': skill_cast.skill_id,
                'damage': effect_result.get('damage', 0),
                'healing': effect_result.get('healing', 0),
                'effects': effect_result.get('effects', []),
                'cooldown': skill_def.cooldown,
                'combo': combo_result
            }
            
        except Exception as e:
            self.skill_stats['failed_casts'] += 1
            self.logger.error("技能释放失败", 
                            skill_id=skill_cast.skill_id,
                            caster_id=skill_cast.caster_id,
                            error=str(e))
            return {
                'success': False,
                'error': f'技能释放失败: {e}'
            }
    
    async def get_skill_cooldown(self, skill_id: str) -> float:
        """
        获取技能冷却时间
        
        Args:
            skill_id: 技能ID
            
        Returns:
            float: 冷却时间（秒）
        """
        try:
            skill_def = self.skill_definitions.get(skill_id)
            if skill_def:
                return skill_def.cooldown
            else:
                self.logger.warning("技能不存在", skill_id=skill_id)
                return 0.0
                
        except Exception as e:
            self.logger.error("获取技能冷却失败", 
                            skill_id=skill_id,
                            error=str(e))
            return 0.0
    
    async def is_skill_available(self, user_id: str, skill_id: str) -> bool:
        """
        检查技能是否可用
        
        Args:
            user_id: 用户ID
            skill_id: 技能ID
            
        Returns:
            bool: 是否可用
        """
        try:
            # 检查用户是否拥有技能
            user_skill = await self._get_user_skill(user_id, skill_id)
            if not user_skill:
                return False
            
            # 检查技能是否装备
            if not user_skill.is_equipped:
                return False
            
            # 检查技能冷却
            if await self._is_skill_on_cooldown(user_id, skill_id):
                return False
            
            return True
            
        except Exception as e:
            self.logger.error("检查技能可用性失败", 
                            user_id=user_id,
                            skill_id=skill_id,
                            error=str(e))
            return False
    
    async def learn_skill(self, user_id: str, skill_id: str) -> bool:
        """
        学习技能
        
        Args:
            user_id: 用户ID
            skill_id: 技能ID
            
        Returns:
            bool: 是否成功学习
        """
        try:
            # 检查技能是否存在
            skill_def = self.skill_definitions.get(skill_id)
            if not skill_def:
                self.logger.warning("技能不存在", skill_id=skill_id)
                return False
            
            # 检查用户是否已学习
            if await self._get_user_skill(user_id, skill_id):
                self.logger.warning("用户已学习该技能", 
                                  user_id=user_id,
                                  skill_id=skill_id)
                return False
            
            # 检查技能数量限制
            user_skills = self.user_skills.get(user_id, [])
            if len(user_skills) >= self.max_skills_per_character:
                self.logger.warning("用户技能数量已达上限", 
                                  user_id=user_id,
                                  skill_count=len(user_skills))
                return False
            
            # 创建用户技能
            user_skill = UserSkill(
                user_id=user_id,
                skill_id=skill_id,
                level=1,
                experience=0,
                last_used=0.0,
                cooldown_end=0.0,
                is_equipped=False,
                slot_position=0
            )
            
            # 添加到用户技能列表
            if user_id not in self.user_skills:
                self.user_skills[user_id] = []
            self.user_skills[user_id].append(user_skill)
            
            self.logger.info("技能学习成功", 
                           user_id=user_id,
                           skill_id=skill_id)
            
            return True
            
        except Exception as e:
            self.logger.error("学习技能失败", 
                            user_id=user_id,
                            skill_id=skill_id,
                            error=str(e))
            return False
    
    async def upgrade_skill(self, user_id: str, skill_id: str) -> bool:
        """
        升级技能
        
        Args:
            user_id: 用户ID
            skill_id: 技能ID
            
        Returns:
            bool: 是否成功升级
        """
        try:
            # 获取用户技能
            user_skill = await self._get_user_skill(user_id, skill_id)
            if not user_skill:
                self.logger.warning("用户未学习该技能", 
                                  user_id=user_id,
                                  skill_id=skill_id)
                return False
            
            # 获取技能定义
            skill_def = self.skill_definitions.get(skill_id)
            if not skill_def:
                self.logger.warning("技能不存在", skill_id=skill_id)
                return False
            
            # 检查是否已达最大等级
            if user_skill.level >= skill_def.max_level:
                self.logger.warning("技能已达最大等级", 
                                  user_id=user_id,
                                  skill_id=skill_id,
                                  level=user_skill.level)
                return False
            
            # 检查升级条件
            next_level = user_skill.level + 1
            level_req = skill_def.level_requirements.get(next_level)
            if level_req:
                required_exp = level_req.get('experience', 0)
                if user_skill.experience < required_exp:
                    self.logger.warning("经验不足无法升级", 
                                      user_id=user_id,
                                      skill_id=skill_id,
                                      current_exp=user_skill.experience,
                                      required_exp=required_exp)
                    return False
            
            # 升级技能
            user_skill.level += 1
            user_skill.experience = 0  # 重置经验
            
            # 更新统计
            self.skill_stats['skill_upgrades'] += 1
            
            self.logger.info("技能升级成功", 
                           user_id=user_id,
                           skill_id=skill_id,
                           new_level=user_skill.level)
            
            return True
            
        except Exception as e:
            self.logger.error("升级技能失败", 
                            user_id=user_id,
                            skill_id=skill_id,
                            error=str(e))
            return False
    
    async def equip_skill(self, user_id: str, skill_id: str, slot_position: int) -> bool:
        """
        装备技能
        
        Args:
            user_id: 用户ID
            skill_id: 技能ID
            slot_position: 装备位置
            
        Returns:
            bool: 是否成功装备
        """
        try:
            # 获取用户技能
            user_skill = await self._get_user_skill(user_id, skill_id)
            if not user_skill:
                self.logger.warning("用户未学习该技能", 
                                  user_id=user_id,
                                  skill_id=skill_id)
                return False
            
            # 检查装备位置
            if slot_position < 0 or slot_position >= self.max_skills_per_character:
                self.logger.warning("装备位置无效", 
                                  slot_position=slot_position,
                                  max_slots=self.max_skills_per_character)
                return False
            
            # 检查位置是否已被占用
            user_skills = self.user_skills.get(user_id, [])
            for skill in user_skills:
                if skill.is_equipped and skill.slot_position == slot_position:
                    # 取消装备已有技能
                    skill.is_equipped = False
                    skill.slot_position = 0
                    break
            
            # 装备技能
            user_skill.is_equipped = True
            user_skill.slot_position = slot_position
            
            self.logger.info("技能装备成功", 
                           user_id=user_id,
                           skill_id=skill_id,
                           slot_position=slot_position)
            
            return True
            
        except Exception as e:
            self.logger.error("装备技能失败", 
                            user_id=user_id,
                            skill_id=skill_id,
                            error=str(e))
            return False
    
    async def get_user_skills(self, user_id: str) -> List[Dict[str, Any]]:
        """
        获取用户技能列表
        
        Args:
            user_id: 用户ID
            
        Returns:
            List[Dict]: 用户技能列表
        """
        try:
            user_skills = self.user_skills.get(user_id, [])
            
            result = []
            for skill in user_skills:
                skill_def = self.skill_definitions.get(skill.skill_id)
                if skill_def:
                    result.append({
                        'skill_id': skill.skill_id,
                        'name': skill_def.name,
                        'level': skill.level,
                        'experience': skill.experience,
                        'is_equipped': skill.is_equipped,
                        'slot_position': skill.slot_position,
                        'cooldown_remaining': await self._get_cooldown_remaining(user_id, skill.skill_id)
                    })
            
            return result
            
        except Exception as e:
            self.logger.error("获取用户技能列表失败", 
                            user_id=user_id,
                            error=str(e))
            return []
    
    async def _validate_skill_cast(self, skill_cast: SkillCast) -> Dict[str, Any]:
        """验证技能释放"""
        try:
            # 检查技能是否存在
            skill_def = self.skill_definitions.get(skill_cast.skill_id)
            if not skill_def:
                return {'valid': False, 'error': '技能不存在'}
            
            # 检查用户是否拥有技能
            if not await self._get_user_skill(skill_cast.caster_id, skill_cast.skill_id):
                return {'valid': False, 'error': '用户未学习该技能'}
            
            # 检查技能冷却
            if await self._is_skill_on_cooldown(skill_cast.caster_id, skill_cast.skill_id):
                return {'valid': False, 'error': '技能正在冷却中'}
            
            # 检查魔法值（简化检查）
            if skill_def.mana_cost > 0:
                # 这里应该检查实际的魔法值
                pass
            
            return {'valid': True}
            
        except Exception as e:
            self.logger.error("验证技能释放失败", error=str(e))
            return {'valid': False, 'error': f'验证失败: {e}'}
    
    async def _get_user_skill(self, user_id: str, skill_id: str) -> Optional[UserSkill]:
        """获取用户技能"""
        try:
            user_skills = self.user_skills.get(user_id, [])
            for skill in user_skills:
                if skill.skill_id == skill_id:
                    return skill
            return None
            
        except Exception as e:
            self.logger.error("获取用户技能失败", error=str(e))
            return None
    
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
    
    async def _apply_skill_cooldown(self, user_id: str, skill_id: str, cooldown: float):
        """应用技能冷却"""
        try:
            if user_id not in self.skill_cooldowns:
                self.skill_cooldowns[user_id] = {}
            
            self.skill_cooldowns[user_id][skill_id] = time.time() + cooldown
            
        except Exception as e:
            self.logger.error("应用技能冷却失败", error=str(e))
    
    async def _get_cooldown_remaining(self, user_id: str, skill_id: str) -> float:
        """获取剩余冷却时间"""
        try:
            if user_id not in self.skill_cooldowns:
                return 0.0
            
            cooldown_end = self.skill_cooldowns[user_id].get(skill_id, 0)
            remaining = cooldown_end - time.time()
            return max(0.0, remaining)
            
        except Exception as e:
            self.logger.error("获取剩余冷却时间失败", error=str(e))
            return 0.0
    
    async def _calculate_skill_effects(self, skill_cast: SkillCast, 
                                     skill_def: SkillDefinition,
                                     user_skill: UserSkill) -> Dict[str, Any]:
        """计算技能效果"""
        try:
            # 基础伤害计算
            base_damage = skill_def.damage
            level_multiplier = 1.0 + (user_skill.level - 1) * 0.1
            final_damage = int(base_damage * level_multiplier)
            
            # 基础治疗计算
            base_healing = skill_def.healing
            final_healing = int(base_healing * level_multiplier)
            
            # 计算附加效果
            effects = []
            for effect_def in skill_def.effects:
                effect = await self._calculate_effect(effect_def, user_skill.level)
                if effect:
                    effects.append(effect)
            
            # 元素伤害加成
            if skill_def.element != SkillElement.NONE:
                element_bonus = await self._calculate_element_bonus(skill_def.element, user_skill.level)
                final_damage = int(final_damage * element_bonus)
            
            # 暴击计算
            crit_chance = 0.05 + (user_skill.level - 1) * 0.01  # 基础5%暴击，每级增加1%
            is_critical = random.random() < crit_chance
            
            if is_critical:
                final_damage = int(final_damage * 1.5)
                final_healing = int(final_healing * 1.5)
                effects.append({
                    'type': 'critical',
                    'value': 1.5,
                    'description': '暴击！'
                })
            
            return {
                'damage': final_damage,
                'healing': final_healing,
                'effects': effects,
                'is_critical': is_critical
            }
            
        except Exception as e:
            self.logger.error("计算技能效果失败", error=str(e))
            return {
                'damage': 0,
                'healing': 0,
                'effects': [],
                'is_critical': False
            }
    
    async def _calculate_effect(self, effect_def: Dict[str, Any], level: int) -> Optional[Dict[str, Any]]:
        """计算单个效果"""
        try:
            effect_type = effect_def.get('type')
            base_value = effect_def.get('value', 0)
            duration = effect_def.get('duration', 0)
            
            # 等级影响
            level_multiplier = 1.0 + (level - 1) * 0.05
            final_value = base_value * level_multiplier
            
            return {
                'type': effect_type,
                'value': final_value,
                'duration': duration,
                'description': effect_def.get('description', '')
            }
            
        except Exception as e:
            self.logger.error("计算效果失败", error=str(e))
            return None
    
    async def _calculate_element_bonus(self, element: SkillElement, level: int) -> float:
        """计算元素伤害加成"""
        try:
            # 元素基础加成
            element_bonuses = {
                SkillElement.FIRE: 1.1,
                SkillElement.WATER: 1.05,
                SkillElement.EARTH: 1.15,
                SkillElement.AIR: 1.08,
                SkillElement.LIGHT: 1.12,
                SkillElement.DARK: 1.12
            }
            
            base_bonus = element_bonuses.get(element, 1.0)
            level_bonus = 1.0 + (level - 1) * 0.02
            
            return base_bonus * level_bonus
            
        except Exception as e:
            self.logger.error("计算元素加成失败", error=str(e))
            return 1.0
    
    async def _record_skill_usage(self, skill_cast: SkillCast, effect_result: Dict[str, Any]):
        """记录技能使用"""
        try:
            user_id = skill_cast.caster_id
            
            if user_id not in self.skill_usage_history:
                self.skill_usage_history[user_id] = []
            
            usage_record = {
                'skill_id': skill_cast.skill_id,
                'target_id': skill_cast.target_id,
                'damage': effect_result.get('damage', 0),
                'healing': effect_result.get('healing', 0),
                'is_critical': effect_result.get('is_critical', False),
                'timestamp': time.time()
            }
            
            self.skill_usage_history[user_id].append(usage_record)
            
            # 限制历史记录数量
            if len(self.skill_usage_history[user_id]) > 100:
                self.skill_usage_history[user_id] = self.skill_usage_history[user_id][-100:]
            
            # 更新技能经验
            user_skill = await self._get_user_skill(user_id, skill_cast.skill_id)
            if user_skill:
                user_skill.experience += 10  # 每次使用增加10经验
                user_skill.last_used = time.time()
            
        except Exception as e:
            self.logger.error("记录技能使用失败", error=str(e))
    
    async def _check_skill_combo(self, user_id: str, skill_id: str) -> Optional[Dict[str, Any]]:
        """检查技能组合"""
        try:
            if not self.enable_skill_combo:
                return None
            
            # 获取用户组合状态
            if user_id not in self.combo_states:
                self.combo_states[user_id] = {
                    'sequence': [],
                    'last_skill_time': 0,
                    'active_combo': None
                }
            
            combo_state = self.combo_states[user_id]
            current_time = time.time()
            
            # 检查时间窗口
            if current_time - combo_state['last_skill_time'] > 3.0:  # 3秒时间窗口
                combo_state['sequence'] = []
                combo_state['active_combo'] = None
            
            # 添加当前技能到序列
            combo_state['sequence'].append(skill_id)
            combo_state['last_skill_time'] = current_time
            
            # 检查是否匹配任何组合
            for combo_id, combo_def in self.skill_combos.items():
                if await self._check_combo_match(combo_state['sequence'], combo_def):
                    # 执行组合
                    combo_result = await self._execute_combo(user_id, combo_def)
                    
                    # 重置序列
                    combo_state['sequence'] = []
                    combo_state['active_combo'] = combo_id
                    
                    return combo_result
            
            return None
            
        except Exception as e:
            self.logger.error("检查技能组合失败", error=str(e))
            return None
    
    async def _check_combo_match(self, sequence: List[str], combo_def: SkillCombo) -> bool:
        """检查组合匹配"""
        try:
            required_sequence = combo_def.skill_sequence
            
            if len(sequence) < len(required_sequence):
                return False
            
            # 检查最后几个技能是否匹配
            recent_sequence = sequence[-len(required_sequence):]
            return recent_sequence == required_sequence
            
        except Exception as e:
            self.logger.error("检查组合匹配失败", error=str(e))
            return False
    
    async def _execute_combo(self, user_id: str, combo_def: SkillCombo) -> Dict[str, Any]:
        """执行技能组合"""
        try:
            return {
                'executed': True,
                'combo_id': combo_def.combo_id,
                'combo_name': combo_def.name,
                'bonus_damage': combo_def.bonus_damage,
                'bonus_effects': combo_def.bonus_effects
            }
            
        except Exception as e:
            self.logger.error("执行技能组合失败", error=str(e))
            return {'executed': False}
    
    async def _load_skill_definitions(self):
        """加载技能定义"""
        try:
            # 基础技能定义
            basic_skills = [
                SkillDefinition(
                    skill_id="fireball",
                    name="火球术",
                    description="释放一个火球攻击敌人",
                    skill_type=SkillType.ACTIVE,
                    element=SkillElement.FIRE,
                    target_type=SkillTargetType.ENEMY,
                    cooldown=3.0,
                    mana_cost=15,
                    cast_time=1.0,
                    range=10.0,
                    damage=30,
                    healing=0,
                    effects=[
                        {
                            'type': 'burn',
                            'value': 5,
                            'duration': 3.0,
                            'description': '燃烧效果'
                        }
                    ],
                    level_requirements={
                        2: {'experience': 100},
                        3: {'experience': 250},
                        4: {'experience': 500},
                        5: {'experience': 1000}
                    },
                    max_level=5
                ),
                SkillDefinition(
                    skill_id="heal",
                    name="治疗术",
                    description="恢复目标的生命值",
                    skill_type=SkillType.ACTIVE,
                    element=SkillElement.LIGHT,
                    target_type=SkillTargetType.ALLY,
                    cooldown=5.0,
                    mana_cost=20,
                    cast_time=2.0,
                    range=8.0,
                    damage=0,
                    healing=40,
                    effects=[
                        {
                            'type': 'regeneration',
                            'value': 5,
                            'duration': 5.0,
                            'description': '生命恢复'
                        }
                    ],
                    level_requirements={
                        2: {'experience': 150},
                        3: {'experience': 300},
                        4: {'experience': 600},
                        5: {'experience': 1200}
                    },
                    max_level=5
                ),
                SkillDefinition(
                    skill_id="lightning_bolt",
                    name="闪电箭",
                    description="释放闪电攻击敌人",
                    skill_type=SkillType.ACTIVE,
                    element=SkillElement.AIR,
                    target_type=SkillTargetType.ENEMY,
                    cooldown=4.0,
                    mana_cost=25,
                    cast_time=0.5,
                    range=12.0,
                    damage=45,
                    healing=0,
                    effects=[
                        {
                            'type': 'stun',
                            'value': 1,
                            'duration': 1.0,
                            'description': '眩晕效果'
                        }
                    ],
                    level_requirements={
                        2: {'experience': 200},
                        3: {'experience': 400},
                        4: {'experience': 800},
                        5: {'experience': 1600}
                    },
                    max_level=5
                ),
                SkillDefinition(
                    skill_id="shield",
                    name="护盾术",
                    description="为目标提供护盾保护",
                    skill_type=SkillType.ACTIVE,
                    element=SkillElement.EARTH,
                    target_type=SkillTargetType.ALLY,
                    cooldown=8.0,
                    mana_cost=30,
                    cast_time=1.5,
                    range=6.0,
                    damage=0,
                    healing=0,
                    effects=[
                        {
                            'type': 'shield',
                            'value': 50,
                            'duration': 10.0,
                            'description': '护盾保护'
                        }
                    ],
                    level_requirements={
                        2: {'experience': 180},
                        3: {'experience': 350},
                        4: {'experience': 700},
                        5: {'experience': 1400}
                    },
                    max_level=5
                )
            ]
            
            # 保存技能定义
            for skill in basic_skills:
                self.skill_definitions[skill.skill_id] = skill
            
            self.logger.info("技能定义加载完成", 
                           skill_count=len(self.skill_definitions))
            
        except Exception as e:
            self.logger.error("加载技能定义失败", error=str(e))
    
    async def _load_skill_combos(self):
        """加载技能组合"""
        try:
            # 基础技能组合
            basic_combos = [
                SkillCombo(
                    combo_id="fire_lightning",
                    name="火雷连击",
                    skill_sequence=["fireball", "lightning_bolt"],
                    timing_window=3.0,
                    bonus_damage=20,
                    bonus_effects=[
                        {
                            'type': 'explosion',
                            'value': 15,
                            'duration': 0,
                            'description': '火雷爆炸'
                        }
                    ],
                    required_level=3
                ),
                SkillCombo(
                    combo_id="heal_shield",
                    name="治疗护盾",
                    skill_sequence=["heal", "shield"],
                    timing_window=2.0,
                    bonus_damage=0,
                    bonus_effects=[
                        {
                            'type': 'blessing',
                            'value': 10,
                            'duration': 15.0,
                            'description': '神圣祝福'
                        }
                    ],
                    required_level=2
                )
            ]
            
            # 保存技能组合
            for combo in basic_combos:
                self.skill_combos[combo.combo_id] = combo
            
            self.logger.info("技能组合加载完成", 
                           combo_count=len(self.skill_combos))
            
        except Exception as e:
            self.logger.error("加载技能组合失败", error=str(e))
    
    async def _initialize_effect_calculators(self):
        """初始化效果计算器"""
        try:
            # 基础效果计算器
            self.effect_calculators = {
                'burn': self._calculate_burn_effect,
                'regeneration': self._calculate_regeneration_effect,
                'stun': self._calculate_stun_effect,
                'shield': self._calculate_shield_effect
            }
            
            self.logger.info("效果计算器初始化完成", 
                           calculator_count=len(self.effect_calculators))
            
        except Exception as e:
            self.logger.error("初始化效果计算器失败", error=str(e))
    
    async def _calculate_burn_effect(self, effect_def: Dict[str, Any], level: int) -> Dict[str, Any]:
        """计算燃烧效果"""
        base_damage = effect_def.get('value', 0)
        duration = effect_def.get('duration', 0)
        level_multiplier = 1.0 + (level - 1) * 0.1
        
        return {
            'type': 'burn',
            'damage_per_second': int(base_damage * level_multiplier),
            'duration': duration,
            'description': f'每秒造成{int(base_damage * level_multiplier)}点燃烧伤害'
        }
    
    async def _calculate_regeneration_effect(self, effect_def: Dict[str, Any], level: int) -> Dict[str, Any]:
        """计算恢复效果"""
        base_healing = effect_def.get('value', 0)
        duration = effect_def.get('duration', 0)
        level_multiplier = 1.0 + (level - 1) * 0.1
        
        return {
            'type': 'regeneration',
            'healing_per_second': int(base_healing * level_multiplier),
            'duration': duration,
            'description': f'每秒恢复{int(base_healing * level_multiplier)}点生命值'
        }
    
    async def _calculate_stun_effect(self, effect_def: Dict[str, Any], level: int) -> Dict[str, Any]:
        """计算眩晕效果"""
        duration = effect_def.get('duration', 0)
        
        return {
            'type': 'stun',
            'duration': duration,
            'description': f'眩晕{duration}秒'
        }
    
    async def _calculate_shield_effect(self, effect_def: Dict[str, Any], level: int) -> Dict[str, Any]:
        """计算护盾效果"""
        base_shield = effect_def.get('value', 0)
        duration = effect_def.get('duration', 0)
        level_multiplier = 1.0 + (level - 1) * 0.15
        
        return {
            'type': 'shield',
            'shield_value': int(base_shield * level_multiplier),
            'duration': duration,
            'description': f'获得{int(base_shield * level_multiplier)}点护盾'
        }
    
    async def _cooldown_update_loop(self):
        """冷却更新循环"""
        while True:
            try:
                await asyncio.sleep(self.skill_cooldown_precision)
                
                current_time = time.time()
                
                # 清理过期的冷却
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
                self.logger.error("冷却更新循环异常", error=str(e))
    
    async def _cleanup_expired_combos(self):
        """清理过期的组合状态"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟清理一次
                
                current_time = time.time()
                
                for user_id, combo_state in list(self.combo_states.items()):
                    # 清理超过5分钟未活动的组合状态
                    if current_time - combo_state['last_skill_time'] > 300:
                        del self.combo_states[user_id]
                        
            except Exception as e:
                self.logger.error("清理过期组合状态异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            'skill_stats': self.skill_stats.copy(),
            'skill_info': {
                'total_skills': len(self.skill_definitions),
                'total_combos': len(self.skill_combos),
                'users_with_skills': len(self.user_skills),
                'active_cooldowns': sum(len(cooldowns) for cooldowns in self.skill_cooldowns.values())
            },
            'performance': {
                'success_rate': (self.skill_stats['successful_casts'] / 
                               max(1, self.skill_stats['total_casts'])) * 100,
                'combo_rate': (self.skill_stats['combo_executions'] / 
                             max(1, self.skill_stats['successful_casts'])) * 100
            }
        }
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理所有数据
            self.skill_definitions.clear()
            self.user_skills.clear()
            self.skill_cooldowns.clear()
            self.skill_combos.clear()
            self.combo_states.clear()
            self.skill_usage_history.clear()
            self.effect_calculators.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Skill服务清理完成")
            
        except Exception as e:
            self.logger.error("Skill服务清理失败", error=str(e))