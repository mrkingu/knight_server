"""
网关服务器主程序

该模块实现了基于Sanic + WebSocket的高性能网关服务器，继承自BaseServer，
提供WebSocket长连接支持、请求路由、协议转换等功能。

主要功能：
- 继承自BaseServer
- 初始化Sanic应用，配置uvloop
- 注册所有路由和中间件
- 实现WebSocket端点
- 启动时自动注册到服务注册中心
- 优雅关闭处理
"""

import asyncio
import signal
import sys
from typing import Optional, Dict, Any
import traceback

from services.base.base_server import BaseServer
from common.logger import logger
from .config import GatewayConfig, load_config
from .websocket_manager import WebSocketManager, create_websocket_manager
from .session_manager import SessionManager, create_session_manager
from .route_manager import RouteManager, create_route_manager
from .gate_handler import GateHandler, create_gate_handler

# 导入控制器
from .controllers.auth_controller import AuthController
from .controllers.game_controller import GameController
from .controllers.chat_controller import ChatController

# 导入服务
from .services.route_service import RouteService
from .services.auth_service import AuthService
from .services.notify_service import NotifyService
from .services.proxy_service import ProxyService

# 导入中间件
from .middleware.auth_middleware import AuthMiddleware
from .middleware.rate_limit_middleware import RateLimitMiddleware
from .middleware.log_middleware import LogMiddleware
from .middleware.error_middleware import ErrorMiddleware

# 尝试导入Sanic相关模块
try:
    from sanic import Sanic, Request, Websocket
    from sanic.response import json as sanic_json
    from sanic.exceptions import ServerError
    import uvloop
    SANIC_AVAILABLE = True
