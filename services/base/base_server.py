"""
基础服务器类模块

该模块提供了所有微服务的基础服务器类，整合了gRPC服务、多进程支持、
异步事件循环、服务注册发现、优雅关闭、自动加载等核心功能。

主要功能：
- 继承并封装gRPC服务器功能
- 支持多进程启动（multiprocessing）
- 支持asyncio事件循环
- 服务注册与发现集成
- 优雅关闭机制
- 自动加载controllers和services
- 心跳检测
- 性能监控接入点
- 日志初始化
- 配置加载

使用示例：
```python
from services.base.base_server import BaseServer

class LogicServer(BaseServer):
    def __init__(self):
        super().__init__(service_name="logic_server")
    
    async def on_startup(self):
        await super().on_startup()
        self.logger.info("Logic server started")
    
    async def on_shutdown(self):
        await super().on_shutdown()
        self.logger.info("Logic server stopped")

if __name__ == "__main__":
    server = LogicServer()
    server.run()
```
"""

import asyncio
import multiprocessing
import signal
import sys
import time
import threading
import importlib
import pkgutil
from typing import Dict, List, Optional, Any, Callable, Type, Union
from dataclasses import dataclass, field
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

try:
    import grpc
    import grpc.aio
    from grpc import StatusCode
    GRPC_AVAILABLE = True
except ImportError:
    GRPC_AVAILABLE = False

from common.logger import logger
from common.grpc.grpc_server import ServerConfig, GrpcServer
from common.registry import ServiceRegistry, ServiceInfo
try:
    from common.monitor import MonitorManager
except ImportError:
    # Mock MonitorManager if not available
    class MonitorManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
        async def start(self):
            pass
        async def stop(self):
            pass

try:
    from common.security import SecurityManager
except ImportError:
    # Mock SecurityManager if not available
    class SecurityManager:
        def __init__(self, *args, **kwargs):
            pass
        async def initialize(self):
            pass
        async def cleanup(self):
            pass

from common.decorator.handler_decorator import get_handler_registry
try:
    from common.proto import ProtoCodec, initialize_proto_system
except ImportError:
    # Mock proto classes if not available
    class ProtoCodec:
        def __init__(self):
            pass
    
    def initialize_proto_system():
        return ProtoCodec()


