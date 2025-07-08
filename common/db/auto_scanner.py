"""
自动扫描注册模块

该模块提供自动化功能，包含以下功能：
- 扫描所有Document类
- 自动创建MongoDB集合
- 自动创建索引
- 生成Repository类
- 注册到全局管理器
"""

import importlib
import inspect
import os
import sys
from pathlib import Path
from typing import Dict, List, Type, Optional, Any, Set, TypeVar
from dataclasses import dataclass

from common.logger import logger
from .base_document import BaseDocument, document_registry
from .base_repository import BaseRepository
from .mongo_manager import mongo_manager


T = TypeVar('T', bound=BaseDocument)


@dataclass
class DocumentInfo:
    """文档信息"""
    document_class: Type[BaseDocument]
    module_name: str
    collection_name: str
    repository_class: Optional[Type[BaseRepository]] = None
    indexes_created: bool = False


@dataclass
class ScanResult:
    """扫描结果"""
    documents_found: int
    documents_registered: int
    repositories_created: int
    indexes_created: int
    errors: List[str]


class DocumentScanner:
    """文档扫描器"""
    
    def __init__(self):
        self._scanned_modules: Set[str] = set()
        self._document_info: Dict[str, DocumentInfo] = {}
        self._repository_cache: Dict[str, Type[BaseRepository]] = {}
    
    def scan_package(self, package_name: str, recursive: bool = True) -> ScanResult:
        """
        扫描包中的文档类
        
        Args:
            package_name: 包名
            recursive: 是否递归扫描子包
            
        Returns:
            扫描结果
        """
        result = ScanResult(0, 0, 0, 0, [])
        
        try:
            # 导入包
            package = importlib.import_module(package_name)
            
            # 扫描包中的模块
            if hasattr(package, '__path__'):
                for path in package.__path__:
                    result = self._scan_directory(path, package_name, recursive, result)
            else:
                # 单个模块
                result = self._scan_module(package, result)
            
            logger.info(f"包扫描完成: {package_name}")
            logger.info(f"找到文档类: {result.documents_found}, "
                       f"注册: {result.documents_registered}, "
                       f"生成仓库: {result.repositories_created}")
            
            if result.errors:
                logger.warning(f"扫描过程中发生 {len(result.errors)} 个错误")
                for error in result.errors:
                    logger.error(f"扫描错误: {error}")
            
            return result
            
        except Exception as e:
            error_msg = f"扫描包失败 {package_name}: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result
    
    def _scan_directory(self, directory: str, base_package: str, 
                       recursive: bool, result: ScanResult) -> ScanResult:
        """扫描目录"""
        try:
            path = Path(directory)
            
            for item in path.iterdir():
                if item.is_file() and item.suffix == '.py' and item.stem != '__init__':
                    # Python文件
                    module_name = f"{base_package}.{item.stem}"
                    if module_name not in self._scanned_modules:
                        try:
                            module = importlib.import_module(module_name)
                            result = self._scan_module(module, result)
                            self._scanned_modules.add(module_name)
                        except Exception as e:
                            error_msg = f"导入模块失败 {module_name}: {e}"
                            result.errors.append(error_msg)
                
                elif item.is_dir() and recursive and not item.name.startswith('.'):
                    # 子目录
                    if (item / '__init__.py').exists():
                        sub_package = f"{base_package}.{item.name}"
                        result = self._scan_directory(str(item), sub_package, recursive, result)
            
            return result
            
        except Exception as e:
            error_msg = f"扫描目录失败 {directory}: {e}"
            result.errors.append(error_msg)
            return result
    
    def _scan_module(self, module, result: ScanResult) -> ScanResult:
        """扫描模块"""
        try:
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, BaseDocument) and 
                    obj != BaseDocument and
                    obj.__module__ == module.__name__):
                    
                    result.documents_found += 1
                    
                    try:
                        # 注册文档类
                        if self._register_document(obj, module.__name__):
                            result.documents_registered += 1
                        
                        # 生成仓库类
                        if self._create_repository(obj):
                            result.repositories_created += 1
                    
                    except Exception as e:
                        error_msg = f"处理文档类失败 {obj.__name__}: {e}"
                        result.errors.append(error_msg)
            
            return result
            
        except Exception as e:
            error_msg = f"扫描模块失败 {module.__name__}: {e}"
            result.errors.append(error_msg)
            return result
    
    def _register_document(self, document_class: Type[BaseDocument], module_name: str) -> bool:
        """注册文档类"""
        try:
            # 检查是否已注册
            class_name = document_class.__name__
            if class_name in self._document_info:
                logger.debug(f"文档类已注册: {class_name}")
                return False
            
            # 注册到文档注册表
            document_registry.register(document_class)
            
            # 保存文档信息
            collection_name = document_class.get_collection_name()
            doc_info = DocumentInfo(
                document_class=document_class,
                module_name=module_name,
                collection_name=collection_name
            )
            
            self._document_info[class_name] = doc_info
            
            logger.debug(f"注册文档类: {class_name} -> {collection_name}")
            return True
            
        except Exception as e:
            logger.error(f"注册文档类失败 {document_class.__name__}: {e}")
            return False
    
    def _create_repository(self, document_class: Type[BaseDocument]) -> bool:
        """创建仓库类"""
        try:
            class_name = document_class.__name__
            
            # 检查是否已创建
            if class_name in self._repository_cache:
                return False
            
            # 动态创建仓库类
            repository_class_name = f"{class_name}Repository"
            
            # 创建仓库类
            repository_class = type(repository_class_name, (BaseRepository,), {
                '__module__': document_class.__module__,
                '_document_class': document_class
            })
            
            # 缓存仓库类
            self._repository_cache[class_name] = repository_class
            
            # 更新文档信息
            if class_name in self._document_info:
                self._document_info[class_name].repository_class = repository_class
            
            logger.debug(f"生成仓库类: {repository_class_name}")
            return True
            
        except Exception as e:
            logger.error(f"创建仓库类失败 {document_class.__name__}: {e}")
            return False
    
    async def create_collections_and_indexes(self) -> ScanResult:
        """创建集合和索引"""
        result = ScanResult(0, 0, 0, 0, [])
        
        try:
            for class_name, doc_info in self._document_info.items():
                if doc_info.indexes_created:
                    continue
                
                try:
                    # 创建集合（MongoDB会自动创建，这里主要是创建索引）
                    await self._create_indexes_for_document(doc_info)
                    doc_info.indexes_created = True
                    result.indexes_created += 1
                    
                except Exception as e:
                    error_msg = f"创建索引失败 {class_name}: {e}"
                    result.errors.append(error_msg)
            
            logger.info(f"索引创建完成: {result.indexes_created}个文档类")
            
            if result.errors:
                logger.warning(f"索引创建过程中发生 {len(result.errors)} 个错误")
                for error in result.errors:
                    logger.error(error)
            
            return result
            
        except Exception as e:
            error_msg = f"批量创建索引失败: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result
    
    async def _create_indexes_for_document(self, doc_info: DocumentInfo):
        """为文档创建索引"""
        collection_name = doc_info.collection_name
        document_class = doc_info.document_class
        
        # 基础索引
        base_indexes = [
            # 主键索引（MongoDB自动创建）
            # {'keys': [('_id', 1)], 'unique': True},
            
            # 软删除索引
            {'keys': [('is_deleted', 1)]},
            
            # 创建时间索引
            {'keys': [('created_at', -1)]},
            
            # 更新时间索引
            {'keys': [('updated_at', -1)]},
            
            # 版本号索引
            {'keys': [('version', 1)]},
            
            # 复合索引：删除状态 + 创建时间
            {'keys': [('is_deleted', 1), ('created_at', -1)]},
        ]
        
        # 创建基础索引
        for index_config in base_indexes:
            try:
                await mongo_manager.create_index(
                    collection_name, 
                    index_config['keys'], 
                    background=True
                )
                logger.debug(f"创建索引: {collection_name}.{index_config['keys']}")
            except Exception as e:
                logger.warning(f"创建基础索引失败 {collection_name}: {e}")
        
        # 检查文档类是否定义了自定义索引
        if hasattr(document_class, 'get_indexes'):
            try:
                custom_indexes = document_class.get_indexes()
                for index_config in custom_indexes:
                    keys = index_config.get('keys', [])
                    options = {k: v for k, v in index_config.items() if k != 'keys'}
                    
                    await mongo_manager.create_index(
                        collection_name, keys, background=True, **options
                    )
                    logger.debug(f"创建自定义索引: {collection_name}.{keys}")
            except Exception as e:
                logger.warning(f"创建自定义索引失败 {collection_name}: {e}")
    
    def get_document_info(self, class_name: str) -> Optional[DocumentInfo]:
        """获取文档信息"""
        return self._document_info.get(class_name)
    
    def get_repository_class(self, document_class_name: str) -> Optional[Type[BaseRepository]]:
        """获取仓库类"""
        return self._repository_cache.get(document_class_name)
    
    def list_scanned_documents(self) -> List[str]:
        """列出已扫描的文档类"""
        return list(self._document_info.keys())
    
    def get_scan_stats(self) -> Dict[str, Any]:
        """获取扫描统计信息"""
        total_documents = len(self._document_info)
        total_repositories = len(self._repository_cache)
        indexed_documents = sum(1 for info in self._document_info.values() if info.indexes_created)
        
        return {
            'total_documents': total_documents,
            'total_repositories': total_repositories,
            'indexed_documents': indexed_documents,
            'scanned_modules': len(self._scanned_modules),
            'module_list': list(self._scanned_modules)
        }


