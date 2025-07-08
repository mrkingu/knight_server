"""
物品业务服务

该模块实现了物品相关的业务逻辑服务，继承自BaseService，
负责背包管理、物品使用、装备系统、物品交易、合成系统等功能。

主要功能：
- 背包管理和查询
- 物品使用和消耗
- 装备系统管理
- 物品交易系统
- 物品合成系统
- 物品模板管理

业务特点：
- 支持多种物品类型
- 完整的装备系统
- 灵活的交易机制
- 强大的合成系统
- 详细的物品统计
"""

import asyncio
import time
import json
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from collections import defaultdict

from services.base import BaseService, ServiceConfig
from services.base import ServiceException, transactional, cached, retry
from common.logger import logger


class ItemType(Enum):
    """物品类型"""
    CONSUMABLE = "consumable"  # 消耗品
    EQUIPMENT = "equipment"    # 装备
    MATERIAL = "material"      # 材料
    QUEST = "quest"           # 任务物品
    CURRENCY = "currency"     # 货币
    CARD = "card"             # 卡牌
    GIFT = "gift"             # 礼品


class ItemRarity(Enum):
    """物品稀有度"""
    COMMON = "common"         # 普通
    UNCOMMON = "uncommon"     # 非凡
    RARE = "rare"            # 稀有
    EPIC = "epic"            # 史诗
    LEGENDARY = "legendary"   # 传说
    MYTHIC = "mythic"        # 神话


class EquipmentSlot(Enum):
    """装备槽位"""
    WEAPON = "weapon"         # 武器
    ARMOR = "armor"          # 护甲
    HELMET = "helmet"        # 头盔
    BOOTS = "boots"          # 靴子
    GLOVES = "gloves"        # 手套
    RING = "ring"            # 戒指
    NECKLACE = "necklace"    # 项链
    ACCESSORY = "accessory"  # 饰品


class TradeStatus(Enum):
    """交易状态"""
    PENDING = "pending"       # 待确认
    CONFIRMED = "confirmed"   # 已确认
    COMPLETED = "completed"   # 已完成
    CANCELLED = "cancelled"   # 已取消
    EXPIRED = "expired"       # 已过期


@dataclass
class ItemServiceConfig(ServiceConfig):
    """物品服务配置"""
    # 背包配置
    default_inventory_capacity: int = 100
    max_inventory_capacity: int = 1000
    inventory_expand_step: int = 10
    
    # 装备配置
    max_equipment_level: int = 100
    equipment_enhance_cost_multiplier: float = 1.5
    
    # 交易配置
    trade_expire_time: int = 1800  # 30分钟
    trade_fee_rate: float = 0.05  # 5%手续费
    max_trade_items: int = 10
    
    # 合成配置
    synthesis_success_rate: float = 0.8  # 80%成功率
    synthesis_time_multiplier: float = 1.0
    max_synthesis_queue: int = 5
    
    # 缓存配置
    item_template_cache_ttl: int = 3600  # 1小时
    user_inventory_cache_ttl: int = 300  # 5分钟


