"""
Python类生成器模块

负责根据Excel解析结果生成Python配置类。
生成的类包含中文注释、类型提示，并遵循PEP 8编码规范。
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime
import keyword

from common.logger import logger
from .excel_parser import ExcelSheetInfo, ExcelFieldInfo


class ClassGenerator:
    """
    Python类生成器
    
    负责根据Excel解析结果生成Python配置类
    """
    
    def __init__(self, output_dir: str = "json_data/class_data"):
        """
        初始化类生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        self.logger = logger
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_class_files(self, sheet_infos: List[ExcelSheetInfo], 
                           usage: str = 'cs') -> List[str]:
        """
        生成Python类文件
        
        Args:
            sheet_infos: Excel表格信息列表
            usage: 使用端标记 ('c', 's', 'cs')
            
        Returns:
            List[str]: 生成的Python类文件路径列表
        """
        generated_files = []
        
        try:
            self.logger.info(f"开始生成Python类文件，使用端: {usage}")
            
            for sheet_info in sheet_infos:
                try:
                    file_path = self._generate_single_class(sheet_info, usage)
                    generated_files.append(file_path)
                    self.logger.info(f"生成Python类文件: {file_path}")
                except Exception as e:
                    self.logger.error(f"生成Python类文件失败: {sheet_info.sheet_name}, 错误: {str(e)}")
                    continue
            
            self.logger.info(f"Python类文件生成完成，共生成{len(generated_files)}个文件")
            return generated_files
            
        except Exception as e:
            self.logger.error(f"生成Python类文件失败, 错误: {str(e)}")
            raise
    
    def _generate_single_class(self, sheet_info: ExcelSheetInfo, usage: str) -> str:
        """
        生成单个Python类文件
        
        Args:
            sheet_info: Excel表格信息
            usage: 使用端标记
            
        Returns:
            str: 生成的Python类文件路径
        """
        # 过滤字段
        filtered_fields = self._filter_fields_by_usage(sheet_info.fields, usage)
        
        # 生成类代码
        class_code = self._generate_class_code(sheet_info, filtered_fields, usage)
        
        # 生成文件路径
        file_name = f"{sheet_info.sheet_name}.py"
        if usage != 'cs':
            file_name = f"{sheet_info.sheet_name}_{usage}.py"
        
        file_path = os.path.join(self.output_dir, file_name)
        
        # 写入Python文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(class_code)
        
        return file_path
    
    def _filter_fields_by_usage(self, fields: List[ExcelFieldInfo], usage: str) -> List[ExcelFieldInfo]:
        """
        根据使用端标记过滤字段
        
        Args:
            fields: 字段信息列表
            usage: 使用端标记
            
        Returns:
            List[ExcelFieldInfo]: 过滤后的字段列表
        """
        if usage == 'cs':
            return fields  # 双端使用，返回所有字段
        
        filtered_fields = []
        for field in fields:
            if field.usage == 'cs' or field.usage == usage:
                filtered_fields.append(field)
        
        return filtered_fields
    
    def _generate_class_code(self, sheet_info: ExcelSheetInfo, 
                           fields: List[ExcelFieldInfo], usage: str) -> str:
        """
        生成类代码
        
        Args:
            sheet_info: Excel表格信息
            fields: 过滤后的字段列表
            usage: 使用端标记
            
        Returns:
            str: 生成的类代码
        """
        # 生成类名
        class_name = self._generate_class_name(sheet_info.sheet_name)
        
        # 生成文件头部
        header = self._generate_file_header(sheet_info, class_name, usage)
        
        # 生成导入部分
        imports = self._generate_imports(fields)
        
        # 生成类定义
        class_def = self._generate_class_definition(class_name, fields, sheet_info)
        
        # 生成类方法
        methods = self._generate_class_methods(class_name, fields)
        
        # 组合完整代码
        code_parts = [header, imports, class_def, methods]
        return '\n\n'.join(code_parts)
    
    def _generate_class_name(self, sheet_name: str) -> str:
        """
        生成类名（驼峰命名）
        
        Args:
            sheet_name: 表格名称
            
        Returns:
            str: 类名
        """
        # 移除特殊字符，转换为驼峰命名
        parts = sheet_name.replace('_', ' ').replace('-', ' ').split()
        class_name = ''.join(word.capitalize() for word in parts)
        
        # 确保类名以字母开头
        if not class_name or not class_name[0].isalpha():
            class_name = 'Config' + class_name
        
        return class_name
    
    def _generate_file_header(self, sheet_info: ExcelSheetInfo, 
                            class_name: str, usage: str) -> str:
        """
        生成文件头部
        
        Args:
            sheet_info: Excel表格信息
            class_name: 类名
            usage: 使用端标记
            
        Returns:
            str: 文件头部代码
        """
        usage_desc = {
            'c': '客户端',
            's': '服务端',
            'cs': '客户端和服务端'
        }.get(usage, usage)
        
        return f'''"""
{class_name} 配置类

从 {sheet_info.sheet_name} 配置表自动生成的Python类
适用于: {usage_desc}

自动生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
生成器: knight_server.json_data.gen_utils.ClassGenerator
源文件: {sheet_info.file_path}

注意: 此文件为自动生成，请勿手动修改！
"""'''
    
    def _generate_imports(self, fields: List[ExcelFieldInfo]) -> str:
        """
        生成导入部分
        
        Args:
            fields: 字段列表
            
        Returns:
            str: 导入部分代码
        """
        imports = [
            "from typing import Optional, List, Dict, Any, Union",
            "from dataclasses import dataclass, field",
            "from datetime import datetime",
            "import json"
        ]
        
        # 检查是否需要额外的导入
        for field_info in fields:
            if field_info.type in ['list', 'dict']:
                # 已经包含在基础导入中
                pass
        
        return '\n'.join(imports)
    
    def _generate_class_definition(self, class_name: str, fields: List[ExcelFieldInfo], 
                                 sheet_info: ExcelSheetInfo) -> str:
        """
        生成类定义
        
        Args:
            class_name: 类名
            fields: 字段列表
            sheet_info: Excel表格信息
            
        Returns:
            str: 类定义代码
        """
        # 生成类装饰器和声明
        class_def = f"@dataclass\nclass {class_name}:"
        
        # 生成类文档字符串
        doc_string = f'    """\n    {class_name} 配置类\n    \n    从 {sheet_info.sheet_name} 配置表生成的数据类\n    """'
        
        # 生成字段定义
        field_defs = []
        for field_info in fields:
            field_def = self._generate_field_definition(field_info)
            field_defs.append(field_def)
        
        # 如果没有字段，添加一个pass
        if not field_defs:
            field_defs.append("    pass")
        
        # 组合类定义
        parts = [class_def, doc_string] + field_defs
        return '\n'.join(parts)
    
    def _generate_field_definition(self, field_info: ExcelFieldInfo) -> str:
        """
        生成字段定义
        
        Args:
            field_info: 字段信息
            
        Returns:
            str: 字段定义代码
        """
        # 生成字段名（确保不是Python关键字）
        field_name = field_info.name
        if keyword.iskeyword(field_name):
            field_name = f"{field_name}_"
        
        # 生成类型注解
        type_annotation = self._get_python_type_annotation(field_info.type)
        
        # 生成默认值
        default_value = self._get_default_value(field_info.type)
        
        # 生成字段定义
        field_def = f"    {field_name}: {type_annotation}"
        if default_value:
            field_def += f" = {default_value}"
        
        # 添加注释
        field_def += f"  # {field_info.comment}"
        
        return field_def
    
    def _get_python_type_annotation(self, data_type: str) -> str:
        """
        获取Python类型注解
        
        Args:
            data_type: 数据类型
            
        Returns:
            str: Python类型注解
        """
        type_mapping = {
            'int': 'Optional[int]',
            'float': 'Optional[float]',
            'str': 'Optional[str]',
            'bool': 'Optional[bool]',
            'list': 'Optional[List[Any]]',
            'dict': 'Optional[Dict[str, Any]]',
        }
        
        return type_mapping.get(data_type, 'Optional[Any]')
    
    def _get_default_value(self, data_type: str) -> str:
        """
        获取默认值
        
        Args:
            data_type: 数据类型
            
        Returns:
            str: 默认值代码
        """
        default_mapping = {
            'int': 'None',
            'float': 'None',
            'str': 'None',
            'bool': 'None',
            'list': 'field(default_factory=list)',
            'dict': 'field(default_factory=dict)',
        }
        
        return default_mapping.get(data_type, 'None')
    
    def _generate_class_methods(self, class_name: str, fields: List[ExcelFieldInfo]) -> str:
        """
        生成类方法
        
        Args:
            class_name: 类名
            fields: 字段列表
            
        Returns:
            str: 类方法代码
        """
        methods = []
        
        # 生成 from_dict 方法
        from_dict_method = self._generate_from_dict_method(class_name, fields)
        methods.append(from_dict_method)
        
        # 生成 to_dict 方法
        to_dict_method = self._generate_to_dict_method(fields)
        methods.append(to_dict_method)
        
        # 生成 from_json 方法
        from_json_method = self._generate_from_json_method(class_name)
        methods.append(from_json_method)
        
        # 生成 to_json 方法
        to_json_method = self._generate_to_json_method()
        methods.append(to_json_method)
        
        return '\n\n'.join(methods)
    
    def _generate_from_dict_method(self, class_name: str, fields: List[ExcelFieldInfo]) -> str:
        """
        生成 from_dict 方法
        
        Args:
            class_name: 类名
            fields: 字段列表
            
        Returns:
            str: from_dict 方法代码
        """
        method_code = f'''    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> '{class_name}':
        """
        从字典创建配置对象
        
        Args:
            data: 字典数据
            
        Returns:
            {class_name}: 配置对象
        """
        return cls('''
        
        # 生成字段赋值
        field_assignments = []
        for field_info in fields:
            field_name = field_info.name
            if keyword.iskeyword(field_name):
                field_name = f"{field_name}_"
            
            field_assignments.append(f"{field_name}=data.get('{field_info.name}')")
        
        if field_assignments:
            method_code += '\n            ' + ',\n            '.join(field_assignments)
        
        method_code += '\n        )'
        
        return method_code
    
    def _generate_to_dict_method(self, fields: List[ExcelFieldInfo]) -> str:
        """
        生成 to_dict 方法
        
        Args:
            fields: 字段列表
            
        Returns:
            str: to_dict 方法代码
        """
        method_code = '''    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Dict[str, Any]: 字典数据
        """
        return {'''
        
        # 生成字段映射
        field_mappings = []
        for field_info in fields:
            field_name = field_info.name
            if keyword.iskeyword(field_name):
                field_name = f"{field_name}_"
            
            field_mappings.append(f"'{field_info.name}': self.{field_name}")
        
        if field_mappings:
            method_code += '\n            ' + ',\n            '.join(field_mappings)
        
        method_code += '\n        }'
        
        return method_code
    
    def _generate_from_json_method(self, class_name: str) -> str:
        """
        生成 from_json 方法
        
        Args:
            class_name: 类名
            
        Returns:
            str: from_json 方法代码
        """
        return f'''    @classmethod
    def from_json(cls, json_str: str) -> '{class_name}':
        """
        从JSON字符串创建配置对象
        
        Args:
            json_str: JSON字符串
            
        Returns:
            {class_name}: 配置对象
        """
        data = json.loads(json_str)
        return cls.from_dict(data)'''
    
    def _generate_to_json_method(self) -> str:
        """
        生成 to_json 方法
        
        Returns:
            str: to_json 方法代码
        """
        return '''    def to_json(self) -> str:
        """
        转换为JSON字符串
        
        Returns:
            str: JSON字符串
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)'''
    
    def generate_client_classes(self, sheet_infos: List[ExcelSheetInfo]) -> List[str]:
        """
        生成客户端类文件
        
        Args:
            sheet_infos: Excel表格信息列表
            
        Returns:
            List[str]: 生成的客户端类文件路径列表
        """
        return self.generate_class_files(sheet_infos, 'c')
    
    def generate_server_classes(self, sheet_infos: List[ExcelSheetInfo]) -> List[str]:
        """
        生成服务端类文件
        
        Args:
            sheet_infos: Excel表格信息列表
            
        Returns:
            List[str]: 生成的服务端类文件路径列表
        """
        return self.generate_class_files(sheet_infos, 's')
    
    def generate_all_classes(self, sheet_infos: List[ExcelSheetInfo]) -> Dict[str, List[str]]:
        """
        生成所有类文件（客户端、服务端、全部）
        
        Args:
            sheet_infos: Excel表格信息列表
            
        Returns:
            Dict[str, List[str]]: 生成的类文件路径字典
        """
        result = {
            'client': self.generate_client_classes(sheet_infos),
            'server': self.generate_server_classes(sheet_infos),
            'all': self.generate_class_files(sheet_infos, 'cs')
        }
        
        return result
    
    def validate_class_file(self, file_path: str) -> bool:
        """
        验证生成的类文件语法
        
        Args:
            file_path: 类文件路径
            
        Returns:
            bool: 是否语法正确
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # 编译代码检查语法
            compile(code, file_path, 'exec')
            return True
            
        except SyntaxError as e:
            self.logger.error(f"类文件语法错误: {file_path}, 错误: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"验证类文件失败: {file_path}, 错误: {str(e)}")
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