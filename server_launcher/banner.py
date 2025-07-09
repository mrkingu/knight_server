"""
启动画面模块

该模块负责显示精美的ASCII艺术logo、启动进度条、服务状态表格和系统信息。
提供视觉化的启动界面，增强用户体验。

主要功能：
- ASCII艺术logo显示
- 启动进度条
- 服务状态表格
- 系统信息展示
- 完整启动画面
"""

import os
import sys
import time
import shutil
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger
from .utils import format_bytes, format_uptime, get_system_info


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
    health_status: str = "Unknown"


class Banner:
    """
    启动画面类
    
    负责显示精美的启动界面，包括logo、进度条、服务表格和系统信息
    """
    
    def __init__(self):
        """初始化启动画面"""
        self.terminal_width = self._get_terminal_width()
        self.colors = self._init_colors()
        
    def _get_terminal_width(self) -> int:
        """获取终端宽度"""
        try:
            return shutil.get_terminal_size().columns
        except:
            return 80
    
    def _init_colors(self) -> Dict[str, str]:
        """初始化颜色代码"""
        if os.name == 'nt' or not sys.stdout.isatty():
            # Windows或非终端环境不使用颜色
            return {name: '' for name in ['RESET', 'BOLD', 'RED', 'GREEN', 'YELLOW', 'BLUE', 'MAGENTA', 'CYAN', 'WHITE']}
        
        return {
            'RESET': '\033[0m',
            'BOLD': '\033[1m',
            'RED': '\033[31m',
            'GREEN': '\033[32m',
            'YELLOW': '\033[33m',
            'BLUE': '\033[34m',
            'MAGENTA': '\033[35m',
            'CYAN': '\033[36m',
            'WHITE': '\033[37m'
        }
    
    def show_logo(self) -> None:
        """显示ASCII艺术logo"""
        logo = f"""
{self.colors['CYAN']}{self.colors['BOLD']}
██╗  ██╗███╗   ██╗██╗ ██████╗ ██╗  ██╗████████╗    ███████╗███████╗██████╗ ██╗   ██╗███████╗██████╗ 
██║ ██╔╝████╗  ██║██║██╔════╝ ██║  ██║╚══██╔══╝    ██╔════╝██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗
█████╔╝ ██╔██╗ ██║██║██║  ███╗███████║   ██║       ███████╗█████╗  ██████╔╝██║   ██║█████╗  ██████╔╝
██╔═██╗ ██║╚██╗██║██║██║   ██║██╔══██║   ██║       ╚════██║██╔══╝  ██╔══██╗╚██╗ ██╔╝██╔══╝  ██╔══██╗
██║  ██╗██║ ╚████║██║╚██████╔╝██║  ██║   ██║       ███████║███████╗██║  ██║ ╚████╔╝ ███████╗██║  ██║
╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝       ╚══════╝╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝
{self.colors['RESET']}

{self.colors['YELLOW']}                           分布式游戏服务器启动器 v1.0.0{self.colors['RESET']}
{self.colors['WHITE']}                          Distributed Game Server Launcher{self.colors['RESET']}
        """
        
        print(logo)
        self._print_separator()
    
    def show_progress(self, current: int, total: int, service_name: str) -> None:
        """
        显示启动进度条
        
        Args:
            current: 当前进度
            total: 总进度
            service_name: 服务名称
        """
        if total <= 0:
            return
            
        progress = current / total
        bar_length = min(50, self.terminal_width - 30)
        filled_length = int(bar_length * progress)
        
        bar = f"{self.colors['GREEN']}{'█' * filled_length}{self.colors['RESET']}"
        bar += f"{self.colors['WHITE']}{'░' * (bar_length - filled_length)}{self.colors['RESET']}"
        
        percentage = int(progress * 100)
        status_text = f"启动服务: {service_name}"
        
        print(f"\r{self.colors['CYAN']}[{bar}] {percentage:3d}%{self.colors['RESET']} {status_text[:30]:<30}", end='', flush=True)
        
        if current == total:
            print()  # 换行
    
    def show_service_table(self, services_info: List[ServiceInfo]) -> None:
        """
        显示服务状态表格
        
        Args:
            services_info: 服务信息列表
        """
        if not services_info:
            return
        
        print(f"\n{self.colors['BOLD']}{self.colors['CYAN']}服务状态列表:{self.colors['RESET']}")
        self._print_separator()
        
        # 表头
        headers = ["服务名称", "类型", "端口", "状态", "PID", "内存", "CPU%", "运行时间", "健康状态"]
        col_widths = [12, 8, 6, 8, 8, 10, 6, 12, 10]
        
        # 调整列宽以适应终端宽度
        total_width = sum(col_widths) + len(col_widths) - 1
        if total_width > self.terminal_width:
            scale_factor = (self.terminal_width - len(col_widths) + 1) / total_width
            col_widths = [max(6, int(w * scale_factor)) for w in col_widths]
        
        # 打印表头
        header_row = " ".join(f"{header:<{width}}" for header, width in zip(headers, col_widths))
        print(f"{self.colors['BOLD']}{self.colors['WHITE']}{header_row}{self.colors['RESET']}")
        print("-" * len(header_row))
        
        # 打印服务信息
        for service in services_info:
            status_color = self._get_status_color(service.status)
            health_color = self._get_health_color(service.health_status)
            
            row_data = [
                service.name[:col_widths[0]],
                service.service_type[:col_widths[1]],
                str(service.port),
                f"{status_color}{service.status}{self.colors['RESET']}",
                str(service.pid) if service.pid else "-",
                service.memory_usage or "-",
                f"{service.cpu_percent:.1f}" if service.cpu_percent else "-",
                service.uptime or "-",
                f"{health_color}{service.health_status}{self.colors['RESET']}"
            ]
            
            formatted_row = []
            for i, (data, width) in enumerate(zip(row_data, col_widths)):
                if i in [3, 8]:  # 状态和健康状态列包含颜色代码
                    formatted_row.append(f"{data:<{width + 10}}")  # 额外空间给颜色代码
                else:
                    formatted_row.append(f"{data:<{width}}")
            
            print(" ".join(formatted_row))
        
        self._print_separator()
    
    def show_system_info(self) -> None:
        """显示系统信息"""
        system_info = get_system_info()
        if not system_info:
            return
        
        print(f"\n{self.colors['BOLD']}{self.colors['CYAN']}系统信息:{self.colors['RESET']}")
        self._print_separator()
        
        # 系统基本信息
        sys_info = system_info.get('system', {})
        print(f"{self.colors['WHITE']}系统平台:{self.colors['RESET']} {sys_info.get('platform', 'Unknown')}")
        print(f"{self.colors['WHITE']}主机名称:{self.colors['RESET']} {sys_info.get('hostname', 'Unknown')}")
        print(f"{self.colors['WHITE']}Python版本:{self.colors['RESET']} {sys_info.get('python_version', 'Unknown')}")
        print(f"{self.colors['WHITE']}系统运行时间:{self.colors['RESET']} {sys_info.get('uptime', 'Unknown')}")
        
        # CPU信息
        cpu_info = system_info.get('cpu', {})
        cpu_color = self._get_usage_color(cpu_info.get('percent', 0))
        print(f"{self.colors['WHITE']}CPU核心数:{self.colors['RESET']} {cpu_info.get('count', 'Unknown')}")
        print(f"{self.colors['WHITE']}CPU使用率:{self.colors['RESET']} {cpu_color}{cpu_info.get('percent', 0):.1f}%{self.colors['RESET']}")
        
        # 内存信息
        memory_info = system_info.get('memory', {})
        memory_color = self._get_usage_color(memory_info.get('percent', 0))
        print(f"{self.colors['WHITE']}内存总量:{self.colors['RESET']} {memory_info.get('total_str', 'Unknown')}")
        print(f"{self.colors['WHITE']}内存使用:{self.colors['RESET']} {memory_color}{memory_info.get('used_str', 'Unknown')} ({memory_info.get('percent', 0):.1f}%){self.colors['RESET']}")
        print(f"{self.colors['WHITE']}内存可用:{self.colors['RESET']} {memory_info.get('available_str', 'Unknown')}")
        
        # 磁盘信息
        disk_info = system_info.get('disk', {})
        disk_color = self._get_usage_color(disk_info.get('percent', 0))
        print(f"{self.colors['WHITE']}磁盘总量:{self.colors['RESET']} {disk_info.get('total_str', 'Unknown')}")
        print(f"{self.colors['WHITE']}磁盘使用:{self.colors['RESET']} {disk_color}{disk_info.get('used_str', 'Unknown')} ({disk_info.get('percent', 0):.1f}%){self.colors['RESET']}")
        
        self._print_separator()
    
    def show_complete_banner(self, services_info: List[ServiceInfo]) -> None:
        """
        显示完整启动画面
        
        Args:
            services_info: 服务信息列表
        """
        self.clear_screen()
        self.show_logo()
        self.show_system_info()
        self.show_service_table(services_info)
        
        # 显示启动完成信息
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total_services = len(services_info)
        running_services = sum(1 for s in services_info if s.status == "运行中")
        
        print(f"\n{self.colors['BOLD']}{self.colors['GREEN']}🎉 服务启动完成!{self.colors['RESET']}")
        print(f"{self.colors['WHITE']}启动时间:{self.colors['RESET']} {current_time}")
        print(f"{self.colors['WHITE']}总服务数:{self.colors['RESET']} {total_services}")
        print(f"{self.colors['WHITE']}运行服务:{self.colors['RESET']} {self.colors['GREEN']}{running_services}{self.colors['RESET']}")
        
        if running_services < total_services:
            failed_services = total_services - running_services
            print(f"{self.colors['WHITE']}失败服务:{self.colors['RESET']} {self.colors['RED']}{failed_services}{self.colors['RESET']}")
        
        self._print_separator()
        print(f"{self.colors['YELLOW']}使用 'python -m server_launcher.cli status' 查看详细状态{self.colors['RESET']}")
        print(f"{self.colors['YELLOW']}使用 'python -m server_launcher.cli interactive' 进入交互模式{self.colors['RESET']}")
        self._print_separator()
    
    def clear_screen(self) -> None:
        """清屏"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def _print_separator(self) -> None:
        """打印分隔线"""
        print(f"{self.colors['BLUE']}{'=' * min(self.terminal_width, 80)}{self.colors['RESET']}")
    
    def _get_status_color(self, status: str) -> str:
        """获取状态颜色"""
        status_colors = {
            "运行中": self.colors['GREEN'],
            "已停止": self.colors['RED'],
            "启动中": self.colors['YELLOW'],
            "停止中": self.colors['YELLOW'],
            "错误": self.colors['RED'],
            "未知": self.colors['WHITE']
        }
        return status_colors.get(status, self.colors['WHITE'])
    
    def _get_health_color(self, health_status: str) -> str:
        """获取健康状态颜色"""
        health_colors = {
            "健康": self.colors['GREEN'],
            "异常": self.colors['RED'],
            "警告": self.colors['YELLOW'],
            "未知": self.colors['WHITE']
        }
        return health_colors.get(health_status, self.colors['WHITE'])
    
    def _get_usage_color(self, usage_percent: float) -> str:
        """获取使用率颜色"""
        if usage_percent >= 90:
            return self.colors['RED']
        elif usage_percent >= 70:
            return self.colors['YELLOW']
        else:
            return self.colors['GREEN']
    
    def show_startup_animation(self, duration: float = 2.0) -> None:
        """
        显示启动动画
        
        Args:
            duration: 动画持续时间（秒）
        """
        frames = [
            "⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"
        ]
        
        start_time = time.time()
        frame_index = 0
        
        while time.time() - start_time < duration:
            frame = frames[frame_index % len(frames)]
            print(f"\r{self.colors['CYAN']}正在启动服务启动器... {frame}{self.colors['RESET']}", end='', flush=True)
            time.sleep(0.1)
            frame_index += 1
        
        print(f"\r{self.colors['GREEN']}✓ 服务启动器已准备就绪{self.colors['RESET']}")
    
    def show_error_message(self, message: str, details: Optional[str] = None) -> None:
        """
        显示错误消息
        
        Args:
            message: 错误消息
            details: 详细信息
        """
        print(f"\n{self.colors['RED']}{self.colors['BOLD']}❌ 错误: {message}{self.colors['RESET']}")
        if details:
            print(f"{self.colors['WHITE']}{details}{self.colors['RESET']}")
        self._print_separator()
    
    def show_warning_message(self, message: str) -> None:
        """
        显示警告消息
        
        Args:
            message: 警告消息
        """
        print(f"\n{self.colors['YELLOW']}{self.colors['BOLD']}⚠️  警告: {message}{self.colors['RESET']}")
    
    def show_success_message(self, message: str) -> None:
        """
        显示成功消息
        
        Args:
            message: 成功消息
        """
        print(f"\n{self.colors['GREEN']}{self.colors['BOLD']}✅ 成功: {message}{self.colors['RESET']}")
    
    def show_info_message(self, message: str) -> None:
        """
        显示信息消息
        
        Args:
            message: 信息消息
        """
        print(f"\n{self.colors['CYAN']}{self.colors['BOLD']}ℹ️  信息: {message}{self.colors['RESET']}")