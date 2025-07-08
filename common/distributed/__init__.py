"""
common/distributed 模块

该模块提供了完整的分布式功能实现，包括：
- 分布式锁
- 分布式ID生成器
- 分布式事务
- 一致性保障
"""

# 分布式锁模块
from .distributed_lock import (
    DistributedLock,
    ExclusiveLock,
    ReentrantLock,
    SharedLock,
    ReadWriteLock,
    LockConfig,
    LockInfo,
    LockType,
    LockState,
    DistributedLockError,
    LockTimeoutError,
    LockNotOwnedError,
    DeadlockError,
    LockExpiredError,
    create_lock,
    distributed_lock,
    distributed_lock_decorator,
    set_default_redis_manager,
    get_default_redis_manager,
    default_config as lock_default_config
)

# 分布式ID生成器模块
from .id_generator import (
    SnowflakeIDGenerator,
    IDGeneratorManager,
    SnowflakeConfig,
    IDMetadata,
    IDFormat,
    IDGeneratorError,
    ClockBackwardError,
    InvalidConfigError,
    WorkerIDConflictError,
    create_id_generator,
    get_id_generator,
    generate_id,
    async_generate_id,
    parse_id,
    id_generator_decorator,
    get_id_generator_manager,
    default_config as id_generator_default_config
)

# 分布式事务模块
from .transaction import (
    TransactionCoordinator,
    TransactionParticipant,
    TCCParticipant,
    TransactionConfig,
    TransactionContext,
    ParticipantInfo,
    TransactionState,
    ParticipantState,
    TransactionType,
    TransactionError,
    TransactionTimeoutError,
    TransactionAbortError,
    ParticipantError,
    get_transaction_coordinator,
    begin_2pc_transaction,
    begin_tcc_transaction,
    execute_transaction,
    distributed_transaction,
    default_config as transaction_default_config
)

# 一致性保障模块
from .consistency import (
    EventualConsistencyManager,
    OptimisticLock,
    ConsistentHashRing,
    ConsistencyConfig,
    VersionInfo,
    DataEntry,
    SyncResult,
    ConsistencyLevel,
    ConflictResolution,
    SyncDirection,
    ConsistencyError,
    VersionConflictError,
    SyncError,
    get_consistency_manager,
    put_data,
    get_data,
    delete_data,
    sync_data,
    create_consistent_hash_ring,
    eventual_consistency,
    default_config as consistency_default_config
)

# 导出所有模块
__all__ = [
    # 分布式锁
    'DistributedLock',
    'ExclusiveLock',
    'ReentrantLock',
    'SharedLock',
    'ReadWriteLock',
    'LockConfig',
    'LockInfo',
    'LockType',
    'LockState',
    'DistributedLockError',
    'LockTimeoutError',
    'LockNotOwnedError',
    'DeadlockError',
    'LockExpiredError',
    'create_lock',
    'distributed_lock',
    'distributed_lock_decorator',
    'set_default_redis_manager',
    'get_default_redis_manager',
    'lock_default_config',
    
    # 分布式ID生成器
    'SnowflakeIDGenerator',
    'IDGeneratorManager',
    'SnowflakeConfig',
    'IDMetadata',
    'IDFormat',
    'IDGeneratorError',
    'ClockBackwardError',
    'InvalidConfigError',
    'WorkerIDConflictError',
    'create_id_generator',
    'get_id_generator',
    'generate_id',
    'async_generate_id',
    'parse_id',
    'id_generator_decorator',
    'get_id_generator_manager',
    'id_generator_default_config',
    
    # 分布式事务
    'TransactionCoordinator',
    'TransactionParticipant',
    'TCCParticipant',
    'TransactionConfig',
    'TransactionContext',
    'ParticipantInfo',
    'TransactionState',
    'ParticipantState',
    'TransactionType',
    'TransactionError',
    'TransactionTimeoutError',
    'TransactionAbortError',
    'ParticipantError',
    'get_transaction_coordinator',
    'begin_2pc_transaction',
    'begin_tcc_transaction',
    'execute_transaction',
    'distributed_transaction',
    'transaction_default_config',
    
    # 一致性保障
    'EventualConsistencyManager',
    'OptimisticLock',
    'ConsistentHashRing',
    'ConsistencyConfig',
    'VersionInfo',
    'DataEntry',
    'SyncResult',
    'ConsistencyLevel',
    'ConflictResolution',
    'SyncDirection',
    'ConsistencyError',
    'VersionConflictError',
    'SyncError',
    'get_consistency_manager',
    'put_data',
    'get_data',
    'delete_data',
    'sync_data',
    'create_consistent_hash_ring',
    'eventual_consistency',
    'consistency_default_config'
]
