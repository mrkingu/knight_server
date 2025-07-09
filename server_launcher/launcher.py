"""
服务启动器主程序
移除CLI支持，改为直接脚本启动
"""
import asyncio
import signal
import sys
from typing import List, Optional, Dict, Any

from setting import config

try:
    from common.logger import logger
except ImportError:
    from loguru import logger


class SimpleServiceManager:
    """简单的服务管理器，用于演示新的配置系统"""
    
    def __init__(self):
        self.services = {}
        self.running_processes = {}
    
    async def start_service(self, service_name: str, instance: Dict[str, Any], settings: Dict[str, Any]):
        """启动服务实例"""
        instance_name = instance.get('name', f"{service_name}-{instance.get('port', 'unknown')}")
        port = instance.get('port')
        
        logger.info(f"模拟启动服务: {instance_name} (端口: {port})")
        logger.info(f"服务设置: {settings}")
        
        # 这里通常会启动实际的服务进程
        # 为了演示，我们只是记录信息
        self.services[instance_name] = {
            'name': instance_name,
            'service_type': service_name,
            'port': port,
            'status': 'running',
            'settings': settings
        }
        
        # 模拟启动时间
        await asyncio.sleep(0.1)
        
        logger.info(f"服务 {instance_name} 启动完成")
        return True
    
    async def stop_service(self, service_name: str):
        """停止服务"""
        logger.info(f"模拟停止服务: {service_name}")
        # 停止该服务类型的所有实例
        to_remove = []
        for instance_name, service_info in self.services.items():
            if service_info['service_type'] == service_name:
                to_remove.append(instance_name)
        
        for instance_name in to_remove:
            del self.services[instance_name]
            logger.info(f"服务实例 {instance_name} 已停止")
        
        await asyncio.sleep(0.1)
        return True
    
    def get_all_services(self):
        """获取所有服务"""
        return self.services
    
    def get_all_services_status(self):
        """获取所有服务状态"""
        return self.services


class SimpleProcessMonitor:
    """简单的进程监控器"""
    
    def __init__(self):
        self.monitoring = False
    
    async def start_monitoring(self):
        """启动监控"""
        self.monitoring = True
        logger.info("进程监控已启动")
        
        while self.monitoring:
            # 模拟监控逻辑
            await asyncio.sleep(5)
    
    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        logger.info("进程监控已停止")


class SimpleHealthChecker:
    """简单的健康检查器"""
    
    def __init__(self):
        self.running = False
    
    async def start(self):
        """启动健康检查"""
        self.running = True
        logger.info("健康检查已启动")
        
        while self.running:
            # 模拟健康检查
            await asyncio.sleep(10)
    
    async def stop(self):
        """停止健康检查"""
        self.running = False
        logger.info("健康检查已停止")


class SimpleBanner:
    """简单的横幅显示"""
    
    def show_logo(self):
        """显示启动logo"""
        print("""
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                                                                                                                          ║
║    ██╗  ██╗███╗   ██╗██╗ ██████╗ ██╗  ██╗████████╗    ███████╗███████╗██████╗ ██╗   ██╗███████╗██████╗                                                                            ║
║    ██║ ██╔╝████╗  ██║██║██╔════╝ ██║  ██║╚══██╔══╝    ██╔════╝██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗                                                                           ║
║    █████╔╝ ██╔██╗ ██║██║██║  ███╗███████║   ██║       ███████╗█████╗  ██████╔╝██║   ██║█████╗  ██████╔╝                                                                           ║
║    ██╔═██╗ ██║╚██╗██║██║██║   ██║██╔══██║   ██║       ╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██╔══╝  ██╔══██╗                                                                           ║
║    ██║  ██╗██║ ╚████║██║╚██████╔╝██║  ██║   ██║       ███████║███████╗██║  ██║ ╚████╔╝ ███████╗██║  ██║                                                                           ║
║    ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝       ╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝                                                                           ║
║                                                                                                                                                                                          ║
║                                                  🚀 分布式游戏服务器启动器 🚀                                                                                                         ║
║                                                                                                                                                                                          ║
║                                                      基于YAML配置的统一管理系统                                                                                                       ║
║                                                                                                                                                                                          ║
╚══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╝
        """)
    
    def show_progress(self, current: int, total: int, service_name: str):
        """显示进度"""
        percentage = (current / total) * 100 if total > 0 else 0
        print(f"[{percentage:6.1f}%] 启动服务: {service_name}")
    
    def show_complete_banner(self, services_info: Dict[str, Any]):
        """显示完成信息"""
        print("\n" + "="*80)
        print("🎉 所有服务启动完成!")
        print("="*80)
        
        if services_info:
            print(f"✅ 总计启动服务: {len(services_info)} 个")
            for service_name, service_info in services_info.items():
                port = service_info.get('port', 'N/A')
                print(f"   • {service_name} (端口: {port})")
        else:
            print("ℹ️  没有启动任何服务")
        
        print("="*80)


