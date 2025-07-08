"""
生产环境配置

该模块提供生产环境的配置参数，继承开发配置并覆盖必要参数，
确保生产环境的安全性、性能和稳定性。
"""

from typing import Dict, Any
from .development import DevelopmentConfig


class ProductionConfig(DevelopmentConfig):
    """
    生产环境配置类
    
    继承开发环境配置，覆盖生产环境特定的配置参数。
    注重安全性、性能优化和监控告警。
    """
    
    def __init__(self):
        """初始化生产环境配置"""
        super().__init__()
        self._required_keys.extend([
            'security.jwt.secret_key',
            'mongodb.username',
            'mongodb.password',
            'monitoring.alerting.webhook_url'
        ])
    
    def get_default_config(self) -> Dict[str, Any]:
        """
        获取生产环境配置
        
        继承开发环境配置并覆盖生产环境特定参数
        
        Returns:
            Dict[str, Any]: 生产环境配置字典
        """
        # 获取基础配置
        config = super().get_default_config()
        
        # 生产环境覆盖配置
        production_overrides = {
            # Redis生产环境配置
            'redis': {
                **config['redis'],
                'host': 'redis-cluster.production.local',
                'password': 'REDIS_PASSWORD_FROM_ENV',
                'max_connections': 200,
                'socket_timeout': 3.0,
                'socket_connect_timeout': 3.0,
                'health_check_interval': 60,
                
                # 启用Redis集群
                'cluster': {
                    'enabled': True,
                    'nodes': [
                        {'host': 'redis-node-1.production.local', 'port': 6379},
                        {'host': 'redis-node-2.production.local', 'port': 6379},
                        {'host': 'redis-node-3.production.local', 'port': 6379},
                        {'host': 'redis-node-4.production.local', 'port': 6379},
                        {'host': 'redis-node-5.production.local', 'port': 6379},
                        {'host': 'redis-node-6.production.local', 'port': 6379},
                    ],
                    'max_connections_per_node': 50,
                    'skip_full_coverage_check': False,
                },
                
                # 生产环境桶配置（延长过期时间）
                'buckets': {
                    **config['redis']['buckets'],
                    'user_data': {
                        **config['redis']['buckets']['user_data'],
                        'expire_time': 172800,  # 48小时
                    },
                    'game_data': {
                        **config['redis']['buckets']['game_data'],
                        'expire_time': 7200,    # 2小时
                    }
                }
            },
            
            # MongoDB生产环境配置
            'mongodb': {
                **config['mongodb'],
                'uri': 'mongodb://mongo-cluster.production.local:27017,mongo-cluster.production.local:27018,mongo-cluster.production.local:27019',
                'database': 'game_production',
                'username': 'MONGO_USERNAME_FROM_ENV',
                'password': 'MONGO_PASSWORD_FROM_ENV',
                'auth_source': 'admin',
                
                # 生产环境连接池配置
                'max_pool_size': 300,
                'min_pool_size': 50,
                'max_idle_time_ms': 600000,  # 10分钟
                'server_selection_timeout_ms': 5000,   # 5秒
                'socket_timeout_ms': 10000,   # 10秒
                'connect_timeout_ms': 5000,   # 5秒
                'heartbeat_frequency_ms': 5000,   # 5秒
                
                # 副本集配置
                'replica_set': 'rs0',
                'read_preference': 'secondaryPreferred',
                'read_concern_level': 'majority',
                'write_concern': {'w': 'majority', 'j': True, 'wtimeout': 5000},
            },
            
            # 服务实例生产环境配置
            'services': {
                # 网关服务
                'gate': {
                    **config['services']['gate'],
                    'workers': 4,
                    'debug': False,
                    'auto_reload': False,
                    'access_log': False,  # 使用专门的访问日志中间件
                    'cors_origins': ['https://game.example.com', 'https://admin.example.com'],
                    'request_timeout': 30,
                    'keep_alive_timeout': 75,
                },
                
                # 逻辑服务
                'logic': {
                    **config['services']['logic'],
                    'workers': 8,
                    'debug': False,
                    'auto_reload': False,
                },
                
                # 聊天服务
                'chat': {
                    **config['services']['chat'],
                    'workers': 4,
                    'debug': False,
                    'auto_reload': False,
                    'max_rooms': 10000,
                    'max_users_per_room': 500,
                    'message_rate_limit': 5,  # 生产环境更严格的限流
                },
                
                # 战斗服务
                'fight': {
                    **config['services']['fight'],
                    'workers': 6,
                    'debug': False,
                    'auto_reload': False,
                    'max_battles': 50000,
                    'battle_timeout': 600,  # 10分钟
                    'tick_rate': 30,  # 30Hz，更高的tick率
                }
            },
            
            # 日志生产环境配置
            'logging': {
                'level': 'INFO',
                'format': '{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}',
                'colorize': False,  # 生产环境关闭颜色
                'backtrace': False,
                'diagnose': False,
                
                # 文件输出配置
                'file': {
                    'enabled': True,
                    'path': '/var/log/game/game_production.log',
                    'rotation': '500 MB',
                    'retention': '30 days',
                    'compression': 'gz',
                    'encoding': 'utf-8',
                    'level': 'INFO',
                },
                
                # 错误日志配置
                'error_file': {
                    'enabled': True,
                    'path': '/var/log/game/error_production.log',
                    'rotation': '200 MB',
                    'retention': '90 days',
                    'compression': 'gz',
                    'level': 'ERROR',
                },
                
                # 业务日志生产环境配置
                'business': {
                    'user_action': {
                        'path': '/var/log/game/user_action_production.log',
                        'rotation': '2 GB',
                        'retention': '30 days',
                        'format': '{time:YYYY-MM-DD HH:mm:ss} | {extra[user_id]} | {extra[action]} | {message}',
                    },
                    'battle': {
                        'path': '/var/log/game/battle_production.log',
                        'rotation': '1 GB',
                        'retention': '15 days',
                        'format': '{time:YYYY-MM-DD HH:mm:ss} | {extra[battle_id]} | {extra[event]} | {message}',
                    }
                },
                
                # 审计日志
                'audit': {
                    'enabled': True,
                    'path': '/var/log/game/audit_production.log',
                    'rotation': '1 GB',
                    'retention': '365 days',  # 审计日志保留1年
                    'compression': 'gz',
                    'format': '{time:YYYY-MM-DD HH:mm:ss} | {extra[user_id]} | {extra[ip]} | {extra[action]} | {extra[resource]} | {message}',
                }
            },
            
            # gRPC生产环境配置
            'grpc': {
                **config['grpc'],
                'default_timeout': 10.0,  # 生产环境更短的超时时间
                'max_receive_message_length': 1024 * 1024 * 16,  # 16MB
                'max_send_message_length': 1024 * 1024 * 16,     # 16MB
                'keepalive_time_ms': 60000,  # 1分钟
                'keepalive_timeout_ms': 10000,  # 10秒
                
                # 生产环境重试策略（更保守）
                'retry': {
                    'max_attempts': 2,
                    'initial_backoff': 0.5,
                    'max_backoff': 5.0,
                    'backoff_multiplier': 1.5,
                    'retryable_status_codes': ['UNAVAILABLE'],
                },
                
                # 服务端配置
                'server': {
                    'max_workers': 32,
                    'grace_period': 10,
                    'compression': 'gzip',
                },
                
                # 客户端连接池配置
                'client_pool': {
                    'max_size': 100,
                    'min_size': 10,
                    'idle_timeout': 120,  # 2分钟
                    'health_check_interval': 30,  # 30秒
                }
            },
            
            # 分布式生产环境配置
            'distributed': {
                **config['distributed'],
                
                # 服务发现配置
                'discovery': {
                    'type': 'consul',  # 生产环境使用Consul
                    'consul_host': 'consul.production.local',
                    'consul_port': 8500,
                    'register_interval': 15,  # 更频繁的注册
                    'health_check_interval': 5,  # 更频繁的健康检查
                    'service_ttl': 30,
                },
                
                # 负载均衡配置
                'load_balancer': {
                    'strategy': 'weighted',  # 使用加权轮询
                    'health_check_enabled': True,
                    'failure_threshold': 2,  # 更敏感的失败检测
                    'recovery_time': 60,
                },
                
                # ID生成器配置
                'id_generator': {
                    'worker_id': 'WORKER_ID_FROM_ENV',  # 从环境变量获取
                    'datacenter_id': 'DATACENTER_ID_FROM_ENV',
                    'epoch': 1609459200000,
                }
            },
            
            # 安全生产环境配置
            'security': {
                # JWT配置
                'jwt': {
                    'secret_key': 'JWT_SECRET_KEY_FROM_ENV',  # 从环境变量获取
                    'algorithm': 'RS256',  # 使用RSA签名
                    'access_token_expire_minutes': 30,  # 更短的过期时间
                    'refresh_token_expire_days': 3,
                    'issuer': 'game-server-production',
                    'private_key_path': '/etc/ssl/private/jwt_private.pem',
                    'public_key_path': '/etc/ssl/certs/jwt_public.pem',
                },
                
                # 限流配置（更严格）
                'rate_limit': {
                    'enabled': True,
                    'requests_per_minute': 60,
                    'burst_size': 10,
                    'storage_type': 'redis',
                    'key_prefix': 'rate_limit:prod:',
                },
                
                # 加密配置
                'encryption': {
                    'algorithm': 'AES-256-GCM',
                    'key_derivation': 'Argon2',  # 更安全的密钥派生
                    'iterations': 3,
                    'memory_cost': 65536,  # 64MB
                    'parallelism': 4,
                    'salt_length': 32,
                    'master_key': 'MASTER_KEY_FROM_ENV',
                },
                
                # TLS/SSL配置
                'tls': {
                    'enabled': True,
                    'cert_file': '/etc/ssl/certs/game_server.crt',
                    'key_file': '/etc/ssl/private/game_server.key',
                    'ca_file': '/etc/ssl/certs/ca.crt',
                    'verify_mode': 'CERT_REQUIRED',
                }
            },
            
            # 监控生产环境配置
            'monitoring': {
                # 指标收集
                'metrics': {
                    'enabled': True,
                    'collect_interval': 30,  # 30秒
                    'retention_days': 30,
                    'prometheus_endpoint': 'http://prometheus.production.local:9090',
                    'grafana_endpoint': 'http://grafana.production.local:3000',
                },
                
                # 链路追踪
                'tracing': {
                    'enabled': True,
                    'sample_rate': 0.1,  # 生产环境10%采样
                    'jaeger_endpoint': 'http://jaeger.production.local:14268/api/traces',
                },
                
                # 告警配置
                'alerting': {
                    'enabled': True,
                    'webhook_url': 'ALERT_WEBHOOK_URL_FROM_ENV',
                    'thresholds': {
                        'cpu_usage': 70,
                        'memory_usage': 80,
                        'error_rate': 1,  # 1%错误率告警
                        'response_time': 500,  # 500ms响应时间告警
                        'disk_usage': 85,
                        'database_connections': 250,
                    },
                    'channels': {
                        'slack': {
                            'enabled': True,
                            'webhook_url': 'SLACK_WEBHOOK_URL_FROM_ENV',
                            'channel': '#alerts-production',
                        },
                        'email': {
                            'enabled': True,
                            'smtp_host': 'smtp.example.com',
                            'smtp_port': 587,
                            'username': 'alerts@example.com',
                            'password': 'EMAIL_PASSWORD_FROM_ENV',
                            'recipients': ['admin@example.com', 'devops@example.com'],
                        }
                    }
                },
                
                # 性能监控
                'performance': {
                    'enabled': True,
                    'apm_service_name': 'game-server-production',
                    'elastic_apm_server_url': 'http://apm.production.local:8200',
                    'elastic_apm_secret_token': 'APM_SECRET_TOKEN_FROM_ENV',
                }
            },
            
            # Celery生产环境配置
            'celery': {
                **config['celery'],
                'broker_url': 'redis://redis-cluster.production.local:6379/4',
                'result_backend': 'redis://redis-cluster.production.local:6379/5',
                'task_time_limit': 600,  # 10分钟
                'task_soft_time_limit': 540,  # 9分钟
                'worker_prefetch_multiplier': 4,
                'worker_max_tasks_per_child': 5000,
                'worker_concurrency': 8,
                
                # 生产环境定时任务
                'beat_schedule': {
                    **config['celery']['beat_schedule'],
                    'backup_user_data': {
                        'task': 'tasks.backup.backup_user_data',
                        'schedule': 3600.0,  # 每小时备份用户数据
                    },
                    'cleanup_temp_files': {
                        'task': 'tasks.cleanup.cleanup_temp_files',
                        'schedule': 1800.0,  # 每30分钟清理临时文件
                    },
                    'generate_daily_reports': {
                        'task': 'tasks.reports.generate_daily_reports',
                        'schedule': 86400.0,  # 每天生成报告
                        'options': {'queue': 'reports'},
                    }
                },
                
                # 队列配置
                'task_routes': {
                    'tasks.backup.*': {'queue': 'backup'},
                    'tasks.reports.*': {'queue': 'reports'},
                    'tasks.notification.*': {'queue': 'notification'},
                    'tasks.default.*': {'queue': 'default'},
                }
            },
            
            # 调试配置（生产环境关闭）
            'debug': {
                'enable_debug_mode': False,
                'enable_profiling': False,
                'enable_request_logging': False,
                'enable_sql_logging': False,
                'slow_query_threshold': 0.5,  # 500ms
            },
            
            # 应用配置
            'app': {
                **config['app'],
                'environment': 'production',
                'max_concurrent_users': 100000,
                'session_timeout': 1800,  # 30分钟
                'maintenance_mode': False,
                'feature_flags': {
                    'new_battle_system': True,
                    'enhanced_chat': True,
                    'analytics_tracking': True,
                }
            },
            
            # 缓存配置
            'cache': {
                'type': 'redis',
                'default_timeout': 300,  # 5分钟
                'key_prefix': 'cache:prod:',
                'version': 1,
                'serializer': 'json',
                'compressor': 'gzip',
                'max_entries': 10000,
                
                # 缓存策略
                'strategies': {
                    'user_profile': {
                        'timeout': 1800,  # 30分钟
                        'max_entries': 50000,
                    },
                    'game_config': {
                        'timeout': 3600,  # 1小时
                        'max_entries': 1000,
                    },
                    'leaderboard': {
                        'timeout': 300,   # 5分钟
                        'max_entries': 100,
                    }
                }
            },
            
            # 备份配置
            'backup': {
                'enabled': True,
                'storage_type': 's3',  # s3, local, ftp
                'aws_access_key_id': 'AWS_ACCESS_KEY_ID_FROM_ENV',
                'aws_secret_access_key': 'AWS_SECRET_ACCESS_KEY_FROM_ENV',
                'aws_region': 'us-west-2',
                'bucket_name': 'game-backups-production',
                'retention_days': 90,
                
                # 备份策略
                'schedules': {
                    'full_backup': {
                        'enabled': True,
                        'cron': '0 2 * * *',  # 每天凌晨2点
                        'retention_count': 7,
                    },
                    'incremental_backup': {
                        'enabled': True,
                        'cron': '0 */4 * * *',  # 每4小时
                        'retention_count': 24,
                    }
                }
            }
        }
        
        # 深度合并配置
        self._deep_merge(config, production_overrides)
        
        return config
    
    def _deep_merge(self, base_dict: Dict[str, Any], override_dict: Dict[str, Any]) -> None:
        """
        深度合并字典
        
        Args:
            base_dict: 基础字典
            override_dict: 覆盖字典
        """
        for key, value in override_dict.items():
            if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                self._deep_merge(base_dict[key], value)
            else:
                base_dict[key] = value


# 配置实例
config = ProductionConfig()