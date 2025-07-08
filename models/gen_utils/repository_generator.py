"""
Repository类生成器模块

负责根据扫描到的文档模型生成对应的Repository类。
生成的Repository类继承BaseRepository，包含类型提示和文档字符串。
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import keyword

from common.logger import logger
from .document_scanner import DocumentClassInfo, DocumentFieldInfo


class RepositoryGenerator:
    """
    Repository类生成器
    
    负责根据扫描到的文档模型生成对应的Repository类
    """
    
    def __init__(self, output_dir: str = "models/repository"):
        """
        初始化生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        self.logger = logger
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_repository_files(self, document_infos: List[DocumentClassInfo]) -> List[str]:
        """
        生成Repository类文件
        
        Args:
            document_infos: 文档类信息列表
            
        Returns:
            List[str]: 生成的Repository类文件路径列表
        """
        generated_files = []
        
        try:
            self.logger.info("开始生成Repository类文件...")
            
            for doc_info in document_infos:
                try:
                    file_path = self._generate_single_repository(doc_info)
                    generated_files.append(file_path)
                    self.logger.info(f"生成Repository类文件: {file_path}")
                except Exception as e:
                    self.logger.error(f"生成Repository类文件失败: {doc_info.name}, 错误: {str(e)}")
                    continue
            
            self.logger.info(f"Repository类文件生成完成，共生成{len(generated_files)}个文件")
            return generated_files
            
        except Exception as e:
            self.logger.error(f"生成Repository类文件失败: {str(e)}")
            raise
    
    def _generate_single_repository(self, doc_info: DocumentClassInfo) -> str:
        """
        生成单个Repository类文件
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            str: 生成的Repository类文件路径
        """
        # 生成Repository类代码
        repo_code = self._generate_repository_code(doc_info)
        
        # 生成文件路径
        repo_name = self._generate_repository_name(doc_info.name)
        file_name = f"{self._to_snake_case(repo_name)}.py"
        file_path = os.path.join(self.output_dir, file_name)
        
        # 检查是否已存在自定义Repository
        if os.path.exists(file_path):
            # 合并自定义方法
            repo_code = self._merge_custom_repository(file_path, repo_code, doc_info)
        
        # 写入Repository文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(repo_code)
        
        return file_path
    
    def _generate_repository_code(self, doc_info: DocumentClassInfo) -> str:
        """
        生成Repository类代码
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            str: 生成的Repository类代码
        """
        # 生成Repository类名
        repo_name = self._generate_repository_name(doc_info.name)
        
        # 生成文件头部
        header = self._generate_file_header(doc_info, repo_name)
        
        # 生成导入部分
        imports = self._generate_imports(doc_info)
        
        # 生成Repository类定义
        repo_def = self._generate_repository_definition(doc_info, repo_name)
        
        # 生成Repository方法
        methods = self._generate_repository_methods(doc_info, repo_name)
        
        # 组合完整代码
        code_parts = [header, imports, repo_def, methods]
        return '\n\n'.join(code_parts)
    
    def _generate_repository_name(self, document_name: str) -> str:
        """
        生成Repository类名
        
        Args:
            document_name: 文档类名
            
        Returns:
            str: Repository类名
        """
        # 移除Document后缀
        base_name = document_name
        if base_name.endswith('Document'):
            base_name = base_name[:-8]
        
        # 添加Repository后缀
        return f"{base_name}Repository"
    
    def _generate_file_header(self, doc_info: DocumentClassInfo, repo_name: str) -> str:
        """
        生成文件头部
        
        Args:
            doc_info: 文档类信息
            repo_name: Repository类名
            
        Returns:
            str: 文件头部代码
        """
        return f'''"""
{repo_name} 数据仓库类

为 {doc_info.name} 文档模型自动生成的Repository类
提供数据的增删改查等基本操作

自动生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
生成器: knight_server.models.gen_utils.RepositoryGenerator
源文档: {doc_info.module}.{doc_info.name}

注意: 此文件为自动生成，可以添加自定义方法，但不要修改自动生成的部分！
"""'''
    
    def _generate_imports(self, doc_info: DocumentClassInfo) -> str:
        """
        生成导入部分
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            str: 导入部分代码
        """
        imports = [
            "from typing import Optional, List, Dict, Any, Union",
            "from datetime import datetime",
            "",
            "from common.db.base_repository import BaseRepository",
            f"from {doc_info.module} import {doc_info.name}",
            "from common.logger import logger"
        ]
        
        return '\n'.join(imports)
    
    def _generate_repository_definition(self, doc_info: DocumentClassInfo, repo_name: str) -> str:
        """
        生成Repository类定义
        
        Args:
            doc_info: 文档类信息
            repo_name: Repository类名
            
        Returns:
            str: Repository类定义代码
        """
        # 生成类定义
        class_def = f"class {repo_name}(BaseRepository[{doc_info.name}]):"
        
        # 生成类文档字符串
        collection_info = f"集合: {doc_info.collection_name}" if doc_info.collection_name else ""
        doc_string = f'''    """
    {doc_info.name} 数据仓库
    
    自动生成的仓库类，提供 {doc_info.name} 数据的增删改查操作
    {collection_info}
    
    继承自 BaseRepository，包含所有基本的数据库操作方法
    """'''
        
        # 生成构造函数
        constructor = self._generate_constructor(doc_info)
        
        # 组合类定义
        parts = [class_def, doc_string, constructor]
        return '\n'.join(parts)
    
    def _generate_constructor(self, doc_info: DocumentClassInfo) -> str:
        """
        生成构造函数
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            str: 构造函数代码
        """
        collection_name = doc_info.collection_name or self._to_snake_case(doc_info.name)
        
        constructor = f'''    def __init__(self):
        """
        初始化 {doc_info.name} 仓库
        """
        super().__init__(
            document_class={doc_info.name},
            collection_name="{collection_name}"
        )
        self.logger = logger'''
        
        return constructor
    
    def _generate_repository_methods(self, doc_info: DocumentClassInfo, repo_name: str) -> str:
        """
        生成Repository方法
        
        Args:
            doc_info: 文档类信息
            repo_name: Repository类名
            
        Returns:
            str: Repository方法代码
        """
        methods = []
        
        # 生成字段查询方法
        field_methods = self._generate_field_query_methods(doc_info)
        methods.extend(field_methods)
        
        # 生成批量操作方法
        batch_methods = self._generate_batch_methods(doc_info)
        methods.extend(batch_methods)
        
        # 生成统计方法
        stats_methods = self._generate_stats_methods(doc_info)
        methods.extend(stats_methods)
        
        # 生成验证方法
        validation_methods = self._generate_validation_methods(doc_info)
        methods.extend(validation_methods)
        
        # 如果没有自定义方法，添加占位符
        if not methods:
            methods.append("    # 可以在此处添加自定义方法\n    pass")
        
        return '\n\n'.join(methods)
    
    def _generate_field_query_methods(self, doc_info: DocumentClassInfo) -> List[str]:
        """
        生成字段查询方法
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            List[str]: 字段查询方法列表
        """
        methods = []
        
        # 为每个字段生成查询方法
        for field_info in doc_info.fields:
            if field_info.name in ['_id', 'created_at', 'updated_at', 'version', 'is_deleted']:
                continue  # 跳过基类字段
            
            method_name = f"find_by_{field_info.name}"
            method_code = f'''    async def {method_name}(self, {field_info.name}: {self._get_python_type(field_info.type)}) -> Optional[{doc_info.name}]:
        """
        根据{field_info.comment}查找文档
        
        Args:
            {field_info.name}: {field_info.comment}
            
        Returns:
            Optional[{doc_info.name}]: 找到的文档或None
        """
        return await self.find_one({{"${field_info.name}": {field_info.name}}})'''
            
            methods.append(method_code)
        
        return methods
    
    def _generate_batch_methods(self, doc_info: DocumentClassInfo) -> List[str]:
        """
        生成批量操作方法
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            List[str]: 批量操作方法列表
        """
        methods = []
        
        # 批量创建方法
        batch_create_method = f'''    async def create_batch(self, documents: List[{doc_info.name}]) -> List[{doc_info.name}]:
        """
        批量创建文档
        
        Args:
            documents: 要创建的文档列表
            
        Returns:
            List[{doc_info.name}]: 创建成功的文档列表
        """
        created_documents = []
        
        for doc in documents:
            try:
                created_doc = await self.create(doc)
                created_documents.append(created_doc)
            except Exception as e:
                self.logger.error(f"批量创建文档失败: {{str(e)}}")
                continue
        
        return created_documents'''
        
        methods.append(batch_create_method)
        
        # 批量更新方法
        batch_update_method = f'''    async def update_batch(self, documents: List[{doc_info.name}]) -> List[{doc_info.name}]:
        """
        批量更新文档
        
        Args:
            documents: 要更新的文档列表
            
        Returns:
            List[{doc_info.name}]: 更新成功的文档列表
        """
        updated_documents = []
        
        for doc in documents:
            try:
                updated_doc = await self.update(doc)
                if updated_doc:
                    updated_documents.append(updated_doc)
            except Exception as e:
                self.logger.error(f"批量更新文档失败: {{str(e)}}")
                continue
        
        return updated_documents'''
        
        methods.append(batch_update_method)
        
        return methods
    
    def _generate_stats_methods(self, doc_info: DocumentClassInfo) -> List[str]:
        """
        生成统计方法
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            List[str]: 统计方法列表
        """
        methods = []
        
        # 计数方法
        count_method = f'''    async def count_documents(self, filter_dict: Dict[str, Any] = None) -> int:
        """
        统计文档数量
        
        Args:
            filter_dict: 过滤条件
            
        Returns:
            int: 文档数量
        """
        return await self.count(filter_dict or {{}})'''
        
        methods.append(count_method)
        
        # 分页查询方法
        paginate_method = f'''    async def paginate(self, page: int = 1, limit: int = 10, 
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
        filter_dict = filter_dict or {{}}
        
        documents = await self.find_many(filter_dict, skip=skip, limit=limit)
        total = await self.count(filter_dict)
        
        return {{
            "documents": documents,
            "total": total,
            "page": page,
            "limit": limit,
            "pages": (total + limit - 1) // limit
        }}'''
        
        methods.append(paginate_method)
        
        return methods
    
    def _generate_validation_methods(self, doc_info: DocumentClassInfo) -> List[str]:
        """
        生成验证方法
        
        Args:
            doc_info: 文档类信息
            
        Returns:
            List[str]: 验证方法列表
        """
        methods = []
        
        # 验证方法
        validate_method = f'''    def validate_document(self, document: {doc_info.name}) -> bool:
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
            self.logger.error(f"文档验证失败: {{str(e)}}")
            return False'''
        
        methods.append(validate_method)
        
        return methods
    
    def _get_python_type(self, type_str: str) -> str:
        """
        获取Python类型字符串
        
        Args:
            type_str: 类型字符串
            
        Returns:
            str: Python类型字符串
        """
        type_mapping = {
            'int': 'int',
            'float': 'float',
            'str': 'str',
            'bool': 'bool',
            'list': 'List[Any]',
            'dict': 'Dict[str, Any]',
            'List': 'List[Any]',
            'Dict': 'Dict[str, Any]',
            'Any': 'Any'
        }
        
        return type_mapping.get(type_str, 'Any')
    
    def _to_snake_case(self, name: str) -> str:
        """
        转换为snake_case
        
        Args:
            name: 原始名称
            
        Returns:
            str: snake_case名称
        """
        import re
        
        # 在大写字母前插入下划线
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
    
    def _merge_custom_repository(self, file_path: str, generated_code: str, 
                                doc_info: DocumentClassInfo) -> str:
        """
        合并自定义Repository代码
        
        Args:
            file_path: 现有文件路径
            generated_code: 生成的代码
            doc_info: 文档类信息
            
        Returns:
            str: 合并后的代码
        """
        try:
            # 读取现有文件
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_code = f.read()
            
            # 检查是否包含自定义方法标记
            if "# 自定义方法开始" in existing_code and "# 自定义方法结束" in existing_code:
                # 提取自定义方法
                start_marker = "# 自定义方法开始"
                end_marker = "# 自定义方法结束"
                
                start_idx = existing_code.find(start_marker)
                end_idx = existing_code.find(end_marker) + len(end_marker)
                
                if start_idx != -1 and end_idx != -1:
                    custom_methods = existing_code[start_idx:end_idx]
                    
                    # 在生成的代码中添加自定义方法
                    generated_code += f"\n\n    {custom_methods}"
            
            return generated_code
            
        except Exception as e:
            self.logger.warning(f"合并自定义Repository代码失败: {str(e)}")
            return generated_code
    
    def validate_repository_file(self, file_path: str) -> bool:
        """
        验证生成的Repository文件
        
        Args:
            file_path: Repository文件路径
            
        Returns:
            bool: 是否有效
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # 编译代码检查语法
            compile(code, file_path, 'exec')
            
            # 检查是否包含Repository类
            if 'class ' not in code or 'Repository' not in code:
                self.logger.error(f"Repository文件缺少Repository类定义: {file_path}")
                return False
            
            # 检查是否继承BaseRepository
            if 'BaseRepository' not in code:
                self.logger.error(f"Repository文件未继承BaseRepository: {file_path}")
                return False
            
            return True
            
        except SyntaxError as e:
            self.logger.error(f"Repository文件语法错误: {file_path}, 错误: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"验证Repository文件失败: {file_path}, 错误: {str(e)}")
            return False
    
    def backup_existing_file(self, file_path: str) -> Optional[str]:
        """
        备份现有文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            Optional[str]: 备份文件路径，如果没有现有文件则返回None
        """
        if not os.path.exists(file_path):
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{file_path}.backup_{timestamp}"
        
        try:
            os.rename(file_path, backup_path)
            self.logger.info(f"备份现有文件: {file_path} -> {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.error(f"备份文件失败: {file_path}, 错误: {str(e)}")
            return None