class RepositoryManager:
    """仓库管理器"""
    
    def __init__(self):
        self._repositories: Dict[str, BaseRepository] = {}
        self._document_scanner = DocumentScanner()
    
    def get_repository(self, document_class: Type[BaseDocument]) -> BaseRepository:
        """
        获取文档类对应的仓库实例
        
        Args:
            document_class: 文档类
            
        Returns:
            仓库实例
        """
        class_name = document_class.__name__
        
        if class_name not in self._repositories:
            # 创建新的仓库实例
            repository = BaseRepository(document_class)
            self._repositories[class_name] = repository
            logger.debug(f"创建仓库实例: {class_name}")
        
        return self._repositories[class_name]
    
    def get_repository_by_name(self, class_name: str) -> Optional[BaseRepository]:
        """
        根据文档类名获取仓库实例
        
        Args:
            class_name: 文档类名
            
        Returns:
            仓库实例或None
        """
        if class_name in self._repositories:
            return self._repositories[class_name]
        
        # 尝试从文档注册表获取文档类
        document_class = document_registry.get_document_class(class_name)
        if document_class:
            return self.get_repository(document_class)
        
        return None
    
    def get_repository_by_collection(self, collection_name: str) -> Optional[BaseRepository]:
        """
        根据集合名获取仓库实例
        
        Args:
            collection_name: 集合名
            
        Returns:
            仓库实例或None
        """
        document_class = document_registry.get_document_class_by_collection(collection_name)
        if document_class:
            return self.get_repository(document_class)
        
        return None
    
    def register_repository(self, document_class: Type[BaseDocument], 
                           repository: BaseRepository):
        """
        注册自定义仓库实例
        
        Args:
            document_class: 文档类
            repository: 仓库实例
        """
        class_name = document_class.__name__
        self._repositories[class_name] = repository
        logger.info(f"注册自定义仓库: {class_name}")
    
    def list_repositories(self) -> List[str]:
        """列出所有仓库"""
        return list(self._repositories.keys())
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            'total_repositories': len(self._repositories),
            'repository_list': self.list_repositories()
        }


