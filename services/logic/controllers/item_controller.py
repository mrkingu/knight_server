"""
物品控制器

该模块实现了物品相关的控制器，继承自BaseController，
负责处理背包管理、物品使用、装备系统、物品交易等功能。

主要功能：
- 背包管理和查询
- 物品使用和消耗
- 装备穿戴和卸载
- 物品交易和转移
- 物品合成和升级

支持的操作：
- 获取背包信息
- 使用物品
- 装备/卸载装备
- 物品交易
- 物品合成
- 物品分解
"""

import asyncio
import time
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

from services.base import BaseController, ControllerConfig
from services.base import ValidationException, AuthorizationException, BusinessException
from common.logger import logger
from common.decorator import handler, controller

# 导入协议定义
try:
    from common.proto import BaseRequest, BaseResponse
    PROTO_AVAILABLE = True
except ImportError:
    logger.warning("协议模块不可用，使用模拟类型")
    PROTO_AVAILABLE = False
    
    @dataclass
    class BaseRequest:
        message_id: int = 0
        user_id: Optional[str] = None
        session_id: Optional[str] = None
        timestamp: float = 0.0
        data: Dict[str, Any] = None
    
    @dataclass
    class BaseResponse:
        message_id: int = 0
        status: str = "success"
        code: int = 200
        message: str = ""
        data: Dict[str, Any] = None
        timestamp: float = 0.0


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


# 背包相关协议
@dataclass
class GetInventoryRequest(BaseRequest):
    """获取背包请求"""
    category: str = "all"  # all, consumable, equipment, material, quest
    page: int = 1
    page_size: int = 50
    sort_by: str = "created_time"  # created_time, name, rarity, type
    sort_order: str = "desc"  # asc, desc


@dataclass
class GetInventoryResponse(BaseResponse):
    """获取背包响应"""
    items: List[Dict[str, Any]] = None
    total_count: int = 0
    capacity: int = 0
    currency: Dict[str, int] = None


@dataclass
class UseItemRequest(BaseRequest):
    """使用物品请求"""
    item_id: str = ""
    quantity: int = 1
    target_id: Optional[str] = None  # 目标ID（如果需要）
    use_context: Dict[str, Any] = None


@dataclass
class UseItemResponse(BaseResponse):
    """使用物品响应"""
    used_item: Dict[str, Any] = None
    effects: List[Dict[str, Any]] = None
    remaining_quantity: int = 0


@dataclass
class EquipItemRequest(BaseRequest):
    """装备物品请求"""
    item_id: str = ""
    slot: Optional[str] = None  # 装备槽位，如果为空则自动选择


@dataclass
class EquipItemResponse(BaseResponse):
    """装备物品响应"""
    equipped_item: Dict[str, Any] = None
    replaced_item: Optional[Dict[str, Any]] = None
    equipment_info: Dict[str, Any] = None


@dataclass
class UnequipItemRequest(BaseRequest):
    """卸载装备请求"""
    slot: str = ""  # 装备槽位


@dataclass
class UnequipItemResponse(BaseResponse):
    """卸载装备响应"""
    unequipped_item: Dict[str, Any] = None
    equipment_info: Dict[str, Any] = None


@dataclass
class TradeItemRequest(BaseRequest):
    """物品交易请求"""
    target_user_id: str = ""
    offer_items: List[Dict[str, Any]] = None  # 提供的物品
    request_items: List[Dict[str, Any]] = None  # 请求的物品
    trade_type: str = "player"  # player, system, auction


@dataclass
class TradeItemResponse(BaseResponse):
    """物品交易响应"""
    trade_id: str = ""
    trade_info: Dict[str, Any] = None


@dataclass
class SynthesizeItemRequest(BaseRequest):
    """物品合成请求"""
    recipe_id: str = ""
    materials: List[Dict[str, Any]] = None  # 材料清单
    quantity: int = 1


@dataclass
class SynthesizeItemResponse(BaseResponse):
    """物品合成响应"""
    synthesized_items: List[Dict[str, Any]] = None
    consumed_materials: List[Dict[str, Any]] = None
    synthesis_info: Dict[str, Any] = None


