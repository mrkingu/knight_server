"""
gRPC配置集成模块

集成框架的配置系统，提供gRPC相关的配置管理。
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

from ..logger import logger
from .connection import ConnectionConfig
from .grpc_pool import PoolConfig
from .grpc_client import ClientConfig, RetryConfig
from .grpc_server import ServerConfig, RateLimitConfig
from .load_balancer import LoadBalanceStrategy
from .exceptions import GrpcConfigurationError


@dataclass
class GrpcConfig:
    """gRPC全局配置"""
    
    # 默认连接配置
    default_connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    
    # 默认池配置
    default_pool: PoolConfig = field(default_factory=PoolConfig)
    
    # 默认客户端配置
    default_client: ClientConfig = field(default_factory=ClientConfig)
    
    # 默认服务器配置
    default_server: ServerConfig = field(default_factory=ServerConfig)
    
    # 服务发现配置
    registry_endpoints: List[str] = field(default_factory=list)
    registry_namespace: str = "default"
    
    # 监控配置
    metrics_enabled: bool = True
    metrics_port: int = 9090
    
    # 日志配置
    log_level: str = "INFO"
    log_grpc_calls: bool = True
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'GrpcConfig':
        """
        从字典创建配置
        
        Args:
            config_dict: 配置字典
            
        Returns:
            GrpcConfig: 配置实例
        """
        try:
            # 解析连接配置
            connection_config = ConnectionConfig()
            if 'connection' in config_dict:
                conn_dict = config_dict['connection']
                for key, value in conn_dict.items():
                    if hasattr(connection_config, key):
                        setattr(connection_config, key, value)
            
            # 解析池配置
            pool_config = PoolConfig(connection_config=connection_config)
            if 'pool' in config_dict:
                pool_dict = config_dict['pool']
                for key, value in pool_dict.items():
                    if key != 'connection_config' and hasattr(pool_config, key):
                        setattr(pool_config, key, value)
            
            # 解析重试配置
            retry_config = RetryConfig()
            if 'retry' in config_dict:
                retry_dict = config_dict['retry']
                for key, value in retry_dict.items():
                    if hasattr(retry_config, key):
                        setattr(retry_config, key, value)
            
            # 解析客户端配置
            client_config = ClientConfig(
                connection_config=connection_config,
                pool_config=pool_config,
                retry_config=retry_config
            )
            if 'client' in config_dict:
                client_dict = config_dict['client']
                for key, value in client_dict.items():
                    if key == 'load_balance_strategy':
                        if isinstance(value, str):
                            value = LoadBalanceStrategy(value)
                    if key not in ['connection_config', 'pool_config', 'retry_config'] and hasattr(client_config, key):
                        setattr(client_config, key, value)
            
            # 解析限流配置
            rate_limit_config = RateLimitConfig()
            if 'rate_limit' in config_dict:
                rate_limit_dict = config_dict['rate_limit']
                for key, value in rate_limit_dict.items():
                    if hasattr(rate_limit_config, key):
                        setattr(rate_limit_config, key, value)
            
            # 解析服务器配置
            server_config = ServerConfig(rate_limit_config=rate_limit_config)
            if 'server' in config_dict:
                server_dict = config_dict['server']
                for key, value in server_dict.items():
                    if key != 'rate_limit_config' and hasattr(server_config, key):
                        setattr(server_config, key, value)
            
            # 创建gRPC配置
            grpc_config = cls(
                default_connection=connection_config,
                default_pool=pool_config,
                default_client=client_config,
                default_server=server_config
            )
            
            # 设置其他配置
            for key, value in config_dict.items():
                if key not in ['connection', 'pool', 'retry', 'client', 'server', 'rate_limit'] and hasattr(grpc_config, key):
                    setattr(grpc_config, key, value)
            
            return grpc_config
            
        except Exception as e:
            raise GrpcConfigurationError(f"解析gRPC配置失败: {e}", cause=e)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        return {
            "connection": self.default_connection.__dict__,
            "pool": {k: v for k, v in self.default_pool.__dict__.items() if k != 'connection_config'},
            "client": {k: v for k, v in self.default_client.__dict__.items() 
                      if k not in ['connection_config', 'pool_config', 'retry_config']},
            "server": {k: v for k, v in self.default_server.__dict__.items() 
                      if k != 'rate_limit_config'},
            "retry": self.default_client.retry_config.__dict__,
            "rate_limit": self.default_server.rate_limit_config.__dict__,
            "registry_endpoints": self.registry_endpoints,
            "registry_namespace": self.registry_namespace,
            "metrics_enabled": self.metrics_enabled,
            "metrics_port": self.metrics_port,
            "log_level": self.log_level,
            "log_grpc_calls": self.log_grpc_calls
        }


def load_grpc_config_from_setting() -> GrpcConfig:
    """
    从设置模块加载gRPC配置
    
    Returns:
        GrpcConfig: gRPC配置实例
    """
    try:
        # 尝试从setting模块导入配置
        from ...setting.config import BaseConfig
        
        # 这里应该有一个专门的gRPC配置类
        # 暂时使用默认配置
        config_dict = {}
        
        # 尝试读取环境变量中的gRPC配置
        import os
        
        # 连接配置
        connection_config = {}
        if os.getenv('GRPC_CONNECT_TIMEOUT'):
            connection_config['connect_timeout'] = float(os.getenv('GRPC_CONNECT_TIMEOUT'))
        if os.getenv('GRPC_REQUEST_TIMEOUT'):
            connection_config['request_timeout'] = float(os.getenv('GRPC_REQUEST_TIMEOUT'))
        if os.getenv('GRPC_USE_SSL'):
            connection_config['use_ssl'] = os.getenv('GRPC_USE_SSL').lower() == 'true'
        if connection_config:
            config_dict['connection'] = connection_config
        
        # 池配置
        pool_config = {}
        if os.getenv('GRPC_POOL_MIN_SIZE'):
            pool_config['min_connections'] = int(os.getenv('GRPC_POOL_MIN_SIZE'))
        if os.getenv('GRPC_POOL_MAX_SIZE'):
            pool_config['max_connections'] = int(os.getenv('GRPC_POOL_MAX_SIZE'))
        if pool_config:
            config_dict['pool'] = pool_config
        
        # 服务器配置
        server_config = {}
        if os.getenv('GRPC_SERVER_HOST'):
            server_config['host'] = os.getenv('GRPC_SERVER_HOST')
        if os.getenv('GRPC_SERVER_PORT'):
            server_config['port'] = int(os.getenv('GRPC_SERVER_PORT'))
        if os.getenv('GRPC_MAX_WORKERS'):
            server_config['max_workers'] = int(os.getenv('GRPC_MAX_WORKERS'))
        if server_config:
            config_dict['server'] = server_config
        
        # 监控配置
        if os.getenv('GRPC_METRICS_ENABLED'):
            config_dict['metrics_enabled'] = os.getenv('GRPC_METRICS_ENABLED').lower() == 'true'
        if os.getenv('GRPC_METRICS_PORT'):
            config_dict['metrics_port'] = int(os.getenv('GRPC_METRICS_PORT'))
        
        # 日志配置
        if os.getenv('GRPC_LOG_LEVEL'):
            config_dict['log_level'] = os.getenv('GRPC_LOG_LEVEL')
        if os.getenv('GRPC_LOG_CALLS'):
            config_dict['log_grpc_calls'] = os.getenv('GRPC_LOG_CALLS').lower() == 'true'
        
        # 服务发现配置
        if os.getenv('GRPC_REGISTRY_ENDPOINTS'):
            config_dict['registry_endpoints'] = os.getenv('GRPC_REGISTRY_ENDPOINTS').split(',')
        if os.getenv('GRPC_REGISTRY_NAMESPACE'):
            config_dict['registry_namespace'] = os.getenv('GRPC_REGISTRY_NAMESPACE')
        
        grpc_config = GrpcConfig.from_dict(config_dict)
        
        logger.info("gRPC配置加载成功")
        return grpc_config
        
    except Exception as e:
        logger.warning(f"从设置模块加载gRPC配置失败，使用默认配置: {e}")
        return GrpcConfig()


# 全局配置实例
_global_grpc_config: Optional[GrpcConfig] = None


def get_grpc_config() -> GrpcConfig:
    """
    获取全局gRPC配置
    
    Returns:
        GrpcConfig: gRPC配置实例
    """
    global _global_grpc_config
    
    if _global_grpc_config is None:
        _global_grpc_config = load_grpc_config_from_setting()
    
    return _global_grpc_config


def set_grpc_config(config: GrpcConfig) -> None:
    """
    设置全局gRPC配置
    
    Args:
        config: gRPC配置实例
    """
    global _global_grpc_config
    _global_grpc_config = config
    logger.info("gRPC全局配置已更新")


def update_grpc_config(config_dict: Dict[str, Any]) -> None:
    """
    更新gRPC配置
    
    Args:
        config_dict: 配置字典
    """
    current_config = get_grpc_config()
    updated_config_dict = current_config.to_dict()
    
    # 递归更新配置
    def deep_update(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                deep_update(target[key], value)
            else:
                target[key] = value
    
    deep_update(updated_config_dict, config_dict)
    
    new_config = GrpcConfig.from_dict(updated_config_dict)
    set_grpc_config(new_config)


# 便捷函数
def get_default_connection_config() -> ConnectionConfig:
    """获取默认连接配置"""
    return get_grpc_config().default_connection


def get_default_pool_config() -> PoolConfig:
    """获取默认池配置"""
    return get_grpc_config().default_pool


def get_default_client_config() -> ClientConfig:
    """获取默认客户端配置"""
    return get_grpc_config().default_client


def get_default_server_config() -> ServerConfig:
    """获取默认服务器配置"""
    return get_grpc_config().default_server


def is_metrics_enabled() -> bool:
    """检查是否启用监控"""
    return get_grpc_config().metrics_enabled


def get_metrics_port() -> int:
    """获取监控端口"""
    return get_grpc_config().metrics_port


def get_registry_endpoints() -> List[str]:
    """获取服务注册中心端点"""
    return get_grpc_config().registry_endpoints


def get_registry_namespace() -> str:
    """获取服务注册命名空间"""
    return get_grpc_config().registry_namespace