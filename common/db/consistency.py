"""
数据一致性保障模块

该模块实现分布式环境下的数据一致性保障机制，包含以下功能：
- 最终一致性实现
- 分布式事务（两阶段提交）
- 事件溯源
- 补偿机制
- 乐观锁（版本号）
- 悲观锁（分布式锁）
- CAS操作
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable, Union, TypeVar, Generic
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from common.logger import logger
from .redis_manager import redis_manager, DistributedLock
from .mongo_manager import mongo_manager, MongoTransaction
from .base_document import BaseDocument


T = TypeVar('T', bound=BaseDocument)


class ConsistencyLevel(Enum):
    """一致性级别"""
    EVENTUAL = "eventual"        # 最终一致性
    STRONG = "strong"           # 强一致性
    WEAK = "weak"               # 弱一致性
    BOUNDED_STALENESS = "bounded_staleness"  # 有界过期一致性


class TransactionStatus(Enum):
    """事务状态"""
    PENDING = "pending"         # 待处理
    PREPARING = "preparing"     # 准备中
    PREPARED = "prepared"       # 已准备
    COMMITTING = "committing"   # 提交中
    COMMITTED = "committed"     # 已提交
    ABORTING = "aborting"       # 回滚中
    ABORTED = "aborted"         # 已回滚
    TIMEOUT = "timeout"         # 超时


class EventType(Enum):
    """事件类型"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    COMPENSATION = "compensation"


@dataclass
class Event:
    """事件"""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType = EventType.CREATE
    aggregate_id: str = ""
    aggregate_type: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    version: int = 1
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'event_id': self.event_id,
            'event_type': self.event_type.value,
            'aggregate_id': self.aggregate_id,
            'aggregate_type': self.aggregate_type,
            'data': self.data,
            'metadata': self.metadata,
            'timestamp': self.timestamp.isoformat(),
            'version': self.version,
            'correlation_id': self.correlation_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """从字典创建事件"""
        return cls(
            event_id=data['event_id'],
            event_type=EventType(data['event_type']),
            aggregate_id=data['aggregate_id'],
            aggregate_type=data['aggregate_type'],
            data=data['data'],
            metadata=data['metadata'],
            timestamp=datetime.fromisoformat(data['timestamp']),
            version=data['version'],
            correlation_id=data.get('correlation_id')
        )


@dataclass
class TransactionParticipant:
    """事务参与者"""
    participant_id: str
    endpoint: str
    status: TransactionStatus = TransactionStatus.PENDING
    last_updated: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DistributedTransaction:
    """分布式事务"""
    transaction_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    coordinator_id: str = ""
    status: TransactionStatus = TransactionStatus.PENDING
    participants: List[TransactionParticipant] = field(default_factory=list)
    operations: List[Dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    timeout_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(minutes=10))
    compensation_operations: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_participant(self, participant_id: str, endpoint: str):
        """添加参与者"""
        participant = TransactionParticipant(participant_id, endpoint)
        self.participants.append(participant)
    
    def update_participant_status(self, participant_id: str, status: TransactionStatus):
        """更新参与者状态"""
        for participant in self.participants:
            if participant.participant_id == participant_id:
                participant.status = status
                participant.last_updated = datetime.utcnow()
                break
    
    def all_participants_prepared(self) -> bool:
        """检查所有参与者是否都已准备"""
        return all(p.status == TransactionStatus.PREPARED for p in self.participants)
    
    def is_timeout(self) -> bool:
        """检查是否超时"""
        return datetime.utcnow() > self.timeout_at
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'transaction_id': self.transaction_id,
            'coordinator_id': self.coordinator_id,
            'status': self.status.value,
            'participants': [
                {
                    'participant_id': p.participant_id,
                    'endpoint': p.endpoint,
                    'status': p.status.value,
                    'last_updated': p.last_updated.isoformat()
                }
                for p in self.participants
            ],
            'operations': self.operations,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'timeout_at': self.timeout_at.isoformat(),
            'compensation_operations': self.compensation_operations
        }


