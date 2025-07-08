"""
开发环境配置

该模块提供开发环境的配置参数，包括Redis配置、MongoDB配置、
服务实例配置、日志配置和gRPC配置等。
"""

from typing import Dict, Any, List
from .config import BaseConfig


class DevelopmentConfig(BaseConfig):
    """
    开发环境配置类
    
    包含开发环境所需的所有配置参数，支持本地开发和测试。
    """
    
    def __init__(self):
        """初始化开发环境配置"""
        super().__init__()
        self._required_keys = [
            'redis.host',
            'mongodb.uri', 
            'services.gate.host',
            'services.logic.host'
        ]
    
    def get_default_config(self) -> Dict[str, Any]:
        """
        获取开发环境默认配置
        
        Returns:
            Dict[str, Any]: 开发环境配置字典
        """
        return {
            # Redis配置
            'redis': {
                'host': 'localhost',
                'port': 6379,
                'password': '',
                'db': 0,
                'max_connections': 50,
                'socket_timeout': 5.0,
                'socket_connect_timeout': 5.0,
                'socket_keepalive': True,
                'socket_keepalive_options': {},
                'health_check_interval': 30,
                'retry_on_timeout': True,
                'decode_responses': True,
                'encoding': 'utf-8',
                
                # Redis集群配置
                'cluster': {
                    'enabled': False,
                    'nodes': [
                        {'host': 'localhost', 'port': 7000},
                        {'host': 'localhost', 'port': 7001},
                        {'host': 'localhost', 'port': 7002},
                    ],
                    'max_connections_per_node': 16,
                    'skip_full_coverage_check': True,
                },
                
                # Redis桶配置（用于分片）
                'buckets': {
                    'user_data': {
                        'db': 0,
                        'key_prefix': 'user:',
                        'expire_time': 86400,  # 24小时
                    },
                    'game_data': {
                        'db': 1,
                        'key_prefix': 'game:',
                        'expire_time': 3600,   # 1小时
                    },
                    'session_data': {
                        'db': 2,
                        'key_prefix': 'session:',
                        'expire_time': 1800,   # 30分钟
                    },
                    'cache_data': {
                        'db': 3,
                        'key_prefix': 'cache:',
                        'expire_time': 300,    # 5分钟
                    },
                },
                
                # Redis发布订阅配置
                'pubsub': {
                    'channel_prefix': 'game:',
                    'max_messages': 1000,
                    'timeout': 1.0,
                }
            },
            
            # MongoDB配置
            'mongodb': {
                'uri': 'mongodb://localhost:27017',
                'database': 'game_dev',
                'username': '',
                'password': '',
                'auth_source': 'admin',
                
                # 连接池配置
                'max_pool_size': 100,
                'min_pool_size': 10,
                'max_idle_time_ms': 300000,  # 5分钟
                'server_selection_timeout_ms': 30000,  # 30秒
                'socket_timeout_ms': 30000,  # 30秒
                'connect_timeout_ms': 10000,  # 10秒
                'heartbeat_frequency_ms': 10000,  # 10秒
                'retry_writes': True,
                'w': 'majority',
                'read_preference': 'primaryPreferred',
                
                # 集合配置
                'collections': {
                    'users': {
                        'indexes': [
                            {'keys': [('user_id', 1)], 'unique': True},
                            {'keys': [('email', 1)], 'unique': True},
                            {'keys': [('created_at', -1)]},
                        ]
                    },
                    'game_records': {
                        'indexes': [
                            {'keys': [('user_id', 1), ('game_type', 1)]},
                            {'keys': [('created_at', -1)]},
                        ]
                    },
                    'chat_messages': {
                        'indexes': [
                            {'keys': [('channel_id', 1), ('created_at', -1)]},
                            {'keys': [('user_id', 1)]},
                        ],
                        'ttl_field': 'created_at',
                        'ttl_seconds': 2592000,  # 30天
                    }
                }
            },
            
            # 服务实例配置
            'services': {
                # 网关服务
                'gate': {
                    'host': '0.0.0.0',
                    'port': 8000,
                    'workers': 1,
                    'debug': True,
                    'auto_reload': True,
                    'access_log': True,
                    'cors_enabled': True,
                    'cors_origins': ['*'],
                    'max_request_size': 100 * 1024 * 1024,  # 100MB
                    'request_timeout': 60,
                    'keep_alive_timeout': 30,
                    'websocket': {
                        'enabled': True,
                        'ping_interval': 20,
                        'ping_timeout': 60,
                        'max_size': 1024 * 1024,  # 1MB
                    }
                },
                
                # 逻辑服务
                'logic': {
                    'host': '0.0.0.0',
                    'port': 8001,
                    'workers': 1,
                    'debug': True,
                    'auto_reload': True,
                },
                
                # 聊天服务
                'chat': {
                    'host': '0.0.0.0',
                    'port': 8002,
                    'workers': 1,
                    'debug': True,
                    'auto_reload': True,
                    'max_rooms': 1000,
                    'max_users_per_room': 100,
                    'message_rate_limit': 10,  # 每秒最多10条消息
                },
                
                # 战斗服务
                'fight': {
                    'host': '0.0.0.0',
                    'port': 8003,
                    'workers': 1,
                    'debug': True,
                    'auto_reload': True,
                    'max_battles': 1000,
                    'battle_timeout': 300,  # 5分钟
                    'tick_rate': 20,  # 20Hz
                }
            },
            
            # 日志配置
            'logging': {
                'level': 'DEBUG',
                'format': '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>',
                'colorize': True,
                'backtrace': True,
                'diagnose': True,
                
                # 文件输出配置
                'file': {
                    'enabled': True,
                    'path': 'logs/game_dev.log',
                    'rotation': '100 MB',
                    'retention': '10 days',
                    'compression': 'zip',
                    'encoding': 'utf-8',
                    'level': 'INFO',
                },
                
                # 错误日志配置
                'error_file': {
                    'enabled': True,
                    'path': 'logs/error_dev.log',
                    'rotation': '50 MB',
                    'retention': '30 days',
                    'compression': 'zip',
                    'level': 'ERROR',
                },
                
                # 业务日志配置
                'business': {
                    'user_action': {
                        'path': 'logs/user_action_dev.log',
                        'rotation': '500 MB',
                        'retention': '7 days',
                        'format': '{time:YYYY-MM-DD HH:mm:ss} | {extra[user_id]} | {extra[action]} | {message}',
                    },
                    'battle': {
                        'path': 'logs/battle_dev.log',
                        'rotation': '200 MB',
                        'retention': '3 days',
                        'format': '{time:YYYY-MM-DD HH:mm:ss} | {extra[battle_id]} | {extra[event]} | {message}',
                    }
                }
            },
            
            # gRPC配置
            'grpc': {
                'default_timeout': 30.0,
                'max_receive_message_length': 1024 * 1024 * 4,  # 4MB
                'max_send_message_length': 1024 * 1024 * 4,     # 4MB
                'keepalive_time_ms': 30000,  # 30秒
                'keepalive_timeout_ms': 5000,  # 5秒
                'keepalive_permit_without_calls': True,
                'http2_max_pings_without_data': 2,
                'http2_min_time_between_pings_ms': 10000,  # 10秒
                'http2_min_ping_interval_without_data_ms': 300000,  # 5分钟
                
                # 重试策略
                'retry': {
                    'max_attempts': 3,
                    'initial_backoff': 1.0,
                    'max_backoff': 10.0,
                    'backoff_multiplier': 2.0,
                    'retryable_status_codes': ['UNAVAILABLE', 'DEADLINE_EXCEEDED'],
                },
                
                # 服务端配置
                'server': {
                    'max_workers': 10,
                    'grace_period': 30,
                    'compression': 'gzip',
                },
                
                # 客户端连接池配置
                'client_pool': {
                    'max_size': 20,
                    'min_size': 2,
                    'idle_timeout': 300,  # 5分钟
                    'health_check_interval': 60,  # 1分钟
                }
            },
            
            # 分布式配置
            'distributed': {
                # 服务发现配置
                'discovery': {
                    'type': 'redis',  # redis, consul, etcd
                    'register_interval': 30,  # 注册间隔（秒）
                    'health_check_interval': 10,  # 健康检查间隔（秒）
                    'service_ttl': 60,  # 服务TTL（秒）
                },
                
                # 负载均衡配置
                'load_balancer': {
                    'strategy': 'round_robin',  # round_robin, weighted, random, least_connections
                    'health_check_enabled': True,
                    'failure_threshold': 3,
                    'recovery_time': 30,
                },
                
                # 分布式锁配置
                'lock': {
                    'type': 'redis',
                    'timeout': 30,
                    'retry_interval': 0.1,
                    'max_retries': 100,
                },
                
                # ID生成器配置（雪花算法）
                'id_generator': {
                    'worker_id': 1,
                    'datacenter_id': 1,
                    'epoch': 1609459200000,  # 2021-01-01 00:00:00 UTC
                }
            },
            
            # 安全配置
            'security': {
                # JWT配置
                'jwt': {
                    'secret_key': 'dev-secret-key-change-in-production',
                    'algorithm': 'HS256',
                    'access_token_expire_minutes': 60,
                    'refresh_token_expire_days': 7,
                    'issuer': 'game-server-dev',
                },
                
                # 限流配置
                'rate_limit': {
                    'enabled': True,
                    'requests_per_minute': 100,
                    'burst_size': 20,
                    'storage_type': 'redis',
                },
                
                # 加密配置
                'encryption': {
                    'algorithm': 'AES-256-GCM',
                    'key_derivation': 'PBKDF2',
                    'iterations': 100000,
                    'salt_length': 32,
                }
            },
            
            # 监控配置
            'monitoring': {
                # 指标收集
                'metrics': {
                    'enabled': True,
                    'collect_interval': 15,  # 15秒
                    'retention_days': 7,
                },
                
                # 链路追踪
                'tracing': {
                    'enabled': True,
                    'sample_rate': 1.0,  # 开发环境100%采样
                    'jaeger_endpoint': 'http://localhost:14268/api/traces',
                },
                
                # 告警配置
                'alerting': {
                    'enabled': False,  # 开发环境关闭告警
                    'webhook_url': '',
                    'thresholds': {
                        'cpu_usage': 80,
                        'memory_usage': 85,
                        'error_rate': 5,
                        'response_time': 1000,  # 毫秒
                    }
                }
            },
            
            # Celery配置（异步任务）
            'celery': {
                'broker_url': 'redis://localhost:6379/4',
                'result_backend': 'redis://localhost:6379/5',
                'task_serializer': 'json',
                'result_serializer': 'json',
                'accept_content': ['json'],
                'timezone': 'Asia/Shanghai',
                'enable_utc': False,
                'task_track_started': True,
                'task_time_limit': 300,  # 5分钟
                'task_soft_time_limit': 240,  # 4分钟
                'worker_prefetch_multiplier': 1,
                'worker_max_tasks_per_child': 1000,
                
                # 定时任务配置
                'beat_schedule': {
                    'cleanup_expired_sessions': {
                        'task': 'tasks.cleanup.cleanup_expired_sessions',
                        'schedule': 300.0,  # 每5分钟执行一次
                    },
                    'update_game_statistics': {
                        'task': 'tasks.statistics.update_game_statistics',
                        'schedule': 3600.0,  # 每小时执行一次
                    }
                }
            },
            
            # 调试配置
            'debug': {
                'enable_debug_mode': True,
                'enable_profiling': False,
                'enable_request_logging': True,
                'enable_sql_logging': True,
                'slow_query_threshold': 1.0,  # 1秒
            },
            
            # 其他配置
            'app': {
                'name': 'Distributed Game Server',
                'version': '1.0.0',
                'environment': 'development',
                'timezone': 'Asia/Shanghai',
                'language': 'zh-CN',
                'max_concurrent_users': 1000,
                'session_timeout': 3600,  # 1小时
            }
        }


# 配置实例
config = DevelopmentConfig()