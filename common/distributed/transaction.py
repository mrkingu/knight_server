"""
分布式事务模块

该模块提供分布式事务功能，包括：
- 两阶段提交（2PC）协议实现
- TCC（Try-Confirm-Cancel）模式支持
- 事务补偿机制
- 事务状态持久化
- 超时回滚机制
- 事务日志和审计
"""

import asyncio
import time
import uuid
import json
from typing import Dict, Any, Optional, List, Union, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from common.logger import logger


class TransactionState(Enum):
    """事务状态枚举"""
    INITIAL = "initial"         # 初始状态
    PREPARING = "preparing"     # 准备阶段
    PREPARED = "prepared"       # 已准备
    COMMITTING = "committing"   # 提交阶段
    COMMITTED = "committed"     # 已提交
    ABORTING = "aborting"       # 中止阶段
    ABORTED = "aborted"         # 已中止
    TIMEOUT = "timeout"         # 超时
    FAILED = "failed"           # 失败


class ParticipantState(Enum):
    """参与者状态枚举"""
    PENDING = "pending"         # 等待中
    PREPARED = "prepared"       # 已准备
    COMMITTED = "committed"     # 已提交
    ABORTED = "aborted"         # 已中止
    FAILED = "failed"           # 失败
    TIMEOUT = "timeout"         # 超时


class TransactionType(Enum):
    """事务类型枚举"""
    TWO_PHASE_COMMIT = "2pc"    # 两阶段提交
    TCC = "tcc"                 # Try-Confirm-Cancel
    SAGA = "saga"               # Saga模式


@dataclass
class TransactionConfig:
    """事务配置"""
    timeout: float = 30.0               # 事务超时时间（秒）
    prepare_timeout: float = 10.0       # 准备阶段超时时间
    commit_timeout: float = 10.0        # 提交阶段超时时间
    retry_count: int = 3                # 重试次数
    retry_delay: float = 1.0            # 重试延迟（秒）
    enable_compensation: bool = True     # 启用补偿机制
    enable_audit_log: bool = True       # 启用审计日志
    enable_persistent: bool = True      # 启用持久化
    coordinator_id: str = "default"     # 协调者ID


@dataclass
class ParticipantInfo:
    """参与者信息"""
    participant_id: str
    endpoint: str
    state: ParticipantState = ParticipantState.PENDING
    prepare_result: Optional[bool] = None
    commit_result: Optional[bool] = None
    error_message: Optional[str] = None
    last_updated: float = field(default_factory=time.time)


@dataclass
class TransactionContext:
    """事务上下文"""
    transaction_id: str
    transaction_type: TransactionType
    state: TransactionState
    participants: Dict[str, ParticipantInfo]
    created_at: float
    updated_at: float
    timeout_at: float
    coordinator_id: str
    business_data: Dict[str, Any] = field(default_factory=dict)
    audit_logs: List[Dict[str, Any]] = field(default_factory=list)
    compensation_data: Dict[str, Any] = field(default_factory=dict)


class TransactionError(Exception):
    """事务异常基类"""
    pass


class TransactionTimeoutError(TransactionError):
    """事务超时异常"""
    pass


class TransactionAbortError(TransactionError):
    """事务中止异常"""
    pass


class ParticipantError(TransactionError):
    """参与者异常"""
    pass


