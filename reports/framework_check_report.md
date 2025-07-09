# 框架完整性检查报告
生成时间: 2025-07-09 02:44:16
项目路径: .

## 检查摘要
- 🔴 错误: 0
- 🟡 警告: 141
- 🔄 重复: 88
- 📦 导入错误: 0

## 🟡 警告信息
- **no_exports**: 模块 common.utils 没有定义 __all__
  - 路径: `common.utils`

- **no_exports**: 模块 server_launcher.launcher 没有定义 __all__
  - 路径: `server_launcher.launcher`

- **no_exports**: 模块 server_launcher.service_manager 没有定义 __all__
  - 路径: `server_launcher.service_manager`

- **no_exports**: 模块 setting.config 没有定义 __all__
  - 路径: `setting.config`

- **unimplemented_method**: 未实现的方法: simple_logger.py:78

- **unimplemented_method**: 未实现的方法: server_launcher/launcher.py:36

- **unimplemented_method**: 未实现的方法: server_launcher/process_pool.py:485

- **unimplemented_method**: 未实现的方法: server_launcher/cli.py:680

- **unimplemented_method**: 未实现的方法: server_launcher/cli.py:714

- **unimplemented_method**: 未实现的方法: scripts/verify_startup.py:197

- **unimplemented_method**: 未实现的方法: scripts/verify_startup.py:250

- **unimplemented_method**: 未实现的方法: common/celery/__init__.py:21

- **unimplemented_method**: 未实现的方法: common/celery/__init__.py:26

- **unimplemented_method**: 未实现的方法: common/db/cache_strategy.py:131

- **unimplemented_method**: 未实现的方法: common/db/cache_strategy.py:136

- **unimplemented_method**: 未实现的方法: common/db/cache_strategy.py:141

- **unimplemented_method**: 未实现的方法: common/db/cache_strategy.py:146

- **unimplemented_method**: 未实现的方法: common/db/mongo_manager.py:320

- **unimplemented_method**: 未实现的方法: common/grpc/load_balancer.py:293

- **unimplemented_method**: 未实现的方法: common/grpc/load_balancer.py:297

- **unimplemented_method**: 未实现的方法: common/grpc/load_balancer.py:301

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:40

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:56

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:59

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:62

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:78

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:81

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:84

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:478

- **unimplemented_method**: 未实现的方法: common/grpc/grpc_server.py:517

- **unimplemented_method**: 未实现的方法: common/grpc/health_check.py:46

- **unimplemented_method**: 未实现的方法: common/grpc/health_check.py:50

- **unimplemented_method**: 未实现的方法: common/security/rate_limiter.py:104

- **unimplemented_method**: 未实现的方法: common/security/rate_limiter.py:109

- **unimplemented_method**: 未实现的方法: common/security/circuit_breaker.py:125

- **unimplemented_method**: 未实现的方法: common/security/circuit_breaker.py:131

- **unimplemented_method**: 未实现的方法: common/distributed/transaction.py:123

- **unimplemented_method**: 未实现的方法: common/distributed/transaction.py:128

- **unimplemented_method**: 未实现的方法: common/distributed/transaction.py:133

- **unimplemented_method**: 未实现的方法: common/distributed/transaction.py:146

- **unimplemented_method**: 未实现的方法: common/distributed/transaction.py:151

- **unimplemented_method**: 未实现的方法: common/distributed/transaction.py:156

- **unimplemented_method**: 未实现的方法: common/distributed/distributed_lock.py:112

- **unimplemented_method**: 未实现的方法: common/distributed/distributed_lock.py:117

- **unimplemented_method**: 未实现的方法: common/distributed/distributed_lock.py:122

- **unimplemented_method**: 未实现的方法: common/distributed/distributed_lock.py:127

- **unimplemented_method**: 未实现的方法: common/decorator/auth_decorator.py:324

- **unimplemented_method**: 未实现的方法: common/decorator/auth_decorator.py:399

- **unimplemented_method**: 未实现的方法: common/decorator/auth_decorator.py:476

- **unimplemented_method**: 未实现的方法: common/decorator/auth_decorator.py:554

- **unimplemented_method**: 未实现的方法: common/decorator/auth_decorator.py:639

- **unimplemented_method**: 未实现的方法: common/decorator/celery_decorator.py:223

- **unimplemented_method**: 未实现的方法: common/decorator/celery_decorator.py:227

- **unimplemented_method**: 未实现的方法: common/decorator/celery_decorator.py:319

- **unimplemented_method**: 未实现的方法: common/decorator/celery_decorator.py:427

- **unimplemented_method**: 未实现的方法: common/decorator/celery_decorator.py:483

