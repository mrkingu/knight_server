"""
Fight消息处理器

该模块实现了Fight服务的统一消息处理器，继承自BaseHandler，
负责消息的接收、解码、路由、异常处理、性能统计等功能。

主要功能：
- 继承自BaseHandler提供完整的消息处理基础功能
- 统一接收和分发Fight相关的消息
- 根据消息类型自动路由到对应的Controller
- 处理异常和错误返回
- 记录请求日志和性能指标
- 支持消息验证和安全检查

消息处理流程：
1. 接收原始消息数据
2. 解码和验证消息
3. 根据消息ID路由到对应的控制器
4. 调用控制器处理业务逻辑
5. 编码响应消息
6. 返回处理结果

支持的消息类型：
- 战斗匹配相关消息（8001-8100）
- 战斗操作相关消息（8101-8200）
- 技能系统相关消息（8201-8300）
- 战斗结算相关消息（8301-8400）
- 战斗回放相关消息（8401-8500）
"""

import asyncio
import time
import traceback
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from services.base import BaseHandler, RequestContext, ResponseContext, MessageType
from common.logger import logger


@dataclass
class FightMessageStats:
    """Fight消息统计"""
    total_messages: int = 0
    match_messages: int = 0
    battle_messages: int = 0
    skill_messages: int = 0
    settlement_messages: int = 0
    replay_messages: int = 0
    error_messages: int = 0
    avg_processing_time: float = 0.0
    max_processing_time: float = 0.0
    min_processing_time: float = float('inf')