except ImportError:
    logger.warning("Sanic not available, using mock implementation")
    SANIC_AVAILABLE = False
    
    # Mock实现
    class MockSanic:
        def __init__(self, name):
            self.name = name
            self.listeners = {'before_server_start': [], 'after_server_stop': []}
            
        def add_route(self, *args, **kwargs):
            pass
            
        def listener(self, event):
            def decorator(func):
                self.listeners[event].append(func)
                return func
            return decorator
            
        def websocket(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
            
        def route(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
            
        def run(self, **kwargs):
            logger.info("Mock Sanic server running")
            
    class MockRequest:
        def __init__(self):
            self.ip = "127.0.0.1"
            self.headers = {}
            
    class MockWebsocket:
        def __init__(self):
            self.ip = "127.0.0.1"
            
        async def send(self, message):
            pass
            
        async def recv(self):
            await asyncio.sleep(1)
            return b"test message"
            
    Sanic = MockSanic
    Request = MockRequest
    Websocket = MockWebsocket
    
    def sanic_json(data):
        return data
    
    def uvloop_install():
        pass
        
    class MockUvloop:
        def __init__(self):
            self.install = uvloop_install
        
    uvloop = MockUvloop()


class GateServer(BaseServer):
    """网关服务器"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化网关服务器
        
        Args:
            config_path: 配置文件路径
        """
        # 加载配置
        self.gateway_config = load_config(config_path)
        
        # 初始化基础服务器
        super().__init__(service_name="gate_server")
        
        # Sanic应用
        self.app: Optional[Sanic] = None
        
        # 管理器实例
        self.websocket_manager: Optional[WebSocketManager] = None
        self.session_manager: Optional[SessionManager] = None
        self.route_manager: Optional[RouteManager] = None
        self.gate_handler: Optional[GateHandler] = None
        
        # 控制器实例通过父类的_controllers属性管理
        # self.controllers: Dict[str, Any] = {}
        
        # 服务实例通过父类的_services属性管理
        # self.services: Dict[str, Any] = {}
        
        # 中间件实例
        self.middleware: Dict[str, Any] = {}
        
        # 运行状态
        self._is_running = False
        
        logger.info("网关服务器初始化完成", 
                   mode=self.gateway_config.mode.value,
                   port=self.gateway_config.websocket.port)
        
    async def initialize(self):
        """初始化服务器"""
        try:
            # 调用基础服务器初始化
            await super().initialize()
            
            # 创建Sanic应用
            self._create_sanic_app()
            
            # 初始化管理器
            await self._initialize_managers()
            
            # 初始化服务
            await self._initialize_services()
            
            # 初始化控制器
            await self._initialize_controllers()
            
            # 初始化中间件
            await self._initialize_middleware()
            
            # 注册路由
            await self._register_routes()
            
            # 设置事件监听器
            self._setup_event_listeners()
            
            logger.info("网关服务器初始化完成")
            
        except Exception as e:
            logger.error("网关服务器初始化失败", error=str(e))
            raise
            
    async def start(self):
        """启动服务器"""
        try:
            if self._is_running:
                logger.warning("服务器已经在运行中")
                return
                
            self._is_running = True
            
            # 启动管理器
            await self._start_managers()
            
            # 启动服务
            await self._start_services()
            
            # 启动Sanic应用
            await self._start_sanic_app()
            
            logger.info("网关服务器启动完成", 
                       host=self.gateway_config.websocket.host,
                       port=self.gateway_config.websocket.port)
            
        except Exception as e:
            logger.error("网关服务器启动失败", error=str(e))
            raise
            
    async def stop(self):
        """停止服务器"""
        try:
            if not self._is_running:
                return
                
            self._is_running = False
            
            # 停止管理器
            await self._stop_managers()
            
            # 停止服务
            await self._stop_services()
            
            # 调用基础服务器停止
            await super().stop()
            
            logger.info("网关服务器停止完成")
            
        except Exception as e:
            logger.error("网关服务器停止失败", error=str(e))
            
    def run(self):
        """运行服务器"""
        try:
            # 安装uvloop
            if SANIC_AVAILABLE:
                uvloop.install()
                
            # 设置信号处理
            self._setup_signal_handlers()
            
            # 启动异步事件循环
            asyncio.run(self._run_async())
            
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在关闭服务器...")
        except Exception as e:
            logger.error("服务器运行失败", error=str(e))
            
    async def _run_async(self):
        """异步运行"""
        try:
            # 初始化服务器
            await self.initialize()
            
            # 启动服务器
            await self.start()
            
            # 保持运行
            while self._is_running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error("异步运行失败", error=str(e))
        finally:
            await self.stop()
            
    def _create_sanic_app(self):
        """创建Sanic应用"""
        self.app = Sanic("gate_server")
        
        # 配置CORS
        if self.gateway_config.security.allowed_origins:
            # TODO: 配置CORS中间件
            pass
            
        logger.info("Sanic应用创建完成")
        
    async def _initialize_managers(self):
        """初始化管理器"""
        # 创建WebSocket管理器
        self.websocket_manager = create_websocket_manager(self.gateway_config)
        
        # 创建会话管理器
        self.session_manager = create_session_manager(self.gateway_config)
        await self.session_manager.initialize()
        
        # 创建路由管理器
        self.route_manager = create_route_manager(self.gateway_config)
        await self.route_manager.initialize()
        
        # 创建网关处理器
        self.gate_handler = create_gate_handler(self.gateway_config)
        await self.gate_handler.initialize()
        
        logger.info("管理器初始化完成")
        
    async def _initialize_services(self):
        """初始化服务"""
        # 路由服务
        route_service = RouteService(self.gateway_config)
        self.add_service('route_service', route_service)
        
        # 认证服务
        auth_service = AuthService(self.gateway_config)
        self.add_service('auth_service', auth_service)
        
        # 通知服务
        notify_service = NotifyService(self.gateway_config)
        self.add_service('notify_service', notify_service)
        
        # 代理服务
        proxy_service = ProxyService(self.gateway_config)
        self.add_service('proxy_service', proxy_service)
        
        # 初始化所有服务
        for service_name, service in self.services.items():
            if hasattr(service, 'initialize'):
                await service.initialize()
            logger.info("服务初始化完成", service_name=service_name)
            
    async def _initialize_controllers(self):
        """初始化控制器"""
        # 认证控制器
        auth_controller = AuthController(
            self.gateway_config,
            self.get_service('auth_service')
        )
        self.add_controller('auth_controller', auth_controller)
        
        # 游戏控制器
        game_controller = GameController(
            self.gateway_config,
            self.get_service('proxy_service')
        )
        self.add_controller('game_controller', game_controller)
        
        # 聊天控制器
        chat_controller = ChatController(
            self.gateway_config,
            self.get_service('proxy_service')
        )
        self.add_controller('chat_controller', chat_controller)
        
        # 注册控制器到路由管理器
        for controller_name, controller in self.controllers.items():
            await self.route_manager.register_controller(controller_name, controller)
            
        logger.info("控制器初始化完成")
        
    async def _initialize_middleware(self):
        """初始化中间件"""
        # 认证中间件
        self.middleware['auth_middleware'] = AuthMiddleware(self.gateway_config)
        
        # 限流中间件
        self.middleware['rate_limit_middleware'] = RateLimitMiddleware(self.gateway_config)
        
        # 日志中间件
        self.middleware['log_middleware'] = LogMiddleware(self.gateway_config)
        
        # 错误处理中间件
        self.middleware['error_middleware'] = ErrorMiddleware(self.gateway_config)
        
        # 注册中间件到路由管理器
        for middleware_name, middleware in self.middleware.items():
            await self.route_manager.register_middleware(middleware_name, middleware)
            
        logger.info("中间件初始化完成")
        
    async def _register_routes(self):
        """注册路由"""
        # 注册WebSocket路由
        @self.app.websocket("/ws")
        async def websocket_handler(request: Request, ws: Websocket):
            await self._handle_websocket_connection(request, ws)
            
        # 注册HTTP路由
        @self.app.route("/health", methods=["GET"])
        async def health_check(request: Request):
            return sanic_json({"status": "healthy", "timestamp": asyncio.get_event_loop().time()})
            
        @self.app.route("/stats", methods=["GET"])
        async def stats_handler(request: Request):
            return sanic_json(self._get_server_stats())
            
        logger.info("路由注册完成")
        
    def _setup_event_listeners(self):
        """设置事件监听器"""
        @self.app.listener('before_server_start')
        async def before_server_start(app, loop):
            logger.info("服务器启动前事件")
            
        @self.app.listener('after_server_stop')
        async def after_server_stop(app, loop):
            logger.info("服务器停止后事件")
            
    async def _start_managers(self):
        """启动管理器"""
        await self.websocket_manager.start()
        await self.session_manager.start()
        logger.info("管理器启动完成")
        
    async def _start_services(self):
        """启动服务"""
        for service_name, service in self.services.items():
            if hasattr(service, 'start'):
                await service.start()
            logger.info("服务启动完成", service_name=service_name)
            
    async def _start_sanic_app(self):
        """启动Sanic应用"""
        if not SANIC_AVAILABLE:
            logger.info("Sanic not available, skipping HTTP server")
            return
            
        # 在后台任务中启动Sanic
        asyncio.create_task(self._run_sanic_server())
        
    async def _run_sanic_server(self):
        """运行Sanic服务器"""
        try:
            self.app.run(
                host=self.gateway_config.websocket.host,
                port=self.gateway_config.websocket.port,
                debug=self.gateway_config.debug,
                workers=self.gateway_config.workers,
                access_log=True
            )
        except Exception as e:
            logger.error("Sanic服务器运行失败", error=str(e))
            
    async def _stop_managers(self):
        """停止管理器"""
        if self.websocket_manager:
            await self.websocket_manager.stop()
        if self.session_manager:
            await self.session_manager.stop()
        logger.info("管理器停止完成")
        
    async def _stop_services(self):
        """停止服务"""
        for service_name, service in self.services.items():
            if hasattr(service, 'stop'):
                await service.stop()
            logger.info("服务停止完成", service_name=service_name)
            
    async def _handle_websocket_connection(self, request: Request, websocket: Websocket):
        """处理WebSocket连接"""
        connection_id = f"conn_{id(websocket)}"
        client_ip = request.ip
        user_agent = request.headers.get('User-Agent', '')
        
        try:
            # 处理连接
            await self.gate_handler.handle_websocket_connect(
                connection_id, websocket, client_ip, user_agent
            )
            
            # 消息循环
            async for message in websocket:
                if isinstance(message, bytes):
                    await self.gate_handler.handle_websocket_message(connection_id, message)
                elif isinstance(message, str):
                    await self.gate_handler.handle_websocket_message(connection_id, message.encode())
                    
        except Exception as e:
            logger.error("WebSocket连接处理失败", 
                        connection_id=connection_id,
                        error=str(e))
        finally:
            # 处理断开
            await self.gate_handler.handle_websocket_disconnect(connection_id)
            
    def _get_server_stats(self) -> Dict[str, Any]:
        """获取服务器统计信息"""
        stats = {
            "server_info": {
                "name": "gate_server",
                "mode": self.gateway_config.mode.value,
                "debug": self.gateway_config.debug,
                "version": "1.0.0"
            },
            "websocket_stats": self.websocket_manager.get_statistics() if self.websocket_manager else {},
            "session_stats": self.session_manager.get_statistics() if self.session_manager else {},
            "route_stats": self.route_manager.get_statistics() if self.route_manager else {},
            "handler_stats": self.gate_handler.get_statistics() if self.gate_handler else {}
        }
        return stats
        
    def _setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            logger.info(f"收到信号 {signum}，正在关闭服务器...")
            self._is_running = False
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
    async def on_startup(self):
        """启动时回调"""
        await super().on_startup()
        logger.info("网关服务器启动完成")
        
    async def on_shutdown(self):
        """关闭时回调"""
        await super().on_shutdown()
        logger.info("网关服务器关闭完成")


def main():
    """主函数"""
    try:
        # 创建网关服务器
        server = GateServer()
        
        # 运行服务器
        server.run()
        
    except Exception as e:
        logger.error("启动网关服务器失败", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()