@dataclass
class BaseServerConfig:
    """基础服务器配置"""
    # 服务基本信息
    service_name: str = "base_server"
    service_version: str = "1.0.0"
    service_description: str = "基础服务器"
    
    # 网络配置
    host: str = "0.0.0.0"
    port: int = 50051
    
    # 进程配置
    enable_multiprocessing: bool = False
    process_count: int = multiprocessing.cpu_count()
    
    # 异步配置
    event_loop_policy: str = "asyncio"  # asyncio, uvloop
    
    # 服务注册配置
    enable_service_registry: bool = True
    registry_host: str = "localhost"
    registry_port: int = 8500
    
    # 健康检查配置
    enable_health_check: bool = True
    health_check_interval: int = 30
    heartbeat_interval: int = 10
    
    # 自动加载配置
    auto_load_controllers: bool = True
    auto_load_services: bool = True
    controllers_package: str = "controllers"
    services_package: str = "services"
    
    # 性能监控配置
    enable_monitoring: bool = True
    metrics_port: int = 9090
    
    # 日志配置
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    # 安全配置
    enable_tls: bool = False
    cert_file: Optional[str] = None
    key_file: Optional[str] = None
    
    # 其他配置
    graceful_shutdown_timeout: int = 30
    max_workers: int = 10
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseServer:
    """
    基础服务器类
    
    所有微服务的基础类，提供统一的服务器功能：
    - gRPC服务器管理
    - 多进程支持
    - 异步事件循环
    - 服务注册发现
    - 优雅关闭
    - 自动加载
    - 心跳检测
    - 性能监控
    - 日志管理
    - 配置管理
    """
    
    def __init__(self, config: Optional[BaseServerConfig] = None, **kwargs):
        """
        初始化基础服务器
        
        Args:
            config: 服务器配置，如果为None则使用默认配置
            **kwargs: 额外的配置参数，会覆盖config中的对应参数
        """
        # 配置初始化
        self.config = config or BaseServerConfig()
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        
        # 基础属性
        self.service_name = self.config.service_name
        self.service_version = self.config.service_version
        self.logger = logger
        
        # 运行状态
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._startup_tasks: List[asyncio.Task] = []
        self._shutdown_tasks: List[asyncio.Task] = []
        
        # 核心组件
        self._grpc_server: Optional[GrpcServer] = None
        self._service_registry: Optional[ServiceRegistry] = None
        self._monitor_manager: Optional[MonitorManager] = None
        self._security_manager: Optional[SecurityManager] = None
        self._proto_codec: Optional[ProtoCodec] = None
        
        # 心跳和健康检查
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        
        # 加载的组件
        self._controllers: Dict[str, Any] = {}
        self._services: Dict[str, Any] = {}
        self._handler_registry = get_handler_registry()
        
        # 进程管理
        self._processes: List[multiprocessing.Process] = []
        self._process_manager: Optional[multiprocessing.Manager] = None
        
        # 信号处理
        self._signal_handlers: Dict[int, Callable] = {}
        
        self.logger.info("基础服务器初始化完成", 
                        service_name=self.service_name,
                        service_version=self.service_version)
    
    async def initialize(self):
        """
        初始化服务器
        
        按顺序初始化所有组件：
        1. 协议系统
        2. 安全管理器
        3. 监控管理器
        4. 服务注册
        5. gRPC服务器
        6. 自动加载组件
        """
        self.logger.info("开始初始化服务器", service_name=self.service_name)
        
        try:
            # 1. 初始化协议系统
            await self._initialize_proto_system()
            
            # 2. 初始化安全管理器
            await self._initialize_security_manager()
            
            # 3. 初始化监控管理器
            await self._initialize_monitor_manager()
            
            # 4. 初始化服务注册
            await self._initialize_service_registry()
            
            # 5. 初始化gRPC服务器
            await self._initialize_grpc_server()
            
            # 6. 自动加载组件
            await self._auto_load_components()
            
            # 7. 设置信号处理
            self._setup_signal_handlers()
            
            self.logger.info("服务器初始化完成", service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("服务器初始化失败", 
                            service_name=self.service_name,
                            error=str(e))
            raise
    
    async def start(self):
        """
        启动服务器
        
        启动所有组件并进入运行状态
        """
        if self._running:
            self.logger.warning("服务器已经在运行中", service_name=self.service_name)
            return
        
        self.logger.info("开始启动服务器", service_name=self.service_name)
        
        try:
            # 调用用户自定义的启动前钩子
            await self.on_startup()
            
            # 启动gRPC服务器
            if self._grpc_server:
                await self._grpc_server.start()
            
            # 注册服务
            if self._service_registry:
                await self._register_service()
            
            # 启动心跳检测
            if self.config.enable_health_check:
                await self._start_heartbeat()
            
            # 启动监控
            if self._monitor_manager:
                await self._monitor_manager.start()
            
            # 设置运行状态
            self._running = True
            
            self.logger.info("服务器启动完成", 
                           service_name=self.service_name,
                           host=self.config.host,
                           port=self.config.port)
            
        except Exception as e:
            self.logger.error("服务器启动失败", 
                            service_name=self.service_name,
                            error=str(e))
            await self.stop()
            raise
    
    async def stop(self):
        """
        停止服务器
        
        优雅关闭所有组件
        """
        if not self._running:
            self.logger.warning("服务器未在运行中", service_name=self.service_name)
            return
        
        self.logger.info("开始停止服务器", service_name=self.service_name)
        
        try:
            # 设置关闭标志
            self._running = False
            self._shutdown_event.set()
            
            # 停止心跳检测
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            
            # 停止健康检查
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
            
            # 注销服务
            if self._service_registry:
                await self._unregister_service()
            
            # 停止gRPC服务器
            if self._grpc_server:
                await self._grpc_server.stop()
            
            # 停止监控
            if self._monitor_manager:
                await self._monitor_manager.stop()
            
            # 调用用户自定义的关闭钩子
            await self.on_shutdown()
            
            # 清理资源
            await self._cleanup_resources()
            
            self.logger.info("服务器停止完成", service_name=self.service_name)
            
        except Exception as e:
            self.logger.error("服务器停止失败", 
                            service_name=self.service_name,
                            error=str(e))
            raise
    
    def run(self):
        """
        运行服务器
        
        根据配置选择单进程或多进程模式运行
        """
        if self.config.enable_multiprocessing:
            self._run_multiprocessing()
        else:
            self._run_single_process()
    
    def _run_single_process(self):
        """单进程模式运行"""
        self.logger.info("以单进程模式运行服务器", service_name=self.service_name)
        
        # 设置事件循环策略
        if self.config.event_loop_policy == "uvloop":
            try:
                import uvloop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            except ImportError:
                self.logger.warning("uvloop不可用，使用默认事件循环策略")
        
        # 运行主循环
        try:
            asyncio.run(self._main_loop())
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号，正在关闭服务器")
        except Exception as e:
            self.logger.error("服务器运行异常", error=str(e))
        finally:
            self.logger.info("服务器运行结束")
    
    def _run_multiprocessing(self):
        """多进程模式运行"""
        self.logger.info("以多进程模式运行服务器", 
                        service_name=self.service_name,
                        process_count=self.config.process_count)
        
        # 创建进程管理器
        self._process_manager = multiprocessing.Manager()
        
        # 启动子进程
        for i in range(self.config.process_count):
            process = multiprocessing.Process(
                target=self._worker_process,
                args=(i,),
                name=f"{self.service_name}_worker_{i}"
            )
            process.start()
            self._processes.append(process)
            self.logger.info("启动工作进程", 
                           service_name=self.service_name,
                           process_id=i,
                           pid=process.pid)
        
        # 等待所有进程结束
        try:
            for process in self._processes:
                process.join()
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号，正在关闭所有进程")
            self._terminate_all_processes()
        except Exception as e:
            self.logger.error("多进程运行异常", error=str(e))
            self._terminate_all_processes()
    
    def _worker_process(self, process_id: int):
        """工作进程入口"""
        self.logger.info("工作进程启动", 
                        service_name=self.service_name,
                        process_id=process_id)
        
        # 为每个进程设置不同的端口
        self.config.port += process_id
        
        try:
            asyncio.run(self._main_loop())
        except Exception as e:
            self.logger.error("工作进程异常", 
                            service_name=self.service_name,
                            process_id=process_id,
                            error=str(e))
    
    def _terminate_all_processes(self):
        """终止所有子进程"""
        for process in self._processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
    
    async def _main_loop(self):
        """主事件循环"""
        try:
            # 初始化服务器
            await self.initialize()
            
            # 启动服务器
            await self.start()
            
            # 等待关闭信号
            await self._shutdown_event.wait()
            
        except Exception as e:
            self.logger.error("主循环异常", error=str(e))
            raise
        finally:
            # 停止服务器
            await self.stop()
    
    async def _initialize_proto_system(self):
        """初始化协议系统"""
        try:
            self._proto_codec = initialize_proto_system()
            self.logger.info("协议系统初始化完成")
        except Exception as e:
            self.logger.error("协议系统初始化失败", error=str(e))
            raise
    
    async def _initialize_security_manager(self):
        """初始化安全管理器"""
        try:
            self._security_manager = SecurityManager()
            await self._security_manager.initialize()
            self.logger.info("安全管理器初始化完成")
        except Exception as e:
            self.logger.error("安全管理器初始化失败", error=str(e))
            raise
    
    async def _initialize_monitor_manager(self):
        """初始化监控管理器"""
        if not self.config.enable_monitoring:
            return
        
        try:
            self._monitor_manager = MonitorManager(
                service_name=self.service_name,
                metrics_port=self.config.metrics_port
            )
            await self._monitor_manager.initialize()
            self.logger.info("监控管理器初始化完成")
        except Exception as e:
            self.logger.error("监控管理器初始化失败", error=str(e))
            raise
    
    async def _initialize_service_registry(self):
        """初始化服务注册"""
        if not self.config.enable_service_registry:
            return
        
        try:
            self._service_registry = ServiceRegistry(
                host=self.config.registry_host,
                port=self.config.registry_port
            )
            await self._service_registry.initialize()
            self.logger.info("服务注册初始化完成")
        except Exception as e:
            self.logger.error("服务注册初始化失败", error=str(e))
            raise
    
    async def _initialize_grpc_server(self):
        """初始化gRPC服务器"""
        if not GRPC_AVAILABLE:
            self.logger.warning("gRPC不可用，跳过gRPC服务器初始化")
            return
        
        try:
            server_config = ServerConfig(
                host=self.config.host,
                port=self.config.port,
                max_workers=self.config.max_workers,
                enable_health_check=self.config.enable_health_check,
                enable_reflection=True
            )
            
            self._grpc_server = GrpcServer(server_config)
            await self._grpc_server.initialize()
            self.logger.info("gRPC服务器初始化完成")
        except Exception as e:
            self.logger.error("gRPC服务器初始化失败", error=str(e))
            raise
    
    async def _auto_load_components(self):
        """自动加载组件"""
        if self.config.auto_load_controllers:
            await self._load_controllers()
        
        if self.config.auto_load_services:
            await self._load_services()
    
    async def _load_controllers(self):
        """加载控制器"""
        try:
            package_name = f"{self.service_name}.{self.config.controllers_package}"
            await self._load_modules(package_name, self._controllers, "Controller")
            self.logger.info("控制器加载完成", count=len(self._controllers))
        except Exception as e:
            self.logger.error("控制器加载失败", error=str(e))
    
    async def _load_services(self):
        """加载服务"""
        try:
            package_name = f"{self.service_name}.{self.config.services_package}"
            await self._load_modules(package_name, self._services, "Service")
            self.logger.info("服务加载完成", count=len(self._services))
        except Exception as e:
            self.logger.error("服务加载失败", error=str(e))
    
    async def _load_modules(self, package_name: str, container: Dict[str, Any], suffix: str):
        """加载模块"""
        try:
            package = importlib.import_module(package_name)
            for finder, name, ispkg in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
                if not ispkg:
                    module = importlib.import_module(name)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and 
                            attr_name.endswith(suffix) and 
                            attr_name != suffix):
                            instance = attr()
                            container[attr_name] = instance
        except ImportError:
            self.logger.warning(f"包 {package_name} 不存在，跳过加载")
    
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"收到信号 {signum}，开始关闭服务器")
            self._shutdown_event.set()
        
        self._signal_handlers[signal.SIGINT] = signal_handler
        self._signal_handlers[signal.SIGTERM] = signal_handler
        
        for sig, handler in self._signal_handlers.items():
            signal.signal(sig, handler)
    
    async def _register_service(self):
        """注册服务"""
        if not self._service_registry:
            return
        
        try:
            service_info = ServiceInfo(
                name=self.service_name,
                version=self.service_version,
                host=self.config.host,
                port=self.config.port,
                metadata=self.config.metadata
            )
            
            await self._service_registry.register_service(service_info)
            self.logger.info("服务注册成功", service_name=self.service_name)
        except Exception as e:
            self.logger.error("服务注册失败", error=str(e))
            raise
    
    async def _unregister_service(self):
        """注销服务"""
        if not self._service_registry:
            return
        
        try:
            await self._service_registry.unregister_service(self.service_name)
            self.logger.info("服务注销成功", service_name=self.service_name)
        except Exception as e:
            self.logger.error("服务注销失败", error=str(e))
    
    async def _start_heartbeat(self):
        """启动心跳检测"""
        async def heartbeat_loop():
            while self._running:
                try:
                    await self._send_heartbeat()
                    await asyncio.sleep(self.config.heartbeat_interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error("心跳检测失败", error=str(e))
                    await asyncio.sleep(self.config.heartbeat_interval)
        
        self._heartbeat_task = asyncio.create_task(heartbeat_loop())
        self.logger.info("心跳检测启动")
    
    async def _send_heartbeat(self):
        """发送心跳"""
        if self._service_registry:
            await self._service_registry.heartbeat(self.service_name)
    
    async def _cleanup_resources(self):
        """清理资源"""
        # 清理控制器
        for controller in self._controllers.values():
            if hasattr(controller, 'cleanup'):
                try:
                    await controller.cleanup()
                except Exception as e:
                    self.logger.error("控制器清理失败", error=str(e))
        
        # 清理服务
        for service in self._services.values():
            if hasattr(service, 'cleanup'):
                try:
                    await service.cleanup()
                except Exception as e:
                    self.logger.error("服务清理失败", error=str(e))
        
        # 清理其他资源
        if self._security_manager:
            await self._security_manager.cleanup()
    
    # 生命周期钩子方法（子类可以重写）
    async def on_startup(self):
        """
        启动时的钩子方法
        
        子类可以重写此方法来添加自定义的启动逻辑
        """
        pass
    
    async def on_shutdown(self):
        """
        关闭时的钩子方法
        
        子类可以重写此方法来添加自定义的关闭逻辑
        """
        pass
    
    # 属性访问方法
    @property
    def is_running(self) -> bool:
        """检查服务器是否在运行"""
        return self._running
    
    @property
    def grpc_server(self) -> Optional[GrpcServer]:
        """获取gRPC服务器实例"""
        return self._grpc_server
    
    @property
    def service_registry(self) -> Optional[ServiceRegistry]:
        """获取服务注册实例"""
        return self._service_registry
    
    @property
    def monitor_manager(self) -> Optional[MonitorManager]:
        """获取监控管理器实例"""
        return self._monitor_manager
    
    @property
    def security_manager(self) -> Optional[SecurityManager]:
        """获取安全管理器实例"""
        return self._security_manager
    
    @property
    def controllers(self) -> Dict[str, Any]:
        """获取已加载的控制器"""
        return self._controllers.copy()
    
    @property
    def services(self) -> Dict[str, Any]:
        """获取已加载的服务"""
        return self._services.copy()
    
    def get_controller(self, name: str) -> Optional[Any]:
        """获取指定名称的控制器"""
        return self._controllers.get(name)
    
    def get_service(self, name: str) -> Optional[Any]:
        """获取指定名称的服务"""
        return self._services.get(name)
    
    def add_controller(self, name: str, controller: Any):
        """添加控制器"""
        self._controllers[name] = controller
        self.logger.info("控制器添加成功", name=name)
    
    def add_service(self, name: str, service: Any):
        """添加服务"""
        self._services[name] = service
        self.logger.info("服务添加成功", name=name)