- **unimplemented_method**: 未实现的方法: common/decorator/proto_decorator.py:340

- **unimplemented_method**: 未实现的方法: common/decorator/__init__.py:20

- **unimplemented_method**: 未实现的方法: common/decorator/__init__.py:29

- **unimplemented_method**: 未实现的方法: common/decorator/__init__.py:34

- **unimplemented_method**: 未实现的方法: common/decorator/__init__.py:38

- **unimplemented_method**: 未实现的方法: common/decorator/grpc_decorator.py:112

- **unimplemented_method**: 未实现的方法: common/decorator/grpc_decorator.py:179

- **unimplemented_method**: 未实现的方法: common/decorator/handler_decorator.py:195

- **unimplemented_method**: 未实现的方法: common/decorator/handler_decorator.py:274

- **unimplemented_method**: 未实现的方法: common/decorator/handler_decorator.py:402

- **unimplemented_method**: 未实现的方法: common/decorator/handler_decorator.py:446

- **unimplemented_method**: 未实现的方法: common/registry/etcd_adapter.py:44

- **unimplemented_method**: 未实现的方法: common/registry/etcd_adapter.py:48

- **unimplemented_method**: 未实现的方法: common/registry/base_adapter.py:165

- **unimplemented_method**: 未实现的方法: common/table/table_cache.py:105

- **unimplemented_method**: 未实现的方法: common/table/table_cache.py:308

- **unimplemented_method**: 未实现的方法: common/table/table_cache.py:316

- **unimplemented_method**: 未实现的方法: common/logger/logger_factory.py:244

- **unimplemented_method**: 未实现的方法: common/logger/mock_logger.py:50

- **unimplemented_method**: 未实现的方法: common/logger/mock_logger.py:54

- **unimplemented_method**: 未实现的方法: common/logger/base_logger.py:34

- **unimplemented_method**: 未实现的方法: common/logger/base_logger.py:37

- **unimplemented_method**: 未实现的方法: common/logger/base_logger.py:390

- **unimplemented_method**: 未实现的方法: common/logger/base_logger.py:419

- **unimplemented_method**: 未实现的方法: common/utils/validation.py:392

- **unimplemented_method**: 未实现的方法: common/utils/async_utils.py:185

- **unimplemented_method**: 未实现的方法: common/utils/async_utils.py:189

- **unimplemented_method**: 未实现的方法: services/logic/logic_handler.py:217

- **unimplemented_method**: 未实现的方法: services/logic/logic_handler.py:394

- **unimplemented_method**: 未实现的方法: services/logic/logic_server.py:60

- **unimplemented_method**: 未实现的方法: services/logic/logic_server.py:63

- **unimplemented_method**: 未实现的方法: services/logic/logic_server.py:66

- **unimplemented_method**: 未实现的方法: services/logic/logic_server.py:69

- **unimplemented_method**: 未实现的方法: services/logic/logic_server.py:72

- **unimplemented_method**: 未实现的方法: services/base/base_notify.py:66

- **unimplemented_method**: 未实现的方法: services/base/base_notify.py:76

- **unimplemented_method**: 未实现的方法: services/base/base_notify.py:78

- **unimplemented_method**: 未实现的方法: services/base/base_notify.py:81

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:72

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:74

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:76

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:78

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:86

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:88

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:90

- **unimplemented_method**: 未实现的方法: services/base/base_server.py:99

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:63

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:65

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:67

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:69

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:71

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:83

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:85

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:91

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:93

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:96

- **unimplemented_method**: 未实现的方法: services/base/base_service.py:582

- **unimplemented_method**: 未实现的方法: services/base/base_repository.py:68

- **unimplemented_method**: 未实现的方法: services/base/base_repository.py:231

- **unimplemented_method**: 未实现的方法: services/base/base_repository.py:233

- **unimplemented_method**: 未实现的方法: services/base/base_repository.py:235

- **unimplemented_method**: 未实现的方法: services/base/base_repository.py:237

- **unimplemented_method**: 未实现的方法: services/base/base_repository.py:239

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:55

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:58

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:83

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:85

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:98

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:100

- **unimplemented_method**: 未实现的方法: services/base/base_handler.py:103

- **unimplemented_method**: 未实现的方法: services/base/base_controller.py:62

- **unimplemented_method**: 未实现的方法: services/base/base_controller.py:64

- **unimplemented_method**: 未实现的方法: services/base/base_controller.py:589

- **unimplemented_method**: 未实现的方法: services/chat/chat_handler.py:230

- **unimplemented_method**: 未实现的方法: services/chat/chat_handler.py:447

- **unimplemented_method**: 未实现的方法: services/chat/chat_server.py:59

