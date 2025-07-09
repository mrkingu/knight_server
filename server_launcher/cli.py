"""
命令行接口模块

该模块提供服务启动器的命令行交互界面，支持交互式命令执行、
服务控制操作、状态查询等功能。

主要功能：
- 解析命令行参数
- 交互式命令处理
- 服务控制命令
- 状态查询命令
- 帮助信息显示
"""

import asyncio
import cmd
import sys
import shlex
import json
from typing import Dict, List, Optional, Any
from pathlib import Path

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger
from .launcher import ServerLauncher
from .banner import Banner
from .utils import get_system_info


class LauncherCLI(cmd.Cmd):
    """
    命令行接口类
    
    提供交互式命令行界面，支持各种服务管理操作
    """
    
    intro = """
欢迎使用 Knight Server Launcher 交互式命令行界面!
输入 'help' 获取帮助信息，输入 'quit' 退出。
"""
    
    prompt = "(launcher) "
    
    def __init__(self, launcher: ServerLauncher):
        """
        初始化命令行接口
        
        Args:
            launcher: 启动器实例
        """
        super().__init__()
        self.launcher = launcher
        self.banner = Banner()
        self.running = True
        
    def do_status(self, args: str) -> None:
        """
        显示服务状态
        
        用法: status [service_name]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not self.launcher.service_manager:
                print("❌ 服务管理器未初始化")
                return
            
            if parts:
                # 显示指定服务状态
                service_name = parts[0]
                status = self.launcher.service_manager.get_service_status(service_name)
                
                if status:
                    self._display_service_detail(status)
                else:
                    print(f"❌ 服务不存在: {service_name}")
            else:
                # 显示所有服务状态
                services_info = self.launcher.get_services_info()
                self.banner.show_service_table(services_info)
                
        except Exception as e:
            print(f"❌ 获取状态失败: {e}")
    
    def do_start(self, args: str) -> None:
        """
        启动服务
        
        用法: start <service_name> [service_name2 ...]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not parts:
                print("❌ 请指定要启动的服务名称")
                return
            
            if not self.launcher.service_manager:
                print("❌ 服务管理器未初始化")
                return
            
            # 启动指定服务
            for service_name in parts:
                print(f"🚀 正在启动服务: {service_name}")
                
                # 在新的事件循环中运行异步函数
                success = asyncio.run(self.launcher.service_manager.start_service(service_name))
                
                if success:
                    print(f"✅ 服务启动成功: {service_name}")
                else:
                    print(f"❌ 服务启动失败: {service_name}")
                    
        except Exception as e:
            print(f"❌ 启动服务失败: {e}")
    
    def do_stop(self, args: str) -> None:
        """
        停止服务
        
        用法: stop <service_name> [service_name2 ...]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not parts:
                print("❌ 请指定要停止的服务名称")
                return
            
            if not self.launcher.service_manager:
                print("❌ 服务管理器未初始化")
                return
            
            # 停止指定服务
            for service_name in parts:
                print(f"🛑 正在停止服务: {service_name}")
                
                success = asyncio.run(self.launcher.service_manager.stop_service(service_name))
                
                if success:
                    print(f"✅ 服务停止成功: {service_name}")
                else:
                    print(f"❌ 服务停止失败: {service_name}")
                    
        except Exception as e:
            print(f"❌ 停止服务失败: {e}")
    
    def do_restart(self, args: str) -> None:
        """
        重启服务
        
        用法: restart <service_name> [service_name2 ...]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not parts:
                print("❌ 请指定要重启的服务名称")
                return
            
            if not self.launcher.service_manager:
                print("❌ 服务管理器未初始化")
                return
            
            # 重启指定服务
            for service_name in parts:
                print(f"🔄 正在重启服务: {service_name}")
                
                success = asyncio.run(self.launcher.restart_service(service_name))
                
                if success:
                    print(f"✅ 服务重启成功: {service_name}")
                else:
                    print(f"❌ 服务重启失败: {service_name}")
                    
        except Exception as e:
            print(f"❌ 重启服务失败: {e}")
    
    def do_health(self, args: str) -> None:
        """
        显示健康检查报告
        
        用法: health [service_name]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not self.launcher.health_checker:
                print("❌ 健康检查器未初始化")
                return
            
            if parts:
                # 显示指定服务的健康历史
                service_name = parts[0]
                history = self.launcher.health_checker.get_service_health_history(service_name, 10)
                
                if history:
                    self._display_health_history(service_name, history)
                else:
                    print(f"❌ 服务 {service_name} 没有健康检查历史")
            else:
                # 显示健康检查报告
                report = self.launcher.health_checker.get_health_report()
                self._display_health_report(report)
                
        except Exception as e:
            print(f"❌ 获取健康信息失败: {e}")
    
    def do_monitor(self, args: str) -> None:
        """
        显示进程监控信息
        
        用法: monitor [service_name]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not self.launcher.process_monitor:
                print("❌ 进程监控器未初始化")
                return
            
            if parts:
                # 显示指定服务的进程信息
                service_name = parts[0]
                
                # 查找服务的PID
                if self.launcher.service_manager:
                    status = self.launcher.service_manager.get_service_status(service_name)
                    if status and status.get('pid'):
                        pid = status['pid']
                        process_info = self.launcher.process_monitor.get_process_info(pid)
                        
                        if process_info:
                            self._display_process_info(process_info)
                        else:
                            print(f"❌ 服务 {service_name} 的进程信息不存在")
                    else:
                        print(f"❌ 服务 {service_name} 未运行")
                else:
                    print("❌ 服务管理器未初始化")
            else:
                # 显示所有进程信息
                stats = self.launcher.process_monitor.get_statistics()
                all_processes = self.launcher.process_monitor.get_all_processes_info()
                
                self._display_monitor_stats(stats, all_processes)
                
        except Exception as e:
            print(f"❌ 获取监控信息失败: {e}")
    
    def do_system(self, args: str) -> None:
        """
        显示系统信息
        
        用法: system
        
        Args:
            args: 命令参数
        """
        try:
            self.banner.show_system_info()
        except Exception as e:
            print(f"❌ 获取系统信息失败: {e}")
    
    def do_report(self, args: str) -> None:
        """
        生成状态报告
        
        用法: report [output_file]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            # 获取状态报告
            report = self.launcher.get_status_report()
            
            if parts:
                # 保存到文件
                output_file = parts[0]
                if self.launcher.save_status_report(output_file):
                    print(f"✅ 状态报告已保存到: {output_file}")
                else:
                    print(f"❌ 保存状态报告失败")
            else:
                # 显示简要报告
                self._display_summary_report(report)
                
        except Exception as e:
            print(f"❌ 生成状态报告失败: {e}")
    
    def do_config(self, args: str) -> None:
        """
        显示配置信息
        
        用法: config [service_name]
        
        Args:
            args: 命令参数
        """
        try:
            parts = shlex.split(args) if args else []
            
            if not self.launcher.config_manager:
                print("❌ 配置管理器未初始化")
                return
            
            if parts:
                # 显示指定服务配置
                service_name = parts[0]
                config = self.launcher.config_manager.get_service_config(service_name)
                
                if config:
                    self._display_service_config(config)
                else:
                    print(f"❌ 服务配置不存在: {service_name}")
            else:
                # 显示所有服务配置概要
                all_configs = self.launcher.config_manager.get_all_configs()
                self._display_configs_summary(all_configs)
                
        except Exception as e:
            print(f"❌ 获取配置信息失败: {e}")
    
    def do_clear(self, args: str) -> None:
        """
        清屏
        
        用法: clear
        
        Args:
            args: 命令参数
        """
        self.banner.clear_screen()
    
    def do_quit(self, args: str) -> bool:
        """
        退出程序
        
        用法: quit
        
        Args:
            args: 命令参数
            
        Returns:
            bool: 是否退出
        """
        print("👋 再见!")
        self.running = False
        return True
    
    def do_exit(self, args: str) -> bool:
        """
        退出程序（别名）
        
        用法: exit
        
        Args:
            args: 命令参数
            
        Returns:
            bool: 是否退出
        """
        return self.do_quit(args)
    
    def do_help(self, args: str) -> None:
        """
        显示帮助信息
        
        用法: help [command]
        
        Args:
            args: 命令参数
        """
        if args:
            super().do_help(args)
        else:
            self._display_help()
    
    def _display_help(self) -> None:
        """显示帮助信息"""
        help_text = """
