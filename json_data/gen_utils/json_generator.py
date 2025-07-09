"""
JSON生成器模块

负责根据Excel解析结果生成JSON配置文件。
支持客户端/服务端字段过滤，生成对应的JSON文件。
"""

import os
import json
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

from common.logger import logger
from .excel_parser import ExcelSheetInfo, ExcelFieldInfo


class JSONGenerator:
    """
    JSON生成器
    
    负责根据Excel解析结果生成JSON配置文件
    """
    
    def __init__(self, output_dir: str = "json_data/json", indent: int = 2):
        """
        初始化JSON生成器
        
        Args:
            output_dir: 输出目录
            indent: JSON格式化缩进
        """
        self.output_dir = output_dir
        self.indent = indent
        self.logger = logger
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_json_files(self, sheet_infos: List[ExcelSheetInfo], 
                          usage: str = 'cs') -> List[str]:
        """
        生成JSON配置文件
        
        Args:
            sheet_infos: Excel表格信息列表
            usage: 使用端标记 ('c', 's', 'cs')
            
        Returns:
            List[str]: 生成的JSON文件路径列表
        """
        generated_files = []
        
        try:
            self.logger.info(f"开始生成JSON配置文件，使用端: {usage}")
            
            for sheet_info in sheet_infos:
                try:
                    file_path = self._generate_single_json(sheet_info, usage)
                    generated_files.append(file_path)
                    self.logger.info(f"生成JSON文件: {file_path}")
                except Exception as e:
                    self.logger.error(f"生成JSON文件失败: {sheet_info.sheet_name}, 错误: {str(e)}")
                    continue
            
            self.logger.info(f"JSON文件生成完成，共生成{len(generated_files)}个文件")
            return generated_files
            
        except Exception as e:
            self.logger.error(f"生成JSON文件失败, 错误: {str(e)}")
            raise
    
    def _generate_single_json(self, sheet_info: ExcelSheetInfo, usage: str) -> str:
        """
        生成单个JSON文件
        
        Args:
            sheet_info: Excel表格信息
            usage: 使用端标记
            
        Returns:
            str: 生成的JSON文件路径
        """
        # 过滤字段
        filtered_fields = self._filter_fields_by_usage(sheet_info.fields, usage)
        
        # 转换数据
        json_data = self._convert_to_json_data(sheet_info, filtered_fields)
        
        # 生成文件路径
        file_name = f"{sheet_info.sheet_name}.json"
        if usage != 'cs':
            file_name = f"{sheet_info.sheet_name}_{usage}.json"
        
        file_path = os.path.join(self.output_dir, file_name)
        
        # 写入JSON文件
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=self.indent)
        
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
    
    def _convert_to_json_data(self, sheet_info: ExcelSheetInfo, 
                             fields: List[ExcelFieldInfo]) -> Dict[str, Any]:
        """
        转换为JSON数据格式
        
        Args:
            sheet_info: Excel表格信息
            fields: 过滤后的字段列表
            
        Returns:
            Dict[str, Any]: JSON数据
        """
        # 构建JSON数据结构
        json_data = {
            "_metadata": {
                "sheet_name": sheet_info.sheet_name,
                "file_path": sheet_info.file_path,
                "generated_at": datetime.now().isoformat(),
                "generator": "knight_server.json_data.gen_utils.JSONGenerator",
                "version": "1.0.0"
            },
            "_schema": {
                "fields": [
                    {
                        "name": field.name,
                        "type": field.type,
                        "comment": field.comment,
                        "usage": field.usage
                    }
                    for field in fields
                ]
            },
            "data": []
        }
        
        # 转换数据行
        for row in sheet_info.data_rows:
            row_data = {}
            for field in fields:
                if field.column_index < len(row):
                    value = row[field.column_index]
                    converted_value = self._convert_data_type(value, field.type)
                    row_data[field.name] = converted_value
                else:
                    row_data[field.name] = None
            
            json_data["data"].append(row_data)
        
        return json_data
    
    def _convert_data_type(self, value: Any, data_type: str) -> Any:
        """
        根据数据类型转换值
        
        Args:
            value: 原始值
            data_type: 数据类型
            
        Returns:
            Any: 转换后的值
        """
        if value is None or value == '':
            return None
        
        try:
            if data_type == 'int':
                return int(value)
            elif data_type == 'float':
                return float(value)
            elif data_type == 'bool':
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes', 'on')
                return bool(value)
            elif data_type == 'str':
                return str(value)
            elif data_type == 'list':
                if isinstance(value, str):
                    return json.loads(value)
                return value if isinstance(value, list) else [value]
            elif data_type == 'dict':
                if isinstance(value, str):
                    return json.loads(value)
                return value if isinstance(value, dict) else {}
            else:
                return str(value)
        except (ValueError, json.JSONDecodeError) as e:
            self.logger.warning(f"数据类型转换失败: {value} -> {data_type}, 错误: {str(e)}")
            return value
    
    def generate_client_json(self, sheet_infos: List[ExcelSheetInfo]) -> List[str]:
        """
        生成客户端JSON文件
        
        Args:
            sheet_infos: Excel表格信息列表
            
        Returns:
            List[str]: 生成的客户端JSON文件路径列表
        """
        return self.generate_json_files(sheet_infos, 'c')
    
    def generate_server_json(self, sheet_infos: List[ExcelSheetInfo]) -> List[str]:
        """
        生成服务端JSON文件
        
        Args:
            sheet_infos: Excel表格信息列表
            
        Returns:
            List[str]: 生成的服务端JSON文件路径列表
        """
        return self.generate_json_files(sheet_infos, 's')
    
    def generate_all_json(self, sheet_infos: List[ExcelSheetInfo]) -> Dict[str, List[str]]:
        """
        生成所有JSON文件（客户端、服务端、全部）
        
        Args:
            sheet_infos: Excel表格信息列表
            
        Returns:
            Dict[str, List[str]]: 生成的JSON文件路径字典
        """
        result = {
            'client': self.generate_client_json(sheet_infos),
            'server': self.generate_server_json(sheet_infos),
            'all': self.generate_json_files(sheet_infos, 'cs')
        }
        
        return result
    
    def validate_json_file(self, file_path: str) -> bool:
        """
        验证JSON文件格式
        
        Args:
            file_path: JSON文件路径
            
        Returns:
            bool: 是否有效
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查必要的字段
            required_fields = ['_metadata', '_schema', 'data']
            for field in required_fields:
                if field not in data:
                    self.logger.error(f"JSON文件缺少必要字段: {field}")
                    return False
            
            # 检查元数据
            metadata = data['_metadata']
            required_metadata = ['sheet_name', 'generated_at', 'generator', 'version']
            for field in required_metadata:
                if field not in metadata:
                    self.logger.error(f"JSON文件元数据缺少必要字段: {field}")
                    return False
            
            # 检查schema
            schema = data['_schema']
            if 'fields' not in schema:
                self.logger.error("JSON文件schema缺少fields字段")
                return False
            
            # 检查数据
            if not isinstance(data['data'], list):
                self.logger.error("JSON文件data字段必须是列表")
                return False
            
            return True
            
        except (json.JSONDecodeError, FileNotFoundError) as e:
            self.logger.error(f"验证JSON文件失败: {file_path}, 错误: {str(e)}")
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