- **unimplemented_method**: 未实现的方法: services/chat/chat_server.py:62

- **unimplemented_method**: 未实现的方法: services/chat/chat_server.py:65

- **unimplemented_method**: 未实现的方法: services/chat/chat_server.py:68

- **unimplemented_method**: 未实现的方法: services/chat/chat_server.py:71

- **unimplemented_method**: 未实现的方法: services/gate/gate_server.py:65

- **unimplemented_method**: 未实现的方法: services/gate/gate_server.py:96

- **unimplemented_method**: 未实现的方法: services/gate/gate_server.py:110

- **unimplemented_method**: 未实现的方法: services/gate/session_manager.py:606

- **unimplemented_method**: 未实现的方法: services/gate/route_manager.py:563

## 🔄 重复实现
- **duplicate_class**: 发现重复类名: UserRepository
  - `demo_base_services.py`
  - `models/generated/user_repository.py`
  - `models/demo/user_repository.py`

- **duplicate_class**: 发现重复类名: UserService
  - `demo_base_services.py`
  - `services/logic/services/user_service.py`

- **duplicate_class**: 发现重复类名: UserController
  - `demo_base_services.py`
  - `services/logic/controllers/user_controller.py`

- **duplicate_class**: 发现重复类名: SimpleLogger
  - `simple_logger.py`
  - `common/grpc/interceptor.py`

- **duplicate_class**: 发现重复类名: LoggerFactory
  - `simple_logger.py`
  - `common/logger/logger_factory.py`

- **duplicate_class**: 发现重复类名: ServiceStatus
  - `server_launcher/service_manager.py`
  - `common/registry/base_adapter.py`

- **duplicate_class**: 发现重复类名: HealthStatus
  - `server_launcher/health_checker.py`
  - `common/grpc/health_check.py`

- **duplicate_class**: 发现重复类名: HealthCheckResult
  - `server_launcher/health_checker.py`
  - `common/grpc/health_check.py`
  - `common/registry/health_monitor.py`

- **duplicate_class**: 发现重复类名: HealthChecker
  - `server_launcher/health_checker.py`
  - `common/registry/base_adapter.py`

- **duplicate_class**: 发现重复类名: HealthCheckType
  - `server_launcher/service_config.py`
  - `common/registry/health_monitor.py`

- **duplicate_class**: 发现重复类名: HealthCheckConfig
  - `server_launcher/service_config.py`
  - `common/grpc/health_check.py`
  - `common/registry/health_monitor.py`

- **duplicate_class**: 发现重复类名: ServiceConfig
  - `server_launcher/service_config.py`
  - `services/base/base_service.py`

- **duplicate_class**: 发现重复类名: ServiceInfo
  - `server_launcher/banner.py`
  - `common/grpc/grpc_server.py`
  - `common/registry/base_adapter.py`

- **duplicate_class**: 发现重复类名: BaseConfig
  - `setting/config.py`
  - `common/table/types.py`

- **duplicate_class**: 发现重复类名: LoginRequest
  - `examples/proto_usage_example.py`
  - `proto/class_data/example_request.py`
  - `services/logic/controllers/user_controller.py`

- **duplicate_class**: 发现重复类名: LoginResponse
  - `examples/proto_usage_example.py`
  - `proto/class_data/example_response.py`
  - `services/logic/controllers/user_controller.py`

- **duplicate_class**: 发现重复类名: GateServer
  - `services/__init__.py`
  - `services/gate/gate_server.py`
  - `services/gate/__init__.py`

- **duplicate_class**: 发现重复类名: LogicServer
  - `services/__init__.py`
  - `services/logic/logic_server.py`
  - `services/logic/__init__.py`

- **duplicate_class**: 发现重复类名: ChatServer
  - `services/__init__.py`
  - `services/chat/__init__.py`
  - `services/chat/chat_server.py`

- **duplicate_class**: 发现重复类名: FightServer
  - `services/__init__.py`
  - `services/fight/__init__.py`

- **duplicate_class**: 发现重复类名: GetUserInfoRequest
  - `proto/class_data/example_request.py`
  - `services/logic/controllers/user_controller.py`

- **duplicate_class**: 发现重复类名: GetUserInfoResponse
  - `proto/class_data/example_response.py`
  - `services/logic/controllers/user_controller.py`

- **duplicate_class**: 发现重复类名: ProtoException
  - `common/proto/exceptions.py`
  - `services/base/base_handler.py`

- **duplicate_class**: 发现重复类名: ValidationException
  - `common/proto/exceptions.py`
  - `services/base/base_controller.py`

