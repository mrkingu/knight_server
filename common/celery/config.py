"""
Celery配置管理模块

提供Celery应用的配置管理功能。
"""

import os
from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from enum import Enum

from kombu import Queue


class BrokerType(Enum):
    """消息代理类型"""
    REDIS = "redis"
    RABBITMQ = "rabbitmq"
    MEMORY = "memory"


class ResultBackendType(Enum):
    """结果后端类型"""
    REDIS = "redis"
    DATABASE = "database"
    CACHE = "cache"
    ELASTICSEARCH = "elasticsearch"


class SerializerType(Enum):
    """序列化器类型"""
    JSON = "json"
    PICKLE = "pickle"
    YAML = "yaml"
    MSGPACK = "msgpack"


@dataclass
class RedisConfig:
    """Redis配置"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 20
    socket_timeout: float = 30.0
    socket_connect_timeout: float = 30.0
    retry_on_timeout: bool = True
    
    def get_url(self) -> str:
        """获取Redis URL"""
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


@dataclass
class RabbitMQConfig:
    """RabbitMQ配置"""
    host: str = "localhost"
    port: int = 5672
    vhost: str = "/"
    username: str = "guest"
    password: str = "guest"
    heartbeat: int = 600
    
    def get_url(self) -> str:
        """获取RabbitMQ URL"""
        return f"amqp://{self.username}:{self.password}@{self.host}:{self.port}/{self.vhost}"


@dataclass
class TaskConfig:
    """任务配置"""
    serializer: SerializerType = SerializerType.JSON
    compression: Optional[str] = None
    ignore_result: bool = False
    store_errors_even_if_ignored: bool = False
    track_started: bool = False
    acks_late: bool = False
    reject_on_worker_lost: bool = False
    
    # 重试配置
    autoretry_for: List[Exception] = field(default_factory=list)
    max_retries: int = 3
    retry_backoff: bool = False
    retry_backoff_max: int = 600
    retry_jitter: bool = True
    
    # 时间限制
    time_limit: Optional[int] = None
    soft_time_limit: Optional[int] = None
    
    # 速率限制
    rate_limit: Optional[str] = None


@dataclass
class WorkerConfig:
    """Worker配置"""
    concurrency: int = 1
    max_tasks_per_child: int = 1000
    task_time_limit: int = 30 * 60  # 30分钟
    task_soft_time_limit: int = 25 * 60  # 25分钟
    worker_prefetch_multiplier: int = 1
    worker_max_tasks_per_child: int = 1000
    worker_disable_rate_limits: bool = False
    worker_hijack_root_logger: bool = False
    worker_log_color: bool = True
    worker_send_task_events: bool = False
    worker_task_log_format: str = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"
    worker_log_format: str = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"


@dataclass
class BeatConfig:
    """Beat调度器配置"""
    schedule_filename: str = "celerybeat-schedule"
    max_loop_interval: int = 300
    sync_every: int = 0
    scheduler_cls: str = "celery.beat:PersistentScheduler"


@dataclass
class MonitoringConfig:
    """监控配置"""
    send_events: bool = True
    send_task_events: bool = True
    task_send_sent_event: bool = True
    worker_send_task_events: bool = True
    enable_utc: bool = True
    timezone: str = "UTC"


@dataclass
class CeleryConfig:
    """Celery完整配置"""
    # 基础配置
    name: str = "knight_server"
    broker_type: BrokerType = BrokerType.REDIS
    result_backend_type: ResultBackendType = ResultBackendType.REDIS
    
    # 连接配置
    redis_config: RedisConfig = field(default_factory=RedisConfig)
    rabbitmq_config: RabbitMQConfig = field(default_factory=RabbitMQConfig)
    
    # 任务配置
    task_config: TaskConfig = field(default_factory=TaskConfig)
    worker_config: WorkerConfig = field(default_factory=WorkerConfig)
    beat_config: BeatConfig = field(default_factory=BeatConfig)
    monitoring_config: MonitoringConfig = field(default_factory=MonitoringConfig)
    
    # 队列配置
    default_queue: str = "default"
    task_routes: Dict[str, str] = field(default_factory=dict)
    task_queues: List[Queue] = field(default_factory=list)
    
    # 序列化配置
    task_serializer: SerializerType = SerializerType.JSON
    result_serializer: SerializerType = SerializerType.JSON
    accept_content: List[str] = field(default_factory=lambda: ["json"])
    
    # 结果配置
    result_expires: int = 3600  # 1小时
    result_backend_transport_options: Dict[str, Any] = field(default_factory=dict)
    
    # 安全配置
    worker_enable_remote_control: bool = True
    worker_send_task_events: bool = False
    
    def get_broker_url(self) -> str:
        """获取消息代理URL"""
        if self.broker_type == BrokerType.REDIS:
            return self.redis_config.get_url()
        elif self.broker_type == BrokerType.RABBITMQ:
            return self.rabbitmq_config.get_url()
        elif self.broker_type == BrokerType.MEMORY:
            return "memory://"
        else:
            raise ValueError(f"不支持的代理类型: {self.broker_type}")
    
    def get_result_backend_url(self) -> str:
        """获取结果后端URL"""
        if self.result_backend_type == ResultBackendType.REDIS:
            return self.redis_config.get_url()
        elif self.result_backend_type == ResultBackendType.DATABASE:
            return "db+sqlite:///celery_results.db"
        elif self.result_backend_type == ResultBackendType.CACHE:
            return "cache+memcached://127.0.0.1:11211/"
        else:
            raise ValueError(f"不支持的结果后端类型: {self.result_backend_type}")
    
    def to_celery_config(self) -> Dict[str, Any]:
        """转换为Celery配置字典"""
        config = {
            # 基础配置
            'broker_url': self.get_broker_url(),
            'result_backend': self.get_result_backend_url(),
            
            # 序列化配置
            'task_serializer': self.task_serializer.value,
            'result_serializer': self.result_serializer.value,
            'accept_content': self.accept_content,
            
            # 时区配置
            'enable_utc': self.monitoring_config.enable_utc,
            'timezone': self.monitoring_config.timezone,
            
            # 结果配置
            'result_expires': self.result_expires,
            'result_backend_transport_options': self.result_backend_transport_options,
            
            # 任务配置
            'task_ignore_result': self.task_config.ignore_result,
            'task_store_errors_even_if_ignored': self.task_config.store_errors_even_if_ignored,
            'task_track_started': self.task_config.track_started,
            'task_acks_late': self.task_config.acks_late,
            'task_reject_on_worker_lost': self.task_config.reject_on_worker_lost,
            'task_time_limit': self.task_config.time_limit,
            'task_soft_time_limit': self.task_config.soft_time_limit,
            'task_rate_limit': self.task_config.rate_limit,
            
            # Worker配置
            'worker_concurrency': self.worker_config.concurrency,
            'worker_max_tasks_per_child': self.worker_config.max_tasks_per_child,
            'worker_prefetch_multiplier': self.worker_config.worker_prefetch_multiplier,
            'worker_disable_rate_limits': self.worker_config.worker_disable_rate_limits,
            'worker_hijack_root_logger': self.worker_config.worker_hijack_root_logger,
            'worker_log_color': self.worker_config.worker_log_color,
            'worker_send_task_events': self.worker_config.worker_send_task_events,
            'worker_task_log_format': self.worker_config.worker_task_log_format,
            'worker_log_format': self.worker_config.worker_log_format,
            
            # Beat配置
            'beat_schedule_filename': self.beat_config.schedule_filename,
            'beat_max_loop_interval': self.beat_config.max_loop_interval,
            'beat_sync_every': self.beat_config.sync_every,
            'beat_scheduler': self.beat_config.scheduler_cls,
            
            # 监控配置
            'worker_send_task_events': self.monitoring_config.worker_send_task_events,
            'task_send_sent_event': self.monitoring_config.task_send_sent_event,
            
            # 队列配置
            'task_default_queue': self.default_queue,
            'task_routes': self.task_routes,
            
            # 安全配置
            'worker_enable_remote_control': self.worker_enable_remote_control,
        }
        
        # 添加队列配置
        if self.task_queues:
            config['task_queues'] = self.task_queues
        
        return config
    
    @classmethod
    def from_env(cls) -> 'CeleryConfig':
        """从环境变量创建配置"""
        config = cls()
        
        # Redis配置
        if os.getenv('REDIS_HOST'):
            config.redis_config.host = os.getenv('REDIS_HOST')
        if os.getenv('REDIS_PORT'):
            config.redis_config.port = int(os.getenv('REDIS_PORT'))
        if os.getenv('REDIS_DB'):
            config.redis_config.db = int(os.getenv('REDIS_DB'))
        if os.getenv('REDIS_PASSWORD'):
            config.redis_config.password = os.getenv('REDIS_PASSWORD')
        
        # RabbitMQ配置
        if os.getenv('RABBITMQ_HOST'):
            config.rabbitmq_config.host = os.getenv('RABBITMQ_HOST')
        if os.getenv('RABBITMQ_PORT'):
            config.rabbitmq_config.port = int(os.getenv('RABBITMQ_PORT'))
        if os.getenv('RABBITMQ_USER'):
            config.rabbitmq_config.username = os.getenv('RABBITMQ_USER')
        if os.getenv('RABBITMQ_PASSWORD'):
            config.rabbitmq_config.password = os.getenv('RABBITMQ_PASSWORD')
        
        # 代理类型
        broker_type = os.getenv('CELERY_BROKER_TYPE', 'redis').lower()
        if broker_type == 'redis':
            config.broker_type = BrokerType.REDIS
        elif broker_type == 'rabbitmq':
            config.broker_type = BrokerType.RABBITMQ
        elif broker_type == 'memory':
            config.broker_type = BrokerType.MEMORY
        
        # Worker配置
        if os.getenv('CELERY_WORKER_CONCURRENCY'):
            config.worker_config.concurrency = int(os.getenv('CELERY_WORKER_CONCURRENCY'))
        if os.getenv('CELERY_WORKER_MAX_TASKS_PER_CHILD'):
            config.worker_config.max_tasks_per_child = int(os.getenv('CELERY_WORKER_MAX_TASKS_PER_CHILD'))
        
        # 时区配置
        if os.getenv('CELERY_TIMEZONE'):
            config.monitoring_config.timezone = os.getenv('CELERY_TIMEZONE')
        
        return config
    
    def update_from_dict(self, config_dict: Dict[str, Any]) -> None:
        """从字典更新配置"""
        for key, value in config_dict.items():
            if hasattr(self, key):
                setattr(self, key, value)
            # 处理嵌套配置
            elif key.startswith('redis_'):
                redis_key = key[6:]  # 去掉'redis_'前缀
                if hasattr(self.redis_config, redis_key):
                    setattr(self.redis_config, redis_key, value)
            elif key.startswith('rabbitmq_'):
                rabbitmq_key = key[9:]  # 去掉'rabbitmq_'前缀
                if hasattr(self.rabbitmq_config, rabbitmq_key):
                    setattr(self.rabbitmq_config, rabbitmq_key, value)
            elif key.startswith('task_'):
                task_key = key[5:]  # 去掉'task_'前缀
                if hasattr(self.task_config, task_key):
                    setattr(self.task_config, task_key, value)
            elif key.startswith('worker_'):
                worker_key = key[7:]  # 去掉'worker_'前缀
                if hasattr(self.worker_config, worker_key):
                    setattr(self.worker_config, worker_key, value)
            elif key.startswith('beat_'):
                beat_key = key[5:]  # 去掉'beat_'前缀
                if hasattr(self.beat_config, beat_key):
                    setattr(self.beat_config, beat_key, value)


def get_default_celery_config() -> CeleryConfig:
    """获取默认Celery配置"""
    config = CeleryConfig()
    
    # 设置默认队列
    config.task_queues = [
        Queue('default', routing_key='default'),
        Queue('high_priority', routing_key='high_priority'),
        Queue('low_priority', routing_key='low_priority'),
        Queue('scheduled', routing_key='scheduled'),
    ]
    
    # 设置任务路由
    config.task_routes = {
        'common.celery.tasks.high_priority.*': {'queue': 'high_priority'},
        'common.celery.tasks.low_priority.*': {'queue': 'low_priority'},
        'common.celery.tasks.scheduled.*': {'queue': 'scheduled'},
    }
    
    return config