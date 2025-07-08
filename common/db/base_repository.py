"""
基础仓库类

该模块提供数据访问层的基础仓库类，包含以下功能：
- 缓存集成（Cache-Aside模式）
- 自动缓存读取和更新
- 缓存失效策略
- 缓存预热
- 分页查询
- 排序支持
- 字段投影
- 事务处理
- 批量操作优化
"""

import asyncio
import hashlib
import json
from typing import Any, Dict, List, Optional, Type, TypeVar, Union, Callable, Tuple
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from common.logger import logger
from .redis_manager import redis_manager, DistributedLock
from .mongo_manager import mongo_manager, MongoTransaction
from .base_document import BaseDocument, ValidationError, DocumentError


T = TypeVar('T', bound=BaseDocument)


class RepositoryError(Exception):
    """仓库相关异常"""
    pass


class CacheError(RepositoryError):
    """缓存相关异常"""
    pass


class QueryError(RepositoryError):
    """查询相关异常"""
    pass


class PageInfo:
    """分页信息"""
    
    def __init__(self, page: int = 1, page_size: int = 20, total: int = 0):
        self.page = max(1, page)
        self.page_size = max(1, min(page_size, 1000))  # 限制最大页面大小
        self.total = max(0, total)
        self.total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        self.has_prev = page > 1
        self.has_next = page < self.total_pages
        self.start_index = (page - 1) * page_size
        self.end_index = min(page * page_size, total)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'page': self.page,
            'page_size': self.page_size,
            'total': self.total,
            'total_pages': self.total_pages,
            'has_prev': self.has_prev,
            'has_next': self.has_next,
            'start_index': self.start_index,
            'end_index': self.end_index
        }


class QueryResult:
    """查询结果"""
    
    def __init__(self, documents: List[T], page_info: Optional[PageInfo] = None):
        self.documents = documents
        self.page_info = page_info
        self.count = len(documents)
    
    def to_dict(self, include_documents: bool = True) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            'count': self.count,
            'page_info': self.page_info.to_dict() if self.page_info else None
        }
        
        if include_documents:
            result['documents'] = [doc.to_dict() for doc in self.documents]
        
        return result


