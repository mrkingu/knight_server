"""
UserRepository 数据仓库类

为 UserDocument 文档模型自动生成的Repository类
提供数据的增删改查等基本操作

自动生成时间: 2025-07-08 16:45:41
生成器: knight_server.models.gen_utils.RepositoryGenerator
源文档: models.document.example_document.UserDocument

注意: 此文件为自动生成，可以添加自定义方法，但不要修改自动生成的部分！
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime

from common.db.base_repository import BaseRepository
from models.document.example_document import UserDocument
from common.logger import logger

class UserRepository(BaseRepository[UserDocument]):
    """
    UserDocument 数据仓库
    
    自动生成的仓库类，提供 UserDocument 数据的增删改查操作
    集合: users
    
    继承自 BaseRepository，包含所有基本的数据库操作方法
    """
    def __init__(self):
        """
        初始化 UserDocument 仓库
        """
        super().__init__(
            document_class=UserDocument,
            collection_name="users"
        )
        self.logger = logger

    async def find_by_username(self, username: str) -> Optional[UserDocument]:
        """
        根据文档字段: username查找文档
        
        Args:
            username: 文档字段: username
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$username": username})

    async def find_by_email(self, email: str) -> Optional[UserDocument]:
        """
        根据文档字段: email查找文档
        
        Args:
            email: 文档字段: email
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$email": email})

    async def find_by_password_hash(self, password_hash: str) -> Optional[UserDocument]:
        """
        根据文档字段: password_hash查找文档
        
        Args:
            password_hash: 文档字段: password_hash
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$password_hash": password_hash})

    async def find_by_profile(self, profile: Dict[str, Any]) -> Optional[UserDocument]:
        """
        根据文档字段: profile查找文档
        
        Args:
            profile: 文档字段: profile
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$profile": profile})

    async def find_by_permissions(self, permissions: List[Any]) -> Optional[UserDocument]:
        """
        根据文档字段: permissions查找文档
        
        Args:
            permissions: 文档字段: permissions
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$permissions": permissions})

    async def find_by_last_login(self, last_login: Any) -> Optional[UserDocument]:
        """
        根据文档字段: last_login查找文档
        
        Args:
            last_login: 文档字段: last_login
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$last_login": last_login})

    async def find_by_is_active(self, is_active: bool) -> Optional[UserDocument]:
        """
        根据文档字段: is_active查找文档
        
        Args:
            is_active: 文档字段: is_active
            
        Returns:
            Optional[UserDocument]: 找到的文档或None
        """
        return await self.find_one({"$is_active": is_active})

    async def create_batch(self, documents: List[UserDocument]) -> List[UserDocument]:
        """
        批量创建文档
        
        Args:
            documents: 要创建的文档列表
            
        Returns:
            List[UserDocument]: 创建成功的文档列表
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

    async def update_batch(self, documents: List[UserDocument]) -> List[UserDocument]:
        """
        批量更新文档
        
        Args:
            documents: 要更新的文档列表
            
        Returns:
            List[UserDocument]: 更新成功的文档列表
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

    def validate_document(self, document: UserDocument) -> bool:
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