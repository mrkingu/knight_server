"""
MongoDB连接池管理器

该模块提供高性能、高可用的MongoDB连接池管理，包含以下功能：
- 异步连接池管理
- 自动重连机制
- 读写分离支持
- 异步CRUD操作
- 批量操作优化
- 事务支持
- 索引管理
- 聚合查询
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Union, Tuple, Callable
from dataclasses import dataclass
from datetime import datetime
from contextlib import asynccontextmanager

from common.logger import logger
from common.utils.singleton import Singleton

# Mock config loader for testing
def load_config():
    """Mock config loader"""
    return {
        'mongodb': {
            'uri': 'mongodb://localhost:27017',
            'database': 'game_dev',
            'username': '',
            'password': '',
            'auth_source': 'admin',
            'max_pool_size': 100,
            'min_pool_size': 10,
            'max_idle_time_ms': 300000,
            'server_selection_timeout_ms': 30000,
            'socket_timeout_ms': 30000,
            'connect_timeout_ms': 10000,
            'heartbeat_frequency_ms': 10000,
            'retry_writes': True,
            'w': 'majority',
            'read_preference': 'primaryPreferred',
            'collections': {
                'users': {
                    'indexes': [
                        {'keys': [('user_id', 1)], 'unique': True},
                        {'keys': [('email', 1)], 'unique': True},
                        {'keys': [('created_at', -1)]},
                    ]
                }
            }
        }
    }


class MongoError(Exception):
    """MongoDB相关异常"""
    pass


class ConnectionError(MongoError):
    """连接相关异常"""
    pass


class TransactionError(MongoError):
    """事务相关异常"""
    pass


@dataclass
class MongoConfig:
    """MongoDB配置"""
    uri: str = "mongodb://localhost:27017"
    database: str = "game_server"
    username: str = ""
    password: str = ""
    auth_source: str = "admin"
    
    # 连接池配置
    max_pool_size: int = 100
    min_pool_size: int = 10
    max_idle_time_ms: int = 300000  # 5分钟
    server_selection_timeout_ms: int = 30000  # 30秒
    socket_timeout_ms: int = 30000  # 30秒
    connect_timeout_ms: int = 10000  # 10秒
    heartbeat_frequency_ms: int = 10000  # 10秒
    retry_writes: bool = True
    w: str = "majority"
    read_preference: str = "primaryPreferred"
    
    # 集合配置
    collections: Dict[str, Dict] = None


class MockCollection:
    """Mock MongoDB集合实现（用于无MongoDB依赖的环境）"""
    
    def __init__(self, name: str):
        self.name = name
        self._documents: Dict[str, Dict] = {}
        self._counter = 1
    
    def _generate_id(self) -> str:
        """生成模拟的ObjectId"""
        object_id = f"mock_{self._counter:012d}"
        self._counter += 1
        return object_id
    
    async def find_one(self, filter_dict: Dict = None, projection: Dict = None) -> Optional[Dict]:
        """查找单个文档"""
        if not filter_dict:
            # 返回第一个文档
            for doc in self._documents.values():
                return self._apply_projection(doc, projection)
            return None
        
        for doc in self._documents.values():
            if self._match_filter(doc, filter_dict):
                return self._apply_projection(doc, projection)
        
        return None
    
    async def find(self, filter_dict: Dict = None, projection: Dict = None, 
                  limit: int = None, skip: int = None, sort: List[Tuple[str, int]] = None) -> List[Dict]:
        """查找多个文档"""
        results = []
        
        for doc in self._documents.values():
            if not filter_dict or self._match_filter(doc, filter_dict):
                results.append(self._apply_projection(doc, projection))
        
        # 应用排序
        if sort:
            for field, direction in reversed(sort):
                results.sort(key=lambda x: x.get(field, ""), reverse=(direction == -1))
        
        # 应用跳过和限制
        if skip:
            results = results[skip:]
        if limit:
            results = results[:limit]
        
        return results
    
    async def insert_one(self, document: Dict) -> str:
        """插入单个文档"""
        doc_copy = document.copy()
        if '_id' not in doc_copy:
            doc_copy['_id'] = self._generate_id()
        
        self._documents[str(doc_copy['_id'])] = doc_copy
        return str(doc_copy['_id'])
    
    async def insert_many(self, documents: List[Dict]) -> List[str]:
        """插入多个文档"""
        inserted_ids = []
        for doc in documents:
            doc_id = await self.insert_one(doc)
            inserted_ids.append(doc_id)
        return inserted_ids
    
    async def update_one(self, filter_dict: Dict, update: Dict) -> bool:
        """更新单个文档"""
        for doc_id, doc in self._documents.items():
            if self._match_filter(doc, filter_dict):
                self._apply_update(doc, update)
                return True
        return False
    
    async def update_many(self, filter_dict: Dict, update: Dict) -> int:
        """更新多个文档"""
        updated_count = 0
        for doc_id, doc in self._documents.items():
            if self._match_filter(doc, filter_dict):
                self._apply_update(doc, update)
                updated_count += 1
        return updated_count
    
    async def delete_one(self, filter_dict: Dict) -> bool:
        """删除单个文档"""
        for doc_id, doc in self._documents.items():
            if self._match_filter(doc, filter_dict):
                del self._documents[doc_id]
                return True
        return False
    
    async def delete_many(self, filter_dict: Dict) -> int:
        """删除多个文档"""
        to_delete = []
        for doc_id, doc in self._documents.items():
            if self._match_filter(doc, filter_dict):
                to_delete.append(doc_id)
        
        for doc_id in to_delete:
            del self._documents[doc_id]
        
        return len(to_delete)
    
    async def count_documents(self, filter_dict: Dict = None) -> int:
        """统计文档数量"""
        if not filter_dict:
            return len(self._documents)
        
        count = 0
        for doc in self._documents.values():
            if self._match_filter(doc, filter_dict):
                count += 1
        return count
    
    async def aggregate(self, pipeline: List[Dict]) -> List[Dict]:
        """聚合查询（简单实现）"""
        results = list(self._documents.values())
        
        for stage in pipeline:
            if '$match' in stage:
                results = [doc for doc in results if self._match_filter(doc, stage['$match'])]
            elif '$limit' in stage:
                results = results[:stage['$limit']]
            elif '$skip' in stage:
                results = results[stage['$skip']:]
            elif '$project' in stage:
                results = [self._apply_projection(doc, stage['$project']) for doc in results]
        
        return results
    
    def _match_filter(self, doc: Dict, filter_dict: Dict) -> bool:
        """检查文档是否匹配过滤条件"""
        for key, value in filter_dict.items():
            if key not in doc:
                return False
            if isinstance(value, dict):
                # 处理操作符
                for op, op_value in value.items():
                    if op == '$eq' and doc[key] != op_value:
                        return False
                    elif op == '$ne' and doc[key] == op_value:
                        return False
                    elif op == '$gt' and doc[key] <= op_value:
                        return False
                    elif op == '$gte' and doc[key] < op_value:
                        return False
                    elif op == '$lt' and doc[key] >= op_value:
                        return False
                    elif op == '$lte' and doc[key] > op_value:
                        return False
                    elif op == '$in' and doc[key] not in op_value:
                        return False
                    elif op == '$nin' and doc[key] in op_value:
                        return False
            else:
                if doc[key] != value:
                    return False
        return True
    
    def _apply_projection(self, doc: Dict, projection: Dict) -> Dict:
        """应用投影"""
        if not projection:
            return doc
        
        result = {}
        if projection.get('_id', 1):
            result['_id'] = doc.get('_id')
        
        for field, include in projection.items():
            if field != '_id' and include:
                if field in doc:
                    result[field] = doc[field]
        
        return result
    
    def _apply_update(self, doc: Dict, update: Dict):
        """应用更新操作"""
        for op, fields in update.items():
            if op == '$set':
                doc.update(fields)
            elif op == '$unset':
                for field in fields:
                    doc.pop(field, None)
            elif op == '$inc':
                for field, value in fields.items():
                    doc[field] = doc.get(field, 0) + value


class MockDatabase:
    """Mock MongoDB数据库实现"""
    
    def __init__(self, name: str):
        self.name = name
        self._collections: Dict[str, MockCollection] = {}
    
    def get_collection(self, name: str) -> MockCollection:
        """获取集合"""
        if name not in self._collections:
            self._collections[name] = MockCollection(name)
        return self._collections[name]
    
    async def list_collection_names(self) -> List[str]:
        """列出所有集合名称"""
        return list(self._collections.keys())


class MockMongoClient:
    """Mock MongoDB客户端实现"""
    
    def __init__(self, uri: str, **kwargs):
        self.uri = uri
        self._databases: Dict[str, MockDatabase] = {}
    
    def get_database(self, name: str) -> MockDatabase:
        """获取数据库"""
        if name not in self._databases:
            self._databases[name] = MockDatabase(name)
        return self._databases[name]
    
    async def close(self):
        """关闭客户端"""
        pass
    
    async def ping(self) -> bool:
        """Ping测试"""
        return True


class MongoConnectionPool:
    """MongoDB连接池"""
    
    def __init__(self, config: MongoConfig):
        self.config = config
        self._client = None
        self._database = None
        self._motor_module = None
        self._pymongo_module = None
        self._is_mock = False
        self._lock = asyncio.Lock()
        
        # 尝试导入MongoDB模块
        try:
            import motor.motor_asyncio as motor
            import pymongo
            self._motor_module = motor
            self._pymongo_module = pymongo
            logger.info(f"使用真实MongoDB连接池: {config.database}")
        except ImportError:
            logger.warning("MongoDB模块未安装，使用Mock实现")
            self._is_mock = True
    
    async def initialize(self):
        """初始化连接池"""
        async with self._lock:
            if self._client is not None:
                return
            
            if self._is_mock:
                self._client = MockMongoClient(self.config.uri)
                self._database = self._client.get_database(self.config.database)
            else:
                # 构建连接URI
                uri = self.config.uri
                if self.config.username and self.config.password:
                    # 如果有用户名和密码，构建认证URI
                    parts = uri.split("://")
                    if len(parts) == 2:
                        uri = f"{parts[0]}://{self.config.username}:{self.config.password}@{parts[1]}"
                
                # 创建客户端
                self._client = self._motor_module.AsyncIOMotorClient(
                    uri,
                    authSource=self.config.auth_source,
                    maxPoolSize=self.config.max_pool_size,
                    minPoolSize=self.config.min_pool_size,
                    maxIdleTimeMS=self.config.max_idle_time_ms,
                    serverSelectionTimeoutMS=self.config.server_selection_timeout_ms,
                    socketTimeoutMS=self.config.socket_timeout_ms,
                    connectTimeoutMS=self.config.connect_timeout_ms,
                    heartbeatFrequencyMS=self.config.heartbeat_frequency_ms,
                    retryWrites=self.config.retry_writes,
                    w=self.config.w,
                    readPreference=self.config.read_preference
                )
                
                self._database = self._client[self.config.database]
            
            logger.info(f"MongoDB连接池初始化完成: {self.config.database}")
    
    async def get_database(self):
        """获取数据库实例"""
        if self._database is None:
            await self.initialize()
        return self._database
    
    async def get_collection(self, collection_name: str):
        """获取集合实例"""
        database = await self.get_database()
        return database.get_collection(collection_name)
    
    async def close(self):
        """关闭连接池"""
        if self._client:
            await self._client.close()
        self._client = None
        self._database = None
        logger.info("MongoDB连接池已关闭")
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            if self._client is None:
                await self.initialize()
            
            if self._is_mock:
                return await self._client.ping()
            else:
                # 执行ping命令
                await self._client.admin.command('ping')
                return True
        except Exception as e:
            logger.error(f"MongoDB健康检查失败: {e}")
            return False


class MongoTransaction:
    """MongoDB事务管理器"""
    
    def __init__(self, client, session=None):
        self.client = client
        self.session = session
        self._is_mock = isinstance(client, MockMongoClient)
    
    async def __aenter__(self):
        """进入事务上下文"""
        if self._is_mock:
            # Mock实现不支持真正的事务
            logger.debug("Mock模式下使用伪事务")
            return self
        
        if self.session is None:
            self.session = await self.client.start_session()
        
        self.session.start_transaction()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """退出事务上下文"""
        if self._is_mock:
            return
        
        try:
            if exc_type is None:
                await self.session.commit_transaction()
                logger.debug("事务提交成功")
            else:
                await self.session.abort_transaction()
                logger.debug("事务已回滚")
        finally:
            await self.session.end_session()
    
    async def commit(self):
        """提交事务"""
        if not self._is_mock and self.session:
            await self.session.commit_transaction()
    
    async def abort(self):
        """回滚事务"""
        if not self._is_mock and self.session:
            await self.session.abort_transaction()


class MongoManager(Singleton):
    """MongoDB管理器"""
    
    def __init__(self, mock: bool = False):
        """初始化MongoDB管理器"""
        if hasattr(self, '_initialized'):
            return
        
        self._pool: Optional[MongoConnectionPool] = None
        self._collections_config: Dict[str, Dict] = {}
        self._mock = mock
        self._initialized = True
        
        logger.info("MongoDB管理器初始化完成")
    
    @classmethod
    def create_instance(cls, mock: bool = False):
        """创建新实例，避免单例模式问题"""
        instance = cls.__new__(cls)
        instance._pool = None
        instance._collections_config = {}
        instance._mock = mock
        instance._initialized = True
        return instance
    
    async def initialize(self, config_data: Optional[Dict] = None):
        """
        初始化MongoDB连接池
        
        Args:
            config_data: 配置数据，如果为None则从配置文件加载
        """
        if config_data is None:
            config = load_config()
            mongo_config_data = config.get('mongodb', {})
        else:
            mongo_config_data = config_data
        
        # 初始化连接池
        mongo_config = MongoConfig(**mongo_config_data)
        self._pool = MongoConnectionPool(mongo_config)
        await self._pool.initialize()
        
        # 保存集合配置
        self._collections_config = mongo_config_data.get('collections', {})
        
        # 初始化集合和索引
        await self._setup_collections()
        
        logger.info("MongoDB管理器初始化完成")
    
    async def _setup_collections(self):
        """设置集合和索引"""
        if not self._collections_config:
            return
        
        database = await self._pool.get_database()
        
        for collection_name, collection_config in self._collections_config.items():
            collection = await self.get_collection(collection_name)
            
            # 创建索引
            indexes = collection_config.get('indexes', [])
            for index_config in indexes:
                try:
                    if not self._pool._is_mock:
                        keys = index_config['keys']
                        options = {k: v for k, v in index_config.items() if k != 'keys'}
                        await collection.create_index(keys, **options)
                        logger.debug(f"创建索引: {collection_name}.{keys}")
                except Exception as e:
                    logger.error(f"创建索引失败 {collection_name}: {e}")
            
            # 设置TTL
            ttl_field = collection_config.get('ttl_field')
            ttl_seconds = collection_config.get('ttl_seconds')
            if ttl_field and ttl_seconds and not self._pool._is_mock:
                try:
                    await collection.create_index(
                        [(ttl_field, 1)], 
                        expireAfterSeconds=ttl_seconds
                    )
                    logger.debug(f"设置TTL: {collection_name}.{ttl_field} ({ttl_seconds}s)")
                except Exception as e:
                    logger.error(f"设置TTL失败 {collection_name}: {e}")
    
    async def get_collection(self, collection_name: str):
        """获取集合实例"""
        if not self._pool:
            raise ConnectionError("MongoDB连接池未初始化")
        return await self._pool.get_collection(collection_name)
    
    async def get_database(self):
        """获取数据库实例"""
        if not self._pool:
            raise ConnectionError("MongoDB连接池未初始化")
        return await self._pool.get_database()
    
    # CRUD操作
    async def find_one(self, collection_name: str, filter_dict: Dict = None, 
                      projection: Dict = None) -> Optional[Dict]:
        """
        查找单个文档
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            projection: 投影字段
            
        Returns:
            文档或None
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.find_one(filter_dict, projection)
            else:
                return await collection.find_one(filter_dict or {}, projection)
        except Exception as e:
            logger.error(f"MongoDB find_one 操作失败 {collection_name}: {e}")
            return None
    
    async def find_many(self, collection_name: str, filter_dict: Dict = None,
                       projection: Dict = None, limit: int = None, skip: int = None,
                       sort: List[Tuple[str, int]] = None) -> List[Dict]:
        """
        查找多个文档
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            projection: 投影字段
            limit: 限制数量
            skip: 跳过数量
            sort: 排序条件
            
        Returns:
            文档列表
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.find(filter_dict, projection, limit, skip, sort)
            else:
                cursor = collection.find(filter_dict or {}, projection)
                
                if sort:
                    cursor = cursor.sort(sort)
                if skip:
                    cursor = cursor.skip(skip)
                if limit:
                    cursor = cursor.limit(limit)
                
                return await cursor.to_list(length=limit)
        except Exception as e:
            logger.error(f"MongoDB find_many 操作失败 {collection_name}: {e}")
            return []
    
    async def insert_one(self, collection_name: str, document: Dict) -> Optional[str]:
        """
        插入单个文档
        
        Args:
            collection_name: 集合名称
            document: 文档数据
            
        Returns:
            插入的文档ID
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.insert_one(document)
            else:
                result = await collection.insert_one(document)
                return str(result.inserted_id)
        except Exception as e:
            logger.error(f"MongoDB insert_one 操作失败 {collection_name}: {e}")
            return None
    
    async def insert_many(self, collection_name: str, documents: List[Dict]) -> List[str]:
        """
        插入多个文档
        
        Args:
            collection_name: 集合名称
            documents: 文档列表
            
        Returns:
            插入的文档ID列表
        """
        if not documents:
            return []
        
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.insert_many(documents)
            else:
                result = await collection.insert_many(documents)
                return [str(oid) for oid in result.inserted_ids]
        except Exception as e:
            logger.error(f"MongoDB insert_many 操作失败 {collection_name}: {e}")
            return []
    
    async def update_one(self, collection_name: str, filter_dict: Dict, 
                        update: Dict) -> bool:
        """
        更新单个文档
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            update: 更新操作
            
        Returns:
            是否更新成功
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.update_one(filter_dict, update)
            else:
                result = await collection.update_one(filter_dict, update)
                return result.modified_count > 0
        except Exception as e:
            logger.error(f"MongoDB update_one 操作失败 {collection_name}: {e}")
            return False
    
    async def update_many(self, collection_name: str, filter_dict: Dict, 
                         update: Dict) -> int:
        """
        更新多个文档
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            update: 更新操作
            
        Returns:
            更新的文档数量
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.update_many(filter_dict, update)
            else:
                result = await collection.update_many(filter_dict, update)
                return result.modified_count
        except Exception as e:
            logger.error(f"MongoDB update_many 操作失败 {collection_name}: {e}")
            return 0
    
    async def delete_one(self, collection_name: str, filter_dict: Dict) -> bool:
        """
        删除单个文档
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            
        Returns:
            是否删除成功
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.delete_one(filter_dict)
            else:
                result = await collection.delete_one(filter_dict)
                return result.deleted_count > 0
        except Exception as e:
            logger.error(f"MongoDB delete_one 操作失败 {collection_name}: {e}")
            return False
    
    async def delete_many(self, collection_name: str, filter_dict: Dict) -> int:
        """
        删除多个文档
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            
        Returns:
            删除的文档数量
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.delete_many(filter_dict)
            else:
                result = await collection.delete_many(filter_dict)
                return result.deleted_count
        except Exception as e:
            logger.error(f"MongoDB delete_many 操作失败 {collection_name}: {e}")
            return 0
    
    async def count_documents(self, collection_name: str, filter_dict: Dict = None) -> int:
        """
        统计文档数量
        
        Args:
            collection_name: 集合名称
            filter_dict: 查询条件
            
        Returns:
            文档数量
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.count_documents(filter_dict)
            else:
                return await collection.count_documents(filter_dict or {})
        except Exception as e:
            logger.error(f"MongoDB count_documents 操作失败 {collection_name}: {e}")
            return 0
    
    async def aggregate(self, collection_name: str, pipeline: List[Dict]) -> List[Dict]:
        """
        聚合查询
        
        Args:
            collection_name: 集合名称
            pipeline: 聚合管道
            
        Returns:
            聚合结果
        """
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                return await collection.aggregate(pipeline)
            else:
                cursor = collection.aggregate(pipeline)
                return await cursor.to_list(length=None)
        except Exception as e:
            logger.error(f"MongoDB aggregate 操作失败 {collection_name}: {e}")
            return []
    
    async def create_transaction(self) -> MongoTransaction:
        """
        创建事务
        
        Returns:
            事务管理器
        """
        if not self._pool:
            raise ConnectionError("MongoDB连接池未初始化")
        
        return MongoTransaction(self._pool._client)
    
    async def bulk_write(self, collection_name: str, operations: List[Dict]) -> Dict:
        """
        批量写操作
        
        Args:
            collection_name: 集合名称
            operations: 操作列表
            
        Returns:
            操作结果
        """
        if not operations:
            return {'inserted_count': 0, 'modified_count': 0, 'deleted_count': 0}
        
        collection = await self.get_collection(collection_name)
        
        try:
            if self._pool._is_mock:
                # Mock实现：逐个执行操作
                inserted_count = 0
                modified_count = 0
                deleted_count = 0
                
                for op in operations:
                    if 'insert_one' in op:
                        await collection.insert_one(op['insert_one']['document'])
                        inserted_count += 1
                    elif 'update_one' in op:
                        success = await collection.update_one(
                            op['update_one']['filter'], 
                            op['update_one']['update']
                        )
                        if success:
                            modified_count += 1
                    elif 'delete_one' in op:
                        success = await collection.delete_one(op['delete_one']['filter'])
                        if success:
                            deleted_count += 1
                
                return {
                    'inserted_count': inserted_count,
                    'modified_count': modified_count,
                    'deleted_count': deleted_count
                }
            else:
                # 构建真实的批量操作
                from pymongo import InsertOne, UpdateOne, DeleteOne
                
                bulk_ops = []
                for op in operations:
                    if 'insert_one' in op:
                        bulk_ops.append(InsertOne(op['insert_one']['document']))
                    elif 'update_one' in op:
                        bulk_ops.append(UpdateOne(
                            op['update_one']['filter'],
                            op['update_one']['update']
                        ))
                    elif 'delete_one' in op:
                        bulk_ops.append(DeleteOne(op['delete_one']['filter']))
                
                result = await collection.bulk_write(bulk_ops)
                return {
                    'inserted_count': result.inserted_count,
                    'modified_count': result.modified_count,
                    'deleted_count': result.deleted_count
                }
        except Exception as e:
            logger.error(f"MongoDB bulk_write 操作失败 {collection_name}: {e}")
            return {'inserted_count': 0, 'modified_count': 0, 'deleted_count': 0}
    
    async def create_index(self, collection_name: str, keys: Union[str, List[Tuple[str, int]]], 
                          **kwargs) -> bool:
        """
        创建索引
        
        Args:
            collection_name: 集合名称
            keys: 索引键
            **kwargs: 索引选项
            
        Returns:
            是否创建成功
        """
        if self._pool._is_mock:
            logger.debug(f"Mock模式：跳过索引创建 {collection_name}")
            return True
        
        collection = await self.get_collection(collection_name)
        
        try:
            await collection.create_index(keys, **kwargs)
            logger.info(f"创建索引成功: {collection_name}.{keys}")
            return True
        except Exception as e:
            logger.error(f"创建索引失败 {collection_name}: {e}")
            return False
    
    async def drop_index(self, collection_name: str, index_name: str) -> bool:
        """
        删除索引
        
        Args:
            collection_name: 集合名称
            index_name: 索引名称
            
        Returns:
            是否删除成功
        """
        if self._pool._is_mock:
            logger.debug(f"Mock模式：跳过索引删除 {collection_name}")
            return True
        
        collection = await self.get_collection(collection_name)
        
        try:
            await collection.drop_index(index_name)
            logger.info(f"删除索引成功: {collection_name}.{index_name}")
            return True
        except Exception as e:
            logger.error(f"删除索引失败 {collection_name}: {e}")
            return False
    
    async def list_indexes(self, collection_name: str) -> List[Dict]:
        """
        列出索引
        
        Args:
            collection_name: 集合名称
            
        Returns:
            索引列表
        """
        if self._pool._is_mock:
            return []
        
        collection = await self.get_collection(collection_name)
        
        try:
            cursor = collection.list_indexes()
            return await cursor.to_list(length=None)
        except Exception as e:
            logger.error(f"列出索引失败 {collection_name}: {e}")
            return []
    
    async def health_check(self) -> bool:
        """
        健康检查
        
        Returns:
            是否健康
        """
        if not self._pool:
            return False
        return await self._pool.health_check()
    
    async def close(self):
        """关闭连接池"""
        if self._pool:
            await self._pool.close()
        self._pool = None
        logger.info("MongoDB管理器已关闭")


# 全局MongoDB管理器实例
mongo_manager = MongoManager()


# 便捷函数
async def find_one_document(collection_name: str, filter_dict: Dict = None, 
                           projection: Dict = None) -> Optional[Dict]:
    """查找单个文档的便捷函数"""
    return await mongo_manager.find_one(collection_name, filter_dict, projection)


async def find_many_documents(collection_name: str, filter_dict: Dict = None,
                             projection: Dict = None, limit: int = None) -> List[Dict]:
    """查找多个文档的便捷函数"""
    return await mongo_manager.find_many(collection_name, filter_dict, projection, limit)


async def insert_document(collection_name: str, document: Dict) -> Optional[str]:
    """插入文档的便捷函数"""
    return await mongo_manager.insert_one(collection_name, document)


async def update_document(collection_name: str, filter_dict: Dict, update: Dict) -> bool:
    """更新文档的便捷函数"""
    return await mongo_manager.update_one(collection_name, filter_dict, update)


async def delete_document(collection_name: str, filter_dict: Dict) -> bool:
    """删除文档的便捷函数"""
    return await mongo_manager.delete_one(collection_name, filter_dict)