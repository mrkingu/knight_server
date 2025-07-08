"""
注册中心工厂

该模块根据配置创建对应的注册中心适配器，支持多注册中心配置，
实现单例模式管理。
"""

from typing import Dict, Any, Type, Optional, List
try:
    from loguru import logger
except ImportError:
    from ..logger.mock_logger import logger

from ..utils.singleton import async_singleton
from .base_adapter import BaseRegistryAdapter
from .etcd_adapter import EtcdAdapter
from .exceptions import RegistryConfigError


# 延迟导入，避免循环依赖
def _get_consul_adapter():
    """延迟导入 ConsulAdapter"""
    try:
        from .consul_adapter import ConsulAdapter
        return ConsulAdapter
    except ImportError:
        return None


@async_singleton
class RegistryFactory:
    """
    注册中心工厂类
    
    根据配置创建和管理注册中心适配器实例，支持多种注册中心类型，
    实现单例模式确保全局唯一性。
    """
    
    def __init__(self):
        """初始化注册中心工厂"""
        self._adapters: Dict[str, BaseRegistryAdapter] = {}
        self._adapter_types: Dict[str, Type[BaseRegistryAdapter]] = {}
        
        # 注册默认适配器类型
        self._register_default_adapters()
    
    def _register_default_adapters(self):
        """注册默认的适配器类型"""
        # 注册 etcd 适配器
        self._adapter_types["etcd"] = EtcdAdapter
        
        # 注册 consul 适配器（如果可用）
        ConsulAdapter = _get_consul_adapter()
        if ConsulAdapter:
            self._adapter_types["consul"] = ConsulAdapter
        
        logger.debug(f"注册默认适配器类型: {list(self._adapter_types.keys())}")
    
    def register_adapter_type(self, adapter_type: str, adapter_class: Type[BaseRegistryAdapter]) -> None:
        """
        注册自定义适配器类型
        
        Args:
            adapter_type: 适配器类型名称
            adapter_class: 适配器类
        """
        self._adapter_types[adapter_type] = adapter_class
        logger.info(f"注册自定义适配器类型: {adapter_type}")
    
    def create_adapter(self, adapter_type: str, config: Dict[str, Any], name: Optional[str] = None) -> BaseRegistryAdapter:
        """
        创建注册中心适配器
        
        Args:
            adapter_type: 适配器类型 (etcd, consul, etc.)
            config: 适配器配置
            name: 适配器实例名称，用于多实例管理
            
        Returns:
            BaseRegistryAdapter: 适配器实例
            
        Raises:
            RegistryConfigError: 配置错误或不支持的适配器类型
        """
        if adapter_type not in self._adapter_types:
            available_types = list(self._adapter_types.keys())
            raise RegistryConfigError(
                f"不支持的注册中心类型: {adapter_type}",
                config_key="adapter_type",
                config_value=adapter_type
            )
        
        try:
            adapter_class = self._adapter_types[adapter_type]
            adapter = adapter_class(config)
            
            # 如果指定了名称，缓存适配器实例
            if name:
                self._adapters[name] = adapter
                logger.info(f"创建注册中心适配器: {name} ({adapter_type})")
            else:
                logger.info(f"创建注册中心适配器: {adapter_type}")
            
            return adapter
            
        except Exception as e:
            logger.error(f"创建注册中心适配器失败: {adapter_type} - {e}")
            raise RegistryConfigError(
                f"创建注册中心适配器失败: {e}",
                config_key="adapter_type",
                config_value=adapter_type,
                cause=e
            )
    
    def get_adapter(self, name: str) -> Optional[BaseRegistryAdapter]:
        """
        获取缓存的适配器实例
        
        Args:
            name: 适配器实例名称
            
        Returns:
            Optional[BaseRegistryAdapter]: 适配器实例
        """
        return self._adapters.get(name)
    
    def create_from_config(self, config: Dict[str, Any]) -> Dict[str, BaseRegistryAdapter]:
        """
        从配置创建多个适配器
        
        Args:
            config: 完整的注册中心配置
            
        Returns:
            Dict[str, BaseRegistryAdapter]: 适配器字典，key为适配器名称
            
        示例配置:
        {
            "default_type": "etcd",
            "adapters": {
                "primary": {
                    "type": "etcd",
                    "config": {
                        "endpoints": ["http://localhost:2379"],
                        "timeout": 5
                    }
                },
                "backup": {
                    "type": "consul", 
                    "config": {
                        "host": "localhost",
                        "port": 8500
                    }
                }
            }
        }
        """
        if "adapters" not in config:
            # 简单配置模式，只有一个适配器
            adapter_type = config.get("type", config.get("default_type", "etcd"))
            adapter_config = config.get("config", config)
            
            adapter = self.create_adapter(adapter_type, adapter_config, "default")
            return {"default": adapter}
        
        # 多适配器配置模式
        adapters = {}
        
        for name, adapter_cfg in config["adapters"].items():
            adapter_type = adapter_cfg.get("type")
            if not adapter_type:
                raise RegistryConfigError(
                    f"适配器 {name} 缺少类型配置",
                    config_key=f"adapters.{name}.type"
                )
            
            adapter_config = adapter_cfg.get("config", {})
            adapter = self.create_adapter(adapter_type, adapter_config, name)
            adapters[name] = adapter
        
        logger.info(f"从配置创建了 {len(adapters)} 个适配器: {list(adapters.keys())}")
        return adapters
    
    def get_supported_types(self) -> List[str]:
        """
        获取支持的适配器类型列表
        
        Returns:
            List[str]: 支持的适配器类型
        """
        return list(self._adapter_types.keys())
    
    async def close_all_adapters(self) -> None:
        """关闭所有缓存的适配器"""
        logger.info("开始关闭所有注册中心适配器...")
        
        for name, adapter in self._adapters.items():
            try:
                await adapter.disconnect()
                logger.info(f"关闭适配器: {name}")
            except Exception as e:
                logger.error(f"关闭适配器失败: {name} - {e}")
        
        self._adapters.clear()
        logger.info("所有注册中心适配器已关闭")
    
    def clear_cache(self) -> None:
        """清空适配器缓存"""
        self._adapters.clear()
        logger.debug("清空适配器缓存")