class FightHandler(BaseHandler):
    """
    Fight消息处理器
    
    负责处理所有Fight相关的消息，包括战斗匹配、战斗操作、
    技能系统、战斗结算、战斗回放等功能的消息路由和处理。
    """
    
    def __init__(self):
        """初始化Fight消息处理器"""
        super().__init__()
        
        # 注册的控制器
        self._controllers: Dict[str, Any] = {}
        
        # 消息路由映射
        self.message_routes = {
            # 战斗匹配相关消息 (8001-8100)
            8001: 'match',      # 加入匹配队列
            8002: 'match',      # 取消匹配
            8003: 'match',      # 匹配状态查询
            8004: 'match',      # 匹配确认
            8005: 'match',      # 匹配拒绝
            8006: 'match',      # 自定义匹配
            8007: 'match',      # 邀请匹配
            8008: 'match',      # 匹配历史
            
            # 战斗操作相关消息 (8101-8200)
            8101: 'battle',     # 加入战斗
            8102: 'battle',     # 战斗操作
            8103: 'battle',     # 战斗状态查询
            8104: 'battle',     # 离开战斗
            8105: 'battle',     # 战斗准备
            8106: 'battle',     # 战斗开始
            8107: 'battle',     # 战斗暂停
            8108: 'battle',     # 战斗恢复
            8109: 'battle',     # 战斗投降
            8110: 'battle',     # 战斗重连
            
            # 技能系统相关消息 (8201-8300)
            8201: 'battle',     # 技能释放
            8202: 'battle',     # 技能打断
            8203: 'battle',     # 技能升级
            8204: 'battle',     # 技能学习
            8205: 'battle',     # 技能重置
            8206: 'battle',     # 技能预选
            8207: 'battle',     # 技能组合
            8208: 'battle',     # 技能冷却查询
            
            # 战斗结算相关消息 (8301-8400)
            8301: 'battle',     # 战斗结算
            8302: 'battle',     # 战斗奖励
            8303: 'battle',     # 战斗统计
            8304: 'battle',     # 战斗评分
            8305: 'battle',     # 战斗记录
            8306: 'battle',     # 战斗成就
            
            # 战斗回放相关消息 (8401-8500)
            8401: 'battle',     # 保存回放
            8402: 'battle',     # 获取回放
            8403: 'battle',     # 删除回放
            8404: 'battle',     # 分享回放
            8405: 'battle',     # 回放列表
            8406: 'battle',     # 回放详情
        }
        
        # 消息统计
        self.message_stats = FightMessageStats()
        
        # 处理时间记录
        self.processing_times: List[float] = []
        self.max_processing_records = 1000
        
        # 消息验证器
        self.message_validators: Dict[int, callable] = {}
        
        # 活跃连接追踪
        self.active_connections: Dict[str, Dict[str, Any]] = {}
        
        # 战斗房间追踪
        self.battle_rooms: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info("Fight消息处理器初始化完成")
    
    async def initialize(self):
        """初始化消息处理器"""
        try:
            # 调用父类初始化
            await super().initialize()
            
            # 初始化消息验证器
            await self._initialize_validators()
            
            # 启动定时任务
            asyncio.create_task(self._update_statistics())
            asyncio.create_task(self._cleanup_inactive_connections())
            
            self.logger.info("Fight消息处理器初始化成功")
            
        except Exception as e:
            self.logger.error("Fight消息处理器初始化失败", error=str(e))
            raise
    
    def register_controller(self, name: str, controller: Any):
        """
        注册控制器
        
        Args:
            name: 控制器名称
            controller: 控制器实例
        """
        self._controllers[name] = controller
        self.logger.info("控制器注册成功", controller_name=name)
    
    async def handle_message(self, message: Any, context: RequestContext) -> Any:
        """
        处理消息
        
        Args:
            message: 消息数据
            context: 请求上下文
            
        Returns:
            Any: 处理结果
        """
        start_time = time.time()
        
        try:
            # 更新连接活跃状态
            await self._update_connection_activity(context.connection_id)
            
            # 验证消息
            if not await self._validate_message(message, context):
                self.message_stats.error_messages += 1
                raise ValueError("消息验证失败")
            
            # 路由消息
            result = await self._route_message(context, message)
            
            # 更新统计
            processing_time = time.time() - start_time
            await self._update_message_stats(context.message_id, processing_time)
            
            self.logger.info("消息处理完成", 
                           message_id=context.message_id,
                           processing_time=processing_time)
            
            return result
            
        except Exception as e:
            processing_time = time.time() - start_time
            self.message_stats.error_messages += 1
            
            self.logger.error("消息处理失败", 
                            message_id=context.message_id,
                            error=str(e),
                            processing_time=processing_time,
                            traceback=traceback.format_exc())
            
            # 返回错误响应
            return {
                'error': str(e),
                'message_id': context.message_id,
                'timestamp': time.time()
            }
    
    async def _route_message(self, context: RequestContext, message: Any) -> Any:
        """路由消息到对应的控制器"""
        try:
            # 获取消息ID
            message_id = getattr(message, 'message_id', context.message_id)
            
            # 查找对应的控制器
            controller_name = self.message_routes.get(message_id)
            if not controller_name:
                raise ValueError(f"未找到消息ID {message_id} 对应的控制器")
            
            # 获取控制器
            controller = self._controllers.get(controller_name)
            if not controller:
                raise ValueError(f"控制器 {controller_name} 未注册")
            
            # 调用控制器处理消息
            return await controller.handle_message(message, context)
            
        except Exception as e:
            self.logger.error("消息路由失败", 
                            message_id=getattr(message, 'message_id', 'unknown'),
                            error=str(e))
            raise
    
    async def _validate_message(self, message: Any, context: RequestContext) -> bool:
        """验证消息"""
        try:
            # 基础验证
            if not hasattr(message, 'message_id'):
                self.logger.warning("消息缺少message_id", 
                                  connection_id=context.connection_id)
                return False
            
            message_id = message.message_id
            
            # 检查消息ID是否支持
            if message_id not in self.message_routes:
                self.logger.warning("不支持的消息ID", 
                                  message_id=message_id,
                                  connection_id=context.connection_id)
                return False
            
            # 自定义验证器
            validator = self.message_validators.get(message_id)
            if validator:
                if not await validator(message, context):
                    self.logger.warning("消息自定义验证失败", 
                                      message_id=message_id,
                                      connection_id=context.connection_id)
                    return False
            
            # 战斗状态验证
            if message_id in range(8101, 8401):  # 战斗相关消息
                if not await self._validate_battle_context(message, context):
                    return False
            
            # 匹配状态验证
            if message_id in range(8001, 8101):  # 匹配相关消息
                if not await self._validate_match_context(message, context):
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error("消息验证异常", 
                            message_id=getattr(message, 'message_id', 'unknown'),
                            error=str(e))
            return False
    
    async def _validate_battle_context(self, message: Any, context: RequestContext) -> bool:
        """验证战斗上下文"""
        try:
            # 检查用户是否在战斗中
            user_id = getattr(context, 'user_id', None)
            if not user_id:
                return False
            
            # 检查战斗房间状态
            battle_id = getattr(message, 'battle_id', None)
            if battle_id and battle_id in self.battle_rooms:
                room_info = self.battle_rooms[battle_id]
                if user_id not in room_info.get('participants', []):
                    self.logger.warning("用户不在战斗房间中", 
                                      user_id=user_id,
                                      battle_id=battle_id)
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error("战斗上下文验证失败", error=str(e))
            return False
    
    async def _validate_match_context(self, message: Any, context: RequestContext) -> bool:
        """验证匹配上下文"""
        try:
            # 检查用户状态
            user_id = getattr(context, 'user_id', None)
            if not user_id:
                return False
            
            # 检查匹配状态
            message_id = message.message_id
            
            # 取消匹配不需要验证匹配状态
            if message_id == 8002:
                return True
            
            # 其他匹配消息的验证逻辑
            return True
            
        except Exception as e:
            self.logger.error("匹配上下文验证失败", error=str(e))
            return False
    
    async def _update_connection_activity(self, connection_id: str):
        """更新连接活跃状态"""
        try:
            if connection_id not in self.active_connections:
                self.active_connections[connection_id] = {
                    'first_seen': time.time(),
                    'last_activity': time.time(),
                    'message_count': 0
                }
            else:
                self.active_connections[connection_id]['last_activity'] = time.time()
                self.active_connections[connection_id]['message_count'] += 1
                
        except Exception as e:
            self.logger.error("更新连接活跃状态失败", 
                            connection_id=connection_id,
                            error=str(e))
    
    async def _update_message_stats(self, message_id: int, processing_time: float):
        """更新消息统计"""
        try:
            self.message_stats.total_messages += 1
            
            # 按消息类型分类统计
            if message_id in range(8001, 8101):
                self.message_stats.match_messages += 1
            elif message_id in range(8101, 8201):
                self.message_stats.battle_messages += 1
            elif message_id in range(8201, 8301):
                self.message_stats.skill_messages += 1
            elif message_id in range(8301, 8401):
                self.message_stats.settlement_messages += 1
            elif message_id in range(8401, 8501):
                self.message_stats.replay_messages += 1
            
            # 更新处理时间统计
            self.processing_times.append(processing_time)
            if len(self.processing_times) > self.max_processing_records:
                self.processing_times = self.processing_times[-self.max_processing_records:]
            
            # 更新处理时间统计数据
            self.message_stats.avg_processing_time = sum(self.processing_times) / len(self.processing_times)
            self.message_stats.max_processing_time = max(self.message_stats.max_processing_time, processing_time)
            self.message_stats.min_processing_time = min(self.message_stats.min_processing_time, processing_time)
            
        except Exception as e:
            self.logger.error("更新消息统计失败", error=str(e))
    
    async def _initialize_validators(self):
        """初始化消息验证器"""
        try:
            # 战斗操作验证器
            async def validate_battle_action(message, context):
                return hasattr(message, 'battle_id') and hasattr(message, 'action_type')
            
            # 技能释放验证器
            async def validate_skill_cast(message, context):
                return (hasattr(message, 'skill_id') and 
                       hasattr(message, 'target_id') and
                       hasattr(message, 'battle_id'))
            
            # 匹配加入验证器
            async def validate_match_join(message, context):
                return hasattr(message, 'match_type') and hasattr(message, 'character_id')
            
            # 注册验证器
            self.message_validators[8102] = validate_battle_action  # 战斗操作
            self.message_validators[8201] = validate_skill_cast     # 技能释放
            self.message_validators[8001] = validate_match_join     # 加入匹配
            
            self.logger.info("消息验证器初始化完成", 
                           validator_count=len(self.message_validators))
            
        except Exception as e:
            self.logger.error("消息验证器初始化失败", error=str(e))
    
    async def _update_statistics(self):
        """更新统计信息"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟更新一次
                
                # 清理过期的处理时间记录
                current_time = time.time()
                cutoff_time = current_time - 3600  # 保留1小时内的记录
                
                # 这里可以添加更复杂的统计逻辑
                
            except Exception as e:
                self.logger.error("更新统计信息异常", error=str(e))
    
    async def _cleanup_inactive_connections(self):
        """清理不活跃的连接"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                inactive_connections = []
                
                for connection_id, info in self.active_connections.items():
                    # 10分钟未活跃的连接视为不活跃
                    if current_time - info['last_activity'] > 600:
                        inactive_connections.append(connection_id)
                
                for connection_id in inactive_connections:
                    del self.active_connections[connection_id]
                
                if inactive_connections:
                    self.logger.info("清理不活跃连接", 
                                   count=len(inactive_connections))
                    
            except Exception as e:
                self.logger.error("清理不活跃连接异常", error=str(e))
    
    def add_battle_room(self, battle_id: str, room_info: Dict[str, Any]):
        """添加战斗房间"""
        try:
            self.battle_rooms[battle_id] = room_info
            self.logger.info("战斗房间添加成功", 
                           battle_id=battle_id,
                           participants=room_info.get('participants', []))
            
        except Exception as e:
            self.logger.error("添加战斗房间失败", 
                            battle_id=battle_id,
                            error=str(e))
    
    def remove_battle_room(self, battle_id: str):
        """移除战斗房间"""
        try:
            if battle_id in self.battle_rooms:
                del self.battle_rooms[battle_id]
                self.logger.info("战斗房间移除成功", battle_id=battle_id)
            
        except Exception as e:
            self.logger.error("移除战斗房间失败", 
                            battle_id=battle_id,
                            error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取处理器统计信息"""
        return {
            'message_stats': {
                'total_messages': self.message_stats.total_messages,
                'match_messages': self.message_stats.match_messages,
                'battle_messages': self.message_stats.battle_messages,
                'skill_messages': self.message_stats.skill_messages,
                'settlement_messages': self.message_stats.settlement_messages,
                'replay_messages': self.message_stats.replay_messages,
                'error_messages': self.message_stats.error_messages,
                'avg_processing_time': self.message_stats.avg_processing_time,
                'max_processing_time': self.message_stats.max_processing_time,
                'min_processing_time': self.message_stats.min_processing_time
            },
            'connection_info': {
                'active_connections': len(self.active_connections),
                'battle_rooms': len(self.battle_rooms)
            },
            'route_info': {
                'registered_controllers': len(self._controllers),
                'message_routes': len(self.message_routes),
                'validators': len(self.message_validators)
            }
        }
    
    def get_route_info(self) -> Dict[str, Any]:
        """获取路由信息"""
        return {
            'message_routes': self.message_routes.copy(),
            'controllers': list(self._controllers.keys()),
            'validators': list(self.message_validators.keys())
        }
    
    async def cleanup(self):
        """清理处理器资源"""
        try:
            # 清理连接信息
            self.active_connections.clear()
            self.battle_rooms.clear()
            
            # 清理统计信息
            self.processing_times.clear()
            
            # 清理控制器引用
            self._controllers.clear()
            
            # 清理验证器
            self.message_validators.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Fight消息处理器清理完成")
            
        except Exception as e:
            self.logger.error("Fight消息处理器清理失败", error=str(e))