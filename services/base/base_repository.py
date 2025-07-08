"""
基础数据访问类模块

该模块提供了与models层集成的基础数据访问类，支持标准CRUD操作、
查询构建、缓存策略、数据验证、事务支持、批量操作等功能。

主要功能：
- 与models层的集成
- 标准CRUD操作
- 查询构建器
- 缓存策略
- 数据验证
- 事务支持
- 批量操作
- 异步数据访问

使用示例：
```python
from services.base.base_repository import BaseRepository

class UserRepository(BaseRepository):
    def __init__(self):
        super().__init__(model_class=User, table_name="users")
    
    async def find_by_email(self, email: str) -> Optional[dict]:
        return await self.find_one({"email": email})
    
    async def find_active_users(self) -> List[dict]:
        return await self.find_many({"status": "active"})
    
    async def create_user_with_profile(self, user_data: dict, profile_data: dict) -> dict:
        async with self.transaction() as tx:
            user = await self.create(user_data, tx=tx)
            profile_data["user_id"] = user["id"]
            await self.profile_repo.create(profile_data, tx=tx)
            return user

# 使用
user_repo = UserRepository()
user = await user_repo.create({
    "username": "test",
    "email": "test@example.com",
    "password": "hashed_password"
})
```
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Type, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from contextlib import asynccontextmanager
from datetime import datetime

from common.logger import logger
try:
    from common.db import get_db_connection, Database, TransactionManager
except ImportError:
    # Mock database classes if not available
    class Database:
        def __init__(self):
            self._data = {}  # Simple in-memory storage
            self._next_id = 1
        
        async def close(self):
            pass
        
        async def insert_one(self, collection_name, data, transaction_id=None):
            # Generate a mock ID
            data_copy = data.copy()
            data_copy["_id"] = f"mock_id_{self._next_id}"
            self._next_id += 1
            
            # Store in memory
            if collection_name not in self._data:
                self._data[collection_name] = []
            self._data[collection_name].append(data_copy)
            
            return data_copy
        
        async def find_one(self, collection_name, filter_dict):
            if collection_name not in self._data:
                return None
            
            for item in self._data[collection_name]:
                # Simple filter matching
                match = True
                for key, value in filter_dict.items():
                    if key not in item or item[key] != value:
                        match = False
                        break
                if match:
                    return item
            return None
        
        async def find_many(self, collection_name, filter_dict=None, sort=None, skip=0, limit=None, projection=None):
            if collection_name not in self._data:
                return []
            
            results = []
            for item in self._data[collection_name]:
                # Simple filter matching
                if filter_dict:
                    match = True
                    for key, value in filter_dict.items():
                        if key not in item or item[key] != value:
                            match = False
                            break
                    if not match:
                        continue
                results.append(item)
            
            # Apply skip and limit
            if skip:
                results = results[skip:]
            if limit:
                results = results[:limit]
            
            return results
        
        async def count(self, collection_name, filter_dict=None):
            if collection_name not in self._data:
                return 0
            
            count = 0
            for item in self._data[collection_name]:
                # Simple filter matching
                if filter_dict:
                    match = True
                    for key, value in filter_dict.items():
                        if key not in item or item[key] != value:
                            match = False
                            break
                    if not match:
                        continue
                count += 1
            
            return count
        
        async def update_one(self, collection_name, filter_dict, update_data, transaction_id=None):
            class MockResult:
                modified_count = 0
            
            if collection_name not in self._data:
                return MockResult()
            
            for item in self._data[collection_name]:
                # Simple filter matching
                match = True
                for key, value in filter_dict.items():
                    if key not in item or item[key] != value:
                        match = False
                        break
                if match:
                    # Apply update
                    if "$set" in update_data:
                        item.update(update_data["$set"])
                    else:
                        item.update(update_data)
                    MockResult.modified_count = 1
                    break
            
            return MockResult()
        
        async def update_many(self, collection_name, filter_dict, update_data, transaction_id=None):
            class MockResult:
                modified_count = 0
            
            if collection_name not in self._data:
                return MockResult()
            
            for item in self._data[collection_name]:
                # Simple filter matching
                match = True
                for key, value in filter_dict.items():
                    if key not in item or item[key] != value:
                        match = False
                        break
                if match:
                    # Apply update
                    if "$set" in update_data:
                        item.update(update_data["$set"])
                    else:
                        item.update(update_data)
                    MockResult.modified_count += 1
            
            return MockResult()
        
        async def delete_one(self, collection_name, filter_dict, transaction_id=None):
            class MockResult:
                deleted_count = 0
            
            if collection_name not in self._data:
                return MockResult()
            
            for i, item in enumerate(self._data[collection_name]):
                # Simple filter matching
                match = True
                for key, value in filter_dict.items():
                    if key not in item or item[key] != value:
                        match = False
                        break
                if match:
                    del self._data[collection_name][i]
                    MockResult.deleted_count = 1
                    break
            
            return MockResult()
        
        async def delete_many(self, collection_name, filter_dict, transaction_id=None):
            class MockResult:
                deleted_count = 0
            
            if collection_name not in self._data:
                return MockResult()
            
            # Remove matching items
            original_length = len(self._data[collection_name])
            self._data[collection_name] = [
                item for item in self._data[collection_name]
                if not all(key in item and item[key] == value for key, value in filter_dict.items())
            ]
            MockResult.deleted_count = original_length - len(self._data[collection_name])
            
            return MockResult()
    
    class TransactionManager:
        def __init__(self):
            pass
        async def initialize(self):
            pass
        async def begin(self, tx_id):
            pass
        async def commit(self, tx_id):
            pass
        async def rollback(self, tx_id):
            pass
    
    def get_db_connection(name):
        return Database()

try:
    from models import BaseModel
except ImportError:
    # Mock BaseModel if not available
    class BaseModel:
        __tablename__ = "mock_table"
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)


class QueryOperator(Enum):
    """查询操作符枚举"""
    EQ = "eq"          # 等于
    NE = "ne"          # 不等于
    GT = "gt"          # 大于
    GTE = "gte"        # 大于等于
    LT = "lt"          # 小于
    LTE = "lte"        # 小于等于
    IN = "in"          # 在列表中
    NOT_IN = "not_in"  # 不在列表中
    LIKE = "like"      # 模糊匹配
    REGEX = "regex"    # 正则匹配
    EXISTS = "exists"  # 字段存在
    SIZE = "size"      # 数组大小


class SortOrder(Enum):
    """排序方向枚举"""
    ASC = 1
    DESC = -1


@dataclass
class QueryCondition:
    """查询条件"""
    field: str
    operator: QueryOperator
    value: Any
    
    def to_dict(self) -> dict:
        """转换为字典格式"""
        if self.operator == QueryOperator.EQ:
            return {self.field: self.value}
        elif self.operator == QueryOperator.NE:
            return {self.field: {"$ne": self.value}}
        elif self.operator == QueryOperator.GT:
            return {self.field: {"$gt": self.value}}
        elif self.operator == QueryOperator.GTE:
            return {self.field: {"$gte": self.value}}
        elif self.operator == QueryOperator.LT:
            return {self.field: {"$lt": self.value}}
        elif self.operator == QueryOperator.LTE:
            return {self.field: {"$lte": self.value}}
        elif self.operator == QueryOperator.IN:
            return {self.field: {"$in": self.value}}
        elif self.operator == QueryOperator.NOT_IN:
            return {self.field: {"$nin": self.value}}
        elif self.operator == QueryOperator.LIKE:
            return {self.field: {"$regex": self.value, "$options": "i"}}
        elif self.operator == QueryOperator.REGEX:
            return {self.field: {"$regex": self.value}}
        elif self.operator == QueryOperator.EXISTS:
            return {self.field: {"$exists": self.value}}
        elif self.operator == QueryOperator.SIZE:
            return {self.field: {"$size": self.value}}
        else:
            return {self.field: self.value}


@dataclass
class SortCondition:
    """排序条件"""
    field: str
    order: SortOrder = SortOrder.ASC
    
    def to_tuple(self) -> tuple:
        """转换为元组格式"""
        return (self.field, self.order.value)


@dataclass
class PaginationOptions:
    """分页选项"""
    page: int = 1
    page_size: int = 20
    skip: Optional[int] = None
    limit: Optional[int] = None
    
    def __post_init__(self):
        """计算skip和limit"""
        if self.skip is None:
            self.skip = (self.page - 1) * self.page_size
        
        if self.limit is None:
            self.limit = self.page_size


@dataclass
class CacheConfig:
    """缓存配置"""
    enable: bool = True
    ttl: int = 300  # 5分钟
    max_size: int = 1000
    key_prefix: str = "repo"


@dataclass
class RepositoryConfig:
    """Repository配置"""
    # 缓存配置
    cache: CacheConfig = field(default_factory=CacheConfig)
    
    # 事务配置
    enable_transactions: bool = True
    transaction_timeout: float = 30.0
    
    # 验证配置
    enable_validation: bool = True
    
    # 批量操作配置
    batch_size: int = 1000
    
    # 查询配置
    default_page_size: int = 20
    max_page_size: int = 1000
    
    # 其他配置
    metadata: Dict[str, Any] = field(default_factory=dict)


class QueryBuilder:
    """查询构建器"""
    
    def __init__(self):
        self._conditions: List[QueryCondition] = []
        self._sort_conditions: List[SortCondition] = []
        self._pagination: Optional[PaginationOptions] = None
        self._projection: Optional[dict] = None
        self._or_conditions: List[List[QueryCondition]] = []
    
    def where(self, field: str, operator: QueryOperator = QueryOperator.EQ, value: Any = None) -> 'QueryBuilder':
        """添加查询条件"""
        if value is None and operator == QueryOperator.EQ:
            # 简化语法：where("field", value)
            value = operator
            operator = QueryOperator.EQ
        
        condition = QueryCondition(field, operator, value)
        self._conditions.append(condition)
        return self
    
    def eq(self, field: str, value: Any) -> 'QueryBuilder':
        """等于条件"""
        return self.where(field, QueryOperator.EQ, value)
    
    def ne(self, field: str, value: Any) -> 'QueryBuilder':
        """不等于条件"""
        return self.where(field, QueryOperator.NE, value)
    
    def gt(self, field: str, value: Any) -> 'QueryBuilder':
        """大于条件"""
        return self.where(field, QueryOperator.GT, value)
    
    def gte(self, field: str, value: Any) -> 'QueryBuilder':
        """大于等于条件"""
        return self.where(field, QueryOperator.GTE, value)
    
    def lt(self, field: str, value: Any) -> 'QueryBuilder':
        """小于条件"""
        return self.where(field, QueryOperator.LT, value)
    
    def lte(self, field: str, value: Any) -> 'QueryBuilder':
        """小于等于条件"""
        return self.where(field, QueryOperator.LTE, value)
    
    def in_(self, field: str, values: List[Any]) -> 'QueryBuilder':
        """在列表中条件"""
        return self.where(field, QueryOperator.IN, values)
    
    def not_in(self, field: str, values: List[Any]) -> 'QueryBuilder':
        """不在列表中条件"""
        return self.where(field, QueryOperator.NOT_IN, values)
    
    def like(self, field: str, pattern: str) -> 'QueryBuilder':
        """模糊匹配条件"""
        return self.where(field, QueryOperator.LIKE, pattern)
    
    def regex(self, field: str, pattern: str) -> 'QueryBuilder':
        """正则匹配条件"""
        return self.where(field, QueryOperator.REGEX, pattern)
    
    def exists(self, field: str, exists: bool = True) -> 'QueryBuilder':
        """字段存在条件"""
        return self.where(field, QueryOperator.EXISTS, exists)
    
    def size(self, field: str, size: int) -> 'QueryBuilder':
        """数组大小条件"""
        return self.where(field, QueryOperator.SIZE, size)
    
    def or_(self, *conditions: List[QueryCondition]) -> 'QueryBuilder':
        """OR条件"""
        self._or_conditions.append(list(conditions))
        return self
    
    def order_by(self, field: str, order: SortOrder = SortOrder.ASC) -> 'QueryBuilder':
        """排序条件"""
        condition = SortCondition(field, order)
        self._sort_conditions.append(condition)
        return self
    
    def order_by_asc(self, field: str) -> 'QueryBuilder':
        """升序排序"""
        return self.order_by(field, SortOrder.ASC)
    
    def order_by_desc(self, field: str) -> 'QueryBuilder':
        """降序排序"""
        return self.order_by(field, SortOrder.DESC)
    
    def paginate(self, page: int, page_size: int) -> 'QueryBuilder':
        """分页"""
        self._pagination = PaginationOptions(page, page_size)
        return self
    
    def skip(self, skip: int) -> 'QueryBuilder':
        """跳过"""
        if self._pagination is None:
            self._pagination = PaginationOptions()
        self._pagination.skip = skip
        return self
    
    def limit(self, limit: int) -> 'QueryBuilder':
        """限制"""
        if self._pagination is None:
            self._pagination = PaginationOptions()
        self._pagination.limit = limit
        return self
    
    def select(self, *fields: str) -> 'QueryBuilder':
        """选择字段"""
        self._projection = {field: 1 for field in fields}
        return self
    
    def exclude(self, *fields: str) -> 'QueryBuilder':
        """排除字段"""
        self._projection = {field: 0 for field in fields}
        return self
    
    def build_filter(self) -> dict:
        """构建过滤条件"""
        filter_dict = {}
        
        # 添加普通条件
        for condition in self._conditions:
            condition_dict = condition.to_dict()
            for key, value in condition_dict.items():
                if key in filter_dict:
                    # 合并条件
                    if isinstance(filter_dict[key], dict) and isinstance(value, dict):
                        filter_dict[key].update(value)
                    else:
                        filter_dict[key] = value
                else:
                    filter_dict[key] = value
        
        # 添加OR条件
        if self._or_conditions:
            or_list = []
            for or_group in self._or_conditions:
                or_dict = {}
                for condition in or_group:
                    condition_dict = condition.to_dict()
                    or_dict.update(condition_dict)
                or_list.append(or_dict)
            
            if or_list:
                if "$or" in filter_dict:
                    filter_dict["$or"].extend(or_list)
                else:
                    filter_dict["$or"] = or_list
        
        return filter_dict
    
    def build_sort(self) -> List[tuple]:
        """构建排序条件"""
        return [condition.to_tuple() for condition in self._sort_conditions]
    
    def build_pagination(self) -> Optional[PaginationOptions]:
        """构建分页选项"""
        return self._pagination
    
    def build_projection(self) -> Optional[dict]:
        """构建投影选项"""
        return self._projection


class BaseRepository:
    """
    基础数据访问类
    
    提供数据访问的基础功能：
    - 标准CRUD操作
    - 查询构建
    - 缓存策略
    - 数据验证
    - 事务支持
    - 批量操作
    - 异步访问
    """
    
    def __init__(self, 
                 model_class: Type[BaseModel] = None,
                 table_name: str = None,
                 database_name: str = "default",
                 config: Optional[RepositoryConfig] = None):
        """
        初始化基础Repository
        
        Args:
            model_class: 模型类
            table_name: 表名
            database_name: 数据库名
            config: Repository配置
        """
        self.config = config or RepositoryConfig()
        self.logger = logger
        
        # 基本信息
        self.model_class = model_class
        self.table_name = table_name or (model_class.__tablename__ if model_class else "")
        self.database_name = database_name
        self.repository_name = self.__class__.__name__
        
        # 数据库连接
        self._database: Optional[Database] = None
        self._transaction_manager = TransactionManager() if self.config.enable_transactions else None
        
        # 缓存
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, float] = {}
        
        # 验证器
        self._validators: Dict[str, Callable] = {}
        
        # 中间件
        self._before_create_middlewares: List[Callable] = []
        self._after_create_middlewares: List[Callable] = []
        self._before_update_middlewares: List[Callable] = []
        self._after_update_middlewares: List[Callable] = []
        self._before_delete_middlewares: List[Callable] = []
        self._after_delete_middlewares: List[Callable] = []
        
        self.logger.info("基础Repository初始化完成", 
                        repository_name=self.repository_name,
                        table_name=self.table_name)
    
    async def initialize(self):
        """初始化Repository"""
        try:
            # 获取数据库连接
            self._database = get_db_connection(self.database_name)
            # 如果获取到None，使用mock数据库
            if self._database is None:
                from common.db import Database
                self._database = Database()
            
            # 初始化事务管理器
            if self._transaction_manager:
                await self._transaction_manager.initialize()
            
            # 注册默认验证器
            self._register_default_validators()
            
            self.logger.info("Repository初始化完成", 
                           repository_name=self.repository_name)
            
        except Exception as e:
            self.logger.error("Repository初始化失败", 
                            repository_name=self.repository_name,
                            error=str(e))
            raise
    
    async def cleanup(self):
        """清理Repository资源"""
        try:
            # 清理缓存
            self._cache.clear()
            self._cache_timestamps.clear()
            
            # 关闭数据库连接
            if self._database:
                await self._database.close()
            
            self.logger.info("Repository清理完成", 
                           repository_name=self.repository_name)
            
        except Exception as e:
            self.logger.error("Repository清理失败", 
                            repository_name=self.repository_name,
                            error=str(e))
    
    def query(self) -> QueryBuilder:
        """创建查询构建器"""
        return QueryBuilder()
    
    async def create(self, data: dict, tx: str = None) -> dict:
        """
        创建记录
        
        Args:
            data: 数据
            tx: 事务ID
            
        Returns:
            dict: 创建的记录
        """
        try:
            # 执行前置中间件
            for middleware in self._before_create_middlewares:
                data = await middleware(data)
            
            # 数据验证
            if self.config.enable_validation:
                await self._validate_data(data, "create")
            
            # 添加时间戳
            now = datetime.now()
            data.setdefault("created_at", now)
            data.setdefault("updated_at", now)
            
            # 创建记录
            result = await self._database.insert_one(self.table_name, data, transaction_id=tx)
            
            # 清理相关缓存
            self._clear_related_cache()
            
            # 执行后置中间件
            for middleware in self._after_create_middlewares:
                result = await middleware(result)
            
            self.logger.debug("记录创建成功", 
                            repository_name=self.repository_name,
                            record_id=result.get("_id"))
            
            return result
            
        except Exception as e:
            self.logger.error("记录创建失败", 
                            repository_name=self.repository_name,
                            error=str(e))
            raise
    
    async def find_by_id(self, record_id: str, use_cache: bool = True) -> Optional[dict]:
        """
        根据ID查找记录
        
        Args:
            record_id: 记录ID
            use_cache: 是否使用缓存
            
        Returns:
            Optional[dict]: 记录数据
        """
        try:
            # 尝试从缓存获取
            if use_cache and self.config.cache.enable:
                cache_key = self._build_cache_key("id", record_id)
                cached_result = self._get_cache(cache_key)
                if cached_result is not None:
                    return cached_result
            
            # 从数据库查询
            result = await self._database.find_one(self.table_name, {"_id": record_id})
            
            # 缓存结果
            if use_cache and self.config.cache.enable and result:
                cache_key = self._build_cache_key("id", record_id)
                self._set_cache(cache_key, result)
            
            return result
            
        except Exception as e:
            self.logger.error("根据ID查找记录失败", 
                            repository_name=self.repository_name,
                            record_id=record_id,
                            error=str(e))
            raise
    
    async def find_one(self, filter_dict: dict, use_cache: bool = False) -> Optional[dict]:
        """
        查找单条记录
        
        Args:
            filter_dict: 查询条件
            use_cache: 是否使用缓存
            
        Returns:
            Optional[dict]: 记录数据
        """
        try:
            # 尝试从缓存获取
            if use_cache and self.config.cache.enable:
                cache_key = self._build_cache_key("one", json.dumps(filter_dict, sort_keys=True))
                cached_result = self._get_cache(cache_key)
                if cached_result is not None:
                    return cached_result
            
            # 从数据库查询
            result = await self._database.find_one(self.table_name, filter_dict)
            
            # 缓存结果
            if use_cache and self.config.cache.enable and result:
                cache_key = self._build_cache_key("one", json.dumps(filter_dict, sort_keys=True))
                self._set_cache(cache_key, result)
            
            return result
            
        except Exception as e:
            self.logger.error("查找单条记录失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            error=str(e))
            raise
    
    async def find_many(self, 
                       filter_dict: dict = None,
                       sort: List[tuple] = None,
                       skip: int = 0,
                       limit: int = None,
                       projection: dict = None,
                       use_cache: bool = False) -> List[dict]:
        """
        查找多条记录
        
        Args:
            filter_dict: 查询条件
            sort: 排序条件
            skip: 跳过数量
            limit: 限制数量
            projection: 投影字段
            use_cache: 是否使用缓存
            
        Returns:
            List[dict]: 记录列表
        """
        try:
            filter_dict = filter_dict or {}
            
            # 尝试从缓存获取
            if use_cache and self.config.cache.enable:
                cache_key = self._build_cache_key("many", json.dumps({
                    "filter": filter_dict,
                    "sort": sort,
                    "skip": skip,
                    "limit": limit,
                    "projection": projection
                }, sort_keys=True))
                cached_result = self._get_cache(cache_key)
                if cached_result is not None:
                    return cached_result
            
            # 从数据库查询
            result = await self._database.find_many(
                collection_name=self.table_name,
                filter_dict=filter_dict,
                sort=sort,
                skip=skip,
                limit=limit,
                projection=projection
            )
            
            # 缓存结果
            if use_cache and self.config.cache.enable:
                cache_key = self._build_cache_key("many", json.dumps({
                    "filter": filter_dict,
                    "sort": sort,
                    "skip": skip,
                    "limit": limit,
                    "projection": projection
                }, sort_keys=True))
                self._set_cache(cache_key, result)
            
            return result
            
        except Exception as e:
            self.logger.error("查找多条记录失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            error=str(e))
            raise
    
    async def find_with_builder(self, builder: QueryBuilder, use_cache: bool = False) -> List[dict]:
        """
        使用查询构建器查找记录
        
        Args:
            builder: 查询构建器
            use_cache: 是否使用缓存
            
        Returns:
            List[dict]: 记录列表
        """
        filter_dict = builder.build_filter()
        sort = builder.build_sort()
        pagination = builder.build_pagination()
        projection = builder.build_projection()
        
        skip = pagination.skip if pagination else 0
        limit = pagination.limit if pagination else None
        
        return await self.find_many(
            filter_dict=filter_dict,
            sort=sort,
            skip=skip,
            limit=limit,
            projection=projection,
            use_cache=use_cache
        )
    
    async def count(self, filter_dict: dict = None) -> int:
        """
        统计记录数量
        
        Args:
            filter_dict: 查询条件
            
        Returns:
            int: 记录数量
        """
        try:
            filter_dict = filter_dict or {}
            return await self._database.count(self.table_name, filter_dict)
            
        except Exception as e:
            self.logger.error("统计记录数量失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            error=str(e))
            raise
    
    async def update_by_id(self, record_id: str, update_data: dict, tx: str = None) -> bool:
        """
        根据ID更新记录
        
        Args:
            record_id: 记录ID
            update_data: 更新数据
            tx: 事务ID
            
        Returns:
            bool: 是否更新成功
        """
        try:
            # 执行前置中间件
            for middleware in self._before_update_middlewares:
                update_data = await middleware(update_data)
            
            # 数据验证
            if self.config.enable_validation:
                await self._validate_data(update_data, "update")
            
            # 添加更新时间戳
            update_data["updated_at"] = datetime.now()
            
            # 更新记录
            result = await self._database.update_one(
                collection_name=self.table_name,
                filter_dict={"_id": record_id},
                update_data={"$set": update_data},
                transaction_id=tx
            )
            
            success = result.modified_count > 0
            
            if success:
                # 清理相关缓存
                self._clear_related_cache()
                
                # 执行后置中间件
                for middleware in self._after_update_middlewares:
                    await middleware(record_id, update_data)
            
            self.logger.debug("记录更新完成", 
                            repository_name=self.repository_name,
                            record_id=record_id,
                            success=success)
            
            return success
            
        except Exception as e:
            self.logger.error("根据ID更新记录失败", 
                            repository_name=self.repository_name,
                            record_id=record_id,
                            error=str(e))
            raise
    
    async def update_many(self, filter_dict: dict, update_data: dict, tx: str = None) -> int:
        """
        批量更新记录
        
        Args:
            filter_dict: 查询条件
            update_data: 更新数据
            tx: 事务ID
            
        Returns:
            int: 更新的记录数量
        """
        try:
            # 执行前置中间件
            for middleware in self._before_update_middlewares:
                update_data = await middleware(update_data)
            
            # 数据验证
            if self.config.enable_validation:
                await self._validate_data(update_data, "update")
            
            # 添加更新时间戳
            update_data["updated_at"] = datetime.now()
            
            # 批量更新
            result = await self._database.update_many(
                collection_name=self.table_name,
                filter_dict=filter_dict,
                update_data={"$set": update_data},
                transaction_id=tx
            )
            
            modified_count = result.modified_count
            
            if modified_count > 0:
                # 清理相关缓存
                self._clear_related_cache()
            
            self.logger.debug("批量更新记录完成", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            modified_count=modified_count)
            
            return modified_count
            
        except Exception as e:
            self.logger.error("批量更新记录失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            error=str(e))
            raise
    
    async def delete_by_id(self, record_id: str, tx: str = None) -> bool:
        """
        根据ID删除记录
        
        Args:
            record_id: 记录ID
            tx: 事务ID
            
        Returns:
            bool: 是否删除成功
        """
        try:
            # 执行前置中间件
            for middleware in self._before_delete_middlewares:
                await middleware(record_id)
            
            # 删除记录
            result = await self._database.delete_one(
                collection_name=self.table_name,
                filter_dict={"_id": record_id},
                transaction_id=tx
            )
            
            success = result.deleted_count > 0
            
            if success:
                # 清理相关缓存
                self._clear_related_cache()
                
                # 执行后置中间件
                for middleware in self._after_delete_middlewares:
                    await middleware(record_id)
            
            self.logger.debug("记录删除完成", 
                            repository_name=self.repository_name,
                            record_id=record_id,
                            success=success)
            
            return success
            
        except Exception as e:
            self.logger.error("根据ID删除记录失败", 
                            repository_name=self.repository_name,
                            record_id=record_id,
                            error=str(e))
            raise
    
    async def delete_many(self, filter_dict: dict, tx: str = None) -> int:
        """
        批量删除记录
        
        Args:
            filter_dict: 查询条件
            tx: 事务ID
            
        Returns:
            int: 删除的记录数量
        """
        try:
            # 执行前置中间件
            for middleware in self._before_delete_middlewares:
                await middleware(filter_dict)
            
            # 批量删除
            result = await self._database.delete_many(
                collection_name=self.table_name,
                filter_dict=filter_dict,
                transaction_id=tx
            )
            
            deleted_count = result.deleted_count
            
            if deleted_count > 0:
                # 清理相关缓存
                self._clear_related_cache()
            
            self.logger.debug("批量删除记录完成", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            deleted_count=deleted_count)
            
            return deleted_count
            
        except Exception as e:
            self.logger.error("批量删除记录失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            error=str(e))
            raise
    
    async def exists(self, filter_dict: dict) -> bool:
        """
        检查记录是否存在
        
        Args:
            filter_dict: 查询条件
            
        Returns:
            bool: 是否存在
        """
        try:
            count = await self.count(filter_dict)
            return count > 0
            
        except Exception as e:
            self.logger.error("检查记录是否存在失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            error=str(e))
            raise
    
    async def paginate(self, 
                      filter_dict: dict = None,
                      page: int = 1,
                      page_size: int = None,
                      sort: List[tuple] = None,
                      projection: dict = None) -> dict:
        """
        分页查询
        
        Args:
            filter_dict: 查询条件
            page: 页码
            page_size: 页面大小
            sort: 排序条件
            projection: 投影字段
            
        Returns:
            dict: 分页结果
        """
        try:
            filter_dict = filter_dict or {}
            page_size = page_size or self.config.default_page_size
            page_size = min(page_size, self.config.max_page_size)
            
            # 计算跳过数量
            skip = (page - 1) * page_size
            
            # 并行执行计数和查询
            total_task = self.count(filter_dict)
            records_task = self.find_many(
                filter_dict=filter_dict,
                sort=sort,
                skip=skip,
                limit=page_size,
                projection=projection
            )
            
            total, records = await asyncio.gather(total_task, records_task)
            
            # 计算总页数
            total_pages = (total + page_size - 1) // page_size
            
            return {
                "records": records,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": total_pages,
                    "has_prev": page > 1,
                    "has_next": page < total_pages
                }
            }
            
        except Exception as e:
            self.logger.error("分页查询失败", 
                            repository_name=self.repository_name,
                            filter_dict=filter_dict,
                            page=page,
                            page_size=page_size,
                            error=str(e))
            raise
    
    @asynccontextmanager
    async def transaction(self, transaction_id: str = None):
        """
        事务上下文管理器
        
        Args:
            transaction_id: 事务ID
        """
        if not self.config.enable_transactions or not self._transaction_manager:
            yield None
            return
        
        if transaction_id is None:
            transaction_id = f"repo_tx_{int(time.time() * 1000000)}"
        
        try:
            # 开始事务
            await self._transaction_manager.begin(transaction_id)
            
            yield transaction_id
            
            # 提交事务
            await self._transaction_manager.commit(transaction_id)
            
        except Exception as e:
            # 回滚事务
            await self._transaction_manager.rollback(transaction_id)
            raise
    
    def _build_cache_key(self, operation: str, identifier: str) -> str:
        """构建缓存键"""
        return f"{self.config.cache.key_prefix}:{self.repository_name}:{operation}:{identifier}"
    
    def _get_cache(self, key: str) -> Any:
        """获取缓存"""
        if key not in self._cache:
            return None
        
        # 检查缓存是否过期
        if time.time() - self._cache_timestamps[key] > self.config.cache.ttl:
            del self._cache[key]
            del self._cache_timestamps[key]
            return None
        
        return self._cache[key]
    
    def _set_cache(self, key: str, value: Any):
        """设置缓存"""
        # 检查缓存大小限制
        if len(self._cache) >= self.config.cache.max_size:
            # 清理最老的缓存项
            oldest_key = min(self._cache_timestamps, key=self._cache_timestamps.get)
            del self._cache[oldest_key]
            del self._cache_timestamps[oldest_key]
        
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()
    
    def _clear_related_cache(self):
        """清理相关缓存"""
        # 清理所有与此Repository相关的缓存
        keys_to_remove = []
        for key in self._cache.keys():
            if self.repository_name in key:
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self._cache[key]
            del self._cache_timestamps[key]
    
    async def _validate_data(self, data: dict, operation: str):
        """验证数据"""
        # 基本验证
        if not data:
            raise ValueError("数据不能为空")
        
        # 调用注册的验证器
        for field, validator in self._validators.items():
            if field in data:
                if not validator(data[field]):
                    raise ValueError(f"字段 {field} 验证失败")
        
        # 模型验证
        if self.model_class:
            try:
                # 使用模型类进行验证
                if operation == "create":
                    self.model_class(**data)
                elif operation == "update":
                    # 更新操作只验证提供的字段
                    instance = self.model_class()
                    for key, value in data.items():
                        if hasattr(instance, key):
                            setattr(instance, key, value)
            except Exception as e:
                raise ValueError(f"模型验证失败: {str(e)}")
    
    def _register_default_validators(self):
        """注册默认验证器"""
        # 邮箱验证器
        def email_validator(value: str) -> bool:
            import re
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            return re.match(pattern, value) is not None
        
        # 手机号验证器
        def phone_validator(value: str) -> bool:
            import re
            pattern = r'^1[3-9]\d{9}$'
            return re.match(pattern, value) is not None
        
        self._validators.update({
            'email': email_validator,
            'phone': phone_validator
        })
    
    def add_validator(self, field: str, validator: Callable):
        """添加验证器"""
        self._validators[field] = validator
    
    def add_before_create_middleware(self, middleware: Callable):
        """添加创建前中间件"""
        self._before_create_middlewares.append(middleware)
    
    def add_after_create_middleware(self, middleware: Callable):
        """添加创建后中间件"""
        self._after_create_middlewares.append(middleware)
    
    def add_before_update_middleware(self, middleware: Callable):
        """添加更新前中间件"""
        self._before_update_middlewares.append(middleware)
    
    def add_after_update_middleware(self, middleware: Callable):
        """添加更新后中间件"""
        self._after_update_middlewares.append(middleware)
    
    def add_before_delete_middleware(self, middleware: Callable):
        """添加删除前中间件"""
        self._before_delete_middlewares.append(middleware)
    
    def add_after_delete_middleware(self, middleware: Callable):
        """添加删除后中间件"""
        self._after_delete_middlewares.append(middleware)
    
    def clear_cache(self, pattern: str = None):
        """清除缓存"""
        if pattern:
            keys_to_remove = []
            for key in self._cache.keys():
                if pattern in key:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._cache[key]
                del self._cache_timestamps[key]
        else:
            self._cache.clear()
            self._cache_timestamps.clear()
    
    @property
    def cache_size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)
    
    @property
    def database(self) -> Database:
        """获取数据库实例"""
        return self._database