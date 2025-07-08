"""
OrderRepository 数据仓库类

为 OrderDocument 文档模型自动生成的Repository类
提供数据的增删改查等基本操作

自动生成时间: 2025-07-08 16:42:52
生成器: knight_server.models.gen_utils.RepositoryGenerator
源文档: models.document.example_document.OrderDocument

注意: 此文件为自动生成，可以添加自定义方法，但不要修改自动生成的部分！
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime

from common.db.base_repository import BaseRepository
from models.document.example_document import OrderDocument
from common.logger import logger

class OrderRepository(BaseRepository[OrderDocument]):
    """
    OrderDocument 数据仓库
    
    自动生成的仓库类，提供 OrderDocument 数据的增删改查操作
    集合: orders
    
    继承自 BaseRepository，包含所有基本的数据库操作方法
    """
    def __init__(self):
        """
        初始化 OrderDocument 仓库
        """
        super().__init__(
            document_class=OrderDocument,
            collection_name="orders"
        )
        self.logger = logger

    async def find_by_order_id(self, order_id: str) -> Optional[OrderDocument]:
        """
        根据文档字段: order_id查找文档
        
        Args:
            order_id: 文档字段: order_id
            
        Returns:
            Optional[OrderDocument]: 找到的文档或None
        """
        return await self.find_one({"$order_id": order_id})

    async def find_by_user_id(self, user_id: str) -> Optional[OrderDocument]:
        """
        根据文档字段: user_id查找文档
        
        Args:
            user_id: 文档字段: user_id
            
        Returns:
            Optional[OrderDocument]: 找到的文档或None
        """
        return await self.find_one({"$user_id": user_id})

    async def find_by_total_amount(self, total_amount: float) -> Optional[OrderDocument]:
        """
        根据文档字段: total_amount查找文档
        
        Args:
            total_amount: 文档字段: total_amount
            
        Returns:
            Optional[OrderDocument]: 找到的文档或None
        """
        return await self.find_one({"$total_amount": total_amount})

    async def find_by_status(self, status: str) -> Optional[OrderDocument]:
        """
        根据文档字段: status查找文档
        
        Args:
            status: 文档字段: status
            
        Returns:
            Optional[OrderDocument]: 找到的文档或None
        """
        return await self.find_one({"$status": status})

    async def find_by_items(self, items: List[Any]) -> Optional[OrderDocument]:
        """
        根据文档字段: items查找文档
        
        Args:
            items: 文档字段: items
            
        Returns:
            Optional[OrderDocument]: 找到的文档或None
        """
        return await self.find_one({"$items": items})

    async def find_by_shipping_address(self, shipping_address: Any) -> Optional[OrderDocument]:
        """
        根据文档字段: shipping_address查找文档
        
        Args:
            shipping_address: 文档字段: shipping_address
            
        Returns:
            Optional[OrderDocument]: 找到的文档或None
        """
        return await self.find_one({"$shipping_address": shipping_address})

    async def create_batch(self, documents: List[OrderDocument]) -> List[OrderDocument]:
        """
        批量创建文档
        
        Args:
            documents: 要创建的文档列表
            
        Returns:
            List[OrderDocument]: 创建成功的文档列表
        """
        created_documents = []
        
        for doc in documents:
            try:
                created_doc = await self.create(doc)
                created_documents.append(created_doc)
            except Exception as e:
                self.logger.error(f"批量创建文档失败: {str(e)}")
                continue
        
        return created_documents

    async def update_batch(self, documents: List[OrderDocument]) -> List[OrderDocument]:
        """
        批量更新文档
        
        Args:
            documents: 要更新的文档列表
            
        Returns:
            List[OrderDocument]: 更新成功的文档列表
        """
        updated_documents = []
        
        for doc in documents:
            try:
                updated_doc = await self.update(doc)
                if updated_doc:
                    updated_documents.append(updated_doc)
            except Exception as e:
                self.logger.error(f"批量更新文档失败: {str(e)}")
                continue
        
        return updated_documents

    async def count_documents(self, filter_dict: Dict[str, Any] = None) -> int:
        """
        统计文档数量
        
        Args:
            filter_dict: 过滤条件
            
        Returns:
            int: 文档数量
        """
        return await self.count(filter_dict or {})

    async def paginate(self, page: int = 1, limit: int = 10, 
                      filter_dict: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        分页查询文档
        
        Args:
            page: 页码（从1开始）
            limit: 每页数量
            filter_dict: 过滤条件
            
        Returns:
            Dict[str, Any]: 分页结果
        """
        skip = (page - 1) * limit
        filter_dict = filter_dict or {}
        
        documents = await self.find_many(filter_dict, skip=skip, limit=limit)
        total = await self.count(filter_dict)
        
        return {
            "documents": documents,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }

    def validate_document(self, document: OrderDocument) -> bool:
        """
        验证文档数据
        
        Args:
            document: 要验证的文档
            
        Returns:
            bool: 验证是否通过
        """
        try:
            # 调用文档的验证方法
            document.validate()
            return True
        except Exception as e:
            self.logger.error(f"文档验证失败: {str(e)}")
            return False