class OptimisticLock:
    """乐观锁实现"""
    
    @staticmethod
    async def update_with_version_check(collection_name: str, doc_id: str, 
                                       current_version: int, update_data: Dict[str, Any]) -> bool:
        """
        使用版本号进行乐观锁更新
        
        Args:
            collection_name: 集合名称
            doc_id: 文档ID
            current_version: 当前版本号
            update_data: 更新数据
            
        Returns:
            是否更新成功
        """
        try:
            # 构建查询条件（包含版本号检查）
            filter_dict = {
                '_id': doc_id,
                'version': current_version,
                'is_deleted': False
            }
            
            # 构建更新操作（增加版本号）
            update_operation = {
                '$set': {**update_data, 'updated_at': datetime.utcnow()},
                '$inc': {'version': 1}
            }
            
            # 执行更新
            result = await mongo_manager.update_one(collection_name, filter_dict, update_operation)
            
            if result:
                logger.debug(f"乐观锁更新成功: {doc_id} (version: {current_version} -> {current_version + 1})")
                return True
            else:
                logger.warning(f"乐观锁更新失败，版本冲突: {doc_id} (version: {current_version})")
                return False
                
        except Exception as e:
            logger.error(f"乐观锁更新异常: {e}")
            return False
    
    @staticmethod
    async def compare_and_swap(collection_name: str, doc_id: str,
                              expected_value: Any, new_value: Any, 
                              field_name: str = 'data') -> bool:
        """
        比较并交换（CAS）操作
        
        Args:
            collection_name: 集合名称
            doc_id: 文档ID
            expected_value: 期望值
            new_value: 新值
            field_name: 字段名
            
        Returns:
            是否交换成功
        """
        try:
            # 构建查询条件
            filter_dict = {
                '_id': doc_id,
                field_name: expected_value,
                'is_deleted': False
            }
            
            # 构建更新操作
            update_operation = {
                '$set': {
                    field_name: new_value,
                    'updated_at': datetime.utcnow()
                },
                '$inc': {'version': 1}
            }
            
            # 执行CAS操作
            result = await mongo_manager.update_one(collection_name, filter_dict, update_operation)
            
            if result:
                logger.debug(f"CAS操作成功: {doc_id}.{field_name} ({expected_value} -> {new_value})")
                return True
            else:
                logger.debug(f"CAS操作失败，值不匹配: {doc_id}.{field_name} (expected: {expected_value})")
                return False
                
        except Exception as e:
            logger.error(f"CAS操作异常: {e}")
            return False