class BaseRepository:
    """
    基础仓库类
    
    提供数据访问层的基础功能，集成Redis缓存和MongoDB持久化。
    """
    
    def __init__(self, document_class: Type[T]):
        """
        初始化仓库
        
        Args:
            document_class: 文档类
        """
        if not issubclass(document_class, BaseDocument):
            raise ValueError("document_class必须继承自BaseDocument")
        
        self.document_class = document_class
        self.collection_name = document_class.get_collection_name()
        
        # 缓存配置
        self.cache_ttl = 3600  # 默认缓存1小时
        self.cache_key_prefix = f"doc:{self.collection_name}"
        self.list_cache_ttl = 300  # 列表缓存5分钟
        
        # 批量操作配置
        self.batch_size = 100
        
        logger.info(f"仓库初始化: {self.document_class.__name__} -> {self.collection_name}")
    
    def _get_cache_key(self, doc_id: str) -> str:
        """生成缓存键名"""
        return f"{self.cache_key_prefix}:{doc_id}"
    
    def _get_list_cache_key(self, query_hash: str) -> str:
        """生成列表查询缓存键名"""
        return f"{self.cache_key_prefix}:list:{query_hash}"
    
    def _get_query_hash(self, filter_dict: Dict = None, projection: Dict = None,
                       sort: List[Tuple[str, int]] = None, limit: int = None,
                       skip: int = None) -> str:
        """生成查询参数的哈希值"""
        query_params = {
            'filter': filter_dict or {},
            'projection': projection or {},
            'sort': sort or [],
            'limit': limit,
            'skip': skip
        }
        
        query_str = json.dumps(query_params, sort_keys=True, default=str)
        return hashlib.md5(query_str.encode()).hexdigest()
    
    async def find_by_id(self, doc_id: str, use_cache: bool = True, 
                        projection: Dict = None) -> Optional[T]:
        """
        通过ID查找文档
        
        Args:
            doc_id: 文档ID
            use_cache: 是否使用缓存
            projection: 投影字段
            
        Returns:
            文档实例或None
        """
        if not doc_id:
            return None
        
        cache_key = self._get_cache_key(doc_id)
        
        # 尝试从缓存获取
        if use_cache:
            try:
                cached_data = await redis_manager.get(cache_key)
                if cached_data:
                    logger.debug(f"缓存命中: {cache_key}")
                    return self.document_class.from_dict(cached_data)
            except Exception as e:
                logger.warning(f"缓存读取失败 {cache_key}: {e}")
        
        # 从数据库查询
        try:
            filter_dict = {'_id': doc_id, 'is_deleted': False}
            doc_data = await mongo_manager.find_one(
                self.collection_name, filter_dict, projection
            )
            
            if doc_data:
                document = self.document_class.from_dict(doc_data)
                
                # 更新缓存
                if use_cache:
                    try:
                        await redis_manager.set(cache_key, doc_data, self.cache_ttl)
                        logger.debug(f"缓存更新: {cache_key}")
                    except Exception as e:
                        logger.warning(f"缓存更新失败 {cache_key}: {e}")
                
                return document
            
            return None
            
        except Exception as e:
            logger.error(f"查询文档失败 {doc_id}: {e}")
            raise QueryError(f"查询失败: {e}")
    
    async def find_many(self, filter_dict: Dict = None, projection: Dict = None,
                       sort: List[Tuple[str, int]] = None, limit: int = None,
                       skip: int = None, use_cache: bool = True) -> List[T]:
        """
        查找多个文档
        
        Args:
            filter_dict: 查询条件
            projection: 投影字段
            sort: 排序条件
            limit: 限制数量
            skip: 跳过数量
            use_cache: 是否使用缓存
            
        Returns:
            文档列表
        """
        # 添加软删除过滤
        if filter_dict is None:
            filter_dict = {}
        if 'is_deleted' not in filter_dict:
            filter_dict['is_deleted'] = False
        
        # 生成缓存键
        query_hash = self._get_query_hash(filter_dict, projection, sort, limit, skip)
        cache_key = self._get_list_cache_key(query_hash)
        
        # 尝试从缓存获取
        if use_cache:
            try:
                cached_data = await redis_manager.get(cache_key)
                if cached_data:
                    logger.debug(f"列表缓存命中: {cache_key}")
                    return [self.document_class.from_dict(doc_data) for doc_data in cached_data]
            except Exception as e:
                logger.warning(f"列表缓存读取失败 {cache_key}: {e}")
        
        # 从数据库查询
        try:
            docs_data = await mongo_manager.find_many(
                self.collection_name, filter_dict, projection, limit, skip, sort
            )
            
            documents = [self.document_class.from_dict(doc_data) for doc_data in docs_data]
            
            # 更新缓存
            if use_cache and documents:
                try:
                    await redis_manager.set(cache_key, docs_data, self.list_cache_ttl)
                    logger.debug(f"列表缓存更新: {cache_key}")
                except Exception as e:
                    logger.warning(f"列表缓存更新失败 {cache_key}: {e}")
            
            return documents
            
        except Exception as e:
            logger.error(f"查询文档列表失败: {e}")
            raise QueryError(f"查询失败: {e}")
    
    async def find_with_pagination(self, filter_dict: Dict = None, projection: Dict = None,
                                 sort: List[Tuple[str, int]] = None, page: int = 1,
                                 page_size: int = 20, use_cache: bool = True) -> QueryResult:
        """
        分页查询文档
        
        Args:
            filter_dict: 查询条件
            projection: 投影字段
            sort: 排序条件
            page: 页码
            page_size: 页面大小
            use_cache: 是否使用缓存
            
        Returns:
            查询结果
        """
        # 参数验证
        page = max(1, page)
        page_size = max(1, min(page_size, 1000))
        
        # 添加软删除过滤
        if filter_dict is None:
            filter_dict = {}
        if 'is_deleted' not in filter_dict:
            filter_dict['is_deleted'] = False
        
        # 计算跳过数量
        skip = (page - 1) * page_size
        
        try:
            # 并发执行计数和查询
            count_task = asyncio.create_task(
                mongo_manager.count_documents(self.collection_name, filter_dict)
            )
            
            docs_task = asyncio.create_task(
                self.find_many(filter_dict, projection, sort, page_size, skip, use_cache)
            )
            
            total_count = await count_task
            documents = await docs_task
            
            # 创建分页信息
            page_info = PageInfo(page, page_size, total_count)
            
            return QueryResult(documents, page_info)
            
        except Exception as e:
            logger.error(f"分页查询失败: {e}")
            raise QueryError(f"分页查询失败: {e}")
    
    async def save(self, document: T, use_cache: bool = True) -> T:
        """
        保存文档（新增或更新）
        
        Args:
            document: 文档实例
            use_cache: 是否更新缓存
            
        Returns:
            保存后的文档实例
        """
        if not isinstance(document, self.document_class):
            raise ValueError(f"文档必须是{self.document_class.__name__}类型")
        
        # 验证文档
        document.validate()
        
        try:
            # 检查是否为新文档
            existing_doc = await self.find_by_id(document._id, use_cache=False)
            
            if existing_doc:
                # 更新现有文档
                return await self._update_document(document, existing_doc, use_cache)
            else:
                # 插入新文档
                return await self._insert_document(document, use_cache)
                
        except Exception as e:
            logger.error(f"保存文档失败 {document._id}: {e}")
            raise RepositoryError(f"保存失败: {e}")
    
    async def _insert_document(self, document: T, use_cache: bool) -> T:
        """插入新文档"""
        doc_data = document.to_dict()
        
        inserted_id = await mongo_manager.insert_one(self.collection_name, doc_data)
        if not inserted_id:
            raise RepositoryError("插入文档失败")
        
        # 确保ID一致
        document._id = inserted_id
        
        # 更新缓存
        if use_cache:
            cache_key = self._get_cache_key(document._id)
            try:
                await redis_manager.set(cache_key, doc_data, self.cache_ttl)
                # 清除相关的列表缓存
                await self._invalidate_list_cache()
            except Exception as e:
                logger.warning(f"缓存更新失败 {cache_key}: {e}")
        
        logger.info(f"插入文档成功: {document._id}")
        return document
    
    async def _update_document(self, document: T, existing_doc: T, use_cache: bool) -> T:
        """更新现有文档"""
        # 乐观锁检查
        if document.version != existing_doc.version:
            raise RepositoryError(f"版本冲突：期望版本{existing_doc.version}，实际版本{document.version}")
        
        # 增加版本号
        document.increment_version()
        
        # 构建更新操作
        update_data = {'$set': document.to_dict()}
        filter_dict = {'_id': document._id, 'version': existing_doc.version}
        
        success = await mongo_manager.update_one(self.collection_name, filter_dict, update_data)
        if not success:
            raise RepositoryError("更新文档失败，可能存在版本冲突")
        
        # 更新缓存
        if use_cache:
            cache_key = self._get_cache_key(document._id)
            try:
                await redis_manager.set(cache_key, document.to_dict(), self.cache_ttl)
                # 清除相关的列表缓存
                await self._invalidate_list_cache()
            except Exception as e:
                logger.warning(f"缓存更新失败 {cache_key}: {e}")
        
        logger.info(f"更新文档成功: {document._id} (version: {document.version})")
        return document
    
    async def delete(self, doc_id: str, soft: bool = True, use_cache: bool = True) -> bool:
        """
        删除文档
        
        Args:
            doc_id: 文档ID
            soft: 是否软删除
            use_cache: 是否更新缓存
            
        Returns:
            是否删除成功
        """
        if not doc_id:
            return False
        
        try:
            if soft:
                # 软删除
                update_data = {
                    '$set': {
                        'is_deleted': True,
                        'updated_at': datetime.utcnow()
                    },
                    '$inc': {'version': 1}
                }
                filter_dict = {'_id': doc_id, 'is_deleted': False}
                success = await mongo_manager.update_one(self.collection_name, filter_dict, update_data)
            else:
                # 硬删除
                filter_dict = {'_id': doc_id}
                success = await mongo_manager.delete_one(self.collection_name, filter_dict)
            
            if success:
                # 删除缓存
                if use_cache:
                    cache_key = self._get_cache_key(doc_id)
                    try:
                        await redis_manager.delete(cache_key)
                        # 清除相关的列表缓存
                        await self._invalidate_list_cache()
                    except Exception as e:
                        logger.warning(f"缓存删除失败 {cache_key}: {e}")
                
                delete_type = "软删除" if soft else "硬删除"
                logger.info(f"{delete_type}文档成功: {doc_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"删除文档失败 {doc_id}: {e}")
            raise RepositoryError(f"删除失败: {e}")
    
    async def delete_many(self, filter_dict: Dict, soft: bool = True) -> int:
        """
        批量删除文档
        
        Args:
            filter_dict: 查询条件
            soft: 是否软删除
            
        Returns:
            删除的文档数量
        """
        if not filter_dict:
            raise ValueError("批量删除必须提供查询条件")
        
        try:
            if soft:
                # 软删除
                update_data = {
                    '$set': {
                        'is_deleted': True,
                        'updated_at': datetime.utcnow()
                    },
                    '$inc': {'version': 1}
                }
                # 添加软删除过滤
                if 'is_deleted' not in filter_dict:
                    filter_dict['is_deleted'] = False
                
                count = await mongo_manager.update_many(self.collection_name, filter_dict, update_data)
            else:
                # 硬删除
                count = await mongo_manager.delete_many(self.collection_name, filter_dict)
            
            if count > 0:
                # 清除列表缓存
                await self._invalidate_list_cache()
                
                delete_type = "软删除" if soft else "硬删除"
                logger.info(f"批量{delete_type}文档成功: {count}个")
            
            return count
            
        except Exception as e:
            logger.error(f"批量删除文档失败: {e}")
            raise RepositoryError(f"批量删除失败: {e}")
    
    async def count(self, filter_dict: Dict = None, include_deleted: bool = False) -> int:
        """
        统计文档数量
        
        Args:
            filter_dict: 查询条件
            include_deleted: 是否包含已删除的文档
            
        Returns:
            文档数量
        """
        if filter_dict is None:
            filter_dict = {}
        
        # 添加软删除过滤
        if not include_deleted and 'is_deleted' not in filter_dict:
            filter_dict['is_deleted'] = False
        
        try:
            return await mongo_manager.count_documents(self.collection_name, filter_dict)
        except Exception as e:
            logger.error(f"统计文档数量失败: {e}")
            raise QueryError(f"统计失败: {e}")
    
    async def exists(self, doc_id: str, use_cache: bool = True) -> bool:
        """
        检查文档是否存在
        
        Args:
            doc_id: 文档ID
            use_cache: 是否使用缓存
            
        Returns:
            是否存在
        """
        if not doc_id:
            return False
        
        # 尝试从缓存检查
        if use_cache:
            cache_key = self._get_cache_key(doc_id)
            try:
                cached_data = await redis_manager.get(cache_key)
                if cached_data:
                    return True
            except Exception as e:
                logger.warning(f"缓存检查失败 {cache_key}: {e}")
        
        # 从数据库检查
        try:
            count = await self.count({'_id': doc_id})
            return count > 0
        except Exception as e:
            logger.error(f"检查文档存在性失败 {doc_id}: {e}")
            return False
    
    async def save_many(self, documents: List[T], use_cache: bool = True) -> List[T]:
        """
        批量保存文档
        
        Args:
            documents: 文档列表
            use_cache: 是否更新缓存
            
        Returns:
            保存后的文档列表
        """
        if not documents:
            return []
        
        # 验证所有文档
        for doc in documents:
            if not isinstance(doc, self.document_class):
                raise ValueError(f"所有文档必须是{self.document_class.__name__}类型")
            doc.validate()
        
        # 分离新文档和更新文档
        new_docs = []
        update_docs = []
        
        for doc in documents:
            if doc.is_new():
                new_docs.append(doc)
            else:
                update_docs.append(doc)
        
        try:
            saved_docs = []
            
            # 批量插入新文档
            if new_docs:
                insert_data = [doc.to_dict() for doc in new_docs]
                inserted_ids = await mongo_manager.insert_many(self.collection_name, insert_data)
                
                for i, doc in enumerate(new_docs):
                    if i < len(inserted_ids):
                        doc._id = inserted_ids[i]
                        saved_docs.append(doc)
            
            # 批量更新现有文档
            for doc in update_docs:
                saved_doc = await self.save(doc, use_cache=False)
                saved_docs.append(saved_doc)
            
            # 批量更新缓存
            if use_cache and saved_docs:
                await self._batch_update_cache(saved_docs)
            
            logger.info(f"批量保存文档成功: {len(saved_docs)}个")
            return saved_docs
            
        except Exception as e:
            logger.error(f"批量保存文档失败: {e}")
            raise RepositoryError(f"批量保存失败: {e}")
    
    async def _batch_update_cache(self, documents: List[T]):
        """批量更新缓存"""
        cache_mapping = {}
        for doc in documents:
            cache_key = self._get_cache_key(doc._id)
            cache_mapping[cache_key] = doc.to_dict()
        
        try:
            await redis_manager.mset(cache_mapping, self.cache_ttl)
            await self._invalidate_list_cache()
        except Exception as e:
            logger.warning(f"批量缓存更新失败: {e}")
    
    async def _invalidate_list_cache(self):
        """使列表缓存失效"""
        try:
            # 获取所有相关的列表缓存键
            pattern = f"{self.cache_key_prefix}:list:*"
            # 由于我们的mock Redis不支持模式匹配，这里简化处理
            # 实际环境中可以使用Redis的SCAN命令
            logger.debug(f"清除列表缓存: {pattern}")
        except Exception as e:
            logger.warning(f"清除列表缓存失败: {e}")
    
    async def aggregate(self, pipeline: List[Dict], use_cache: bool = False) -> List[Dict]:
        """
        聚合查询
        
        Args:
            pipeline: 聚合管道
            use_cache: 是否使用缓存
            
        Returns:
            聚合结果
        """
        if not pipeline:
            return []
        
        # 生成缓存键
        cache_key = None
        if use_cache:
            pipeline_str = json.dumps(pipeline, sort_keys=True, default=str)
            pipeline_hash = hashlib.md5(pipeline_str.encode()).hexdigest()
            cache_key = f"{self.cache_key_prefix}:agg:{pipeline_hash}"
            
            # 尝试从缓存获取
            try:
                cached_result = await redis_manager.get(cache_key)
                if cached_result:
                    logger.debug(f"聚合缓存命中: {cache_key}")
                    return cached_result
            except Exception as e:
                logger.warning(f"聚合缓存读取失败: {e}")
        
        try:
            result = await mongo_manager.aggregate(self.collection_name, pipeline)
            
            # 更新缓存
            if use_cache and cache_key and result:
                try:
                    await redis_manager.set(cache_key, result, self.list_cache_ttl)
                except Exception as e:
                    logger.warning(f"聚合缓存更新失败: {e}")
            
            return result
            
        except Exception as e:
            logger.error(f"聚合查询失败: {e}")
            raise QueryError(f"聚合查询失败: {e}")
    
    @asynccontextmanager
    async def transaction(self):
        """
        事务上下文管理器
        
        Usage:
            async with repository.transaction():
                await repository.save(doc1)
                await repository.save(doc2)
        """
        transaction = await mongo_manager.create_transaction()
        async with transaction:
            yield transaction
    
    async def create_lock(self, key: str, timeout: int = 30) -> DistributedLock:
        """
        创建分布式锁
        
        Args:
            key: 锁键名
            timeout: 超时时间
            
        Returns:
            分布式锁实例
        """
        lock_key = f"{self.collection_name}:lock:{key}"
        return await redis_manager.create_lock(lock_key, timeout)
    
    async def warmup_cache(self, filter_dict: Dict = None, limit: int = 100):
        """
        缓存预热
        
        Args:
            filter_dict: 查询条件
            limit: 预热数量限制
        """
        try:
            logger.info(f"开始缓存预热: {self.collection_name}")
            
            documents = await self.find_many(filter_dict, limit=limit, use_cache=False)
            
            # 批量更新缓存
            if documents:
                await self._batch_update_cache(documents)
                logger.info(f"缓存预热完成: {len(documents)}个文档")
            else:
                logger.info("缓存预热完成: 无数据")
                
        except Exception as e:
            logger.error(f"缓存预热失败: {e}")
    
    async def refresh_cache(self, doc_id: str) -> bool:
        """
        刷新单个文档的缓存
        
        Args:
            doc_id: 文档ID
            
        Returns:
            是否刷新成功
        """
        try:
            # 从数据库重新获取
            document = await self.find_by_id(doc_id, use_cache=False)
            if document:
                cache_key = self._get_cache_key(doc_id)
                await redis_manager.set(cache_key, document.to_dict(), self.cache_ttl)
                logger.debug(f"缓存刷新成功: {doc_id}")
                return True
            else:
                # 文档不存在，删除缓存
                cache_key = self._get_cache_key(doc_id)
                await redis_manager.delete(cache_key)
                logger.debug(f"文档不存在，删除缓存: {doc_id}")
                return False
                
        except Exception as e:
            logger.error(f"缓存刷新失败 {doc_id}: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取仓库统计信息
        
        Returns:
            统计信息
        """
        return {
            'collection_name': self.collection_name,
            'document_class': self.document_class.__name__,
            'cache_ttl': self.cache_ttl,
            'list_cache_ttl': self.list_cache_ttl,
            'batch_size': self.batch_size,
            'cache_key_prefix': self.cache_key_prefix
        }


# 便捷函数
def create_repository(document_class: Type[T]) -> BaseRepository:
    """创建仓库实例的便捷函数"""
    return BaseRepository(document_class)