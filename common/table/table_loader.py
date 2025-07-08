"""
配置表加载器模块

负责从JSON文件加载配置数据，并转换为对应的配置对象。
"""

import json
import os
import glob
from typing import Dict, Any, List, Type, Optional, Union
from pathlib import Path
from dataclasses import dataclass

from common.logger import logger

from .types import BaseConfig, LoaderConfig, ConfigMetadata, ConfigType, ConfigRegistry, ConfigId
from .exceptions import ConfigLoadError, ConfigValidationError, ConfigTypeError, SchemaValidationError


@dataclass
class LoadResult:
    """加载结果"""
    success: bool
    config_count: int
    errors: List[str]
    metadata: Optional[ConfigMetadata] = None


class SimpleJSONValidator:
    """简单的JSON验证器"""
    
    @staticmethod
    def validate_structure(data: Any, schema: Dict[str, Any]) -> bool:
        """
        简单的结构验证
        
        Args:
            data: 要验证的数据
            schema: 模式定义
            
        Returns:
            bool: 是否符合模式
        """
        if not isinstance(data, dict):
            return False
        
        required = schema.get('required', [])
        properties = schema.get('properties', {})
        
        # 检查必需字段
        for field in required:
            if field not in data:
                return False
        
        # 简单的类型检查
        for field, field_schema in properties.items():
            if field in data:
                expected_type = field_schema.get('type')
                value = data[field]
                
                if expected_type == 'string' and not isinstance(value, str):
                    return False
                elif expected_type == 'number' and not isinstance(value, (int, float)):
                    return False
                elif expected_type == 'boolean' and not isinstance(value, bool):
                    return False
        
        return True