class EventStore:
    """事件存储"""
    
    EVENTS_COLLECTION = "events"
    SNAPSHOTS_COLLECTION = "snapshots"
    
    async def append_event(self, event: Event) -> bool:
        """
        追加事件到事件流
        
        Args:
            event: 事件
            
        Returns:
            是否追加成功
        """
        try:
            # 检查版本号连续性
            if event.version > 1:
                last_event = await self.get_last_event(event.aggregate_id, event.aggregate_type)
                if last_event and last_event.version != event.version - 1:
                    raise ValueError(f"事件版本号不连续: expected {last_event.version + 1}, got {event.version}")
            
            # 存储事件
            event_data = event.to_dict()
            result = await mongo_manager.insert_one(self.EVENTS_COLLECTION, event_data)
            
            if result:
                logger.debug(f"事件追加成功: {event.event_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"事件追加失败: {e}")
            return False
    
    async def get_events(self, aggregate_id: str, aggregate_type: str,
                        from_version: int = 1, to_version: Optional[int] = None) -> List[Event]:
        """
        获取聚合的事件流
        
        Args:
            aggregate_id: 聚合ID
            aggregate_type: 聚合类型
            from_version: 起始版本
            to_version: 结束版本
            
        Returns:
            事件列表
        """
        try:
            # 构建查询条件
            filter_dict = {
                'aggregate_id': aggregate_id,
                'aggregate_type': aggregate_type,
                'version': {'$gte': from_version}
            }
            
            if to_version is not None:
                filter_dict['version']['$lte'] = to_version
            
            # 按版本号排序
            sort = [('version', 1)]
            
            # 查询事件
            events_data = await mongo_manager.find_many(
                self.EVENTS_COLLECTION, filter_dict, sort=sort
            )
            
            # 转换为事件对象
            events = [Event.from_dict(event_data) for event_data in events_data]
            
            return events
            
        except Exception as e:
            logger.error(f"获取事件流失败: {e}")
            return []
    
    async def get_last_event(self, aggregate_id: str, aggregate_type: str) -> Optional[Event]:
        """
        获取聚合的最后一个事件
        
        Args:
            aggregate_id: 聚合ID
            aggregate_type: 聚合类型
            
        Returns:
            最后一个事件或None
        """
        try:
            filter_dict = {
                'aggregate_id': aggregate_id,
                'aggregate_type': aggregate_type
            }
            
            sort = [('version', -1)]
            
            event_data = await mongo_manager.find_one(
                self.EVENTS_COLLECTION, filter_dict, sort=sort
            )
            
            if event_data:
                return Event.from_dict(event_data)
            
            return None
            
        except Exception as e:
            logger.error(f"获取最后事件失败: {e}")
            return None
    
    async def save_snapshot(self, aggregate_id: str, aggregate_type: str,
                           version: int, data: Dict[str, Any]) -> bool:
        """
        保存聚合快照
        
        Args:
            aggregate_id: 聚合ID
            aggregate_type: 聚合类型
            version: 版本号
            data: 快照数据
            
        Returns:
            是否保存成功
        """
        try:
            snapshot_data = {
                'aggregate_id': aggregate_id,
                'aggregate_type': aggregate_type,
                'version': version,
                'data': data,
                'created_at': datetime.utcnow()
            }
            
            # 使用upsert操作
            filter_dict = {
                'aggregate_id': aggregate_id,
                'aggregate_type': aggregate_type
            }
            
            update_operation = {'$set': snapshot_data}
            
            # 先尝试更新，如果不存在则插入
            result = await mongo_manager.update_one(
                self.SNAPSHOTS_COLLECTION, filter_dict, update_operation
            )
            
            if not result:
                result = await mongo_manager.insert_one(self.SNAPSHOTS_COLLECTION, snapshot_data)
            
            if result:
                logger.debug(f"快照保存成功: {aggregate_id} (version: {version})")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"快照保存失败: {e}")
            return False
    
    async def get_snapshot(self, aggregate_id: str, aggregate_type: str) -> Optional[Dict[str, Any]]:
        """
        获取聚合快照
        
        Args:
            aggregate_id: 聚合ID
            aggregate_type: 聚合类型
            
        Returns:
            快照数据或None
        """
        try:
            filter_dict = {
                'aggregate_id': aggregate_id,
                'aggregate_type': aggregate_type
            }
            
            snapshot_data = await mongo_manager.find_one(self.SNAPSHOTS_COLLECTION, filter_dict)
            
            return snapshot_data
            
        except Exception as e:
            logger.error(f"获取快照失败: {e}")
            return None


