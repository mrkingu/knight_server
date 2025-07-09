"""
服务启动器主程序模块

该模块是服务启动器的核心，负责整个服务集群的启动、监控和管理。
协调各个组件的工作，处理系统信号，提供统一的管理接口。

主要功能：
- 解析命令行参数
- 加载服务配置
- 初始化各个管理器
- 协调服务启动流程
- 处理系统信号
- 主事件循环
"""

import os
import sys
import signal
import asyncio
import argparse
import time
import json
from typing import Dict, List, Optional, Any
from pathlib import Path
from dataclasses import dataclass

try:
    from common.logger import logger, LoggerFactory
except ImportError:
    from simple_logger import logger, LoggerFactory
try:
    from setting.env_manager import initialize_environment, get_config
except ImportError:
    # 简单的环境管理器兼容性
    def initialize_environment():
        pass
    
    def get_config():
        return None
from .service_config import ServiceConfigManager, create_default_config
from .service_manager import ServiceManager, create_service_manager
from .process_monitor import ProcessMonitor, ProcessMonitorConfig, create_process_monitor
from .health_checker import HealthChecker, default_alert_handler
from .process_pool import ProcessPool
from .banner import Banner, ServiceInfo
from .utils import get_system_info, check_port_available


@dataclass
class LauncherStats:
    """启动器统计信息"""
    start_time: float
    total_services: int = 0
    running_services: int = 0
    failed_services: int = 0
    total_restarts: int = 0
    last_health_check: float = 0.0
    
    def get_uptime(self) -> float:
        """获取运行时间"""
        return time.time() - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'start_time': self.start_time,
            'uptime': self.get_uptime(),
            'total_services': self.total_services,
            'running_services': self.running_services,
            'failed_services': self.failed_services,
            'total_restarts': self.total_restarts,
            'last_health_check': self.last_health_check
        }