class TransactionParticipant(ABC):
    """事务参与者抽象基类"""
    
    @abstractmethod
    async def prepare(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """准备阶段"""
        pass
    
    @abstractmethod
    async def commit(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """提交阶段"""
        pass
    
    @abstractmethod
    async def abort(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """中止阶段"""
        pass
    
    async def compensate(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """补偿操作（可选）"""
        return True


class TCCParticipant(ABC):
    """TCC参与者抽象基类"""
    
    @abstractmethod
    async def try_phase(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """Try阶段"""
        pass
    
    @abstractmethod
    async def confirm_phase(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """Confirm阶段"""
        pass
    
    @abstractmethod
    async def cancel_phase(self, transaction_id: str, context: Dict[str, Any]) -> bool:
        """Cancel阶段"""
        pass


class TransactionCoordinator:
    """事务协调器"""
    
    def __init__(self, config: TransactionConfig, redis_manager=None):
        """
        初始化事务协调器
        
        Args:
            config: 事务配置
            redis_manager: Redis管理器（用于持久化）
        """
        self.config = config
        self.redis_manager = redis_manager
        self.transactions: Dict[str, TransactionContext] = {}
        self.participants: Dict[str, TransactionParticipant] = {}
        self.tcc_participants: Dict[str, TCCParticipant] = {}
        
        # 启动超时检查任务
        self.timeout_task = asyncio.create_task(self._timeout_check_loop())
    
    def register_participant(self, participant_id: str, participant: TransactionParticipant):
        """注册事务参与者"""
        self.participants[participant_id] = participant
        logger.info(f"注册事务参与者: {participant_id}")
    
    def register_tcc_participant(self, participant_id: str, participant: TCCParticipant):
        """注册TCC参与者"""
        self.tcc_participants[participant_id] = participant
        logger.info(f"注册TCC参与者: {participant_id}")
    
    def unregister_participant(self, participant_id: str):
        """注销参与者"""
        self.participants.pop(participant_id, None)
        self.tcc_participants.pop(participant_id, None)
        logger.info(f"注销参与者: {participant_id}")
    
    async def begin_transaction(self, transaction_type: TransactionType = TransactionType.TWO_PHASE_COMMIT,
                              participant_ids: List[str] = None,
                              business_data: Dict[str, Any] = None) -> str:
        """
        开始事务
        
        Args:
            transaction_type: 事务类型
            participant_ids: 参与者ID列表
            business_data: 业务数据
            
        Returns:
            str: 事务ID
        """
        transaction_id = str(uuid.uuid4())
        current_time = time.time()
        
        # 创建参与者信息
        participants = {}
        if participant_ids:
            for pid in participant_ids:
                participants[pid] = ParticipantInfo(
                    participant_id=pid,
                    endpoint=f"participant://{pid}"
                )
        
        # 创建事务上下文
        context = TransactionContext(
            transaction_id=transaction_id,
            transaction_type=transaction_type,
            state=TransactionState.INITIAL,
            participants=participants,
            created_at=current_time,
            updated_at=current_time,
            timeout_at=current_time + self.config.timeout,
            coordinator_id=self.config.coordinator_id,
            business_data=business_data or {},
        )
        
        # 记录审计日志
        await self._add_audit_log(context, "TRANSACTION_BEGIN", {
            'transaction_type': transaction_type.value,
            'participant_count': len(participants),
            'timeout': self.config.timeout
        })
        
        # 保存事务
        self.transactions[transaction_id] = context
        
        # 持久化
        if self.config.enable_persistent:
            await self._save_transaction(context)
        
        logger.info(f"开始事务: {transaction_id}, 类型: {transaction_type.value}, 参与者: {participant_ids}")
        return transaction_id
    
    async def execute_2pc(self, transaction_id: str, context_data: Dict[str, Any] = None) -> bool:
        """
        执行两阶段提交事务
        
        Args:
            transaction_id: 事务ID
            context_data: 上下文数据
            
        Returns:
            bool: 是否成功
        """
        context = self.transactions.get(transaction_id)
        if not context:
            raise TransactionError(f"事务不存在: {transaction_id}")
        
        if context.transaction_type != TransactionType.TWO_PHASE_COMMIT:
            raise TransactionError(f"事务类型不匹配: {context.transaction_type}")
        
        try:
            # 第一阶段：准备
            await self._update_transaction_state(context, TransactionState.PREPARING)
            prepare_success = await self._prepare_phase(context, context_data or {})
            
            if prepare_success:
                await self._update_transaction_state(context, TransactionState.PREPARED)
                
                # 第二阶段：提交
                await self._update_transaction_state(context, TransactionState.COMMITTING)
                commit_success = await self._commit_phase(context, context_data or {})
                
                if commit_success:
                    await self._update_transaction_state(context, TransactionState.COMMITTED)
                    logger.info(f"2PC事务提交成功: {transaction_id}")
                    return True
                else:
                    await self._update_transaction_state(context, TransactionState.FAILED)
                    logger.error(f"2PC事务提交失败: {transaction_id}")
                    return False
            else:
                # 准备失败，回滚
                await self._update_transaction_state(context, TransactionState.ABORTING)
                await self._abort_phase(context, context_data or {})
                await self._update_transaction_state(context, TransactionState.ABORTED)
                logger.warning(f"2PC事务准备失败，已回滚: {transaction_id}")
                return False
                
        except Exception as e:
            logger.error(f"2PC事务执行异常: {transaction_id}, 错误: {e}")
            await self._update_transaction_state(context, TransactionState.FAILED)
            # 尝试回滚
            try:
                await self._abort_phase(context, context_data or {})
            except Exception as abort_error:
                logger.error(f"回滚失败: {abort_error}")
            return False
    
    async def execute_tcc(self, transaction_id: str, context_data: Dict[str, Any] = None) -> bool:
        """
        执行TCC事务
        
        Args:
            transaction_id: 事务ID
            context_data: 上下文数据
            
        Returns:
            bool: 是否成功
        """
        context = self.transactions.get(transaction_id)
        if not context:
            raise TransactionError(f"事务不存在: {transaction_id}")
        
        if context.transaction_type != TransactionType.TCC:
            raise TransactionError(f"事务类型不匹配: {context.transaction_type}")
        
        try:
            # Try阶段
            await self._update_transaction_state(context, TransactionState.PREPARING)
            try_success = await self._try_phase(context, context_data or {})
            
            if try_success:
                await self._update_transaction_state(context, TransactionState.PREPARED)
                
                # Confirm阶段
                await self._update_transaction_state(context, TransactionState.COMMITTING)
                confirm_success = await self._confirm_phase(context, context_data or {})
                
                if confirm_success:
                    await self._update_transaction_state(context, TransactionState.COMMITTED)
                    logger.info(f"TCC事务提交成功: {transaction_id}")
                    return True
                else:
                    await self._update_transaction_state(context, TransactionState.FAILED)
                    logger.error(f"TCC事务Confirm失败: {transaction_id}")
                    return False
            else:
                # Try失败，执行Cancel
                await self._update_transaction_state(context, TransactionState.ABORTING)
                await self._cancel_phase(context, context_data or {})
                await self._update_transaction_state(context, TransactionState.ABORTED)
                logger.warning(f"TCC事务Try失败，已Cancel: {transaction_id}")
                return False
                
        except Exception as e:
            logger.error(f"TCC事务执行异常: {transaction_id}, 错误: {e}")
            await self._update_transaction_state(context, TransactionState.FAILED)
            # 尝试Cancel
            try:
                await self._cancel_phase(context, context_data or {})
            except Exception as cancel_error:
                logger.error(f"Cancel失败: {cancel_error}")
            return False
    
    async def _prepare_phase(self, context: TransactionContext, context_data: Dict[str, Any]) -> bool:
        """准备阶段"""
        tasks = []
        for participant_id, participant_info in context.participants.items():
            participant = self.participants.get(participant_id)
            if participant:
                task = asyncio.create_task(
                    self._call_participant_prepare(context, participant_id, participant, context_data)
                )
                tasks.append(task)
        
        if not tasks:
            return True
        
        # 等待所有参与者响应
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查结果
        all_prepared = True
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"参与者准备异常: {result}")
                all_prepared = False
            elif not result:
                all_prepared = False
        
        return all_prepared
    
    async def _commit_phase(self, context: TransactionContext, context_data: Dict[str, Any]) -> bool:
        """提交阶段"""
        tasks = []
        for participant_id, participant_info in context.participants.items():
            participant = self.participants.get(participant_id)
            if participant:
                task = asyncio.create_task(
                    self._call_participant_commit(context, participant_id, participant, context_data)
                )
                tasks.append(task)
        
        if not tasks:
            return True
        
        # 等待所有参与者响应
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查结果
        all_committed = True
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"参与者提交异常: {result}")
                all_committed = False
            elif not result:
                all_committed = False
        
        return all_committed
    
    async def _abort_phase(self, context: TransactionContext, context_data: Dict[str, Any]) -> bool:
        """中止阶段"""
        tasks = []
        for participant_id, participant_info in context.participants.items():
            participant = self.participants.get(participant_id)
            if participant:
                task = asyncio.create_task(
                    self._call_participant_abort(context, participant_id, participant, context_data)
                )
                tasks.append(task)
        
        if not tasks:
            return True
        
        # 等待所有参与者响应
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 记录失败的中止操作
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"参与者中止异常: {result}")
        
        return True  # 即使部分失败也返回True，因为这是清理操作
    
    async def _try_phase(self, context: TransactionContext, context_data: Dict[str, Any]) -> bool:
        """TCC Try阶段"""
        tasks = []
        for participant_id, participant_info in context.participants.items():
            participant = self.tcc_participants.get(participant_id)
            if participant:
                task = asyncio.create_task(
                    self._call_tcc_participant_try(context, participant_id, participant, context_data)
                )
                tasks.append(task)
        
        if not tasks:
            return True
        
        # 等待所有参与者响应
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查结果
        all_tried = True
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"TCC Try异常: {result}")
                all_tried = False
            elif not result:
                all_tried = False
        
        return all_tried
    
    async def _confirm_phase(self, context: TransactionContext, context_data: Dict[str, Any]) -> bool:
        """TCC Confirm阶段"""
        tasks = []
        for participant_id, participant_info in context.participants.items():
            participant = self.tcc_participants.get(participant_id)
            if participant:
                task = asyncio.create_task(
                    self._call_tcc_participant_confirm(context, participant_id, participant, context_data)
                )
                tasks.append(task)
        
        if not tasks:
            return True
        
        # 等待所有参与者响应
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 检查结果
        all_confirmed = True
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"TCC Confirm异常: {result}")
                all_confirmed = False
            elif not result:
                all_confirmed = False
        
        return all_confirmed
    
    async def _cancel_phase(self, context: TransactionContext, context_data: Dict[str, Any]) -> bool:
        """TCC Cancel阶段"""
        tasks = []
        for participant_id, participant_info in context.participants.items():
            participant = self.tcc_participants.get(participant_id)
            if participant:
                task = asyncio.create_task(
                    self._call_tcc_participant_cancel(context, participant_id, participant, context_data)
                )
                tasks.append(task)
        
        if not tasks:
            return True
        
        # 等待所有参与者响应
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 记录失败的Cancel操作
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"TCC Cancel异常: {result}")
        
        return True  # 即使部分失败也返回True，因为这是清理操作
    
    async def _call_participant_prepare(self, context: TransactionContext, participant_id: str,
                                      participant: TransactionParticipant, context_data: Dict[str, Any]) -> bool:
        """调用参与者准备方法"""
        try:
            timeout = asyncio.timeout(self.config.prepare_timeout)
            async with timeout:
                result = await participant.prepare(context.transaction_id, context_data)
                
                # 更新参与者状态
                participant_info = context.participants[participant_id]
                participant_info.state = ParticipantState.PREPARED if result else ParticipantState.FAILED
                participant_info.prepare_result = result
                participant_info.last_updated = time.time()
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"参与者准备超时: {participant_id}")
            context.participants[participant_id].state = ParticipantState.TIMEOUT
            return False
        except Exception as e:
            logger.error(f"参与者准备异常: {participant_id}, 错误: {e}")
            participant_info = context.participants[participant_id]
            participant_info.state = ParticipantState.FAILED
            participant_info.error_message = str(e)
            return False
    
    async def _call_participant_commit(self, context: TransactionContext, participant_id: str,
                                     participant: TransactionParticipant, context_data: Dict[str, Any]) -> bool:
        """调用参与者提交方法"""
        try:
            timeout = asyncio.timeout(self.config.commit_timeout)
            async with timeout:
                result = await participant.commit(context.transaction_id, context_data)
                
                # 更新参与者状态
                participant_info = context.participants[participant_id]
                participant_info.state = ParticipantState.COMMITTED if result else ParticipantState.FAILED
                participant_info.commit_result = result
                participant_info.last_updated = time.time()
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"参与者提交超时: {participant_id}")
            context.participants[participant_id].state = ParticipantState.TIMEOUT
            return False
        except Exception as e:
            logger.error(f"参与者提交异常: {participant_id}, 错误: {e}")
            participant_info = context.participants[participant_id]
            participant_info.state = ParticipantState.FAILED
            participant_info.error_message = str(e)
            return False
    
    async def _call_participant_abort(self, context: TransactionContext, participant_id: str,
                                    participant: TransactionParticipant, context_data: Dict[str, Any]) -> bool:
        """调用参与者中止方法"""
        try:
            timeout = asyncio.timeout(self.config.commit_timeout)
            async with timeout:
                result = await participant.abort(context.transaction_id, context_data)
                
                # 更新参与者状态
                participant_info = context.participants[participant_id]
                participant_info.state = ParticipantState.ABORTED if result else ParticipantState.FAILED
                participant_info.last_updated = time.time()
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"参与者中止超时: {participant_id}")
            context.participants[participant_id].state = ParticipantState.TIMEOUT
            return False
        except Exception as e:
            logger.error(f"参与者中止异常: {participant_id}, 错误: {e}")
            participant_info = context.participants[participant_id]
            participant_info.state = ParticipantState.FAILED
            participant_info.error_message = str(e)
            return False
    
    async def _call_tcc_participant_try(self, context: TransactionContext, participant_id: str,
                                       participant: TCCParticipant, context_data: Dict[str, Any]) -> bool:
        """调用TCC参与者Try方法"""
        try:
            timeout = asyncio.timeout(self.config.prepare_timeout)
            async with timeout:
                result = await participant.try_phase(context.transaction_id, context_data)
                
                # 更新参与者状态
                participant_info = context.participants[participant_id]
                participant_info.state = ParticipantState.PREPARED if result else ParticipantState.FAILED
                participant_info.prepare_result = result
                participant_info.last_updated = time.time()
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"TCC Try超时: {participant_id}")
            context.participants[participant_id].state = ParticipantState.TIMEOUT
            return False
        except Exception as e:
            logger.error(f"TCC Try异常: {participant_id}, 错误: {e}")
            participant_info = context.participants[participant_id]
            participant_info.state = ParticipantState.FAILED
            participant_info.error_message = str(e)
            return False
    
    async def _call_tcc_participant_confirm(self, context: TransactionContext, participant_id: str,
                                          participant: TCCParticipant, context_data: Dict[str, Any]) -> bool:
        """调用TCC参与者Confirm方法"""
        try:
            timeout = asyncio.timeout(self.config.commit_timeout)
            async with timeout:
                result = await participant.confirm_phase(context.transaction_id, context_data)
                
                # 更新参与者状态
                participant_info = context.participants[participant_id]
                participant_info.state = ParticipantState.COMMITTED if result else ParticipantState.FAILED
                participant_info.commit_result = result
                participant_info.last_updated = time.time()
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"TCC Confirm超时: {participant_id}")
            context.participants[participant_id].state = ParticipantState.TIMEOUT
            return False
        except Exception as e:
            logger.error(f"TCC Confirm异常: {participant_id}, 错误: {e}")
            participant_info = context.participants[participant_id]
            participant_info.state = ParticipantState.FAILED
            participant_info.error_message = str(e)
            return False
    
    async def _call_tcc_participant_cancel(self, context: TransactionContext, participant_id: str,
                                         participant: TCCParticipant, context_data: Dict[str, Any]) -> bool:
        """调用TCC参与者Cancel方法"""
        try:
            timeout = asyncio.timeout(self.config.commit_timeout)
            async with timeout:
                result = await participant.cancel_phase(context.transaction_id, context_data)
                
                # 更新参与者状态
                participant_info = context.participants[participant_id]
                participant_info.state = ParticipantState.ABORTED if result else ParticipantState.FAILED
                participant_info.last_updated = time.time()
                
                return result
                
        except asyncio.TimeoutError:
            logger.error(f"TCC Cancel超时: {participant_id}")
            context.participants[participant_id].state = ParticipantState.TIMEOUT
            return False
        except Exception as e:
            logger.error(f"TCC Cancel异常: {participant_id}, 错误: {e}")
            participant_info = context.participants[participant_id]
            participant_info.state = ParticipantState.FAILED
            participant_info.error_message = str(e)
            return False
    
    async def _update_transaction_state(self, context: TransactionContext, new_state: TransactionState):
        """更新事务状态"""
        old_state = context.state
        context.state = new_state
        context.updated_at = time.time()
        
        # 记录审计日志
        await self._add_audit_log(context, "STATE_CHANGE", {
            'old_state': old_state.value,
            'new_state': new_state.value
        })
        
        # 持久化
        if self.config.enable_persistent:
            await self._save_transaction(context)
        
        logger.debug(f"事务状态更新: {context.transaction_id}, {old_state.value} -> {new_state.value}")
    
    async def _add_audit_log(self, context: TransactionContext, event_type: str, data: Dict[str, Any]):
        """添加审计日志"""
        if not self.config.enable_audit_log:
            return
        
        log_entry = {
            'timestamp': time.time(),
            'event_type': event_type,
            'transaction_id': context.transaction_id,
            'coordinator_id': context.coordinator_id,
            'data': data
        }
        
        context.audit_logs.append(log_entry)
        
        # 限制日志数量
        if len(context.audit_logs) > 100:
            context.audit_logs = context.audit_logs[-100:]
    
    async def _save_transaction(self, context: TransactionContext):
        """持久化事务"""
        if not self.redis_manager:
            return
        
        try:
            key = f"transaction:{context.transaction_id}"
            data = {
                'transaction_id': context.transaction_id,
                'transaction_type': context.transaction_type.value,
                'state': context.state.value,
                'participants': {
                    pid: {
                        'participant_id': p.participant_id,
                        'endpoint': p.endpoint,
                        'state': p.state.value,
                        'prepare_result': p.prepare_result,
                        'commit_result': p.commit_result,
                        'error_message': p.error_message,
                        'last_updated': p.last_updated
                    } for pid, p in context.participants.items()
                },
                'created_at': context.created_at,
                'updated_at': context.updated_at,
                'timeout_at': context.timeout_at,
                'coordinator_id': context.coordinator_id,
                'business_data': context.business_data,
                'audit_logs': context.audit_logs,
                'compensation_data': context.compensation_data
            }
            
            # 设置过期时间为超时时间的2倍
            ttl = int((context.timeout_at - time.time()) * 2)
            if ttl > 0:
                await self.redis_manager.setex(key, ttl, json.dumps(data))
            
        except Exception as e:
            logger.error(f"持久化事务失败: {context.transaction_id}, 错误: {e}")
    
    async def _load_transaction(self, transaction_id: str) -> Optional[TransactionContext]:
        """加载事务"""
        if not self.redis_manager:
            return None
        
        try:
            key = f"transaction:{transaction_id}"
            data = await self.redis_manager.get(key)
            
            if not data:
                return None
            
            transaction_data = json.loads(data)
            
            # 重建参与者信息
            participants = {}
            for pid, p_data in transaction_data['participants'].items():
                participants[pid] = ParticipantInfo(
                    participant_id=p_data['participant_id'],
                    endpoint=p_data['endpoint'],
                    state=ParticipantState(p_data['state']),
                    prepare_result=p_data.get('prepare_result'),
                    commit_result=p_data.get('commit_result'),
                    error_message=p_data.get('error_message'),
                    last_updated=p_data['last_updated']
                )
            
            # 重建事务上下文
            context = TransactionContext(
                transaction_id=transaction_data['transaction_id'],
                transaction_type=TransactionType(transaction_data['transaction_type']),
                state=TransactionState(transaction_data['state']),
                participants=participants,
                created_at=transaction_data['created_at'],
                updated_at=transaction_data['updated_at'],
                timeout_at=transaction_data['timeout_at'],
                coordinator_id=transaction_data['coordinator_id'],
                business_data=transaction_data.get('business_data', {}),
                audit_logs=transaction_data.get('audit_logs', []),
                compensation_data=transaction_data.get('compensation_data', {})
            )
            
            return context
            
        except Exception as e:
            logger.error(f"加载事务失败: {transaction_id}, 错误: {e}")
            return None
    
    async def _timeout_check_loop(self):
        """超时检查循环"""
        while True:
            try:
                await asyncio.sleep(1.0)  # 每秒检查一次
                current_time = time.time()
                
                timeout_transactions = []
                for transaction_id, context in self.transactions.items():
                    if (context.timeout_at < current_time and 
                        context.state not in [TransactionState.COMMITTED, TransactionState.ABORTED, TransactionState.TIMEOUT]):
                        timeout_transactions.append(transaction_id)
                
                # 处理超时事务
                for transaction_id in timeout_transactions:
                    await self._handle_transaction_timeout(transaction_id)
                    
            except asyncio.CancelledError:
                logger.debug("超时检查任务已取消")
                break
            except Exception as e:
                logger.error(f"超时检查异常: {e}")
    
    async def _handle_transaction_timeout(self, transaction_id: str):
        """处理事务超时"""
        context = self.transactions.get(transaction_id)
        if not context:
            return
        
        logger.warning(f"事务超时: {transaction_id}")
        
        # 更新状态为超时
        await self._update_transaction_state(context, TransactionState.TIMEOUT)
        
        # 尝试回滚
        try:
            if context.transaction_type == TransactionType.TWO_PHASE_COMMIT:
                await self._abort_phase(context, {})
            elif context.transaction_type == TransactionType.TCC:
                await self._cancel_phase(context, {})
        except Exception as e:
            logger.error(f"超时回滚失败: {transaction_id}, 错误: {e}")
    
    def get_transaction(self, transaction_id: str) -> Optional[TransactionContext]:
        """获取事务上下文"""
        return self.transactions.get(transaction_id)
    
    async def abort_transaction(self, transaction_id: str) -> bool:
        """中止事务"""
        context = self.transactions.get(transaction_id)
        if not context:
            logger.warning(f"事务不存在: {transaction_id}")
            return False
        
        if context.state in [TransactionState.COMMITTED, TransactionState.ABORTED]:
            logger.warning(f"事务已结束，无法中止: {transaction_id}")
            return False
        
        try:
            await self._update_transaction_state(context, TransactionState.ABORTING)
            
            if context.transaction_type == TransactionType.TWO_PHASE_COMMIT:
                await self._abort_phase(context, {})
            elif context.transaction_type == TransactionType.TCC:
                await self._cancel_phase(context, {})
            
            await self._update_transaction_state(context, TransactionState.ABORTED)
            logger.info(f"事务中止成功: {transaction_id}")
            return True
            
        except Exception as e:
            logger.error(f"事务中止失败: {transaction_id}, 错误: {e}")
            await self._update_transaction_state(context, TransactionState.FAILED)
            return False
    
    def list_transactions(self) -> List[str]:
        """列出所有事务ID"""
        return list(self.transactions.keys())
    
    def get_transaction_stats(self) -> Dict[str, Any]:
        """获取事务统计信息"""
        stats = {
            'total_transactions': len(self.transactions),
            'by_state': {},
            'by_type': {}
        }
        
        for context in self.transactions.values():
            # 按状态统计
            state_key = context.state.value
            stats['by_state'][state_key] = stats['by_state'].get(state_key, 0) + 1
            
            # 按类型统计
            type_key = context.transaction_type.value
            stats['by_type'][type_key] = stats['by_type'].get(type_key, 0) + 1
        
        return stats
    
    async def cleanup_completed_transactions(self):
        """清理已完成的事务"""
        completed_transactions = []
        current_time = time.time()
        
        for transaction_id, context in self.transactions.items():
            if (context.state in [TransactionState.COMMITTED, TransactionState.ABORTED, TransactionState.TIMEOUT] and
                current_time - context.updated_at > 3600):  # 1小时后清理
                completed_transactions.append(transaction_id)
        
        for transaction_id in completed_transactions:
            del self.transactions[transaction_id]
            logger.debug(f"清理已完成事务: {transaction_id}")
        
        logger.info(f"清理了 {len(completed_transactions)} 个已完成事务")
    
    async def close(self):
        """关闭协调器"""
        if self.timeout_task:
            self.timeout_task.cancel()
            try:
                await self.timeout_task
            except asyncio.CancelledError:
                pass
        
        logger.info("事务协调器已关闭")