class ServerLauncher:
    """
    服务启动器
    负责启动和管理所有配置的服务
    """
    
    def __init__(self):
        """初始化启动器"""
        self.service_manager = SimpleServiceManager()
        self.process_monitor = SimpleProcessMonitor()
        self.health_checker = SimpleHealthChecker()
        self.banner = SimpleBanner()
        self._running = False
        
        # 注册信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        logger.info(f"收到信号 {signum}，准备关闭服务...")
        self._running = False
    
    async def start(self, services: Optional[List[str]] = None):
        """
        启动服务
        
        Args:
            services: 要启动的服务列表，None表示启动所有服务
        """
        self._running = True
        
        # 显示启动logo
        self.banner.show_logo()
        
        # 获取启动顺序
        startup_order = config.get('launcher.startup_order', [])
        if services:
            # 按配置的顺序启动指定服务
            startup_order = [s for s in startup_order if s in services]
        
        # 启动服务
        logger.info(f"准备启动服务: {startup_order}")
        
        total_instances = sum(
            len(config.get_service_config(service_name).get('instances', []))
            for service_name in startup_order
        )
        current_instance = 0
        
        for service_name in startup_order:
            if not self._running:
                break
                
            # 获取服务配置
            service_config = config.get_service_config(service_name)
            if not service_config:
                logger.warning(f"未找到服务配置: {service_name}")
                continue
            
            # 启动服务实例
            instances = service_config.get('instances', [])
            startup_interval = service_config.get('startup_interval', 0.5)
            
            for instance in instances:
                if not self._running:
                    break
                    
                instance_name = instance.get('name', service_name)
                logger.info(f"启动服务实例: {instance_name}")
                
                # 显示进度
                current_instance += 1
                self.banner.show_progress(
                    current_instance,
                    total_instances,
                    instance_name
                )
                
                # 启动实例
                await self.service_manager.start_service(
                    service_name,
                    instance,
                    service_config.get('settings', {})
                )
                
                # 启动间隔
                await asyncio.sleep(startup_interval)
        
        # 显示完成画面
        if self._running:
            services_info = self.service_manager.get_all_services_status()
            self.banner.show_complete_banner(services_info)
            
            # 启动监控
            await self._start_monitoring()
    
    async def _start_monitoring(self):
        """启动监控任务"""
        tasks = []
        
        # 启动进程监控
        monitor_task = asyncio.create_task(self.process_monitor.start_monitoring())
        tasks.append(monitor_task)
        
        # 启动健康检查
        if config.get('launcher.health_check.enabled', True):
            health_task = asyncio.create_task(self.health_checker.start())
            tasks.append(health_task)
        
        # 等待运行
        try:
            while self._running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到键盘中断信号")
        finally:
            # 停止监控
            self.process_monitor.stop_monitoring()
            if config.get('launcher.health_check.enabled', True):
                await self.health_checker.stop()
            
            # 取消所有任务
            for task in tasks:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
    
    async def stop(self):
        """停止所有服务"""
        self._running = False
        
        # 获取停止顺序
        shutdown_order = config.get(
            'launcher.shutdown_order',
            list(reversed(config.get('launcher.startup_order', [])))
        )
        
        logger.info(f"按顺序停止服务: {shutdown_order}")
        
        for service_name in shutdown_order:
            await self.service_manager.stop_service(service_name)
        
        logger.info("所有服务已停止")
    
    async def run(self):
        """运行启动器"""
        try:
            await self.start()
        except Exception as e:
            logger.error(f"启动失败: {e}")
            raise
        finally:
            if self._running:
                await self.stop()


# 启动入口
def main():
    """主函数"""
    launcher = ServerLauncher()
    
    try:
        asyncio.run(launcher.run())
    except KeyboardInterrupt:
        logger.info("启动器已退出")
    except Exception as e:
        logger.error(f"启动器异常退出: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()