- **duplicate_class**: 发现重复类名: CompressionType
  - `common/proto/codec.py`
  - `common/utils/json_utils.py`
  - `common/notify/protocol_adapter.py`

- **duplicate_class**: 发现重复类名: ProtoCodec
  - `common/proto/codec.py`
  - `services/logic/logic_handler.py`
  - `services/logic/notify_service.py`
  - `services/base/base_notify.py`
  - `services/base/base_server.py`
  - `services/base/base_handler.py`
  - `services/chat/chat_handler.py`

- **duplicate_class**: 发现重复类名: MessageHeader
  - `common/proto/header.py`
  - `services/base/base_handler.py`

- **duplicate_class**: 发现重复类名: BaseRequest
  - `common/proto/base_proto.py`
  - `services/base/base_controller.py`
  - `services/logic/controllers/user_controller.py`
  - `services/logic/controllers/game_controller.py`
  - `services/logic/controllers/item_controller.py`

- **duplicate_class**: 发现重复类名: BaseResponse
  - `common/proto/base_proto.py`
  - `services/base/base_controller.py`
  - `services/logic/controllers/user_controller.py`
  - `services/logic/controllers/game_controller.py`
  - `services/logic/controllers/item_controller.py`

- **duplicate_class**: 发现重复类名: RedisConfig
  - `common/celery/config.py`
  - `common/db/redis_manager.py`

- **duplicate_class**: 发现重复类名: TaskStatus
  - `common/celery/delay_task.py`
  - `common/decorator/celery_decorator.py`
  - `services/logic/controllers/game_controller.py`
  - `services/logic/services/game_service.py`

- **duplicate_class**: 发现重复类名: TaskType
  - `common/celery/task_manager.py`
  - `services/logic/services/game_service.py`

- **duplicate_class**: 发现重复类名: TaskStatistics
  - `common/celery/task_manager.py`
  - `common/decorator/celery_decorator.py`

- **duplicate_class**: 发现重复类名: TaskInfo
  - `common/celery/task_manager.py`
  - `common/decorator/celery_decorator.py`

- **duplicate_class**: 发现重复类名: AsyncTaskManager
  - `common/celery/async_task.py`
  - `common/utils/async_utils.py`
  - `services/base/base_service.py`

- **duplicate_class**: 发现重复类名: CacheStrategy
  - `common/db/redis_manager.py`
  - `common/table/table_cache.py`
  - `common/table/types.py`

- **duplicate_class**: 发现重复类名: DistributedLock
  - `common/db/redis_manager.py`
  - `common/distributed/distributed_lock.py`

- **duplicate_class**: 发现重复类名: CacheStats
  - `common/db/cache_strategy.py`
  - `common/table/table_cache.py`

- **duplicate_class**: 发现重复类名: CacheError
  - `common/db/base_repository.py`
  - `common/table/exceptions.py`

- **duplicate_class**: 发现重复类名: BaseRepository
  - `common/db/base_repository.py`
  - `services/base/base_repository.py`

- **duplicate_class**: 发现重复类名: ConsistencyLevel
  - `common/db/consistency.py`
  - `common/distributed/consistency.py`

- **duplicate_class**: 发现重复类名: TransactionParticipant
  - `common/db/consistency.py`
  - `common/distributed/transaction.py`

- **duplicate_class**: 发现重复类名: OptimisticLock
  - `common/db/consistency.py`
  - `common/distributed/consistency.py`

- **duplicate_class**: 发现重复类名: TransactionError
  - `common/db/mongo_manager.py`
  - `common/distributed/transaction.py`

- **duplicate_class**: 发现重复类名: ValidationError
  - `common/db/base_document.py`
  - `common/utils/validation.py`

- **duplicate_class**: 发现重复类名: DocumentScanner
  - `common/db/auto_scanner.py`
  - `models/gen_utils/document_scanner.py`

- **duplicate_class**: 发现重复类名: StatusCode
  - `common/grpc/interceptor.py`
  - `common/grpc/connection.py`
  - `common/grpc/grpc_client.py`

- **duplicate_class**: 发现重复类名: grpc
  - `common/grpc/interceptor.py`
  - `common/grpc/connection.py`
  - `common/grpc/grpc_server.py`

- **duplicate_class**: 发现重复类名: ConnectionStats
  - `common/grpc/connection.py`
  - `common/registry/load_balancer.py`

- **duplicate_class**: 发现重复类名: aio
  - `common/grpc/connection.py`
  - `common/grpc/grpc_server.py`

- **duplicate_class**: 发现重复类名: LoadBalancer
  - `common/grpc/load_balancer.py`
  - `common/registry/load_balancer.py`

