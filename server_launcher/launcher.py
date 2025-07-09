"""
服务启动器
基于Supervisor的进程管理方案
"""
import os
import sys
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Dict

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from setting import config
from server_launcher.supervisor_config_generator import SupervisorConfigGenerator
from server_launcher.banner import Banner
from common.logger import logger


class ServerLauncher:
    """
    服务启动器
    使用Supervisor管理所有服务进程
    """
    
    def __init__(self):
        """初始化启动器"""
        self.banner = Banner()
        self.config_generator = SupervisorConfigGenerator()
        self.supervisor_config_path = Path("setting/supervisor.conf")
        self.supervisord_pid_file = Path("logs/supervisord.pid")
        
    def setup(self):
        """设置环境"""
        # 确保日志目录存在
        log_dir = Path(config.get('common.log_dir', 'logs'))
        log_dir.mkdir(exist_ok=True)
        
        # 生成supervisor配置
        logger.info("生成Supervisor配置文件...")
        self.config_generator.generate()
        logger.info(f"配置文件已生成: {self.supervisor_config_path}")
        
    def start_all(self):
        """启动所有服务"""
        self.setup()
        
        # 显示启动logo
        self.banner.show_logo()
        
        # 检查supervisord是否已经运行
        if self._is_supervisord_running():
            logger.info("Supervisord已经在运行，重新加载配置...")
            self._reload_supervisor()
        else:
            logger.info("启动Supervisord...")
            self._start_supervisord()
            
        # 启动所有服务
        logger.info("启动所有服务...")
        startup_order = config.get('launcher.startup_order', [])
        
        for service_name in startup_order:
            service_config = config.get_service_config(service_name)
            if not service_config:
                continue
                
            instances = service_config.get('instances', [])
            for instance in instances:
                process_name = f"{service_name}_{instance['port']}"
                self._start_process(process_name)
                
                # 显示进度
                self.banner.show_progress(
                    self._get_running_count(),
                    self._get_total_count(),
                    process_name
                )
                
                # 启动间隔
                startup_interval = service_config.get('startup_interval', 0.5)
                time.sleep(startup_interval)
        
        # 显示完成画面
        time.sleep(1)  # 等待所有服务完全启动
        services_info = self._get_all_services_status()
        self.banner.show_complete_banner(services_info)
        
    def stop_all(self):
        """停止所有服务"""
        logger.info("停止所有服务...")
        
        # 按照停止顺序停止服务
        shutdown_order = config.get(
            'launcher.shutdown_order',
            list(reversed(config.get('launcher.startup_order', [])))
        )
        
        for service_name in shutdown_order:
            service_config = config.get_service_config(service_name)
            if not service_config:
                continue
                
            instances = service_config.get('instances', [])
            for instance in instances:
                process_name = f"{service_name}_{instance['port']}"
                self._stop_process(process_name)
                
        # 停止supervisord
        logger.info("停止Supervisord...")
        self._stop_supervisord()
        
    def restart_all(self):
        """重启所有服务"""
        logger.info("重启所有服务...")
        self.stop_all()
        time.sleep(2)
        self.start_all()
        
    def start_service(self, service_name: str):
        """启动指定服务的所有实例"""
        service_config = config.get_service_config(service_name)
        if not service_config:
            logger.error(f"未找到服务配置: {service_name}")
            return
            
        instances = service_config.get('instances', [])
        for instance in instances:
            process_name = f"{service_name}_{instance['port']}"
            self._start_process(process_name)
            
    def stop_service(self, service_name: str):
        """停止指定服务的所有实例"""
        service_config = config.get_service_config(service_name)
        if not service_config:
            logger.error(f"未找到服务配置: {service_name}")
            return
            
        instances = service_config.get('instances', [])
        for instance in instances:
            process_name = f"{service_name}_{instance['port']}"
            self._stop_process(process_name)
            
    def status(self):
        """显示所有服务状态"""
        if not self._is_supervisord_running():
            logger.warning("Supervisord未运行")
            return
            
        # 获取所有进程状态
        result = self._supervisorctl("status")
        if result.returncode == 0:
            print("\n" + "="*80)
            print("服务状态:")
            print("="*80)
            print(result.stdout)
            print("="*80)
        else:
            logger.error("获取状态失败")
            
    def _is_supervisord_running(self) -> bool:
        """检查supervisord是否在运行"""
        return self.supervisord_pid_file.exists()
        
    def _start_supervisord(self):
        """启动supervisord"""
        cmd = [
            "supervisord",
            "-c", str(self.supervisor_config_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"启动Supervisord失败: {result.stderr}")
            raise RuntimeError("启动Supervisord失败")
            
        # 等待supervisord完全启动
        time.sleep(2)
        
    def _stop_supervisord(self):
        """停止supervisord"""
        if self._is_supervisord_running():
            self._supervisorctl("shutdown")
            
    def _reload_supervisor(self):
        """重新加载supervisor配置"""
        self._supervisorctl("reread")
        self._supervisorctl("update")
        
    def _start_process(self, process_name: str):
        """启动指定进程"""
        result = self._supervisorctl(f"start {process_name}")
        if result.returncode == 0:
            logger.info(f"✓ 启动进程: {process_name}")
        else:
            logger.error(f"✗ 启动进程失败: {process_name}")
            
    def _stop_process(self, process_name: str):
        """停止指定进程"""
        result = self._supervisorctl(f"stop {process_name}")
        if result.returncode == 0:
            logger.info(f"✓ 停止进程: {process_name}")
        else:
            logger.error(f"✗ 停止进程失败: {process_name}")
            
    def _supervisorctl(self, command: str):
        """执行supervisorctl命令"""
        cmd = [
            "supervisorctl",
            "-c", str(self.supervisor_config_path)
        ] + command.split()
        
        return subprocess.run(cmd, capture_output=True, text=True)
        
    def _get_all_services_status(self) -> List[Dict]:
        """获取所有服务状态信息"""
        services_info = []
        
        result = self._supervisorctl("status")
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line:
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[0]
                        status = parts[1]
                        # 解析服务名和端口
                        if '_' in name:
                            service_type, port = name.rsplit('_', 1)
                            services_info.append({
                                'name': name,
                                'type': service_type,
                                'port': int(port),
                                'status': status,
                                'pid': parts[3] if len(parts) > 3 and status == 'RUNNING' else None
                            })
                            
        return services_info
        
    def _get_running_count(self) -> int:
        """获取正在运行的服务数量"""
        services = self._get_all_services_status()
        return len([s for s in services if s['status'] == 'RUNNING'])
        
    def _get_total_count(self) -> int:
        """获取服务总数"""
        total = 0
        for service_name in config.get('services', {}):
            service_config = config.get_service_config(service_name)
            total += len(service_config.get('instances', []))
        return total


def main():
    """主函数"""
    launcher = ServerLauncher()
    
    # 简单的命令映射
    import sys
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == 'start':
            launcher.start_all()
        elif command == 'stop':
            launcher.stop_all()
        elif command == 'restart':
            launcher.restart_all()
        elif command == 'status':
            launcher.status()
        else:
            print(f"未知命令: {command}")
            print("可用命令: start, stop, restart, status")
    else:
        # 默认启动所有服务
        launcher.start_all()


if __name__ == "__main__":
    main()