class TwoPhaseCommitCoordinator:
    """两阶段提交协调器"""
    
    TRANSACTIONS_COLLECTION = "distributed_transactions"
    
    def __init__(self):
        self.coordinator_id = str(uuid.uuid4())
    
    async def begin_transaction(self, participants: List[Dict[str, str]]) -> DistributedTransaction:
        """
        开始分布式事务
        
        Args:
            participants: 参与者列表 [{'participant_id': 'id', 'endpoint': 'url'}]
            
        Returns:
            分布式事务
        """
        transaction = DistributedTransaction(coordinator_id=self.coordinator_id)
        
        for p in participants:
            transaction.add_participant(p['participant_id'], p['endpoint'])
        
        # 保存事务记录
        await self._save_transaction(transaction)
        
        logger.info(f"开始分布式事务: {transaction.transaction_id}")
        return transaction
    
    async def prepare_phase(self, transaction: DistributedTransaction,
                           operations: List[Dict[str, Any]]) -> bool:
        """
        执行准备阶段
        
        Args:
            transaction: 分布式事务
            operations: 操作列表
            
        Returns:
            是否所有参与者都准备成功
        """
        transaction.status = TransactionStatus.PREPARING
        transaction.operations = operations
        await self._save_transaction(transaction)
        
        try:
            # 并发向所有参与者发送准备请求
            prepare_tasks = []
            for participant in transaction.participants:
                task = asyncio.create_task(
                    self._send_prepare_request(participant, operations)
                )
                prepare_tasks.append((participant.participant_id, task))
            
            # 等待所有准备响应
            all_prepared = True
            for participant_id, task in prepare_tasks:
                try:
                    prepared = await asyncio.wait_for(task, timeout=30)
                    if prepared:
                        transaction.update_participant_status(participant_id, TransactionStatus.PREPARED)
                    else:
                        transaction.update_participant_status(participant_id, TransactionStatus.ABORTED)
                        all_prepared = False
                except asyncio.TimeoutError:
                    logger.error(f"参与者准备超时: {participant_id}")
                    transaction.update_participant_status(participant_id, TransactionStatus.TIMEOUT)
                    all_prepared = False
                except Exception as e:
                    logger.error(f"参与者准备失败 {participant_id}: {e}")
                    transaction.update_participant_status(participant_id, TransactionStatus.ABORTED)
                    all_prepared = False
            
            # 更新事务状态
            if all_prepared:
                transaction.status = TransactionStatus.PREPARED
                logger.info(f"所有参与者准备成功: {transaction.transaction_id}")
            else:
                transaction.status = TransactionStatus.ABORTED
                logger.warning(f"部分参与者准备失败: {transaction.transaction_id}")
            
            await self._save_transaction(transaction)
            return all_prepared
            
        except Exception as e:
            logger.error(f"准备阶段异常: {e}")
            transaction.status = TransactionStatus.ABORTED
            await self._save_transaction(transaction)
            return False
    
    async def commit_phase(self, transaction: DistributedTransaction) -> bool:
        """
        执行提交阶段
        
        Args:
            transaction: 分布式事务
            
        Returns:
            是否提交成功
        """
        if transaction.status != TransactionStatus.PREPARED:
            logger.error(f"事务状态不正确，无法提交: {transaction.status}")
            return False
        
        transaction.status = TransactionStatus.COMMITTING
        await self._save_transaction(transaction)
        
        try:
            # 并发向所有参与者发送提交请求
            commit_tasks = []
            for participant in transaction.participants:
                if participant.status == TransactionStatus.PREPARED:
                    task = asyncio.create_task(
                        self._send_commit_request(participant, transaction.operations)
                    )
                    commit_tasks.append((participant.participant_id, task))
            
            # 等待所有提交响应
            all_committed = True
            for participant_id, task in commit_tasks:
                try:
                    committed = await asyncio.wait_for(task, timeout=30)
                    if committed:
                        transaction.update_participant_status(participant_id, TransactionStatus.COMMITTED)
                    else:
                        all_committed = False
                except Exception as e:
                    logger.error(f"参与者提交失败 {participant_id}: {e}")
                    all_committed = False
            
            # 更新事务状态
            if all_committed:
                transaction.status = TransactionStatus.COMMITTED
                logger.info(f"分布式事务提交成功: {transaction.transaction_id}")
            else:
                # 部分提交失败，需要补偿
                transaction.status = TransactionStatus.ABORTED
                logger.error(f"分布式事务提交失败: {transaction.transaction_id}")
                await self._compensate_transaction(transaction)
            
            await self._save_transaction(transaction)
            return all_committed
            
        except Exception as e:
            logger.error(f"提交阶段异常: {e}")
            transaction.status = TransactionStatus.ABORTED
            await self._save_transaction(transaction)
            return False
    
    async def abort_transaction(self, transaction: DistributedTransaction) -> bool:
        """
        回滚事务
        
        Args:
            transaction: 分布式事务
            
        Returns:
            是否回滚成功
        """
        transaction.status = TransactionStatus.ABORTING
        await self._save_transaction(transaction)
        
        try:
            # 向所有已准备的参与者发送回滚请求
            abort_tasks = []
            for participant in transaction.participants:
                if participant.status == TransactionStatus.PREPARED:
                    task = asyncio.create_task(
                        self._send_abort_request(participant, transaction.operations)
                    )
                    abort_tasks.append((participant.participant_id, task))
            
            # 等待所有回滚响应
            for participant_id, task in abort_tasks:
                try:
                    await asyncio.wait_for(task, timeout=30)
                    transaction.update_participant_status(participant_id, TransactionStatus.ABORTED)
                except Exception as e:
                    logger.error(f"参与者回滚失败 {participant_id}: {e}")
            
            transaction.status = TransactionStatus.ABORTED
            await self._save_transaction(transaction)
            
            logger.info(f"分布式事务回滚完成: {transaction.transaction_id}")
            return True
            
        except Exception as e:
            logger.error(f"回滚阶段异常: {e}")
            return False
    
    async def _send_prepare_request(self, participant: TransactionParticipant,
                                   operations: List[Dict[str, Any]]) -> bool:
        """发送准备请求（模拟实现）"""
        # 这里应该是真实的网络请求到参与者
        # 为了演示，我们模拟一个成功的响应
        await asyncio.sleep(0.1)  # 模拟网络延迟
        logger.debug(f"发送准备请求到 {participant.participant_id}")
        return True  # 模拟成功准备
    
    async def _send_commit_request(self, participant: TransactionParticipant,
                                  operations: List[Dict[str, Any]]) -> bool:
        """发送提交请求（模拟实现）"""
        await asyncio.sleep(0.1)  # 模拟网络延迟
        logger.debug(f"发送提交请求到 {participant.participant_id}")
        return True  # 模拟成功提交
    
    async def _send_abort_request(self, participant: TransactionParticipant,
                                 operations: List[Dict[str, Any]]) -> bool:
        """发送回滚请求（模拟实现）"""
        await asyncio.sleep(0.1)  # 模拟网络延迟
        logger.debug(f"发送回滚请求到 {participant.participant_id}")
        return True  # 模拟成功回滚
    
    async def _compensate_transaction(self, transaction: DistributedTransaction):
        """补偿事务"""
        logger.warning(f"开始补偿事务: {transaction.transaction_id}")
        
        # 执行补偿操作
        for compensation_op in transaction.compensation_operations:
            try:
                # 这里应该执行具体的补偿逻辑
                logger.debug(f"执行补偿操作: {compensation_op}")
            except Exception as e:
                logger.error(f"补偿操作失败: {e}")
    
    async def _save_transaction(self, transaction: DistributedTransaction):
        """保存事务状态"""
        try:
            filter_dict = {'transaction_id': transaction.transaction_id}
            update_operation = {'$set': transaction.to_dict()}
            
            # 尝试更新，如果不存在则插入
            result = await mongo_manager.update_one(
                self.TRANSACTIONS_COLLECTION, filter_dict, update_operation
            )
            
            if not result:
                await mongo_manager.insert_one(self.TRANSACTIONS_COLLECTION, transaction.to_dict())
                
        except Exception as e:
            logger.error(f"保存事务状态失败: {e}")
    
    async def recover_transactions(self):
        """恢复未完成的事务"""
        try:
            # 查找未完成的事务
            filter_dict = {
                'coordinator_id': self.coordinator_id,
                'status': {'$in': [
                    TransactionStatus.PREPARING.value,
                    TransactionStatus.PREPARED.value,
                    TransactionStatus.COMMITTING.value,
                    TransactionStatus.ABORTING.value
                ]}
            }
            
            transactions_data = await mongo_manager.find_many(
                self.TRANSACTIONS_COLLECTION, filter_dict
            )
            
            for tx_data in transactions_data:
                # 检查是否超时
                created_at = datetime.fromisoformat(tx_data['created_at'])
                if datetime.utcnow() - created_at > timedelta(hours=1):
                    # 超时事务，强制回滚
                    logger.warning(f"发现超时事务，强制回滚: {tx_data['transaction_id']}")
                    # 这里应该实现具体的超时处理逻辑
            
        except Exception as e:
            logger.error(f"事务恢复失败: {e}")


