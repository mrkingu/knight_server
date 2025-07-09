"""
server_launcher 模块

该模块提供了功能完整的服务启动器，支持一键启动所有配置的微服务实例，
提供进程监控、健康检查、优雅关闭等功能。

主要功能：
- 一键启动所有配置的微服务实例
- 支持启动指定的服务组或单个服务
- 服务的优雅启动和关闭
- 实时进程监控和健康检查
- 自动重启和异常处理
- 精美的ASCII艺术启动画面
- 命令行交互界面

模块结构：
- launcher.py: 启动器主程序
- service_manager.py: 服务管理器
- process_monitor.py: 进程监控器
- health_checker.py: 健康检查器
- service_config.py: 服务配置管理
- process_pool.py: 进程池管理
- banner.py: 启动画面
- cli.py: 命令行接口
- utils.py: 工具函数

使用示例：
    # 启动所有服务
    python -m server_launcher.launcher start --all
    
    # 启动指定服务
    python -m server_launcher.launcher start --service gate,logic
    
    # 查看服务状态
    python -m server_launcher.launcher status
    
    # 交互模式
    python -m server_launcher.cli interactive
"""

from .launcher import ServerLauncher
from .service_manager import ServiceManager
from .process_monitor import ProcessMonitor
from .health_checker import HealthChecker
from .service_config import ServiceConfigManager
from .process_pool import ProcessPool
from .banner import Banner
from .cli import CLI
from .utils import get_system_info, check_port_available

__all__ = [
    'ServerLauncher',
    'ServiceManager', 
    'ProcessMonitor',
    'HealthChecker',
    'ServiceConfigManager',
    'ProcessPool',
    'Banner',
    'CLI',
    'get_system_info',
    'check_port_available'
]