# 便捷函数

def create_registry_adapter(
    adapter_type: str, 
    config: Dict[str, Any], 
    name: Optional[str] = None
) -> BaseRegistryAdapter:
    """
    创建注册中心适配器的便捷函数
    
    Args:
        adapter_type: 适配器类型
        config: 配置
        name: 适配器名称
        
    Returns:
        BaseRegistryAdapter: 适配器实例
    """
    factory = RegistryFactory.get_instance()
    return factory.create_adapter(adapter_type, config, name)


def create_registry_adapters_from_config(config: Dict[str, Any]) -> Dict[str, BaseRegistryAdapter]:
    """
    从配置创建注册中心适配器的便捷函数
    
    Args:
        config: 完整配置
        
    Returns:
        Dict[str, BaseRegistryAdapter]: 适配器字典
    """
    factory = RegistryFactory.get_instance()
    return factory.create_from_config(config)


def get_registry_adapter(name: str) -> Optional[BaseRegistryAdapter]:
    """
    获取缓存的注册中心适配器的便捷函数
    
    Args:
        name: 适配器名称
        
    Returns:
        Optional[BaseRegistryAdapter]: 适配器实例
    """
    factory = RegistryFactory.get_instance()
    return factory.get_adapter(name)


# 配置验证器

def validate_registry_config(config: Dict[str, Any]) -> None:
    """
    验证注册中心配置
    
    Args:
        config: 注册中心配置
        
    Raises:
        RegistryConfigError: 配置验证失败
    """
    if not isinstance(config, dict):
        raise RegistryConfigError("注册中心配置必须是字典类型")
    
    if "adapters" in config:
        # 多适配器配置验证
        adapters_config = config["adapters"]
        if not isinstance(adapters_config, dict):
            raise RegistryConfigError("adapters 配置必须是字典类型")
        
        if not adapters_config:
            raise RegistryConfigError("adapters 配置不能为空")
        
        factory = RegistryFactory.get_instance()
        supported_types = factory.get_supported_types()
        
        for name, adapter_cfg in adapters_config.items():
            if not isinstance(adapter_cfg, dict):
                raise RegistryConfigError(f"适配器 {name} 配置必须是字典类型")
            
            adapter_type = adapter_cfg.get("type")
            if not adapter_type:
                raise RegistryConfigError(f"适配器 {name} 缺少 type 配置")
            
            if adapter_type not in supported_types:
                raise RegistryConfigError(
                    f"适配器 {name} 类型 {adapter_type} 不受支持",
                    config_key=f"adapters.{name}.type",
                    config_value=adapter_type
                )
    
    else:
        # 单适配器配置验证
        adapter_type = config.get("type", config.get("default_type"))
        if not adapter_type:
            raise RegistryConfigError("缺少适配器类型配置 (type 或 default_type)")
        
        factory = RegistryFactory.get_instance()
        supported_types = factory.get_supported_types()
        
        if adapter_type not in supported_types:
            raise RegistryConfigError(
                f"适配器类型 {adapter_type} 不受支持",
                config_key="type",
                config_value=adapter_type
            )