class ConsistencyManager:
    """一致性管理器"""
    
    def __init__(self):
        self.event_store = EventStore()
        self.coordinator = TwoPhaseCommitCoordinator()
        
    async def ensure_eventual_consistency(self, aggregate_id: str, aggregate_type: str,
                                        timeout: float = 10.0) -> bool:
        """
        确保最终一致性
        
        Args:
            aggregate_id: 聚合ID
            aggregate_type: 聚合类型
            timeout: 超时时间
            
        Returns:
            是否达到一致性
        """
        start_time = datetime.utcnow()
        
        while (datetime.utcnow() - start_time).total_seconds() < timeout:
            try:
                # 检查是否有待处理的事件
                pending_events = await self._get_pending_events(aggregate_id, aggregate_type)
                if not pending_events:
                    return True
                
                # 处理待处理的事件
                for event in pending_events:
                    await self._process_event(event)
                
                await asyncio.sleep(0.1)  # 短暂等待
                
            except Exception as e:
                logger.error(f"确保最终一致性失败: {e}")
                return False
        
        logger.warning(f"最终一致性超时: {aggregate_id}")
        return False
    
    async def _get_pending_events(self, aggregate_id: str, aggregate_type: str) -> List[Event]:
        """获取待处理的事件（模拟实现）"""
        # 这里应该实现具体的待处理事件查询逻辑
        return []
    
    async def _process_event(self, event: Event):
        """处理事件（模拟实现）"""
        # 这里应该实现具体的事件处理逻辑
        logger.debug(f"处理事件: {event.event_id}")
    
    async def create_distributed_lock(self, resource_key: str, timeout: int = 30) -> DistributedLock:
        """
        创建分布式锁
        
        Args:
            resource_key: 资源键
            timeout: 超时时间
            
        Returns:
            分布式锁
        """
        lock_key = f"consistency:lock:{resource_key}"
        return await redis_manager.create_lock(lock_key, timeout)
    
    async def execute_with_strong_consistency(self, operations: List[Callable], 
                                            participants: List[Dict[str, str]]) -> bool:
        """
        以强一致性执行操作
        
        Args:
            operations: 操作列表
            participants: 参与者列表
            
        Returns:
            是否执行成功
        """
        if not participants:
            # 单节点操作，直接执行
            try:
                for operation in operations:
                    if asyncio.iscoroutinefunction(operation):
                        await operation()
                    else:
                        operation()
                return True
            except Exception as e:
                logger.error(f"单节点强一致性操作失败: {e}")
                return False
        
        # 分布式操作，使用两阶段提交
        transaction = await self.coordinator.begin_transaction(participants)
        
        try:
            # 准备阶段
            operation_data = [{'operation': str(op)} for op in operations]
            prepared = await self.coordinator.prepare_phase(transaction, operation_data)
            
            if prepared:
                # 提交阶段
                return await self.coordinator.commit_phase(transaction)
            else:
                # 回滚
                await self.coordinator.abort_transaction(transaction)
                return False
                
        except Exception as e:
            logger.error(f"分布式强一致性操作失败: {e}")
            await self.coordinator.abort_transaction(transaction)
            return False


