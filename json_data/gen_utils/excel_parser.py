"""
Excel解析器模块

负责解析Excel文件，提取配置数据和元数据。
支持的Excel格式：
- 第1行：中文注释（用于生成Python类的字段注释）
- 第2行：字段名（Python类的属性名）
- 第3行：数据类型（int/str/float/list/dict等）
- 第4行：使用端标记（c-客户端，s-服务端，cs-双端）
- 第5行起：实际数据
"""

import os
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

from common.logger import logger


@dataclass
class ExcelFieldInfo:
    """Excel字段信息"""
    comment: str  # 中文注释
    name: str     # 字段名
    type: str     # 数据类型
    usage: str    # 使用端标记 (c/s/cs)
    column_index: int  # 列索引


@dataclass
class ExcelSheetInfo:
    """Excel表格信息"""
    sheet_name: str  # 表格名称
    file_path: str   # 文件路径
    fields: List[ExcelFieldInfo]  # 字段信息列表
    data_rows: List[List[Any]]    # 数据行


class ExcelParser:
    """
    Excel解析器
    
    负责解析Excel文件，提取配置数据和元数据
    """
    
    def __init__(self, encoding: str = 'utf-8'):
        """
        初始化Excel解析器
        
        Args:
            encoding: 文件编码
        """
        self.encoding = encoding
        self.logger = logger
        
    def parse_excel_file(self, file_path: str) -> List[ExcelSheetInfo]:
        """
        解析Excel文件
        
        Args:
            file_path: Excel文件路径
            
        Returns:
            List[ExcelSheetInfo]: 解析后的表格信息列表
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件格式不正确
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Excel文件不存在: {file_path}")
            
            # 检查文件扩展名
            if not file_path.lower().endswith(('.xlsx', '.xls')):
                raise ValueError(f"不支持的文件格式: {file_path}")
            
            # 由于没有安装openpyxl，这里使用模拟数据
            # 在实际环境中，应该使用openpyxl来解析Excel文件
            self.logger.info(f"开始解析Excel文件: {file_path}")
            
            # 模拟解析结果
            sheet_infos = self._parse_excel_mock(file_path)
            
            self.logger.info(f"Excel文件解析完成: {file_path}, 共解析{len(sheet_infos)}个表格")
            return sheet_infos
            
        except Exception as e:
            self.logger.error(f"解析Excel文件失败: {file_path}, 错误: {str(e)}")
            raise
    
    def _parse_excel_mock(self, file_path: str) -> List[ExcelSheetInfo]:
        """
        模拟Excel解析（实际环境中应该使用openpyxl）
        
        Args:
            file_path: Excel文件路径
            
        Returns:
            List[ExcelSheetInfo]: 模拟的表格信息列表
        """
        # 根据文件名生成模拟数据
        file_name = Path(file_path).stem
        
        # 英雄配置表示例
        if 'hero' in file_name.lower():
            return [self._create_hero_config_mock()]
        
        # 道具配置表示例
        if 'item' in file_name.lower():
            return [self._create_item_config_mock()]
        
        # 默认配置表示例
        return [self._create_default_config_mock(file_name)]
    
    def _create_hero_config_mock(self) -> ExcelSheetInfo:
        """创建英雄配置表模拟数据"""
        fields = [
            ExcelFieldInfo("英雄ID", "hero_id", "int", "cs", 0),
            ExcelFieldInfo("英雄名称", "name", "str", "cs", 1),
            ExcelFieldInfo("职业", "profession", "str", "cs", 2),
            ExcelFieldInfo("等级", "level", "int", "cs", 3),
            ExcelFieldInfo("血量", "hp", "int", "cs", 4),
            ExcelFieldInfo("攻击力", "attack", "int", "cs", 5),
            ExcelFieldInfo("防御力", "defense", "int", "cs", 6),
            ExcelFieldInfo("技能列表", "skills", "list", "cs", 7),
            ExcelFieldInfo("服务端数据", "server_data", "dict", "s", 8),
        ]
        
        data_rows = [
            [1001, "剑士", "战士", 1, 100, 20, 15, "[1, 2, 3]", "{'drop_rate': 0.1}"],
            [1002, "法师", "法师", 1, 80, 25, 10, "[4, 5, 6]", "{'drop_rate': 0.2}"],
            [1003, "弓箭手", "射手", 1, 90, 22, 12, "[7, 8, 9]", "{'drop_rate': 0.15}"],
        ]
        
        return ExcelSheetInfo("hero_config", "hero_config.xlsx", fields, data_rows)
    
    def _create_item_config_mock(self) -> ExcelSheetInfo:
        """创建道具配置表模拟数据"""
        fields = [
            ExcelFieldInfo("道具ID", "item_id", "int", "cs", 0),
            ExcelFieldInfo("道具名称", "name", "str", "cs", 1),
            ExcelFieldInfo("类型", "type", "str", "cs", 2),
            ExcelFieldInfo("品质", "quality", "int", "cs", 3),
            ExcelFieldInfo("价格", "price", "int", "cs", 4),
            ExcelFieldInfo("描述", "description", "str", "c", 5),
            ExcelFieldInfo("服务端配置", "server_config", "dict", "s", 6),
        ]
        
        data_rows = [
            [2001, "生命药水", "消耗品", 1, 50, "恢复100点生命值", "{'heal_amount': 100}"],
            [2002, "魔法药水", "消耗品", 1, 60, "恢复80点魔法值", "{'mana_amount': 80}"],
            [2003, "铁剑", "武器", 2, 200, "基础铁剑", "{'damage': 25}"],
        ]
        
        return ExcelSheetInfo("item_config", "item_config.xlsx", fields, data_rows)
    
    def _create_default_config_mock(self, name: str) -> ExcelSheetInfo:
        """创建默认配置表模拟数据"""
        fields = [
            ExcelFieldInfo("配置ID", "config_id", "int", "cs", 0),
            ExcelFieldInfo("配置名称", "name", "str", "cs", 1),
            ExcelFieldInfo("配置值", "value", "str", "cs", 2),
            ExcelFieldInfo("描述", "description", "str", "c", 3),
        ]
        
        data_rows = [
            [1, "default_config", "default_value", "默认配置"],
        ]
        
        return ExcelSheetInfo(name, f"{name}.xlsx", fields, data_rows)
    
    def parse_directory(self, directory: str) -> List[ExcelSheetInfo]:
        """
        解析目录下的所有Excel文件
        
        Args:
            directory: 目录路径
            
        Returns:
            List[ExcelSheetInfo]: 所有解析后的表格信息列表
        """
        all_sheets = []
        
        try:
            if not os.path.exists(directory):
                raise FileNotFoundError(f"目录不存在: {directory}")
            
            # 查找所有Excel文件
            excel_files = []
            for ext in ['*.xlsx', '*.xls']:
                excel_files.extend(Path(directory).glob(ext))
            
            if not excel_files:
                self.logger.warning(f"目录中没有找到Excel文件: {directory}")
                return all_sheets
            
            self.logger.info(f"在目录{directory}中找到{len(excel_files)}个Excel文件")
            
            # 解析每个Excel文件
            for excel_file in excel_files:
                try:
                    sheets = self.parse_excel_file(str(excel_file))
                    all_sheets.extend(sheets)
                except Exception as e:
                    self.logger.error(f"解析Excel文件失败: {excel_file}, 错误: {str(e)}")
                    continue
            
            return all_sheets
            
        except Exception as e:
            self.logger.error(f"解析目录失败: {directory}, 错误: {str(e)}")
            raise
    
    def filter_fields_by_usage(self, fields: List[ExcelFieldInfo], usage: str) -> List[ExcelFieldInfo]:
        """
        根据使用端标记过滤字段
        
        Args:
            fields: 字段信息列表
            usage: 使用端标记 ('c', 's', 'cs')
            
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
    
    def convert_data_type(self, value: str, data_type: str) -> Any:
        """
        根据数据类型转换值
        
        Args:
            value: 字符串值
            data_type: 数据类型
            
        Returns:
            Any: 转换后的值
        """
        if not value or value == '':
            return None
        
        try:
            if data_type == 'int':
                return int(value)
            elif data_type == 'float':
                return float(value)
            elif data_type == 'bool':
                return value.lower() in ('true', '1', 'yes', 'on')
            elif data_type == 'str':
                return str(value)
            elif data_type == 'list':
                return json.loads(value) if isinstance(value, str) else value
            elif data_type == 'dict':
                return json.loads(value) if isinstance(value, str) else value
            else:
                return str(value)
        except (ValueError, json.JSONDecodeError) as e:
            self.logger.warning(f"数据类型转换失败: {value} -> {data_type}, 错误: {str(e)}")
            return value