- **duplicate_class**: 发现重复类名: RoundRobinBalancer
  - `common/grpc/load_balancer.py`
  - `common/registry/load_balancer.py`

- **duplicate_class**: 发现重复类名: RandomBalancer
  - `common/grpc/load_balancer.py`
  - `common/registry/load_balancer.py`

- **duplicate_class**: 发现重复类名: ConsistentHashBalancer
  - `common/grpc/load_balancer.py`
  - `common/registry/load_balancer.py`

- **duplicate_class**: 发现重复类名: WeightedRoundRobinBalancer
  - `common/grpc/load_balancer.py`
  - `common/registry/load_balancer.py`

- **duplicate_class**: 发现重复类名: RateLimiter
  - `common/grpc/grpc_server.py`
  - `common/security/rate_limiter.py`

- **duplicate_class**: 发现重复类名: RateLimitRule
  - `common/security/rate_limiter.py`
  - `services/gate/middleware/rate_limit_middleware.py`

- **duplicate_class**: 发现重复类名: RateLimitConfig
  - `common/security/rate_limiter.py`
  - `services/gate/config.py`

- **duplicate_class**: 发现重复类名: CircuitBreakerConfig
  - `common/security/circuit_breaker.py`
  - `services/gate/config.py`

- **duplicate_class**: 发现重复类名: TransactionContext
  - `common/distributed/transaction.py`
  - `services/base/base_service.py`

- **duplicate_class**: 发现重复类名: RouteInfo
  - `common/decorator/handler_decorator.py`
  - `services/gate/route_manager.py`

- **duplicate_class**: 发现重复类名: HandlerStatistics
  - `common/decorator/handler_decorator.py`
  - `services/base/base_handler.py`

- **duplicate_class**: 发现重复类名: CacheEntry
  - `common/registry/service_discovery.py`
  - `common/table/table_cache.py`

- **duplicate_class**: 发现重复类名: LoadBalanceStrategy
  - `common/registry/load_balancer.py`
  - `services/gate/config.py`

- **duplicate_class**: 发现重复类名: RequestContext
  - `common/registry/load_balancer.py`
  - `services/base/base_handler.py`
  - `services/base/base_controller.py`
  - `services/gate/gate_handler.py`

- **duplicate_class**: 发现重复类名: CacheConfig
  - `common/table/types.py`
  - `services/base/base_repository.py`

- **duplicate_class**: 发现重复类名: MockLogger
  - `common/logger/mock_logger.py`
  - `common/logger/base_logger.py`

- **duplicate_class**: 发现重复类名: LogLevel
  - `common/logger/logger_config.py`
  - `services/gate/middleware/log_middleware.py`

- **duplicate_class**: 发现重复类名: MessageType
  - `common/notify/push_service.py`
  - `services/base/base_handler.py`

- **duplicate_class**: 发现重复类名: MessagePriority
  - `common/notify/notify_queue.py`
  - `services/base/base_notify.py`

- **duplicate_class**: 发现重复类名: ConnectionStatus
  - `common/notify/notify_manager.py`
  - `services/gate/websocket_manager.py`

- **duplicate_class**: 发现重复类名: NotifyStatistics
  - `common/notify/notify_manager.py`
  - `services/base/base_notify.py`

- **duplicate_class**: 发现重复类名: HeroConfig
  - `json_data/generated/class_data/hero_config.py`
  - `json_data/demo/class_data/hero_config.py`

- **duplicate_class**: 发现重复类名: OrderRepository
  - `models/generated/order_repository.py`
  - `models/demo/order_repository.py`

- **duplicate_class**: 发现重复类名: MockGrpcServer
  - `services/logic/logic_server.py`
  - `services/chat/chat_server.py`

- **duplicate_class**: 发现重复类名: MonitorManager
  - `services/base/base_notify.py`
  - `services/base/base_server.py`
  - `services/base/base_service.py`
  - `services/base/base_handler.py`

- **duplicate_class**: 发现重复类名: SecurityManager
  - `services/base/base_server.py`
  - `services/base/base_handler.py`
  - `services/base/base_controller.py`

- **duplicate_class**: 发现重复类名: TransactionManager
  - `services/base/base_service.py`
  - `services/base/base_repository.py`

- **duplicate_class**: 发现重复类名: MockResult
  - `services/base/base_repository.py`
  - `services/base/base_repository.py`
  - `services/base/base_repository.py`
  - `services/base/base_repository.py`

- **duplicate_class**: 发现重复类名: ResponseContext
  - `services/base/base_handler.py`
  - `services/base/base_controller.py`

- **duplicate_class**: 发现重复类名: BaseController
  - `services/base/base_controller.py`
  - `services/gate/controllers/base_controller.py`