# 默认配置实例
default_config = TransactionConfig()

# 默认事务协调器实例
_default_coordinator = None


def get_transaction_coordinator(config: TransactionConfig = None, redis_manager=None) -> TransactionCoordinator:
    """
    获取事务协调器实例
    
    Args:
        config: 事务配置
        redis_manager: Redis管理器
        
    Returns:
        TransactionCoordinator: 事务协调器实例
    """
    global _default_coordinator
    
    if config is None:
        config = default_config
    
    if _default_coordinator is None:
        _default_coordinator = TransactionCoordinator(config, redis_manager)
    
    return _default_coordinator


# 便捷函数
async def begin_2pc_transaction(participant_ids: List[str], business_data: Dict[str, Any] = None) -> str:
    """开始2PC事务的便捷函数"""
    coordinator = get_transaction_coordinator()
    return await coordinator.begin_transaction(
        TransactionType.TWO_PHASE_COMMIT, 
        participant_ids, 
        business_data
    )


async def begin_tcc_transaction(participant_ids: List[str], business_data: Dict[str, Any] = None) -> str:
    """开始TCC事务的便捷函数"""
    coordinator = get_transaction_coordinator()
    return await coordinator.begin_transaction(
        TransactionType.TCC, 
        participant_ids, 
        business_data
    )