class AutoScanner:
    """自动扫描器"""
    
    def __init__(self):
        self.document_scanner = DocumentScanner()
        self.repository_manager = RepositoryManager()
    
    async def auto_scan_and_setup(self, packages: List[str], 
                                 create_indexes: bool = True) -> ScanResult:
        """
        自动扫描并设置
        
        Args:
            packages: 要扫描的包列表
            create_indexes: 是否创建索引
            
        Returns:
            扫描结果
        """
        total_result = ScanResult(0, 0, 0, 0, [])
        
        try:
            # 扫描所有包
            for package_name in packages:
                result = self.document_scanner.scan_package(package_name, recursive=True)
                
                # 合并结果
                total_result.documents_found += result.documents_found
                total_result.documents_registered += result.documents_registered
                total_result.repositories_created += result.repositories_created
                total_result.errors.extend(result.errors)
            
            # 创建集合和索引
            if create_indexes:
                index_result = await self.document_scanner.create_collections_and_indexes()
                total_result.indexes_created = index_result.indexes_created
                total_result.errors.extend(index_result.errors)
            
            # 生成仓库实例
            self._setup_repositories()
            
            logger.info("自动扫描和设置完成")
            logger.info(f"总计 - 文档: {total_result.documents_found}, "
                       f"注册: {total_result.documents_registered}, "
                       f"仓库: {total_result.repositories_created}, "
                       f"索引: {total_result.indexes_created}")
            
            if total_result.errors:
                logger.warning(f"总计发生 {len(total_result.errors)} 个错误")
            
            return total_result
            
        except Exception as e:
            error_msg = f"自动扫描失败: {e}"
            logger.error(error_msg)
            total_result.errors.append(error_msg)
            return total_result
    
    def _setup_repositories(self):
        """设置仓库"""
        for class_name in self.document_scanner.list_scanned_documents():
            document_class = document_registry.get_document_class(class_name)
            if document_class:
                # 确保仓库存在
                self.repository_manager.get_repository(document_class)
    
    def get_repository(self, document_class: Type[BaseDocument]) -> BaseRepository:
        """获取仓库实例"""
        return self.repository_manager.get_repository(document_class)
    
    def get_repository_by_name(self, class_name: str) -> Optional[BaseRepository]:
        """根据文档类名获取仓库实例"""
        return self.repository_manager.get_repository_by_name(class_name)
    
    def get_repository_by_collection(self, collection_name: str) -> Optional[BaseRepository]:
        """根据集合名获取仓库实例"""
        return self.repository_manager.get_repository_by_collection(collection_name)
    
    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有统计信息"""
        return {
            'scanner_stats': self.document_scanner.get_scan_stats(),
            'repository_stats': self.repository_manager.get_stats()
        }


# 全局自动扫描器实例
auto_scanner = AutoScanner()


# 便捷函数
async def scan_and_setup_documents(packages: List[str], create_indexes: bool = True) -> ScanResult:
    """扫描并设置文档的便捷函数"""
    return await auto_scanner.auto_scan_and_setup(packages, create_indexes)


def get_repository(document_class: Type[BaseDocument]) -> BaseRepository:
    """获取仓库的便捷函数"""
    return auto_scanner.get_repository(document_class)


def get_repository_by_name(class_name: str) -> Optional[BaseRepository]:
    """根据类名获取仓库的便捷函数"""
    return auto_scanner.get_repository_by_name(class_name)


def get_repository_by_collection(collection_name: str) -> Optional[BaseRepository]:
    """根据集合名获取仓库的便捷函数"""
    return auto_scanner.get_repository_by_collection(collection_name)


async def quick_setup(models_package: str = "models") -> bool:
    """快速设置的便捷函数"""
    try:
        result = await scan_and_setup_documents([models_package])
        success = (result.documents_found > 0 and 
                  len(result.errors) == 0)
        
        if success:
            logger.info(f"快速设置成功: 发现 {result.documents_found} 个文档类")
        else:
            logger.error(f"快速设置失败: {len(result.errors)} 个错误")
        
        return success
        
    except Exception as e:
        logger.error(f"快速设置异常: {e}")
        return False


# 用于支持类型提示的仓库获取函数
def repo(document_class: Type[T]) -> BaseRepository:
    """
    获取指定文档类的仓库实例（支持类型提示）
    
    Args:
        document_class: 文档类
        
    Returns:
        仓库实例
    """
    return get_repository(document_class)