- **duplicate_class**: 发现重复类名: GameController
  - `services/logic/controllers/game_controller.py`
  - `services/gate/controllers/game_controller.py`

- **duplicate_class**: 发现重复类名: ItemType
  - `services/logic/controllers/item_controller.py`
  - `services/logic/services/item_service.py`

- **duplicate_class**: 发现重复类名: ItemRarity
  - `services/logic/controllers/item_controller.py`
  - `services/logic/services/item_service.py`

- **duplicate_class**: 发现重复类名: EquipmentSlot
  - `services/logic/controllers/item_controller.py`
  - `services/logic/services/item_service.py`

- **duplicate_function**: 关键函数 start 在多个文件中定义
  - `server_launcher/process_pool.py`
  - `server_launcher/process_pool.py`
  - `common/grpc/grpc_server.py`
  - `common/table/hot_reload.py`
  - `common/table/hot_reload.py`

- **duplicate_function**: 关键函数 stop 在多个文件中定义
  - `server_launcher/process_pool.py`
  - `server_launcher/process_pool.py`
  - `common/grpc/grpc_server.py`
  - `common/table/hot_reload.py`
  - `common/table/hot_reload.py`

- **duplicate_function**: 关键函数 close 在多个文件中定义
  - `common/grpc/connection.py`
  - `common/logger/sls_logger.py`
  - `common/logger/battle_logger.py`
  - `common/logger/base_logger.py`

## 🔗 模块依赖关系
- `test_gateway` 依赖:
  - `services.gate.config`
  - `services.gate.gate_handler`
  - `services.gate.middleware.auth_middleware`
  - `services.gate.middleware.error_middleware`
  - `services.gate.middleware.log_middleware`
  - `services.gate.middleware.rate_limit_middleware`
  - `services.gate.route_manager`
  - `services.gate.services.auth_service`
  - `services.gate.services.notify_service`
  - `services.gate.services.proxy_service`
  - `services.gate.services.route_service`
  - `services.gate.session_manager`
  - `services.gate.websocket_manager`

- `test_grpc_basic` 依赖:
  - `common.grpc`
  - `common.grpc.health_check`

- `demo_base_services` 依赖:
  - `services.base`

- `validate_grpc_requirements` 依赖:
  - `common.grpc.exceptions`
  - `common.grpc.grpc_client`
  - `common.grpc.grpc_pool`
  - `common.grpc.grpc_server`
  - `common.grpc.health_check`
  - `common.grpc.interceptor`
  - `common.grpc.load_balancer`

- `test_gateway_basic` 依赖:
  - `services.gate.config`
  - `services.gate.middleware.auth_middleware`
  - `services.gate.middleware.error_middleware`
  - `services.gate.middleware.log_middleware`
  - `services.gate.middleware.rate_limit_middleware`
  - `services.gate.route_manager`

- `server_launcher.launcher` 依赖:
  - `common.logger`

- `server_launcher.service_manager` 依赖:
  - `common.logger`

- `server_launcher.process_pool` 依赖:
  - `common.logger`

- `server_launcher.health_checker` 依赖:
  - `common.logger`

- `server_launcher.service_config` 依赖:
  - `common.logger`

- `server_launcher.banner` 依赖:
  - `common.logger`

- `server_launcher.cli` 依赖:
  - `common.logger`

- `server_launcher.process_monitor` 依赖:
  - `common.logger`

- `server_launcher.utils` 依赖:
  - `common.logger`

- `tests.test_security_distributed_basic` 依赖:
  - `common.distributed`
  - `common.security`

- `tests.test_db_module` 依赖:
  - `common.db.base_document`
  - `common.db.base_repository`
  - `common.db.mongo_manager`
  - `common.db.redis_manager`

- `scripts.verify_startup` 依赖:
  - `common.db`
  - `common.db.mongo_manager`
  - `common.db.redis_manager`
  - `common.distributed`
  - `common.distributed.consistency`
  - `common.distributed.id_generator`
  - `common.distributed.transaction`
  - `common.grpc`
  - `common.grpc.load_balancer`
  - `common.logger`
  - `common.monitor`
  - `common.notify`
  - `common.proto`
  - `common.proto.header`
  - `common.security`
  - `services.base`
  - `services.chat`
  - `services.fight`
  - `services.gate`
  - `services.logic`

- `examples.registry_example` 依赖:
  - `common.registry`

- `examples.proto_usage_example` 依赖:
  - `common.proto`

- `examples.grpc_example` 依赖:
  - `common.grpc`
  - `common.grpc.health_check`
  - `common.grpc.interceptor`

- `examples.logger_example` 依赖:
  - `common.logger`

