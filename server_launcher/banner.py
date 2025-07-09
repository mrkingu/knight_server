"""
启动器横幅和界面显示模块
"""
import time
import os
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime
from dataclasses import dataclass

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

from common.logger import logger


@dataclass
class ServiceInfo:
    """服务信息数据类"""
    name: str
    service_type: str
    port: int
    status: str
    pid: Optional[int] = None
    memory_usage: Optional[str] = None
    cpu_percent: Optional[float] = None
    uptime: Optional[str] = None
    health_status: Optional[str] = None


class Banner:
    """启动器横幅显示类"""
    
    def __init__(self):
        self.logo_text = """
╔═══════════════════════════════════════════════════════════════════════════════╗
║                                                                               ║
║    ██╗  ██╗███╗   ██╗██╗ ██████╗ ██╗  ██╗████████╗    ███████╗███████╗██╗    ║
║    ██║ ██╔╝████╗  ██║██║██╔════╝ ██║  ██║╚══██╔══╝    ██╔════╝██╔════╝██║    ║
║    █████╔╝ ██╔██╗ ██║██║██║  ███╗███████║   ██║       ███████╗█████╗  ██║    ║
║    ██╔═██╗ ██║╚██╗██║██║██║   ██║██╔══██║   ██║       ╚════██║██╔══╝  ██║    ║
║    ██║  ██╗██║ ╚████║██║╚██████╔╝██║  ██║   ██║       ███████║███████╗██║    ║
║    ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝       ╚══════╝╚══════╝╚═╝    ║
║                                                                               ║
║                        Knight Server Launcher v2.0                           ║
║                     基于Supervisor的分布式服务管理系统                          ║
║                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""
    
    def show_logo(self):
        """显示启动Logo"""
        print(self.logo_text)
        print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 79)
    
    def show_progress(self, current: int, total: int, service_name: str):
        """显示启动进度"""
        progress = int((current / total) * 50) if total > 0 else 0
        bar = "█" * progress + "░" * (50 - progress)
        percentage = (current / total) * 100 if total > 0 else 0
        
        print(f"\r启动进度: [{bar}] {percentage:.1f}% - {service_name}", end="", flush=True)
        if current == total:
            print()  # 换行
    
    def show_service_table(self, services_info: List[ServiceInfo]):
        """显示服务状态表格"""
        if not services_info:
            print("没有找到任何服务")
            return
            
        # 表头
        print("\n" + "=" * 100)
        print("服务状态概览")
        print("=" * 100)
        
        # 表格标题
        headers = ["服务名称", "类型", "端口", "状态", "PID", "内存使用", "CPU%", "运行时间", "健康状态"]
        print(f"{'服务名称':<15} {'类型':<8} {'端口':<6} {'状态':<8} {'PID':<8} {'内存使用':<10} {'CPU%':<6} {'运行时间':<12} {'健康状态':<8}")
        print("-" * 100)
        
        # 服务信息
        for service in services_info:
            pid_str = str(service.pid) if service.pid else "N/A"
            memory_str = service.memory_usage or "N/A"
            cpu_str = f"{service.cpu_percent:.1f}" if service.cpu_percent else "N/A"
            uptime_str = service.uptime or "N/A"
            health_str = service.health_status or "未知"
            
            print(f"{service.name:<15} {service.service_type:<8} {service.port:<6} {service.status:<8} {pid_str:<8} {memory_str:<10} {cpu_str:<6} {uptime_str:<12} {health_str:<8}")
        
        print("=" * 100)
    
    def show_system_info(self):
        """显示系统信息"""
        print("\n" + "=" * 50)
        print("系统信息")
        print("=" * 50)
        
        if PSUTIL_AVAILABLE:
            # CPU信息
            cpu_count = psutil.cpu_count()
            cpu_percent = psutil.cpu_percent(interval=1)
            print(f"CPU核心数: {cpu_count}")
            print(f"CPU使用率: {cpu_percent:.1f}%")
            
            # 内存信息
            memory = psutil.virtual_memory()
            print(f"内存总量: {self._format_bytes(memory.total)}")
            print(f"内存使用: {self._format_bytes(memory.used)} ({memory.percent:.1f}%)")
            print(f"内存可用: {self._format_bytes(memory.available)}")
            
            # 磁盘信息
            disk = psutil.disk_usage('/')
            print(f"磁盘总量: {self._format_bytes(disk.total)}")
            print(f"磁盘使用: {self._format_bytes(disk.used)} ({disk.percent:.1f}%)")
            print(f"磁盘可用: {self._format_bytes(disk.free)}")
            
            # 系统信息
            print(f"系统负载: {os.getloadavg()}")
            print(f"启动时间: {datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            print("未安装psutil，无法获取详细系统信息")
            print(f"Python版本: {sys.version}")
            print(f"操作系统: {os.name}")
        
        print("=" * 50)
    
    def show_complete_banner(self, services_info: List[Dict[str, Any]]):
        """显示启动完成横幅"""
        print("\n" + "🎉" * 30)
        print("           服务启动完成！")
        print("🎉" * 30)
        
        # 统计信息
        total_services = len(services_info)
        running_services = len([s for s in services_info if s.get('status') == 'RUNNING'])
        
        print(f"\n📊 服务统计:")
        print(f"   总服务数: {total_services}")
        print(f"   运行中:   {running_services}")
        print(f"   失败:     {total_services - running_services}")
        
        # 服务列表
        print(f"\n🚀 运行中的服务:")
        for service in services_info:
            if service.get('status') == 'RUNNING':
                print(f"   ✅ {service['name']} ({service['type']}) - 端口: {service['port']}")
        
        # 失败的服务
        failed_services = [s for s in services_info if s.get('status') != 'RUNNING']
        if failed_services:
            print(f"\n❌ 失败的服务:")
            for service in failed_services:
                print(f"   ❌ {service['name']} ({service['type']}) - 状态: {service.get('status', 'UNKNOWN')}")
        
        print("\n" + "=" * 60)
        print("💡 使用提示:")
        print("   - 查看状态: python status.py")
        print("   - 停止服务: python stop.py")
        print("   - 重启服务: python restart.py")
        print("   - 查看日志: supervisorctl -c setting/supervisor.conf tail -f <服务名>")
        print("=" * 60)
    
    def show_success_message(self, message: str):
        """显示成功消息"""
        print(f"\n✅ {message}")
    
    def show_error_message(self, message: str):
        """显示错误消息"""
        print(f"\n❌ {message}")
    
    def show_warning_message(self, message: str):
        """显示警告消息"""
        print(f"\n⚠️  {message}")
    
    def show_info_message(self, message: str):
        """显示信息消息"""
        print(f"\nℹ️  {message}")
    
    def _format_bytes(self, bytes_value: int) -> str:
        """格式化字节数为人类可读格式"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024.0:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024.0
        return f"{bytes_value:.1f} PB"