# 配置模板生成器

def generate_etcd_config(
    endpoints: List[str] = None,
    timeout: int = 5,
    username: Optional[str] = None,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    生成 etcd 配置模板
    
    Args:
        endpoints: etcd 端点列表
        timeout: 连接超时时间
        username: 用户名
        password: 密码
        
    Returns:
        Dict[str, Any]: etcd 配置
    """
    if endpoints is None:
        endpoints = ["http://localhost:2379"]
    
    config = {
        "type": "etcd",
        "config": {
            "endpoints": endpoints,
            "timeout": timeout
        }
    }
    
    if username and password:
        config["config"]["username"] = username
        config["config"]["password"] = password
    
    return config


def generate_consul_config(
    host: str = "localhost",
    port: int = 8500,
    token: Optional[str] = None,
    scheme: str = "http"
) -> Dict[str, Any]:
    """
    生成 consul 配置模板
    
    Args:
        host: consul 主机
        port: consul 端口
        token: 访问令牌
        scheme: 协议方案
        
    Returns:
        Dict[str, Any]: consul 配置
    """
    config = {
        "type": "consul",
        "config": {
            "host": host,
            "port": port,
            "scheme": scheme
        }
    }
    
    if token:
        config["config"]["token"] = token
    
    return config


def generate_multi_adapter_config(
    primary_type: str = "etcd",
    backup_type: str = "consul",
    primary_config: Optional[Dict[str, Any]] = None,
    backup_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    生成多适配器配置模板
    
    Args:
        primary_type: 主适配器类型
        backup_type: 备用适配器类型
        primary_config: 主适配器配置
        backup_config: 备用适配器配置
        
    Returns:
        Dict[str, Any]: 多适配器配置
    """
    if primary_config is None:
        if primary_type == "etcd":
            primary_config = generate_etcd_config()["config"]
        elif primary_type == "consul":
            primary_config = generate_consul_config()["config"]
        else:
            primary_config = {}
    
    if backup_config is None:
        if backup_type == "etcd":
            backup_config = generate_etcd_config()["config"]
        elif backup_type == "consul":
            backup_config = generate_consul_config()["config"]
        else:
            backup_config = {}
    
    return {
        "adapters": {
            "primary": {
                "type": primary_type,
                "config": primary_config
            },
            "backup": {
                "type": backup_type,
                "config": backup_config
            }
        }
    }