class ServerLauncher:
    """
    服务启动器主类
    
    负责整个服务集群的启动、监控和管理
    """
    
    def __init__(self):
        """初始化服务启动器"""
        self.config_manager: Optional[ServiceConfigManager] = None
        self.service_manager: Optional[ServiceManager] = None
        self.process_monitor: Optional[ProcessMonitor] = None
        self.health_checker: Optional[HealthChecker] = None
        self.process_pool: Optional[ProcessPool] = None
        self.banner = Banner()
        
        # 运行状态
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # 统计信息
        self.stats = LauncherStats(start_time=time.time())
        
        # 配置文件路径
        self.config_file = "server_launcher_config.yaml"
        
        logger.info("服务启动器已初始化")
    
    def load_config(self, config_file: Optional[str] = None) -> bool:
        """
        加载服务配置
        
        Args:
            config_file: 配置文件路径
            
        Returns:
            bool: 是否成功加载
        """
        try:
            if config_file:
                self.config_file = config_file
            
            # 检查配置文件是否存在
            if not os.path.exists(self.config_file):
                logger.warning(f"配置文件不存在: {self.config_file}")
                self._create_default_config()
            
            # 加载配置
            self.config_manager = ServiceConfigManager()
            self.config_manager.load_from_file(self.config_file)
            
            # 验证配置
            errors = self.config_manager.validate_all_configs()
            if errors:
                logger.error("配置验证失败:")
                for service_name, error_list in errors.items():
                    for error in error_list:
                        logger.error(f"  {service_name}: {error}")
                return False
            
            logger.info(f"配置加载成功: {self.config_file}")
            return True
            
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            return False
    
    def _create_default_config(self) -> None:
        """创建默认配置文件"""
        try:
            default_content = create_default_config()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write(default_content)
            
            logger.info(f"已创建默认配置文件: {self.config_file}")
            
        except Exception as e:
            logger.error(f"创建默认配置文件失败: {e}")
    
    async def _initialize_components(self) -> bool:
        """
        初始化各个组件
        
        Returns:
            bool: 是否成功初始化
        """
        try:
            # 初始化进程池
            self.process_pool = ProcessPool(
                max_workers=self.config_manager.launcher_config.max_workers
            )
            self.process_pool.start()
            
            # 初始化进程监控器
            monitor_config = ProcessMonitorConfig(
                monitor_interval=self.config_manager.launcher_config.process_monitor_interval
            )
            self.process_monitor = create_process_monitor(monitor_config)
            await self.process_monitor.start_monitoring()
            
            # 初始化健康检查器
            self.health_checker = HealthChecker(
                check_interval=self.config_manager.launcher_config.health_check_interval
            )
            self.health_checker.add_alert_handler(default_alert_handler)
            await self.health_checker.start()
            
            # 初始化服务管理器
            self.service_manager = create_service_manager(
                config_manager=self.config_manager,
                process_monitor=self.process_monitor,
                health_checker=self.health_checker,
                process_pool=self.process_pool
            )
            
            # 注册服务到健康检查器
            for service_config in self.config_manager.get_all_configs().values():
                if service_config.health_check:
                    self.health_checker.register_service(service_config)
            
            logger.info("所有组件初始化成功")
            return True
            
        except Exception as e:
            logger.error(f"初始化组件失败: {e}")
            return False
    
    async def start_all_services(self) -> bool:
        """
        启动所有服务
        
        Returns:
            bool: 是否成功启动所有服务
        """
        try:
            logger.info("开始启动所有服务...")
            
            # 显示启动动画
            self.banner.show_startup_animation(2.0)
            
            # 获取服务列表
            all_services = list(self.config_manager.get_all_configs().keys())
            total_services = len(all_services)
            
            # 显示启动进度
            current = 0
            for service_name in all_services:
                current += 1
                self.banner.show_progress(current, total_services, service_name)
                
                # 启动服务
                await self.service_manager.start_service(service_name)
                
                # 等待服务稳定
                await asyncio.sleep(1)
            
            # 更新统计信息
            self.stats.total_services = total_services
            self.stats.running_services = len(self.service_manager.get_running_services())
            self.stats.failed_services = len(self.service_manager.get_failed_services())
            
            print()  # 换行
            logger.info(f"服务启动完成: {self.stats.running_services}/{self.stats.total_services}")
            
            return self.stats.running_services == self.stats.total_services
            
        except Exception as e:
            logger.error(f"启动所有服务失败: {e}")
            return False
    
    async def stop_all_services(self) -> bool:
        """
        停止所有服务
        
        Returns:
            bool: 是否成功停止所有服务
        """
        try:
            logger.info("开始停止所有服务...")
            
            if self.service_manager:
                success = await self.service_manager.stop_all_services()
                
                # 更新统计信息
                self.stats.running_services = len(self.service_manager.get_running_services())
                
                logger.info("所有服务停止完成")
                return success
            
            return True
            
        except Exception as e:
            logger.error(f"停止所有服务失败: {e}")
            return False
    
    async def restart_service(self, service_name: str) -> bool:
        """
        重启指定服务
        
        Args:
            service_name: 服务名称
            
        Returns:
            bool: 是否成功重启
        """
        try:
            if not self.service_manager:
                logger.error("服务管理器未初始化")
                return False
            
            success = await self.service_manager.restart_service(service_name)
            
            if success:
                self.stats.total_restarts += 1
                logger.info(f"服务重启成功: {service_name}")
            else:
                logger.error(f"服务重启失败: {service_name}")
            
            return success
            
        except Exception as e:
            logger.error(f"重启服务异常 ({service_name}): {e}")
            return False
    
    def get_services_info(self) -> List[ServiceInfo]:
        """
        获取服务信息列表
        
        Returns:
            List[ServiceInfo]: 服务信息列表
        """
        services_info = []
        
        if not self.service_manager:
            return services_info
        
        all_status = self.service_manager.get_all_services_status()
        
        for service_name, status_info in all_status.items():
            # 获取健康状态
            health_status = "未知"
            if self.health_checker:
                health_report = self.health_checker.get_health_report()
                service_health = health_report.get('services', {}).get(service_name, {})
                health_status = service_health.get('status', '未知')
            
            # 获取进程信息
            memory_usage = None
            cpu_percent = None
            uptime = None
            
            if status_info.get('process_info'):
                proc_info = status_info['process_info']
                memory_usage = proc_info.get('memory_info', {}).get('rss_str')
                cpu_percent = proc_info.get('cpu_percent')
                uptime = proc_info.get('uptime')
            
            service_info = ServiceInfo(
                name=service_name,
                service_type=status_info['config']['service_type'],
                port=status_info['config']['port'],
                status=status_info['status'],
                pid=status_info['pid'],
                memory_usage=memory_usage,
                cpu_percent=cpu_percent,
                uptime=uptime,
                health_status=health_status
            )
            
            services_info.append(service_info)
        
        return services_info
    
    def _setup_signal_handlers(self) -> None:
        """设置信号处理器"""
        def signal_handler(signum, frame):
            logger.info(f"收到信号 {signum}，开始优雅关闭...")
            self.shutdown_event.set()
        
        # 设置信号处理器
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Windows系统额外处理
        if os.name == 'nt':
            signal.signal(signal.SIGBREAK, signal_handler)
    
    async def _monitor_services(self) -> None:
        """监控服务状态"""
        while self.running:
            try:
                # 更新统计信息
                if self.service_manager:
                    self.stats.running_services = len(self.service_manager.get_running_services())
                    self.stats.failed_services = len(self.service_manager.get_failed_services())
                    
                    # 获取重启统计
                    service_stats = self.service_manager.get_statistics()
                    self.stats.total_restarts = service_stats.get('total_restarts', 0)
                
                # 更新健康检查时间
                self.stats.last_health_check = time.time()
                
                # 等待下次检查
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"监控服务异常: {e}")
                await asyncio.sleep(10)
    
    async def run(self) -> None:
        """运行服务启动器"""
        try:
            # 设置信号处理器
            self._setup_signal_handlers()
            
            # 显示启动画面
            self.banner.clear_screen()
            self.banner.show_logo()
            
            # 初始化环境和日志
            initialize_environment()
            
            # 加载配置
            if not self.load_config():
                self.banner.show_error_message("配置加载失败")
                return
            
            # 初始化组件
            if not await self._initialize_components():
                self.banner.show_error_message("组件初始化失败")
                return
            
            # 启动所有服务
            if not await self.start_all_services():
                self.banner.show_warning_message("部分服务启动失败")
            
            # 显示完整启动画面
            services_info = self.get_services_info()
            self.banner.show_complete_banner(services_info)
            
            # 设置运行状态
            self.running = True
            
            # 启动监控任务
            monitor_task = asyncio.create_task(self._monitor_services())
            
            # 等待关闭信号
            await self.shutdown_event.wait()
            
            # 停止监控任务
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
            # 优雅关闭
            await self._shutdown()
            
        except Exception as e:
            logger.error(f"运行服务启动器异常: {e}")
            self.banner.show_error_message(f"运行异常: {str(e)}")
        finally:
            logger.info("服务启动器已退出")
    
    async def _shutdown(self) -> None:
        """优雅关闭"""
        try:
            logger.info("开始优雅关闭...")
            self.running = False
            
            # 停止所有服务
            if self.service_manager:
                await self.service_manager.graceful_shutdown(timeout=30)
            
            # 停止健康检查器
            if self.health_checker:
                await self.health_checker.stop()
            
            # 停止进程监控器
            if self.process_monitor:
                await self.process_monitor.stop_monitoring()
            
            # 停止进程池
            if self.process_pool:
                self.process_pool.stop()
            
            logger.info("优雅关闭完成")
            
        except Exception as e:
            logger.error(f"优雅关闭异常: {e}")
    
    def get_status_report(self) -> Dict[str, Any]:
        """
        获取状态报告
        
        Returns:
            Dict[str, Any]: 状态报告
        """
        report = {
            'launcher_stats': self.stats.to_dict(),
            'system_info': get_system_info(),
            'services': {},
            'health_report': {},
            'process_stats': {},
            'service_manager_stats': {}
        }
        
        # 服务状态
        if self.service_manager:
            report['services'] = self.service_manager.get_all_services_status()
            report['service_manager_stats'] = self.service_manager.get_statistics()
        
        # 健康检查报告
        if self.health_checker:
            report['health_report'] = self.health_checker.get_health_report()
        
        # 进程监控统计
        if self.process_monitor:
            report['process_stats'] = self.process_monitor.get_statistics()
        
        return report
    
    def save_status_report(self, file_path: str) -> bool:
        """
        保存状态报告到文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 是否成功保存
        """
        try:
            report = self.get_status_report()
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False, default=str)
            
            logger.info(f"状态报告已保存到: {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"保存状态报告失败: {e}")
            return False


def parse_arguments() -> argparse.Namespace:
    """
    解析命令行参数
    
    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(
        description="Knight Server Launcher - 分布式游戏服务器启动器",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        'action',
        choices=['start', 'stop', 'restart', 'status', 'interactive'],
        help='操作类型'
    )
    
    parser.add_argument(
        '--config', '-c',
        default='server_launcher_config.yaml',
        help='配置文件路径'
    )
    
    parser.add_argument(
        '--service', '-s',
        help='指定服务名称（多个服务用逗号分隔）'
    )
    
    parser.add_argument(
        '--all', '-a',
        action='store_true',
        help='操作所有服务'
    )
    
    parser.add_argument(
        '--output', '-o',
        help='输出文件路径（用于status命令）'
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='日志级别'
    )
    
    parser.add_argument(
        '--daemon', '-d',
        action='store_true',
        help='以守护进程模式运行'
    )
    
    return parser.parse_args()


async def main():
    """主函数"""
    try:
        # 解析命令行参数
        args = parse_arguments()
        
        # 创建启动器实例
        launcher = ServerLauncher()
        
        # 设置配置文件
        if args.config:
            launcher.config_file = args.config
        
        # 执行相应操作
        if args.action == 'start':
            await launcher.run()
        elif args.action == 'status':
            # 加载配置
            if not launcher.load_config():
                print("配置加载失败")
                return
            
            # 初始化组件
            if not await launcher._initialize_components():
                print("组件初始化失败")
                return
            
            # 获取状态报告
            report = launcher.get_status_report()
            
            if args.output:
                launcher.save_status_report(args.output)
            else:
                # 显示状态信息
                services_info = launcher.get_services_info()
                launcher.banner.show_service_table(services_info)
                launcher.banner.show_system_info()
        
        elif args.action == 'interactive':
            # 交互模式将在cli.py中实现
            print("交互模式请使用: python -m server_launcher.cli interactive")
        
        else:
            print(f"操作 {args.action} 暂未实现")
    
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出程序")
    except Exception as e:
        logger.error(f"程序异常: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())