@controller(name="ItemController")
class ItemController(BaseController):
    """物品控制器
    
    处理所有物品相关的请求，包括背包管理、物品使用、装备系统、交易等。
    """
    
    def __init__(self, config: Optional[ControllerConfig] = None):
        """初始化物品控制器"""
        super().__init__(config)
        
        # 物品服务
        self.item_service = None
        
        # 背包配置
        self.default_inventory_capacity = 100
        self.max_inventory_capacity = 1000
        
        # 装备槽位配置
        self.equipment_slots = {
            slot.value: {"name": slot.value, "max_items": 1}
            for slot in EquipmentSlot
        }
        
        # 物品使用冷却时间
        self.item_cooldowns: Dict[str, Dict[str, float]] = {}  # user_id -> {item_type: cooldown_end_time}
        
        # 交易会话
        self.active_trades: Dict[str, Dict[str, Any]] = {}
        
        # 合成队列
        self.synthesis_queue: Dict[str, List[Dict[str, Any]]] = {}
        
        # 物品缓存
        self.item_cache: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info("物品控制器初始化完成")
    
    async def initialize(self):
        """初始化物品控制器"""
        try:
            await super().initialize()
            
            # 获取物品服务
            self.item_service = self.get_service("item_service")
            if not self.item_service:
                raise ValueError("物品服务未注册")
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_trades())
            asyncio.create_task(self._process_synthesis_queue())
            asyncio.create_task(self._refresh_item_cache())
            
            self.logger.info("物品控制器初始化完成")
            
        except Exception as e:
            self.logger.error("物品控制器初始化失败", error=str(e))
            raise
    
    @handler(GetInventoryRequest, GetInventoryResponse)
    async def handle_get_inventory(self, request: GetInventoryRequest, context=None) -> GetInventoryResponse:
        """
        处理获取背包请求
        
        Args:
            request: 获取背包请求
            context: 请求上下文
            
        Returns:
            GetInventoryResponse: 获取背包响应
        """
        try:
            # 参数验证
            if request.page < 1 or request.page_size < 1 or request.page_size > 100:
                raise ValidationException("页码和页面大小参数无效")
            
            valid_categories = ["all", "consumable", "equipment", "material", "quest", "currency", "card", "gift"]
            if request.category not in valid_categories:
                raise ValidationException(f"无效的物品分类: {request.category}")
            
            valid_sort_fields = ["created_time", "name", "rarity", "type", "level"]
            if request.sort_by not in valid_sort_fields:
                raise ValidationException(f"无效的排序字段: {request.sort_by}")
            
            # 调用物品服务获取背包信息
            inventory_result = await self.item_service.get_user_inventory(
                user_id=request.user_id,
                category=request.category,
                page=request.page,
                page_size=request.page_size,
                sort_by=request.sort_by,
                sort_order=request.sort_order
            )
            
            # 构造响应
            response = GetInventoryResponse(
                message_id=request.message_id,
                items=inventory_result["items"],
                total_count=inventory_result["total_count"],
                capacity=inventory_result["capacity"],
                currency=inventory_result.get("currency", {}),
                timestamp=time.time()
            )
            
            self.logger.info("获取背包成功",
                           user_id=request.user_id,
                           category=request.category,
                           item_count=len(inventory_result["items"]))
            
            return response
            
        except ValidationException as e:
            self.logger.warning("获取背包参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("获取背包处理异常", error=str(e))
            raise BusinessException(f"获取背包失败: {str(e)}")
    
    @handler(UseItemRequest, UseItemResponse)
    async def handle_use_item(self, request: UseItemRequest, context=None) -> UseItemResponse:
        """
        处理使用物品请求
        
        Args:
            request: 使用物品请求
            context: 请求上下文
            
        Returns:
            UseItemResponse: 使用物品响应
        """
        try:
            # 参数验证
            if not request.item_id:
                raise ValidationException("物品ID不能为空")
            
            if request.quantity <= 0:
                raise ValidationException("使用数量必须大于0")
            
            # 检查物品冷却时间
            if await self._check_item_cooldown(request.user_id, request.item_id):
                raise BusinessException("物品使用冷却中")
            
            # 调用物品服务使用物品
            use_result = await self.item_service.use_item(
                user_id=request.user_id,
                item_id=request.item_id,
                quantity=request.quantity,
                target_id=request.target_id,
                use_context=request.use_context or {}
            )
            
            # 设置物品冷却时间
            await self._set_item_cooldown(request.user_id, request.item_id, use_result.get("cooldown", 0))
            
            # 构造响应
            response = UseItemResponse(
                message_id=request.message_id,
                used_item=use_result["used_item"],
                effects=use_result.get("effects", []),
                remaining_quantity=use_result.get("remaining_quantity", 0),
                timestamp=time.time()
            )
            
            self.logger.info("使用物品成功",
                           user_id=request.user_id,
                           item_id=request.item_id,
                           quantity=request.quantity)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("使用物品参数验证失败", error=str(e))
            raise
        except BusinessException as e:
            self.logger.warning("使用物品业务异常", error=str(e))
            raise
        except Exception as e:
            self.logger.error("使用物品处理异常", error=str(e))
            raise BusinessException(f"使用物品失败: {str(e)}")
    
    @handler(EquipItemRequest, EquipItemResponse)
    async def handle_equip_item(self, request: EquipItemRequest, context=None) -> EquipItemResponse:
        """
        处理装备物品请求
        
        Args:
            request: 装备物品请求
            context: 请求上下文
            
        Returns:
            EquipItemResponse: 装备物品响应
        """
        try:
            # 参数验证
            if not request.item_id:
                raise ValidationException("物品ID不能为空")
            
            if request.slot and request.slot not in self.equipment_slots:
                raise ValidationException(f"无效的装备槽位: {request.slot}")
            
            # 调用物品服务装备物品
            equip_result = await self.item_service.equip_item(
                user_id=request.user_id,
                item_id=request.item_id,
                slot=request.slot
            )
            
            # 构造响应
            response = EquipItemResponse(
                message_id=request.message_id,
                equipped_item=equip_result["equipped_item"],
                replaced_item=equip_result.get("replaced_item"),
                equipment_info=equip_result["equipment_info"],
                timestamp=time.time()
            )
            
            self.logger.info("装备物品成功",
                           user_id=request.user_id,
                           item_id=request.item_id,
                           slot=equip_result["equipped_item"]["slot"])
            
            return response
            
        except ValidationException as e:
            self.logger.warning("装备物品参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("装备物品处理异常", error=str(e))
            raise BusinessException(f"装备物品失败: {str(e)}")
    
    @handler(UnequipItemRequest, UnequipItemResponse)
    async def handle_unequip_item(self, request: UnequipItemRequest, context=None) -> UnequipItemResponse:
        """
        处理卸载装备请求
        
        Args:
            request: 卸载装备请求
            context: 请求上下文
            
        Returns:
            UnequipItemResponse: 卸载装备响应
        """
        try:
            # 参数验证
            if not request.slot:
                raise ValidationException("装备槽位不能为空")
            
            if request.slot not in self.equipment_slots:
                raise ValidationException(f"无效的装备槽位: {request.slot}")
            
            # 调用物品服务卸载装备
            unequip_result = await self.item_service.unequip_item(
                user_id=request.user_id,
                slot=request.slot
            )
            
            # 构造响应
            response = UnequipItemResponse(
                message_id=request.message_id,
                unequipped_item=unequip_result["unequipped_item"],
                equipment_info=unequip_result["equipment_info"],
                timestamp=time.time()
            )
            
            self.logger.info("卸载装备成功",
                           user_id=request.user_id,
                           slot=request.slot)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("卸载装备参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("卸载装备处理异常", error=str(e))
            raise BusinessException(f"卸载装备失败: {str(e)}")
    
    @handler(TradeItemRequest, TradeItemResponse)
    async def handle_trade_item(self, request: TradeItemRequest, context=None) -> TradeItemResponse:
        """
        处理物品交易请求
        
        Args:
            request: 物品交易请求
            context: 请求上下文
            
        Returns:
            TradeItemResponse: 物品交易响应
        """
        try:
            # 参数验证
            if not request.target_user_id:
                raise ValidationException("目标用户ID不能为空")
            
            if request.user_id == request.target_user_id:
                raise ValidationException("不能与自己交易")
            
            if not request.offer_items:
                raise ValidationException("必须提供交易物品")
            
            # 检查交易类型
            valid_trade_types = ["player", "system", "auction"]
            if request.trade_type not in valid_trade_types:
                raise ValidationException(f"无效的交易类型: {request.trade_type}")
            
            # 调用物品服务创建交易
            trade_result = await self.item_service.create_trade(
                user_id=request.user_id,
                target_user_id=request.target_user_id,
                offer_items=request.offer_items,
                request_items=request.request_items or [],
                trade_type=request.trade_type
            )
            
            # 记录活跃交易
            self.active_trades[trade_result["trade_id"]] = {
                "trade_info": trade_result,
                "created_time": time.time(),
                "expires_at": time.time() + 1800  # 30分钟过期
            }
            
            # 构造响应
            response = TradeItemResponse(
                message_id=request.message_id,
                trade_id=trade_result["trade_id"],
                trade_info=trade_result,
                timestamp=time.time()
            )
            
            self.logger.info("创建物品交易成功",
                           user_id=request.user_id,
                           target_user_id=request.target_user_id,
                           trade_id=trade_result["trade_id"])
            
            return response
            
        except ValidationException as e:
            self.logger.warning("物品交易参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("物品交易处理异常", error=str(e))
            raise BusinessException(f"物品交易失败: {str(e)}")
    
    @handler(SynthesizeItemRequest, SynthesizeItemResponse)
    async def handle_synthesize_item(self, request: SynthesizeItemRequest, context=None) -> SynthesizeItemResponse:
        """
        处理物品合成请求
        
        Args:
            request: 物品合成请求
            context: 请求上下文
            
        Returns:
            SynthesizeItemResponse: 物品合成响应
        """
        try:
            # 参数验证
            if not request.recipe_id:
                raise ValidationException("合成配方ID不能为空")
            
            if not request.materials:
                raise ValidationException("必须提供合成材料")
            
            if request.quantity <= 0:
                raise ValidationException("合成数量必须大于0")
            
            # 调用物品服务合成物品
            synthesis_result = await self.item_service.synthesize_item(
                user_id=request.user_id,
                recipe_id=request.recipe_id,
                materials=request.materials,
                quantity=request.quantity
            )
            
            # 构造响应
            response = SynthesizeItemResponse(
                message_id=request.message_id,
                synthesized_items=synthesis_result["synthesized_items"],
                consumed_materials=synthesis_result["consumed_materials"],
                synthesis_info=synthesis_result["synthesis_info"],
                timestamp=time.time()
            )
            
            self.logger.info("物品合成成功",
                           user_id=request.user_id,
                           recipe_id=request.recipe_id,
                           quantity=request.quantity)
            
            return response
            
        except ValidationException as e:
            self.logger.warning("物品合成参数验证失败", error=str(e))
            raise
        except Exception as e:
            self.logger.error("物品合成处理异常", error=str(e))
            raise BusinessException(f"物品合成失败: {str(e)}")
    
    async def _check_item_cooldown(self, user_id: str, item_id: str) -> bool:
        """检查物品冷却时间"""
        if user_id not in self.item_cooldowns:
            return False
        
        cooldown_info = self.item_cooldowns[user_id].get(item_id)
        if not cooldown_info:
            return False
        
        return time.time() < cooldown_info
    
    async def _set_item_cooldown(self, user_id: str, item_id: str, cooldown_seconds: float):
        """设置物品冷却时间"""
        if cooldown_seconds <= 0:
            return
        
        if user_id not in self.item_cooldowns:
            self.item_cooldowns[user_id] = {}
        
        self.item_cooldowns[user_id][item_id] = time.time() + cooldown_seconds
    
    async def _cleanup_expired_trades(self):
        """清理过期交易"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟检查一次
                
                current_time = time.time()
                expired_trades = []
                
                for trade_id, trade_session in self.active_trades.items():
                    if current_time > trade_session["expires_at"]:
                        expired_trades.append(trade_id)
                
                # 清理过期交易
                for trade_id in expired_trades:
                    trade_session = self.active_trades.pop(trade_id)
                    await self.item_service.cancel_trade(trade_id, "expired")
                    
                    self.logger.info("清理过期交易",
                                   trade_id=trade_id)
                
            except Exception as e:
                self.logger.error("清理过期交易异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _process_synthesis_queue(self):
        """处理合成队列"""
        while True:
            try:
                await asyncio.sleep(10)  # 每10秒处理一次
                
                # 处理所有用户的合成队列
                for user_id, queue in self.synthesis_queue.items():
                    if not queue:
                        continue
                    
                    # 处理队列中的第一个合成任务
                    synthesis_task = queue[0]
                    
                    # 检查合成是否完成
                    if time.time() >= synthesis_task["complete_time"]:
                        # 完成合成
                        await self.item_service.complete_synthesis(
                            user_id=user_id,
                            synthesis_id=synthesis_task["synthesis_id"]
                        )
                        
                        # 从队列中移除
                        queue.pop(0)
                        
                        self.logger.info("合成任务完成",
                                       user_id=user_id,
                                       synthesis_id=synthesis_task["synthesis_id"])
                
            except Exception as e:
                self.logger.error("处理合成队列异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _refresh_item_cache(self):
        """刷新物品缓存"""
        while True:
            try:
                await asyncio.sleep(600)  # 每10分钟刷新一次
                
                # 刷新物品模板缓存
                item_templates = await self.item_service.get_item_templates()
                self.item_cache["templates"] = item_templates
                
                # 刷新合成配方缓存
                synthesis_recipes = await self.item_service.get_synthesis_recipes()
                self.item_cache["recipes"] = synthesis_recipes
                
                self.logger.info("物品缓存刷新完成",
                               template_count=len(item_templates),
                               recipe_count=len(synthesis_recipes))
                
            except Exception as e:
                self.logger.error("刷新物品缓存异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理控制器资源"""
        try:
            await super().cleanup()
            
            # 清理所有交易
            for trade_id in list(self.active_trades.keys()):
                await self.item_service.cancel_trade(trade_id, "server_shutdown")
            
            # 清理所有合成队列
            for user_id, queue in self.synthesis_queue.items():
                for synthesis_task in queue:
                    await self.item_service.cancel_synthesis(
                        user_id=user_id,
                        synthesis_id=synthesis_task["synthesis_id"]
                    )
            
            self.active_trades.clear()
            self.synthesis_queue.clear()
            self.item_cooldowns.clear()
            self.item_cache.clear()
            
            self.logger.info("物品控制器资源清理完成")
            
        except Exception as e:
            self.logger.error("物品控制器资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取控制器统计信息"""
        return {
            "active_trades": len(self.active_trades),
            "synthesis_queues": len(self.synthesis_queue),
            "item_cooldowns": len(self.item_cooldowns),
            "item_cache_size": len(self.item_cache),
            "controller_name": self.__class__.__name__,
            "equipment_slots": list(self.equipment_slots.keys()),
            "default_inventory_capacity": self.default_inventory_capacity,
            "max_inventory_capacity": self.max_inventory_capacity
        }


def create_item_controller(config: Optional[ControllerConfig] = None) -> ItemController:
    """
    创建物品控制器实例
    
    Args:
        config: 控制器配置
        
    Returns:
        ItemController实例
    """
    try:
        controller = ItemController(config)
        logger.info("物品控制器创建成功")
        return controller
        
    except Exception as e:
        logger.error("创建物品控制器失败", error=str(e))
        raise