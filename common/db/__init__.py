"""
common/db 模块

该模块提供了高性能、高可用的数据库访问层，包含以下功能：
- Redis连接池管理和缓存策略
- MongoDB连接池管理和异步操作
- 基础文档类和仓库模式
- 数据一致性保障机制
- 自动扫描和注册功能

主要组件：
- RedisManager: Redis连接池和缓存管理
- MongoManager: MongoDB连接池和数据操作
- BaseDocument: 文档基类
- BaseRepository: 仓库基类
- 缓存策略: LRU/LFU/FIFO等缓存策略
- 一致性管理: 分布式锁、事务、事件溯源
- 自动扫描: 文档类自动发现和仓库生成

使用示例：
    # 初始化数据库管理器
    from common.db import initialize_database
    await initialize_database()

    # 使用文档和仓库
    from common.db import BaseDocument, get_repository
    from dataclasses import dataclass

    @dataclass
    class User(BaseDocument):
        username: str = ""
        email: str = ""

    user_repo = get_repository(User)
    user = User(username="test", email="test@example.com")
    await user_repo.save(user)

    # 使用缓存
    from common.db import redis_manager
    await redis_manager.set("key", "value", ttl=3600)
    value = await redis_manager.get("key")

    # 使用分布式锁
    from common.db import create_distributed_lock
    async with await create_distributed_lock("resource_key"):
        # 临界区代码
        pass
"""

# 导入核心管理器
from .redis_manager import (
    redis_manager,
    RedisManager,
    RedisConnectionPool,
    DistributedLock,
    BloomFilter,
    get_redis_value,
    set_redis_value,
    delete_redis_keys,
    create_redis_lock,
)

from .mongo_manager import (
    mongo_manager,
    MongoManager,
    MongoConnectionPool,
    MongoTransaction,
    find_one_document,
    find_many_documents,
    insert_document,
    update_document,
    delete_document,
)

# 导入文档和仓库基类
from .base_document import (
    BaseDocument,
    DocumentRegistry,
    document_registry,
    register_document,
    get_document_class,
    get_document_class_by_collection,
    list_registered_documents,
    create_document_from_dict,
    # 示例文档类
    User,
    GameRecord,
)

from .base_repository import (
    BaseRepository,
    PageInfo,
    QueryResult,
    create_repository,
)

# 导入缓存策略
from .cache_strategy import (
    CacheMode,
    EvictionPolicy,
    BaseCacheStrategy,
    LRUCacheStrategy,
    LFUCacheStrategy,
    FIFOCacheStrategy,
    CacheAsideStrategy,
    WriteThroughStrategy,
    WriteBehindStrategy,
    CacheManager,
    cache_manager,
    create_lru_cache,
    create_lfu_cache,
    create_fifo_cache,
    get_cache_strategy,
)

# 导入一致性管理
from .consistency import (
    ConsistencyLevel,
    TransactionStatus,
    EventType,
    Event,
    OptimisticLock,
    EventStore,
    TwoPhaseCommitCoordinator,
    ConsistencyManager,
    consistency_manager,
    optimistic_update,
    compare_and_swap,
    create_distributed_lock,
    append_event,
)

# 导入自动扫描
from .auto_scanner import (
    DocumentScanner,
    RepositoryManager,
    AutoScanner,
    auto_scanner,
    scan_and_setup_documents,
    get_repository,
    get_repository_by_name,
    get_repository_by_collection,
    quick_setup,
    repo,
)


# 便捷的初始化函数
async def initialize_database(redis_config: dict = None, mongo_config: dict = None):
    """
    初始化数据库管理器
    
    Args:
        redis_config: Redis配置，如果为None则从配置文件加载
        mongo_config: MongoDB配置，如果为None则从配置文件加载
    """
    try:
        # 初始化Redis管理器
        await redis_manager.initialize(redis_config)
        
        # 初始化MongoDB管理器  
        await mongo_manager.initialize(mongo_config)
        
        from common.logger import logger
        logger.info("数据库管理器初始化完成")
        
    except Exception as e:
        from common.logger import logger
        logger.error(f"数据库管理器初始化失败: {e}")
        raise


async def shutdown_database():
    """关闭数据库管理器"""
    try:
        await redis_manager.close()
        await mongo_manager.close()
        
        from common.logger import logger
        logger.info("数据库管理器已关闭")
        
    except Exception as e:
        from common.logger import logger
        logger.error(f"数据库管理器关闭失败: {e}")


# 导出所有公共接口
__all__ = [
    # 初始化函数
    'initialize_database',
    'shutdown_database',
    
    # Redis相关
    'redis_manager',
    'RedisManager',
    'RedisConnectionPool', 
    'DistributedLock',
    'BloomFilter',
    'get_redis_value',
    'set_redis_value',
    'delete_redis_keys',
    'create_redis_lock',
    
    # MongoDB相关
    'mongo_manager',
    'MongoManager',
    'MongoConnectionPool',
    'MongoTransaction',
    'find_one_document',
    'find_many_documents',
    'insert_document',
    'update_document',
    'delete_document',
    
    # 文档和仓库
    'BaseDocument',
    'DocumentRegistry',
    'document_registry',
    'register_document',
    'get_document_class',
    'get_document_class_by_collection',
    'list_registered_documents',
    'create_document_from_dict',
    'User',
    'GameRecord',
    'BaseRepository',
    'PageInfo',
    'QueryResult',
    'create_repository',
    
    # 缓存策略
    'CacheMode',
    'EvictionPolicy',
    'BaseCacheStrategy',
    'LRUCacheStrategy',
    'LFUCacheStrategy',
    'FIFOCacheStrategy',
    'CacheAsideStrategy',
    'WriteThroughStrategy',
    'WriteBehindStrategy',
    'CacheManager',
    'cache_manager',
    'create_lru_cache',
    'create_lfu_cache',
    'create_fifo_cache',
    'get_cache_strategy',
    
    # 一致性管理
    'ConsistencyLevel',
    'TransactionStatus',
    'EventType',
    'Event',
    'OptimisticLock',
    'EventStore',
    'TwoPhaseCommitCoordinator',
    'ConsistencyManager',
    'consistency_manager',
    'optimistic_update',
    'compare_and_swap',
    'create_distributed_lock',
    'append_event',
    
    # 自动扫描
    'DocumentScanner',
    'RepositoryManager',
    'AutoScanner',
    'auto_scanner',
    'scan_and_setup_documents',
    'get_repository',
    'get_repository_by_name',
    'get_repository_by_collection',
    'quick_setup',
    'repo',
]
