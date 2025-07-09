"""
配置加载器
负责加载和管理YAML配置文件
"""
import os
import yaml
from typing import Any, Dict, Optional
from pathlib import Path
from loguru import logger


class ConfigLoader:
    """
    配置加载器
    支持YAML配置文件加载和环境变量覆盖
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器
        
        Args:
            config_path: 配置文件路径，默认为 setting/config.yml
        """
        self._config: Dict[str, Any] = {}
        self._config_path = config_path or self._get_default_config_path()
        self._load_config()
        self._apply_env_overrides()
    
    def _get_default_config_path(self) -> str:
        """获取默认配置文件路径"""
        return os.path.join(
            os.path.dirname(__file__),
            'config.yml'
        )
    
    def _load_config(self):
        """加载配置文件"""
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(f"配置文件不存在: {self._config_path}")
        
        with open(self._config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
    
    def _apply_env_overrides(self):
        """应用环境变量覆盖"""
        # 环境变量格式: GAME_<key>
        # 例如: GAME_DATABASE_MONGODB_HOST -> database.mongodb.host
        #      GAME_COMMON_LOG_LEVEL -> common.log_level
        for key, value in os.environ.items():
            if key.startswith('GAME_'):
                self._set_config_from_env(key, value)
    
    def _set_config_from_env(self, env_key: str, env_value: str):
        """从环境变量设置配置值"""
        # 将环境变量转换为配置路径
        # GAME_DATABASE_MONGODB_HOST -> database.mongodb.host
        # GAME_COMMON_LOG_LEVEL -> common.log_level
        parts = env_key[5:].lower().split('_')
        
        # 尝试直接设置，如果存在则覆盖
        self._set_nested_config(parts, env_value)
    
    def _set_nested_config(self, parts: list, value: str):
        """设置嵌套配置值"""
        parsed_value = self._parse_env_value(value)
        
        # 尝试多种可能的路径组合
        # 例如：['common', 'log', 'level'] 可能对应 common.log_level 或 common.log.level
        for i in range(len(parts)):
            # 尝试将某些部分用下划线连接
            test_parts = parts[:i] + ['_'.join(parts[i:i+2])] + parts[i+2:] if i < len(parts) - 1 else parts
            if self._try_set_config_path(test_parts, parsed_value):
                return
        
        # 如果上述尝试都失败，使用标准的嵌套结构
        current = self._config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = parsed_value
    
    def _try_set_config_path(self, parts: list, value):
        """尝试设置配置路径"""
        current = self._config
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                return False
            current = current[part]
        
        # 检查最后一个键是否存在
        if parts[-1] in current:
            current[parts[-1]] = value
            return True
        return False
    
    def _parse_env_value(self, value: str) -> Any:
        """解析环境变量值的类型"""
        # 尝试转换为布尔值
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        
        # 尝试转换为数字
        try:
            if '.' in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
        
        # 返回字符串
        return value
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        支持点号分隔的键路径，如 'database.mongodb.host'
        支持数组索引，如 'services.gate.instances.0.port'
        
        Args:
            key: 配置键路径
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            elif isinstance(value, list) and k.isdigit():
                # 处理数组索引
                index = int(k)
                if 0 <= index < len(value):
                    value = value[index]
                else:
                    return default
            else:
                return default
        
        return value
    
    def get_service_config(self, service_name: str) -> Dict[str, Any]:
        """
        获取服务配置
        
        Args:
            service_name: 服务名称
            
        Returns:
            服务配置字典
        """
        return self.get(f'services.{service_name}', {})
    
    def get_service_instances(self, service_name: str) -> list:
        """
        获取服务实例配置列表
        
        Args:
            service_name: 服务名称
            
        Returns:
            实例配置列表
        """
        return self.get(f'services.{service_name}.instances', [])
    
    def get_database_config(self, db_type: str) -> Dict[str, Any]:
        """
        获取数据库配置
        
        Args:
            db_type: 数据库类型 (mongodb/redis)
            
        Returns:
            数据库配置字典
        """
        return self.get(f'database.{db_type}', {})
    
    def reload(self):
        """重新加载配置文件"""
        self._load_config()
        self._apply_env_overrides()
    
    def __getattr__(self, name: str) -> Any:
        """支持通过属性访问配置"""
        return self._config.get(name)
    
    def __getitem__(self, key: str) -> Any:
        """支持通过索引访问配置"""
        return self.get(key)