- `proto.class_data.example_request` 依赖:
  - `common.proto.base_proto`

- `proto.class_data.example_response` 依赖:
  - `common.proto.base_proto`

- `proto.gen_utils.generator_main` 依赖:
  - `common.logger`

- `proto.gen_utils.type_converter` 依赖:
  - `common.logger`

- `proto.gen_utils.proto_generator` 依赖:
  - `common.logger`

- `proto.gen_utils.proto_scanner` 依赖:
  - `common.logger`

- `common.celery.delay_task` 依赖:
  - `common.logger`

- `common.celery.beat_schedule` 依赖:
  - `common.logger`

- `common.celery.task_manager` 依赖:
  - `common.logger`

- `common.celery.async_task` 依赖:
  - `common.logger`

- `common.celery.celery_app` 依赖:
  - `common.logger`

- `common.celery.decorators` 依赖:
  - `common.logger`

- `common.db.redis_manager` 依赖:
  - `common.logger`
  - `common.utils.singleton`

- `common.db.cache_strategy` 依赖:
  - `common.logger`

- `common.db.base_repository` 依赖:
  - `common.logger`

- `common.db` 依赖:
  - `common.logger`

- `common.db.consistency` 依赖:
  - `common.logger`

- `common.db.mongo_manager` 依赖:
  - `common.logger`
  - `common.utils.singleton`

- `common.db.base_document` 依赖:
  - `common.logger`
  - `common.utils.id_generator`

- `common.db.auto_scanner` 依赖:
  - `common.logger`

- `common.grpc.interceptor` 依赖:
  - `common.logger`
  - `common.monitor`

- `common.security.rate_limiter` 依赖:
  - `common.logger`

- `common.security.circuit_breaker` 依赖:
  - `common.logger`

- `common.security.jwt_auth` 依赖:
  - `common.logger`

- `common.security.signature` 依赖:
  - `common.logger`

- `common.distributed.transaction` 依赖:
  - `common.logger`

- `common.distributed.distributed_lock` 依赖:
  - `common.logger`

- `common.distributed.consistency` 依赖:
  - `common.logger`

- `common.distributed.id_generator` 依赖:
  - `common.logger`

- `common.decorator.auth_decorator` 依赖:
  - `common.logger`

- `common.decorator.celery_decorator` 依赖:
  - `common.logger`

- `common.decorator.proto_decorator` 依赖:
  - `common.logger`

- `common.decorator.grpc_decorator` 依赖:
  - `common.logger`

- `common.decorator.handler_decorator` 依赖:
  - `common.logger`

- `common.table.hot_reload` 依赖:
  - `common.logger`

- `common.table.table_loader` 依赖:
  - `common.logger`

- `common.table.table_manager` 依赖:
  - `common.logger`

- `common.notify.push_service` 依赖:
  - `common.logger`

- `common.notify.protocol_adapter` 依赖:
  - `common.logger`

- `common.notify.notify_queue` 依赖:
  - `common.logger`

- `common.notify.notify_manager` 依赖:
  - `common.logger`

- `json_data.gen_utils.generator_main` 依赖:
  - `common.logger`

- `json_data.gen_utils.excel_parser` 依赖:
  - `common.logger`

- `json_data.gen_utils.json_generator` 依赖:
  - `common.logger`

- `json_data.gen_utils.class_generator` 依赖:
  - `common.logger`

- `models.generated.user_repository` 依赖:
  - `common.db.base_repository`
  - `common.logger`

- `models.generated.order_repository` 依赖:
  - `common.db.base_repository`
  - `common.logger`

- `models.gen_utils.generator_main` 依赖:
  - `common.logger`

- `models.gen_utils.repository_generator` 依赖:
  - `common.logger`

- `models.gen_utils.document_scanner` 依赖:
  - `common.logger`

- `models.demo.user_repository` 依赖:
  - `common.db.base_repository`
  - `common.logger`

- `models.demo.order_repository` 依赖:
  - `common.db.base_repository`
  - `common.logger`

- `models.document.example_document` 依赖:
  - `common.db.base_document`

- `tests.integration.test_framework_integration` 依赖:
  - `common.db`
  - `common.db.base_document`
  - `common.db.mongo_manager`
  - `common.db.redis_manager`
  - `common.distributed`
  - `common.distributed.consistency`
  - `common.distributed.id_generator`
  - `common.grpc`
  - `common.logger`
  - `common.proto`
  - `services.base`

- `tests.integration.test_logger_integration` 依赖:
  - `common.logger`

- `tests.unit.test_proto` 依赖:
  - `common.proto`

- `tests.unit.test_logger` 依赖:
  - `common.logger`

