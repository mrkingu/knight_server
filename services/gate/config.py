"""
网关服务配置模块

该模块定义了网关服务的所有配置项，包括WebSocket配置、后端服务配置、
限流配置、安全配置等。支持环境变量覆盖和动态配置更新。

主要配置项：
- WebSocket服务配置
- 后端服务地址配置
- 限流和熔断配置
- 认证和安全配置
- 日志和监控配置
"""

import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from common.logger import logger


class GatewayMode(Enum):
    """网关模式枚举"""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LoadBalanceStrategy(Enum):
    """负载均衡策略枚举"""
    ROUND_ROBIN = "round_robin"
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"
    LEAST_CONNECTIONS = "least_connections"
    RANDOM = "random"


@dataclass
class WebSocketConfig:
    """WebSocket配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    max_connections: int = 10000
    heartbeat_interval: int = 30  # 心跳间隔(秒)
    connection_timeout: int = 60  # 连接超时(秒)
    message_max_size: int = 1024 * 1024  # 最大消息大小(1MB)
    compression: bool = True  # 消息压缩
    ping_interval: int = 20  # ping间隔(秒)
    ping_timeout: int = 10  # ping超时(秒)
    close_timeout: int = 5  # 关闭超时(秒)
    max_queue_size: int = 1000  # 消息队列大小
    

@dataclass
class BackendService:
    """后端服务配置"""
    name: str
    host: str
    port: int
    weight: int = 100
    max_connections: int = 50
    timeout: int = 30
    enabled: bool = True
    health_check_path: str = "/health"
    

@dataclass
class RateLimitConfig:
    """限流配置"""
    enabled: bool = True
    global_limit: int = 10000  # 全局QPS限制
    user_limit: int = 100  # 单用户QPS限制
    ip_limit: int = 500  # 单IP QPS限制
    window_size: int = 60  # 滑动窗口大小(秒)
    burst_size: int = 200  # 突发流量大小
    

@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    enabled: bool = True
    failure_threshold: int = 50  # 失败阈值百分比
    success_threshold: int = 10  # 成功阈值(半开状态)
    timeout: int = 60  # 熔断超时(秒)
    minimum_requests: int = 20  # 最小请求数
    

@dataclass
class AuthConfig:
    """认证配置"""
    enabled: bool = True
    jwt_secret: str = "your-secret-key"
    jwt_algorithm: str = "HS256"
    token_expire_time: int = 3600  # Token过期时间(秒)
    refresh_token_expire_time: int = 604800  # 刷新Token过期时间(秒)
    max_login_attempts: int = 5  # 最大登录尝试次数
    login_cooldown: int = 300  # 登录冷却时间(秒)
    

@dataclass
class SecurityConfig:
    """安全配置"""
    enable_signature: bool = True  # 启用签名验证
    enable_encryption: bool = False  # 启用消息加密
    enable_ip_whitelist: bool = False  # 启用IP白名单
    enable_rate_limit: bool = True  # 启用限流
    enable_circuit_breaker: bool = True  # 启用熔断
    max_request_size: int = 1024 * 1024  # 最大请求大小
    allowed_origins: List[str] = field(default_factory=lambda: ["*"])  # 允许的跨域源
    

@dataclass
class LogConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "{time} | {level} | {message}"
    file_path: str = "logs/gateway.log"
    max_size: str = "100MB"
    backup_count: int = 5
    compression: str = "gz"
    

@dataclass
class MonitorConfig:
    """监控配置"""
    enabled: bool = True
    metrics_port: int = 8001
    health_check_path: str = "/health"
    metrics_path: str = "/metrics"
    enable_tracing: bool = True
    jaeger_endpoint: str = "http://localhost:14268/api/traces"
    

@dataclass
class GatewayConfig:
    """网关主配置"""
    mode: GatewayMode = GatewayMode.DEVELOPMENT
    debug: bool = False
    workers: int = 1
    
    # 子配置
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    backend_services: Dict[str, BackendService] = field(default_factory=dict)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    log: LogConfig = field(default_factory=LogConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    
    # Redis配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_max_connections: int = 100
    
    # 负载均衡配置
    load_balance_strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN
    
    def __post_init__(self):
        """初始化后处理"""
        self._load_from_env()
        self._init_backend_services()
        self._validate_config()
        
    def _load_from_env(self):
        """从环境变量加载配置"""
        # WebSocket配置
        self.websocket.host = os.getenv("GATEWAY_HOST", self.websocket.host)
        self.websocket.port = int(os.getenv("GATEWAY_PORT", self.websocket.port))
        self.websocket.max_connections = int(os.getenv("GATEWAY_MAX_CONNECTIONS", self.websocket.max_connections))
        
        # Redis配置
        self.redis_host = os.getenv("REDIS_HOST", self.redis_host)
        self.redis_port = int(os.getenv("REDIS_PORT", self.redis_port))
        self.redis_password = os.getenv("REDIS_PASSWORD", self.redis_password)
        
        # 认证配置
        self.auth.jwt_secret = os.getenv("JWT_SECRET", self.auth.jwt_secret)
        
        # 模式配置
        mode_str = os.getenv("GATEWAY_MODE", self.mode.value)
        try:
            self.mode = GatewayMode(mode_str)
        except ValueError:
            logger.warning(f"无效的网关模式: {mode_str}，使用默认模式")
            
    def _init_backend_services(self):
        """初始化后端服务配置"""
        if not self.backend_services:
            # 默认服务配置
            self.backend_services = {
                "logic_service": BackendService(
                    name="logic_service",
                    host=os.getenv("LOGIC_SERVICE_HOST", "localhost"),
                    port=int(os.getenv("LOGIC_SERVICE_PORT", "50051")),
                    weight=100,
                    max_connections=50
                ),
                "chat_service": BackendService(
                    name="chat_service", 
                    host=os.getenv("CHAT_SERVICE_HOST", "localhost"),
                    port=int(os.getenv("CHAT_SERVICE_PORT", "50052")),
                    weight=100,
                    max_connections=50
                ),
                "fight_service": BackendService(
                    name="fight_service",
                    host=os.getenv("FIGHT_SERVICE_HOST", "localhost"),
                    port=int(os.getenv("FIGHT_SERVICE_PORT", "50053")),
                    weight=100,
                    max_connections=50
                )
            }
            
    def _validate_config(self):
        """验证配置有效性"""
        # 验证端口范围
        if not (1024 <= self.websocket.port <= 65535):
            raise ValueError(f"无效的WebSocket端口: {self.websocket.port}")
            
        # 验证连接数限制
        if self.websocket.max_connections <= 0:
            raise ValueError("最大连接数必须大于0")
            
        # 验证JWT密钥
        if len(self.auth.jwt_secret) < 32:
            logger.warning("JWT密钥长度过短，建议使用32字符以上的密钥")
            
        # 验证后端服务配置
        for service_name, service in self.backend_services.items():
            if not service.host or not service.port:
                raise ValueError(f"后端服务配置无效: {service_name}")
                
    def get_backend_service(self, service_name: str) -> Optional[BackendService]:
        """获取后端服务配置"""
        return self.backend_services.get(service_name)
        
    def add_backend_service(self, service: BackendService):
        """添加后端服务"""
        self.backend_services[service.name] = service
        logger.info(f"添加后端服务: {service.name} -> {service.host}:{service.port}")
        
    def remove_backend_service(self, service_name: str):
        """移除后端服务"""
        if service_name in self.backend_services:
            del self.backend_services[service_name]
            logger.info(f"移除后端服务: {service_name}")
            
    def update_rate_limit(self, **kwargs):
        """更新限流配置"""
        for key, value in kwargs.items():
            if hasattr(self.rate_limit, key):
                setattr(self.rate_limit, key, value)
                logger.info(f"更新限流配置: {key} = {value}")
                
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "mode": self.mode.value,
            "debug": self.debug,
            "workers": self.workers,
            "websocket": self.websocket.__dict__,
            "backend_services": {k: v.__dict__ for k, v in self.backend_services.items()},
            "rate_limit": self.rate_limit.__dict__,
            "circuit_breaker": self.circuit_breaker.__dict__,
            "auth": self.auth.__dict__,
            "security": self.security.__dict__,
            "log": self.log.__dict__,
            "monitor": self.monitor.__dict__,
            "redis_host": self.redis_host,
            "redis_port": self.redis_port,
            "load_balance_strategy": self.load_balance_strategy.value
        }


# 默认配置实例
default_config = GatewayConfig()


def load_config(config_path: Optional[str] = None) -> GatewayConfig:
    """
    加载网关配置
    
    Args:
        config_path: 配置文件路径，如果为None则使用默认配置
        
    Returns:
        GatewayConfig: 网关配置实例
    """
    if config_path:
        # TODO: 从配置文件加载
        logger.info(f"从配置文件加载配置: {config_path}")
        pass
    
    config = GatewayConfig()
    logger.info("网关配置加载完成", extra={"config_mode": config.mode.value})
    return config


def create_development_config() -> GatewayConfig:
    """创建开发环境配置"""
    config = GatewayConfig()
    config.mode = GatewayMode.DEVELOPMENT
    config.debug = True
    config.websocket.host = "0.0.0.0"
    config.websocket.port = 8000
    config.websocket.max_connections = 1000
    config.log.level = "DEBUG"
    return config


def create_production_config() -> GatewayConfig:
    """创建生产环境配置"""
    config = GatewayConfig()
    config.mode = GatewayMode.PRODUCTION
    config.debug = False
    config.workers = 4
    config.websocket.max_connections = 10000
    config.security.enable_signature = True
    config.security.enable_rate_limit = True
    config.security.enable_circuit_breaker = True
    config.log.level = "INFO"
    return config


def create_testing_config() -> GatewayConfig:
    """创建测试环境配置"""
    config = GatewayConfig()
    config.mode = GatewayMode.TESTING
    config.debug = True
    config.websocket.port = 8888
    config.websocket.max_connections = 100
    config.auth.enabled = False
    config.security.enable_signature = False
    config.security.enable_rate_limit = False
    config.log.level = "DEBUG"
    return config