# 全局一致性管理器
consistency_manager = ConsistencyManager()


# 便捷函数
async def optimistic_update(collection_name: str, doc_id: str, 
                           current_version: int, update_data: Dict[str, Any]) -> bool:
    """乐观锁更新的便捷函数"""
    return await OptimisticLock.update_with_version_check(
        collection_name, doc_id, current_version, update_data
    )


async def compare_and_swap(collection_name: str, doc_id: str,
                          expected_value: Any, new_value: Any, 
                          field_name: str = 'data') -> bool:
    """CAS操作的便捷函数"""
    return await OptimisticLock.compare_and_swap(
        collection_name, doc_id, expected_value, new_value, field_name
    )


async def create_distributed_lock(resource_key: str, timeout: int = 30) -> DistributedLock:
    """创建分布式锁的便捷函数"""
    return await consistency_manager.create_distributed_lock(resource_key, timeout)


async def append_event(aggregate_id: str, aggregate_type: str, event_type: EventType,
                      data: Dict[str, Any], version: int = 1) -> bool:
    """追加事件的便捷函数"""
    event = Event(
        aggregate_id=aggregate_id,
        aggregate_type=aggregate_type,
        event_type=event_type,
        data=data,
        version=version
    )
    return await consistency_manager.event_store.append_event(event)