async def execute_transaction(transaction_id: str, context_data: Dict[str, Any] = None) -> bool:
    """执行事务的便捷函数"""
    coordinator = get_transaction_coordinator()
    context = coordinator.get_transaction(transaction_id)
    
    if not context:
        raise TransactionError(f"事务不存在: {transaction_id}")
    
    if context.transaction_type == TransactionType.TWO_PHASE_COMMIT:
        return await coordinator.execute_2pc(transaction_id, context_data)
    elif context.transaction_type == TransactionType.TCC:
        return await coordinator.execute_tcc(transaction_id, context_data)
    else:
        raise TransactionError(f"不支持的事务类型: {context.transaction_type}")


# 事务装饰器
def distributed_transaction(transaction_type: TransactionType = TransactionType.TWO_PHASE_COMMIT,
                           participant_ids: List[str] = None,
                           auto_execute: bool = True):
    """分布式事务装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            coordinator = get_transaction_coordinator()
            
            # 开始事务
            transaction_id = await coordinator.begin_transaction(
                transaction_type, 
                participant_ids or []
            )
            
            try:
                # 执行业务逻辑
                result = await func(transaction_id, *args, **kwargs)
                
                # 自动执行事务
                if auto_execute:
                    success = await execute_transaction(transaction_id)
                    if not success:
                        raise TransactionAbortError(f"事务执行失败: {transaction_id}")
                
                return result
                
            except Exception as e:
                # 中止事务
                await coordinator.abort_transaction(transaction_id)
                raise e
        
        return wrapper
    return decorator