- `tests.performance.test_logger_performance` 依赖:
  - `common.logger`

- `services.logic.logic_handler` 依赖:
  - `common.decorator`
  - `common.logger`
  - `common.proto`
  - `services.base`

- `services.logic.logic_server` 依赖:
  - `common.logger`
  - `services.base`
  - `services.game_service`
  - `services.item_service`
  - `services.user_service`

- `services.logic.notify_service` 依赖:
  - `common.logger`
  - `common.proto`
  - `services.base`

- `services.base.base_notify` 依赖:
  - `common.grpc.grpc_client`
  - `common.logger`
  - `common.monitor`
  - `common.notify.notify_manager`
  - `common.proto`

- `services.base.base_server` 依赖:
  - `common.decorator.handler_decorator`
  - `common.grpc.grpc_server`
  - `common.logger`
  - `common.monitor`
  - `common.proto`
  - `common.registry`
  - `common.security`

- `services.base.base_service` 依赖:
  - `common.celery.async_task`
  - `common.db`
  - `common.grpc.grpc_client`
  - `common.logger`
  - `common.monitor`

- `services.base.base_repository` 依赖:
  - `common.db`
  - `common.logger`

- `services.base.base_handler` 依赖:
  - `common.decorator.handler_decorator`
  - `common.logger`
  - `common.monitor`
  - `common.proto`
  - `common.proto.header`
  - `common.security`

- `services.base.base_controller` 依赖:
  - `common.decorator.handler_decorator`
  - `common.logger`
  - `common.proto`
  - `common.security`

- `services.chat.chat_handler` 依赖:
  - `common.decorator`
  - `common.logger`
  - `common.proto`
  - `services.base`

- `services.chat.chat_server` 依赖:
  - `common.logger`
  - `services.base`
  - `services.channel_service`
  - `services.chat_service`
  - `services.filter_service`

- `services.gate.config` 依赖:
  - `common.logger`

- `services.gate.gate_handler` 依赖:
  - `common.logger`
  - `common.monitor`
  - `common.proto`

- `services.gate.gate_server` 依赖:
  - `common.logger`
  - `services.auth_service`
  - `services.base.base_server`
  - `services.notify_service`
  - `services.proxy_service`
  - `services.route_service`

- `services.gate.websocket_manager` 依赖:
  - `common.logger`
  - `common.utils.singleton`

- `services.gate.session_manager` 依赖:
  - `common.db.redis_manager`
  - `common.logger`
  - `common.security`
  - `common.utils.singleton`

- `services.gate.route_manager` 依赖:
  - `common.logger`
  - `common.utils.singleton`

- `services.logic.controllers.user_controller` 依赖:
  - `common.decorator`
  - `common.logger`
  - `common.proto`
  - `services.base`

- `services.logic.controllers.game_controller` 依赖:
  - `common.decorator`
  - `common.logger`
  - `common.proto`
  - `services.base`

- `services.logic.controllers.item_controller` 依赖:
  - `common.decorator`
  - `common.logger`
  - `common.proto`
  - `services.base`

- `services.logic.services.game_service` 依赖:
  - `common.logger`
  - `services.base`

- `services.logic.services.user_service` 依赖:
  - `common.logger`
  - `services.base`

- `services.logic.services.item_service` 依赖:
  - `common.logger`
  - `services.base`

- `services.gate.controllers.chat_controller` 依赖:
  - `common.logger`

- `services.gate.controllers.game_controller` 依赖:
  - `common.logger`

- `services.gate.controllers.auth_controller` 依赖:
  - `common.logger`
  - `common.security`

- `services.gate.controllers.base_controller` 依赖:
  - `common.logger`
  - `services.base.base_controller`

- `services.gate.middleware.error_middleware` 依赖:
  - `common.logger`

- `services.gate.middleware.auth_middleware` 依赖:
  - `common.logger`
  - `common.security`

- `services.gate.middleware.log_middleware` 依赖:
  - `common.logger`

- `services.gate.middleware.rate_limit_middleware` 依赖:
  - `common.logger`
  - `common.security`

- `services.gate.services.proxy_service` 依赖:
  - `common.grpc`
  - `common.logger`
  - `common.proto`

- `services.gate.services.route_service` 依赖:
  - `common.grpc`
  - `common.logger`

- `services.gate.services.notify_service` 依赖:
  - `common.db.redis_manager`
  - `common.logger`

- `services.gate.services.auth_service` 依赖:
  - `common.db.redis_manager`
  - `common.logger`
  - `common.security`

## 💡 改进建议
3. 检查并合并重复的实现
4. 处理警告信息，提高代码质量

## 总结
✅ 框架整体结构良好，可以正常运行