可用命令:

📊 状态查询:
  status [service]     - 显示服务状态
  health [service]     - 显示健康检查信息
  monitor [service]    - 显示进程监控信息
  system              - 显示系统信息
  report [file]       - 生成状态报告
  config [service]    - 显示配置信息

🎛️  服务控制:
  start <service>     - 启动服务
  stop <service>      - 停止服务
  restart <service>   - 重启服务

🔧 工具命令:
  clear               - 清屏
  help [command]      - 显示帮助信息
  quit/exit           - 退出程序

💡 使用提示:
  - 命令支持自动补全，按 Tab 键补全
  - 服务名称可以使用通配符
  - 多个服务名称用空格分隔
  - 使用 'help <command>' 获取详细帮助

示例:
  status gate-8001           # 查看指定服务状态
  start gate-8001 logic-9001 # 启动多个服务
  health                     # 查看所有服务健康状态
  report /tmp/report.json    # 生成状态报告
"""
        print(help_text)
    
    def _display_service_detail(self, status: Dict[str, Any]) -> None:
        """显示服务详细信息"""
        print(f"\n📋 服务详细信息: {status['name']}")
        print("=" * 50)
        
        # 基本信息
        print(f"状态: {status['status']}")
        print(f"进程ID: {status['pid'] or 'N/A'}")
        print(f"启动时间: {status['start_time'] or 'N/A'}")
        print(f"运行时间: {status['uptime']:.2f}秒" if status['uptime'] > 0 else "运行时间: N/A")
        print(f"重启次数: {status['restart_count']}")
        
        # 配置信息
        config = status['config']
        print(f"\n⚙️  配置信息:")
        print(f"  服务类型: {config['service_type']}")
        print(f"  端口: {config['port']}")
        print(f"  进程数: {config['process_count']}")
        print(f"  自动重启: {config['auto_restart']}")
        
        if config['dependencies']:
            print(f"  依赖服务: {', '.join(config['dependencies'])}")
        
        # 进程信息
        if status.get('process_info'):
            proc_info = status['process_info']
            print(f"\n🔍 进程信息:")
            print(f"  CPU使用率: {proc_info.get('cpu_percent', 0):.1f}%")
            print(f"  内存使用率: {proc_info.get('memory_percent', 0):.1f}%")
            print(f"  线程数: {proc_info.get('num_threads', 0)}")
            print(f"  文件描述符: {proc_info.get('num_fds', 0)}")
        
        # 错误信息
        if status.get('error_message'):
            print(f"\n❌ 错误信息: {status['error_message']}")
    
    def _display_health_history(self, service_name: str, history: List[Dict[str, Any]]) -> None:
        """显示健康检查历史"""
        print(f"\n🏥 健康检查历史: {service_name}")
        print("=" * 60)
        
        for record in history[-10:]:  # 显示最近10条记录
            timestamp = record['timestamp']
            status = record['status']
            response_time = record['response_time']
            message = record['message']
            
            # 格式化时间
            import datetime
            dt = datetime.datetime.fromtimestamp(timestamp)
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # 状态图标
            status_icon = {
                '健康': '✅',
                '异常': '❌',
                '警告': '⚠️',
                '未知': '❓'
            }.get(status, '❓')
            
            print(f"{time_str} {status_icon} {status} ({response_time:.3f}s) - {message}")
    
    def _display_health_report(self, report: Dict[str, Any]) -> None:
        """显示健康检查报告"""
        print("\n🏥 健康检查报告")
        print("=" * 50)
        
        # 统计信息
        print(f"总服务数: {report.get('total_services', 0)}")
        print(f"健康服务: {report.get('healthy_services', 0)}")
        print(f"异常服务: {report.get('unhealthy_services', 0)}")
        print(f"警告服务: {report.get('warning_services', 0)}")
        
        # 服务详情
        services = report.get('services', {})
        if services:
            print(f"\n📊 服务状态:")
            for service_name, info in services.items():
                status = info.get('status', '未知')
                response_time = info.get('response_time', 0)
                success_rate = info.get('success_rate_1h', 0)
                
                status_icon = {
                    '健康': '✅',
                    '异常': '❌',
                    '警告': '⚠️',
                    '未知': '❓'
                }.get(status, '❓')
                
                print(f"  {service_name}: {status_icon} {status} ({response_time:.3f}s, {success_rate:.1%})")
    
    def _display_process_info(self, info: Dict[str, Any]) -> None:
        """显示进程信息"""
        print(f"\n🔍 进程信息: {info['service_name']} (PID: {info['pid']})")
        print("=" * 50)
        
        print(f"进程名: {info['name']}")
        print(f"状态: {info['status']}")
        print(f"运行时间: {info['uptime']:.2f}秒")
        print(f"重启次数: {info['restart_count']}")
        
        if info['last_metrics']:
            metrics = info['last_metrics']
            print(f"\n📊 资源使用:")
            print(f"  CPU使用率: {metrics['cpu_percent']:.1f}%")
            print(f"  内存使用率: {metrics['memory_percent']:.1f}%")
            print(f"  物理内存: {metrics['memory_rss'] / 1024 / 1024:.1f} MB")
            print(f"  虚拟内存: {metrics['memory_vms'] / 1024 / 1024:.1f} MB")
            print(f"  线程数: {metrics['num_threads']}")
            print(f"  文件描述符: {metrics['num_fds']}")
            print(f"  网络连接: {metrics['connections']}")
        
        # 平均性能
        print(f"\n📈 平均性能 (1分钟):")
        print(f"  平均CPU: {info['average_cpu_1min']:.1f}%")
        print(f"  平均内存: {info['average_memory_1min']:.1f}%")
        
        # 告警信息
        if info.get('alerts'):
            print(f"\n⚠️  最近告警:")
            for alert in info['alerts']:
                print(f"  - {alert}")
    
    def _display_monitor_stats(self, stats: Dict[str, Any], processes: Dict[int, Dict[str, Any]]) -> None:
        """显示监控统计信息"""
        print("\n📊 进程监控统计")
        print("=" * 50)
        
        print(f"总进程数: {stats.get('total_processes', 0)}")
        print(f"活跃进程: {stats.get('active_processes', 0)}")
        print(f"总重启次数: {stats.get('total_restarts', 0)}")
        print(f"总告警次数: {stats.get('total_alerts', 0)}")
        print(f"平均CPU使用率: {stats.get('average_cpu', 0):.1f}%")
        print(f"平均内存使用率: {stats.get('average_memory', 0):.1f}%")
        
        # 最后监控时间
        if stats.get('last_monitor_time'):
            import datetime
            dt = datetime.datetime.fromtimestamp(stats['last_monitor_time'])
            print(f"最后监控时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 进程列表
        if processes:
            print(f"\n🔍 活跃进程:")
            for pid, info in processes.items():
                if info['is_alive']:
                    print(f"  PID {pid}: {info['service_name']} (运行时间: {info['uptime']:.1f}s)")
    
    def _display_configs_summary(self, configs: Dict[str, Any]) -> None:
        """显示配置概要"""
        print("\n⚙️  服务配置概要")
        print("=" * 50)
        
        for service_name, config in configs.items():
            enabled = "✅" if config.enabled else "❌"
            print(f"{enabled} {service_name} ({config.service_type.value}:{config.port})")
            
            if config.dependencies:
                print(f"    依赖: {', '.join(config.dependencies)}")
    
    def _display_service_config(self, config: Any) -> None:
        """显示服务配置详情"""
        print(f"\n⚙️  服务配置: {config.name}")
        print("=" * 50)
        
        print(f"服务类型: {config.service_type.value}")
        print(f"端口: {config.port}")
        print(f"进程数: {config.process_count}")
        print(f"自动重启: {config.auto_restart}")
        print(f"启用状态: {config.enabled}")
        
        if config.dependencies:
            print(f"依赖服务: {', '.join(config.dependencies)}")
        
        # 超时配置
        print(f"\n⏱️  超时配置:")
        print(f"  启动超时: {config.startup_timeout}秒")
        print(f"  关闭超时: {config.shutdown_timeout}秒")
        print(f"  重启延迟: {config.restart_delay}秒")
        
        # 重启配置
        print(f"\n🔄 重启配置:")
        print(f"  最大重启次数: {config.max_restarts}")
        print(f"  重启窗口: {config.restart_window}秒")
        print(f"  优先级: {config.priority}")
        
        # 健康检查
        if config.health_check:
            hc = config.health_check
            print(f"\n🏥 健康检查:")
            print(f"  类型: {hc.type.value}")
            print(f"  检查间隔: {hc.interval}秒")
            print(f"  超时时间: {hc.timeout}秒")
            print(f"  重试次数: {hc.retries}")
            
            if hc.endpoint:
                print(f"  端点: {hc.endpoint}")
            if hc.method:
                print(f"  方法: {hc.method}")
        
        # 环境变量
        if config.env_vars:
            print(f"\n🌍 环境变量:")
            for key, value in config.env_vars.items():
                print(f"  {key}={value}")
    
    def _display_summary_report(self, report: Dict[str, Any]) -> None:
        """显示概要报告"""
        print("\n📋 系统状态概要")
        print("=" * 50)
        
        # 启动器统计
        launcher_stats = report.get('launcher_stats', {})
        print(f"启动器运行时间: {launcher_stats.get('uptime', 0):.1f}秒")
        print(f"总服务数: {launcher_stats.get('total_services', 0)}")
        print(f"运行中服务: {launcher_stats.get('running_services', 0)}")
        print(f"失败服务: {launcher_stats.get('failed_services', 0)}")
        print(f"总重启次数: {launcher_stats.get('total_restarts', 0)}")
        
        # 系统信息
        system_info = report.get('system_info', {})
        if system_info:
            cpu_info = system_info.get('cpu', {})
            memory_info = system_info.get('memory', {})
            
            print(f"\n💻 系统资源:")
            print(f"  CPU使用率: {cpu_info.get('percent', 0):.1f}%")
            print(f"  内存使用率: {memory_info.get('percent', 0):.1f}%")
            print(f"  可用内存: {memory_info.get('available_str', 'N/A')}")
        
        # 健康检查
        health_report = report.get('health_report', {})
        if health_report:
            print(f"\n🏥 健康状态:")
            print(f"  健康服务: {health_report.get('healthy_services', 0)}")
            print(f"  异常服务: {health_report.get('unhealthy_services', 0)}")
            print(f"  警告服务: {health_report.get('warning_services', 0)}")
    
    def emptyline(self) -> None:
        """处理空行"""
        pass
    
    def onecmd(self, line: str) -> bool:
        """处理单个命令"""
        try:
            return super().onecmd(line)
        except KeyboardInterrupt:
            print("\n使用 'quit' 命令退出程序")
            return False
        except Exception as e:
            print(f"❌ 命令执行异常: {e}")
            return False


class CLI:
    """
    命令行接口类
    
    提供用户交互界面，支持各种启动器操作
    """
    
    def __init__(self, launcher: ServerLauncher):
        """
        初始化CLI
        
        Args:
            launcher: 启动器实例
        """
        self.launcher = launcher
        self.banner = Banner()
    
    def parse_args(self) -> None:
        """解析命令行参数"""
        # 这个方法在launcher.py中已经实现
        pass
    
    def interactive_mode(self) -> None:
        """交互模式"""
        try:
            # 显示欢迎信息
            self.banner.clear_screen()
            self.banner.show_logo()
            
            # 检查启动器状态
            if not self.launcher.config_manager:
                if not self.launcher.load_config():
                    print("❌ 配置加载失败，无法进入交互模式")
                    return
            
            # 创建命令行界面
            cli = LauncherCLI(self.launcher)
            
            # 显示服务状态
            if self.launcher.service_manager:
                services_info = self.launcher.get_services_info()
                self.banner.show_service_table(services_info)
            
            # 进入交互模式
            cli.cmdloop()
            
        except KeyboardInterrupt:
            print("\n👋 再见!")
        except Exception as e:
            print(f"❌ 交互模式异常: {e}")
    
    def execute_command(self, command: str) -> None:
        """
        执行命令
        
        Args:
            command: 命令字符串
        """
        # 这个方法可以用于脚本化执行命令
        cli = LauncherCLI(self.launcher)
        cli.onecmd(command)


async def main():
    """主函数"""
    try:
        # 创建启动器实例
        launcher = ServerLauncher()
        
        # 创建CLI实例
        cli = CLI(launcher)
        
        # 进入交互模式
        cli.interactive_mode()
        
    except Exception as e:
        print(f"❌ 程序异常: {e}")


if __name__ == "__main__":
    asyncio.run(main())