class ItemService(BaseService):
    """物品业务服务
    
    提供物品相关的所有业务逻辑，包括背包管理、装备系统、交易、合成等。
    """
    
    def __init__(self, 
                 max_inventory_size: int = 1000,
                 enable_cache: bool = True,
                 cache_ttl: int = 300,
                 config: Optional[ItemServiceConfig] = None):
        """
        初始化物品服务
        
        Args:
            max_inventory_size: 最大背包容量
            enable_cache: 是否启用缓存
            cache_ttl: 缓存TTL
            config: 物品服务配置
        """
        super().__init__(config=config)
        
        self.item_config = config or ItemServiceConfig()
        self.max_inventory_size = max_inventory_size
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        
        # 物品模板数据
        self.item_templates: Dict[str, Dict[str, Any]] = {}
        
        # 用户背包数据
        self.user_inventories: Dict[str, Dict[str, Any]] = {}
        
        # 用户装备数据
        self.user_equipment: Dict[str, Dict[str, Any]] = {}
        
        # 交易数据
        self.active_trades: Dict[str, Dict[str, Any]] = {}
        
        # 合成配方数据
        self.synthesis_recipes: Dict[str, Dict[str, Any]] = {}
        
        # 合成队列
        self.synthesis_queues: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        
        # 统计数据
        self.stats = {
            "total_items": 0,
            "total_trades": 0,
            "completed_trades": 0,
            "total_synthesis": 0,
            "completed_synthesis": 0,
            "active_users": 0
        }
        
        self.logger.info("物品服务初始化完成", 
                        max_inventory_size=max_inventory_size,
                        enable_cache=enable_cache)
    
    async def initialize(self):
        """初始化物品服务"""
        try:
            await super().initialize()
            
            # 初始化物品模板
            await self._initialize_item_templates()
            
            # 初始化合成配方
            await self._initialize_synthesis_recipes()
            
            # 创建测试用户背包
            await self._create_test_inventories()
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_trades())
            asyncio.create_task(self._process_synthesis_queues())
            
            self.logger.info("物品服务初始化完成")
            
        except Exception as e:
            self.logger.error("物品服务初始化失败", error=str(e))
            raise
    
    async def _initialize_item_templates(self):
        """初始化物品模板"""
        try:
            # 创建一些基础物品模板
            templates = [
                {
                    "item_id": "sword_001",
                    "name": "铁剑",
                    "type": ItemType.EQUIPMENT.value,
                    "rarity": ItemRarity.COMMON.value,
                    "slot": EquipmentSlot.WEAPON.value,
                    "level": 1,
                    "attributes": {"attack": 10, "durability": 100},
                    "description": "普通的铁制长剑",
                    "icon": "sword_001.png",
                    "max_stack": 1
                },
                {
                    "item_id": "potion_001",
                    "name": "生命药水",
                    "type": ItemType.CONSUMABLE.value,
                    "rarity": ItemRarity.COMMON.value,
                    "level": 1,
                    "effects": [{"type": "heal", "value": 50}],
                    "description": "恢复50点生命值",
                    "icon": "potion_001.png",
                    "max_stack": 99,
                    "cooldown": 5
                },
                {
                    "item_id": "material_001",
                    "name": "铁矿石",
                    "type": ItemType.MATERIAL.value,
                    "rarity": ItemRarity.COMMON.value,
                    "level": 1,
                    "description": "制作武器的基础材料",
                    "icon": "material_001.png",
                    "max_stack": 999
                },
                {
                    "item_id": "coin",
                    "name": "金币",
                    "type": ItemType.CURRENCY.value,
                    "rarity": ItemRarity.COMMON.value,
                    "level": 1,
                    "description": "游戏中的基础货币",
                    "icon": "coin.png",
                    "max_stack": 999999
                }
            ]
            
            for template in templates:
                self.item_templates[template["item_id"]] = template
            
            self.logger.info("物品模板初始化完成", 
                           template_count=len(self.item_templates))
            
        except Exception as e:
            self.logger.error("物品模板初始化失败", error=str(e))
            raise
    
    async def _initialize_synthesis_recipes(self):
        """初始化合成配方"""
        try:
            # 创建一些基础合成配方
            recipes = [
                {
                    "recipe_id": "recipe_001",
                    "name": "铁剑合成",
                    "result_item": "sword_001",
                    "result_quantity": 1,
                    "materials": [
                        {"item_id": "material_001", "quantity": 3},
                        {"item_id": "coin", "quantity": 100}
                    ],
                    "success_rate": 0.9,
                    "synthesis_time": 60,  # 60秒
                    "level_required": 1
                },
                {
                    "recipe_id": "recipe_002",
                    "name": "生命药水合成",
                    "result_item": "potion_001",
                    "result_quantity": 3,
                    "materials": [
                        {"item_id": "material_001", "quantity": 1},
                        {"item_id": "coin", "quantity": 50}
                    ],
                    "success_rate": 0.95,
                    "synthesis_time": 30,  # 30秒
                    "level_required": 1
                }
            ]
            
            for recipe in recipes:
                self.synthesis_recipes[recipe["recipe_id"]] = recipe
            
            self.logger.info("合成配方初始化完成", 
                           recipe_count=len(self.synthesis_recipes))
            
        except Exception as e:
            self.logger.error("合成配方初始化失败", error=str(e))
            raise
    
    async def _create_test_inventories(self):
        """创建测试用户背包"""
        try:
            test_users = ["user_1", "user_2"]
            
            for user_id in test_users:
                # 创建背包
                self.user_inventories[user_id] = {
                    "user_id": user_id,
                    "capacity": self.item_config.default_inventory_capacity,
                    "items": [
                        {
                            "item_id": "sword_001",
                            "instance_id": str(uuid.uuid4()),
                            "quantity": 1,
                            "level": 1,
                            "attributes": {"attack": 10, "durability": 100},
                            "obtained_time": time.time()
                        },
                        {
                            "item_id": "potion_001",
                            "instance_id": str(uuid.uuid4()),
                            "quantity": 5,
                            "level": 1,
                            "obtained_time": time.time()
                        },
                        {
                            "item_id": "material_001",
                            "instance_id": str(uuid.uuid4()),
                            "quantity": 10,
                            "level": 1,
                            "obtained_time": time.time()
                        },
                        {
                            "item_id": "coin",
                            "instance_id": str(uuid.uuid4()),
                            "quantity": 1000,
                            "level": 1,
                            "obtained_time": time.time()
                        }
                    ],
                    "currency": {"coin": 1000, "diamond": 100}
                }
                
                # 创建装备信息
                self.user_equipment[user_id] = {
                    "user_id": user_id,
                    "equipped_items": {},
                    "total_attributes": {},
                    "equipment_level": 1,
                    "last_update": time.time()
                }
                
                self.stats["active_users"] += 1
            
            self.logger.info("测试用户背包创建完成", user_count=len(test_users))
            
        except Exception as e:
            self.logger.error("创建测试用户背包失败", error=str(e))
            raise
    
    @cached(ttl=300)
    async def get_user_inventory(self, 
                                user_id: str,
                                category: str = "all",
                                page: int = 1,
                                page_size: int = 50,
                                sort_by: str = "created_time",
                                sort_order: str = "desc") -> Dict[str, Any]:
        """
        获取用户背包
        
        Args:
            user_id: 用户ID
            category: 物品分类
            page: 页码
            page_size: 页面大小
            sort_by: 排序字段
            sort_order: 排序方向
            
        Returns:
            背包信息
        """
        try:
            inventory = self.user_inventories.get(user_id)
            if not inventory:
                # 创建新的背包
                inventory = await self._create_user_inventory(user_id)
            
            items = inventory["items"]
            
            # 过滤物品
            if category != "all":
                filtered_items = []
                for item in items:
                    template = self.item_templates.get(item["item_id"])
                    if template and template["type"] == category:
                        filtered_items.append(item)
                items = filtered_items
            
            # 排序
            if sort_by == "created_time":
                items.sort(key=lambda x: x.get("obtained_time", 0), 
                          reverse=(sort_order == "desc"))
            elif sort_by == "name":
                items.sort(key=lambda x: self.item_templates.get(x["item_id"], {}).get("name", ""), 
                          reverse=(sort_order == "desc"))
            elif sort_by == "rarity":
                rarity_order = {r.value: i for i, r in enumerate(ItemRarity)}
                items.sort(key=lambda x: rarity_order.get(
                    self.item_templates.get(x["item_id"], {}).get("rarity", "common"), 0), 
                          reverse=(sort_order == "desc"))
            
            # 分页
            total_count = len(items)
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_items = items[start_idx:end_idx]
            
            # 添加模板信息
            for item in page_items:
                template = self.item_templates.get(item["item_id"])
                if template:
                    item.update(template)
            
            return {
                "items": page_items,
                "total_count": total_count,
                "capacity": inventory["capacity"],
                "currency": inventory.get("currency", {})
            }
            
        except Exception as e:
            self.logger.error("获取用户背包失败", error=str(e))
            raise ServiceException(f"获取用户背包失败: {str(e)}")
    
    async def _create_user_inventory(self, user_id: str) -> Dict[str, Any]:
        """创建用户背包"""
        try:
            inventory = {
                "user_id": user_id,
                "capacity": self.item_config.default_inventory_capacity,
                "items": [],
                "currency": {"coin": 0, "diamond": 0},
                "created_time": time.time()
            }
            
            self.user_inventories[user_id] = inventory
            self.stats["active_users"] += 1
            
            return inventory
            
        except Exception as e:
            self.logger.error("创建用户背包失败", error=str(e))
            raise
    
    @transactional
    async def use_item(self, 
                      user_id: str,
                      item_id: str,
                      quantity: int = 1,
                      target_id: Optional[str] = None,
                      use_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        使用物品
        
        Args:
            user_id: 用户ID
            item_id: 物品ID
            quantity: 使用数量
            target_id: 目标ID
            use_context: 使用上下文
            
        Returns:
            使用结果
        """
        try:
            inventory = self.user_inventories.get(user_id)
            if not inventory:
                raise ServiceException("用户背包不存在")
            
            # 查找物品
            item = None
            for inv_item in inventory["items"]:
                if inv_item["item_id"] == item_id:
                    item = inv_item
                    break
            
            if not item:
                raise ServiceException("物品不存在")
            
            if item["quantity"] < quantity:
                raise ServiceException("物品数量不足")
            
            # 获取物品模板
            template = self.item_templates.get(item_id)
            if not template:
                raise ServiceException("物品模板不存在")
            
            # 检查物品类型
            if template["type"] != ItemType.CONSUMABLE.value:
                raise ServiceException("该物品不能使用")
            
            # 应用物品效果
            effects = []
            for effect in template.get("effects", []):
                effect_result = await self._apply_item_effect(user_id, effect, target_id)
                effects.append(effect_result)
            
            # 减少物品数量
            item["quantity"] -= quantity
            if item["quantity"] <= 0:
                inventory["items"].remove(item)
            
            # 构建使用结果
            result = {
                "used_item": {
                    "item_id": item_id,
                    "quantity": quantity,
                    "effects": effects
                },
                "effects": effects,
                "remaining_quantity": item["quantity"] if item["quantity"] > 0 else 0,
                "cooldown": template.get("cooldown", 0)
            }
            
            self.logger.info("物品使用成功", 
                           user_id=user_id,
                           item_id=item_id,
                           quantity=quantity)
            
            return result
            
        except Exception as e:
            self.logger.error("使用物品失败", error=str(e))
            raise ServiceException(f"使用物品失败: {str(e)}")
    
    async def _apply_item_effect(self, user_id: str, effect: Dict[str, Any], target_id: Optional[str] = None) -> Dict[str, Any]:
        """应用物品效果"""
        try:
            effect_type = effect["type"]
            effect_value = effect["value"]
            
            effect_result = {
                "type": effect_type,
                "value": effect_value,
                "target_id": target_id or user_id,
                "applied_time": time.time()
            }
            
            # 这里应该根据效果类型调用相应的服务
            # 现在只是记录日志
            self.logger.info("物品效果应用", 
                           user_id=user_id,
                           effect_type=effect_type,
                           effect_value=effect_value)
            
            return effect_result
            
        except Exception as e:
            self.logger.error("应用物品效果失败", error=str(e))
            raise
    
    @transactional
    async def equip_item(self, user_id: str, item_id: str, slot: Optional[str] = None) -> Dict[str, Any]:
        """
        装备物品
        
        Args:
            user_id: 用户ID
            item_id: 物品ID
            slot: 装备槽位
            
        Returns:
            装备结果
        """
        try:
            inventory = self.user_inventories.get(user_id)
            if not inventory:
                raise ServiceException("用户背包不存在")
            
            equipment = self.user_equipment.get(user_id)
            if not equipment:
                raise ServiceException("用户装备信息不存在")
            
            # 查找物品
            item = None
            for inv_item in inventory["items"]:
                if inv_item["item_id"] == item_id:
                    item = inv_item
                    break
            
            if not item:
                raise ServiceException("物品不存在")
            
            # 获取物品模板
            template = self.item_templates.get(item_id)
            if not template:
                raise ServiceException("物品模板不存在")
            
            # 检查物品类型
            if template["type"] != ItemType.EQUIPMENT.value:
                raise ServiceException("该物品不能装备")
            
            # 确定装备槽位
            if slot is None:
                slot = template["slot"]
            elif slot != template["slot"]:
                raise ServiceException("装备槽位不匹配")
            
            # 检查当前槽位是否有装备
            replaced_item = None
            if slot in equipment["equipped_items"]:
                replaced_item = equipment["equipped_items"][slot]
                # 将原装备放回背包
                await self._add_item_to_inventory(user_id, replaced_item)
            
            # 装备新物品
            equipment["equipped_items"][slot] = item.copy()
            equipment["last_update"] = time.time()
            
            # 从背包中移除物品
            inventory["items"].remove(item)
            
            # 重新计算装备属性
            await self._recalculate_equipment_attributes(user_id)
            
            result = {
                "equipped_item": item,
                "replaced_item": replaced_item,
                "equipment_info": equipment
            }
            
            self.logger.info("装备物品成功", 
                           user_id=user_id,
                           item_id=item_id,
                           slot=slot)
            
            return result
            
        except Exception as e:
            self.logger.error("装备物品失败", error=str(e))
            raise ServiceException(f"装备物品失败: {str(e)}")
    
    @transactional
    async def unequip_item(self, user_id: str, slot: str) -> Dict[str, Any]:
        """
        卸载装备
        
        Args:
            user_id: 用户ID
            slot: 装备槽位
            
        Returns:
            卸载结果
        """
        try:
            equipment = self.user_equipment.get(user_id)
            if not equipment:
                raise ServiceException("用户装备信息不存在")
            
            # 检查槽位是否有装备
            if slot not in equipment["equipped_items"]:
                raise ServiceException("该槽位没有装备")
            
            # 获取装备
            unequipped_item = equipment["equipped_items"][slot]
            
            # 将装备放回背包
            await self._add_item_to_inventory(user_id, unequipped_item)
            
            # 从装备槽位移除
            del equipment["equipped_items"][slot]
            equipment["last_update"] = time.time()
            
            # 重新计算装备属性
            await self._recalculate_equipment_attributes(user_id)
            
            result = {
                "unequipped_item": unequipped_item,
                "equipment_info": equipment
            }
            
            self.logger.info("卸载装备成功", 
                           user_id=user_id,
                           slot=slot)
            
            return result
            
        except Exception as e:
            self.logger.error("卸载装备失败", error=str(e))
            raise ServiceException(f"卸载装备失败: {str(e)}")
    
    async def _add_item_to_inventory(self, user_id: str, item: Dict[str, Any]):
        """添加物品到背包"""
        try:
            inventory = self.user_inventories.get(user_id)
            if not inventory:
                raise ServiceException("用户背包不存在")
            
            # 检查背包容量
            if len(inventory["items"]) >= inventory["capacity"]:
                raise ServiceException("背包已满")
            
            # 添加物品
            inventory["items"].append(item)
            
        except Exception as e:
            self.logger.error("添加物品到背包失败", error=str(e))
            raise
    
    async def _recalculate_equipment_attributes(self, user_id: str):
        """重新计算装备属性"""
        try:
            equipment = self.user_equipment.get(user_id)
            if not equipment:
                return
            
            total_attributes = {}
            
            # 计算所有装备的属性总和
            for slot, item in equipment["equipped_items"].items():
                attributes = item.get("attributes", {})
                for attr_name, attr_value in attributes.items():
                    if attr_name in total_attributes:
                        total_attributes[attr_name] += attr_value
                    else:
                        total_attributes[attr_name] = attr_value
            
            equipment["total_attributes"] = total_attributes
            
        except Exception as e:
            self.logger.error("重新计算装备属性失败", error=str(e))
            raise
    
    @transactional
    async def create_trade(self, 
                          user_id: str,
                          target_user_id: str,
                          offer_items: List[Dict[str, Any]],
                          request_items: List[Dict[str, Any]],
                          trade_type: str = "player") -> Dict[str, Any]:
        """
        创建交易
        
        Args:
            user_id: 用户ID
            target_user_id: 目标用户ID
            offer_items: 提供的物品
            request_items: 请求的物品
            trade_type: 交易类型
            
        Returns:
            交易信息
        """
        try:
            # 生成交易ID
            trade_id = str(uuid.uuid4())
            
            # 创建交易信息
            trade_info = {
                "trade_id": trade_id,
                "initiator_id": user_id,
                "target_id": target_user_id,
                "offer_items": offer_items,
                "request_items": request_items,
                "trade_type": trade_type,
                "status": TradeStatus.PENDING.value,
                "created_time": time.time(),
                "expires_at": time.time() + self.item_config.trade_expire_time,
                "initiator_confirmed": False,
                "target_confirmed": False
            }
            
            # 保存交易
            self.active_trades[trade_id] = trade_info
            
            # 更新统计
            self.stats["total_trades"] += 1
            
            self.logger.info("创建交易成功", 
                           trade_id=trade_id,
                           initiator_id=user_id,
                           target_id=target_user_id)
            
            return trade_info
            
        except Exception as e:
            self.logger.error("创建交易失败", error=str(e))
            raise ServiceException(f"创建交易失败: {str(e)}")
    
    @transactional
    async def cancel_trade(self, trade_id: str, reason: str = "user_cancel"):
        """
        取消交易
        
        Args:
            trade_id: 交易ID
            reason: 取消原因
        """
        try:
            trade_info = self.active_trades.get(trade_id)
            if not trade_info:
                raise ServiceException("交易不存在")
            
            # 更新交易状态
            trade_info["status"] = TradeStatus.CANCELLED.value
            trade_info["cancel_reason"] = reason
            trade_info["cancelled_time"] = time.time()
            
            # 从活跃交易中移除
            del self.active_trades[trade_id]
            
            self.logger.info("取消交易成功", 
                           trade_id=trade_id,
                           reason=reason)
            
        except Exception as e:
            self.logger.error("取消交易失败", error=str(e))
            raise ServiceException(f"取消交易失败: {str(e)}")
    
    @transactional
    async def synthesize_item(self, 
                             user_id: str,
                             recipe_id: str,
                             materials: List[Dict[str, Any]],
                             quantity: int = 1) -> Dict[str, Any]:
        """
        合成物品
        
        Args:
            user_id: 用户ID
            recipe_id: 合成配方ID
            materials: 材料列表
            quantity: 合成数量
            
        Returns:
            合成结果
        """
        try:
            # 获取合成配方
            recipe = self.synthesis_recipes.get(recipe_id)
            if not recipe:
                raise ServiceException("合成配方不存在")
            
            # 检查材料
            await self._check_synthesis_materials(user_id, recipe, materials, quantity)
            
            # 消耗材料
            consumed_materials = await self._consume_synthesis_materials(user_id, recipe, quantity)
            
            # 计算成功率
            success_rate = recipe["success_rate"]
            success = time.time() % 1 < success_rate  # 简单的成功率计算
            
            synthesized_items = []
            if success:
                # 生成结果物品
                result_item = await self._create_synthesis_result(user_id, recipe, quantity)
                synthesized_items.append(result_item)
            
            # 更新统计
            self.stats["total_synthesis"] += 1
            if success:
                self.stats["completed_synthesis"] += 1
            
            synthesis_info = {
                "recipe_id": recipe_id,
                "success": success,
                "synthesis_time": recipe["synthesis_time"],
                "quantity": quantity,
                "completed_time": time.time()
            }
            
            result = {
                "synthesized_items": synthesized_items,
                "consumed_materials": consumed_materials,
                "synthesis_info": synthesis_info
            }
            
            self.logger.info("物品合成成功", 
                           user_id=user_id,
                           recipe_id=recipe_id,
                           success=success)
            
            return result
            
        except Exception as e:
            self.logger.error("物品合成失败", error=str(e))
            raise ServiceException(f"物品合成失败: {str(e)}")
    
    async def _check_synthesis_materials(self, user_id: str, recipe: Dict[str, Any], materials: List[Dict[str, Any]], quantity: int):
        """检查合成材料"""
        try:
            inventory = self.user_inventories.get(user_id)
            if not inventory:
                raise ServiceException("用户背包不存在")
            
            # 检查每种材料的数量
            for material_req in recipe["materials"]:
                required_quantity = material_req["quantity"] * quantity
                item_id = material_req["item_id"]
                
                # 在背包中查找材料
                available_quantity = 0
                for item in inventory["items"]:
                    if item["item_id"] == item_id:
                        available_quantity += item["quantity"]
                
                if available_quantity < required_quantity:
                    raise ServiceException(f"材料{item_id}数量不足")
                    
        except Exception as e:
            self.logger.error("检查合成材料失败", error=str(e))
            raise
    
    async def _consume_synthesis_materials(self, user_id: str, recipe: Dict[str, Any], quantity: int) -> List[Dict[str, Any]]:
        """消耗合成材料"""
        try:
            inventory = self.user_inventories.get(user_id)
            consumed_materials = []
            
            # 消耗每种材料
            for material_req in recipe["materials"]:
                required_quantity = material_req["quantity"] * quantity
                item_id = material_req["item_id"]
                
                remaining_to_consume = required_quantity
                
                # 从背包中消耗材料
                for item in inventory["items"][:]:  # 使用切片创建副本
                    if item["item_id"] == item_id and remaining_to_consume > 0:
                        consumed_amount = min(item["quantity"], remaining_to_consume)
                        
                        consumed_materials.append({
                            "item_id": item_id,
                            "quantity": consumed_amount
                        })
                        
                        item["quantity"] -= consumed_amount
                        remaining_to_consume -= consumed_amount
                        
                        if item["quantity"] <= 0:
                            inventory["items"].remove(item)
                        
                        if remaining_to_consume <= 0:
                            break
            
            return consumed_materials
            
        except Exception as e:
            self.logger.error("消耗合成材料失败", error=str(e))
            raise
    
    async def _create_synthesis_result(self, user_id: str, recipe: Dict[str, Any], quantity: int) -> Dict[str, Any]:
        """创建合成结果"""
        try:
            result_item_id = recipe["result_item"]
            result_quantity = recipe["result_quantity"] * quantity
            
            # 创建结果物品
            result_item = {
                "item_id": result_item_id,
                "instance_id": str(uuid.uuid4()),
                "quantity": result_quantity,
                "level": 1,
                "obtained_time": time.time(),
                "source": "synthesis"
            }
            
            # 添加到用户背包
            await self._add_item_to_inventory(user_id, result_item)
            
            return result_item
            
        except Exception as e:
            self.logger.error("创建合成结果失败", error=str(e))
            raise
    
    async def complete_synthesis(self, user_id: str, synthesis_id: str):
        """完成合成"""
        try:
            # 这里应该处理合成完成的逻辑
            self.logger.info("合成完成", user_id=user_id, synthesis_id=synthesis_id)
            
        except Exception as e:
            self.logger.error("完成合成失败", error=str(e))
            raise ServiceException(f"完成合成失败: {str(e)}")
    
    async def cancel_synthesis(self, user_id: str, synthesis_id: str):
        """取消合成"""
        try:
            # 这里应该处理合成取消的逻辑
            self.logger.info("合成取消", user_id=user_id, synthesis_id=synthesis_id)
            
        except Exception as e:
            self.logger.error("取消合成失败", error=str(e))
            raise ServiceException(f"取消合成失败: {str(e)}")
    
    async def get_item_templates(self) -> Dict[str, Dict[str, Any]]:
        """获取物品模板"""
        return self.item_templates
    
    async def get_synthesis_recipes(self) -> Dict[str, Dict[str, Any]]:
        """获取合成配方"""
        return self.synthesis_recipes
    
    async def _cleanup_expired_trades(self):
        """清理过期交易"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                
                current_time = time.time()
                expired_trades = []
                
                for trade_id, trade_info in self.active_trades.items():
                    if current_time > trade_info["expires_at"]:
                        expired_trades.append(trade_id)
                
                for trade_id in expired_trades:
                    await self.cancel_trade(trade_id, "expired")
                
            except Exception as e:
                self.logger.error("清理过期交易异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _process_synthesis_queues(self):
        """处理合成队列"""
        while True:
            try:
                await asyncio.sleep(10)  # 每10秒检查一次
                
                # 处理所有用户的合成队列
                for user_id, queue in self.synthesis_queues.items():
                    if queue:
                        # 处理队列中的第一个任务
                        synthesis_task = queue[0]
                        
                        if time.time() >= synthesis_task["complete_time"]:
                            await self.complete_synthesis(user_id, synthesis_task["synthesis_id"])
                            queue.pop(0)
                
            except Exception as e:
                self.logger.error("处理合成队列异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            await super().cleanup()
            
            # 清理所有交易
            for trade_id in list(self.active_trades.keys()):
                await self.cancel_trade(trade_id, "server_shutdown")
            
            # 清理合成队列
            self.synthesis_queues.clear()
            
            self.logger.info("物品服务资源清理完成")
            
        except Exception as e:
            self.logger.error("物品服务资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            **self.stats,
            "service_name": self.__class__.__name__,
            "inventories": len(self.user_inventories),
            "equipment": len(self.user_equipment),
            "active_trades": len(self.active_trades),
            "synthesis_recipes": len(self.synthesis_recipes),
            "synthesis_queues": len(self.synthesis_queues)
        }


def create_item_service(config: Optional[ItemServiceConfig] = None) -> ItemService:
    """
    创建物品服务实例
    
    Args:
        config: 物品服务配置
        
    Returns:
        ItemService实例
    """
    try:
        service = ItemService(config=config)
        logger.info("物品服务创建成功")
        return service
        
    except Exception as e:
        logger.error("创建物品服务失败", error=str(e))
        raise