class ConfigLoader:
    """
    配置加载器
    
    负责从JSON文件加载配置数据并转换为配置对象
    """
    
    def __init__(self, config: LoaderConfig):
        """
        初始化配置加载器
        
        Args:
            config: 加载器配置
        """
        self.config = config
        self._schema_cache: Dict[str, Dict[str, Any]] = {}
        self._setup_schema_cache()
    
    def _setup_schema_cache(self) -> None:
        """设置模式缓存"""
        # 定义基础配置模式
        base_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "number"},
                "name": {"type": "string"}
            },
            "required": ["id", "name"]
        }
        
        # 物品配置模式
        item_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "number"},
                "name": {"type": "string"},
                "type": {"type": "number"},
                "quality": {"type": "number"},
                "level": {"type": "number"},
                "price": {"type": "number"},
                "stack_limit": {"type": "number"},
                "description": {"type": "string"}
            },
            "required": ["id", "name", "type"]
        }
        
        # 技能配置模式
        skill_schema = {
            "type": "object",
            "properties": {
                "id": {"type": "number"},
                "name": {"type": "string"},
                "type": {"type": "number"},
                "level": {"type": "number"},
                "damage": {"type": "number"},
                "cost": {"type": "number"},
                "cooldown": {"type": "number"},
                "description": {"type": "string"}
            },
            "required": ["id", "name", "type"]
        }
        
        self._schema_cache = {
            "base": base_schema,
            "item": item_schema,
            "skill": skill_schema
        }
    
    def load_config_file(self, file_path: str) -> LoadResult:
        """
        加载配置文件
        
        Args:
            file_path: 配置文件路径
            
        Returns:
            LoadResult: 加载结果
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                raise ConfigLoadError(file_path, "文件不存在")
            
            # 读取文件内容
            with open(file_path, 'r', encoding=self.config.encoding) as f:
                try:
                    raw_data = json.load(f)
                except json.JSONDecodeError as e:
                    raise ConfigLoadError(file_path, f"JSON解析错误: {e}")
            
            # 确定配置类型
            config_type = self._detect_config_type(file_path, raw_data)
            
            # 验证模式
            if self.config.validate_schema:
                self._validate_schema(file_path, raw_data, config_type)
            
            # 创建元数据
            metadata = self._create_metadata(file_path, config_type)
            
            # 加载配置数据
            configs = self._load_configs(raw_data, config_type)
            
            logger.info(f"成功加载配置文件: {file_path}, 配置数量: {len(configs)}")
            
            return LoadResult(
                success=True,
                config_count=len(configs),
                errors=[],
                metadata=metadata
            )
            
        except Exception as e:
            error_msg = f"加载配置文件失败: {file_path} - {str(e)}"
            logger.error(error_msg)
            return LoadResult(
                success=False,
                config_count=0,
                errors=[error_msg]
            )
    
    def load_config_directory(self, directory: str = None) -> Dict[str, LoadResult]:
        """
        加载配置目录
        
        Args:
            directory: 配置目录路径，默认使用配置中的目录
            
        Returns:
            Dict[str, LoadResult]: 文件名到加载结果的映射
        """
        if directory is None:
            directory = self.config.config_dir
        
        results = {}
        
        try:
            # 获取所有配置文件
            pattern = os.path.join(directory, self.config.file_pattern)
            config_files = glob.glob(pattern)
            
            if not config_files:
                logger.warning(f"在目录 {directory} 中未找到配置文件")
                return results
            
            # 加载每个配置文件
            for file_path in config_files:
                filename = os.path.basename(file_path)
                results[filename] = self.load_config_file(file_path)
            
            logger.info(f"完成配置目录加载: {directory}, 文件数量: {len(config_files)}")
            
        except Exception as e:
            error_msg = f"加载配置目录失败: {directory} - {str(e)}"
            logger.error(error_msg)
            results["_error"] = LoadResult(
                success=False,
                config_count=0,
                errors=[error_msg]
            )
        
        return results
    
    def _detect_config_type(self, file_path: str, data: Any) -> str:
        """
        检测配置类型
        
        Args:
            file_path: 文件路径
            data: 配置数据
            
        Returns:
            str: 配置类型
        """
        # 从文件名推断类型
        filename = os.path.basename(file_path).lower()
        
        if "item" in filename:
            return "item"
        elif "skill" in filename:
            return "skill"
        elif "monster" in filename:
            return "monster"
        elif "level" in filename:
            return "level"
        elif "system" in filename:
            return "system"
        
        # 从数据结构推断类型
        if isinstance(data, list) and len(data) > 0:
            first_item = data[0]
            if isinstance(first_item, dict):
                # 检查字段来推断类型
                if "type" in first_item and "price" in first_item:
                    return "item"
                elif "damage" in first_item and "cooldown" in first_item:
                    return "skill"
        
        # 默认返回基础类型
        return "base"
    
    def _validate_schema(self, file_path: str, data: Any, config_type: str) -> None:
        """
        验证配置模式
        
        Args:
            file_path: 文件路径
            data: 配置数据
            config_type: 配置类型
        """
        if not self.config.validate_schema:
            return
        
        schema = self._schema_cache.get(config_type)
        if schema is None:
            schema = self._schema_cache["base"]
        
        errors = []
        
        # 验证数据结构
        if isinstance(data, list):
            for i, item in enumerate(data):
                if not SimpleJSONValidator.validate_structure(item, schema):
                    errors.append(f"第{i+1}项数据验证失败")
        else:
            if not SimpleJSONValidator.validate_structure(data, schema):
                errors.append("数据结构验证失败")
        
        if errors:
            raise SchemaValidationError(file_path, errors)
    
    def _create_metadata(self, file_path: str, config_type: str) -> ConfigMetadata:
        """
        创建配置元数据
        
        Args:
            file_path: 文件路径
            config_type: 配置类型
            
        Returns:
            ConfigMetadata: 配置元数据
        """
        stat = os.stat(file_path)
        
        return ConfigMetadata(
            file_path=file_path,
            config_type=ConfigType(config_type) if config_type in [e.value for e in ConfigType] else ConfigType.SYSTEM,
            last_modified=stat.st_mtime,
            version="1.0.0"
        )
    
    def _load_configs(self, data: Any, config_type: str) -> List[BaseConfig]:
        """
        加载配置对象
        
        Args:
            data: 配置数据
            config_type: 配置类型
            
        Returns:
            List[BaseConfig]: 配置对象列表
        """
        # 获取配置类
        config_class = ConfigRegistry.get(config_type)
        if config_class is None:
            raise ConfigTypeError(config_type)
        
        configs = []
        
        try:
            if isinstance(data, list):
                # 数组格式的配置
                for item_data in data:
                    if isinstance(item_data, dict):
                        config = config_class(**item_data)
                        configs.append(config)
            elif isinstance(data, dict):
                # 对象格式的配置
                config = config_class(**data)
                configs.append(config)
            else:
                raise ConfigLoadError("unknown", f"不支持的数据格式: {type(data)}")
            
        except Exception as e:
            raise ConfigLoadError("create_config", f"创建配置对象失败: {str(e)}")
        
        return configs
    
    def reload_config_file(self, file_path: str) -> LoadResult:
        """
        重新加载配置文件
        
        Args:
            file_path: 配置文件路径
            
        Returns:
            LoadResult: 加载结果
        """
        logger.info(f"重新加载配置文件: {file_path}")
        return self.load_config_file(file_path)
    
    def get_config_files(self, directory: str = None) -> List[str]:
        """
        获取配置文件列表
        
        Args:
            directory: 配置目录路径
            
        Returns:
            List[str]: 配置文件路径列表
        """
        if directory is None:
            directory = self.config.config_dir
        
        pattern = os.path.join(directory, self.config.file_pattern)
        return glob.glob(pattern)
    
    def validate_config_file(self, file_path: str) -> List[str]:
        """
        验证配置文件
        
        Args:
            file_path: 配置文件路径
            
        Returns:
            List[str]: 验证错误列表
        """
        errors = []
        
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                errors.append(f"文件不存在: {file_path}")
                return errors
            
            # 读取文件内容
            with open(file_path, 'r', encoding=self.config.encoding) as f:
                try:
                    raw_data = json.load(f)
                except json.JSONDecodeError as e:
                    errors.append(f"JSON解析错误: {e}")
                    return errors
            
            # 检测配置类型
            config_type = self._detect_config_type(file_path, raw_data)
            
            # 验证模式
            try:
                self._validate_schema(file_path, raw_data, config_type)
            except SchemaValidationError as e:
                errors.extend(e.schema_errors)
            
            # 验证配置对象创建
            try:
                self._load_configs(raw_data, config_type)
            except Exception as e:
                errors.append(f"配置对象创建失败: {str(e)}")
            
        except Exception as e:
            errors.append(f"验证过程异常: {str(e)}")
        
        return errors
    
    def get_supported_config_types(self) -> List[str]:
        """
        获取支持的配置类型列表
        
        Returns:
            List[str]: 配置类型列表
        """
        return ConfigRegistry.list_configs()
    
    def add_config_type(self, config_type: str, config_class: Type[BaseConfig], schema: Dict[str, Any] = None) -> None:
        """
        添加配置类型
        
        Args:
            config_type: 配置类型名称
            config_class: 配置类
            schema: 配置模式（可选）
        """
        # 注册配置类
        ConfigRegistry.register(config_type, config_class)
        
        # 添加模式
        if schema:
            self._schema_cache[config_type] = schema
        
        logger.info(f"添加配置类型: {config_type}")
    
    def remove_config_type(self, config_type: str) -> None:
        """
        移除配置类型
        
        Args:
            config_type: 配置类型名称
        """
        # 从注册表中移除
        if config_type in ConfigRegistry._registry:
            del ConfigRegistry._registry[config_type]
        
        # 从模式缓存中移除
        if config_type in self._schema_cache:
            del self._schema_cache[config_type]
        
        logger.info(f"移除配置类型: {config_type}")