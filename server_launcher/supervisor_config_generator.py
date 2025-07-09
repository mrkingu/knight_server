"""
Supervisor配置生成器
根据config.yml自动生成supervisor配置
"""
import os
import sys
from pathlib import Path
from typing import Dict, List

from setting import config
from common.logger import logger


class SupervisorConfigGenerator:
    """
    Supervisor配置生成器
    自动根据服务配置生成supervisor.conf
    """
    
    def __init__(self):
        """初始化生成器"""
        self.output_path = Path("setting/supervisor.conf")
        self.project_root = Path(__file__).resolve().parents[2]
        
    def generate(self):
        """生成supervisor配置文件"""
        sections = []
        
        # 生成supervisord配置
        sections.append(self._generate_supervisord_section())
        
        # 生成supervisorctl配置
        sections.append(self._generate_supervisorctl_section())
        
        # 生成各服务配置
        services = config.get('services', {})
        for service_name, service_config in services.items():
            instances = service_config.get('instances', [])
            for instance in instances:
                section = self._generate_program_section(
                    service_name,
                    instance,
                    service_config.get('settings', {})
                )
                sections.append(section)
                
        # 生成服务组配置
        sections.append(self._generate_group_section())
        
        # 写入配置文件
        content = '\n\n'.join(sections)
        self.output_path.parent.mkdir(exist_ok=True)
        self.output_path.write_text(content, encoding='utf-8')
        
        logger.info(f"Supervisor配置已生成: {self.output_path}")
        
    def _generate_supervisord_section(self) -> str:
        """生成supervisord主配置"""
        log_dir = Path(config.get('common.log_dir', 'logs')).resolve()
        log_dir.mkdir(exist_ok=True)
        
        return f"""[supervisord]
logfile={log_dir}/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile={log_dir}/supervisord.pid
nodaemon=false
minfds=1024
minprocs=200
user={os.getenv('USER', 'root')}
childlogdir={log_dir}"""
        
    def _generate_supervisorctl_section(self) -> str:
        """生成supervisorctl配置"""
        return """[supervisorctl]
serverurl=unix:///tmp/supervisor.sock

[unix_http_server]
file=/tmp/supervisor.sock
chmod=0700

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface"""
        
    def _generate_program_section(
        self,
        service_name: str,
        instance: Dict,
        settings: Dict
    ) -> str:
        """生成单个服务程序配置"""
        port = instance['port']
        process_name = f"{service_name}_{port}"
        
        # 构建启动命令
        command = self._build_start_command(service_name, port)
        
        # 日志路径
        log_dir = Path(config.get('common.log_dir', 'logs')).resolve()
        stdout_log = log_dir / f"{process_name}.out.log"
        stderr_log = log_dir / f"{process_name}.err.log"
        
        # 环境变量
        environment = self._build_environment(service_name, instance, settings)
        
        # 优先级（根据启动顺序）
        startup_order = config.get('launcher.startup_order', [])
        priority = 999 - startup_order.index(service_name) * 10 if service_name in startup_order else 500
        
        return f"""[program:{process_name}]
command={command}
process_name={process_name}
directory={self.project_root}
autostart=false
autorestart=true
startsecs=5
startretries=3
user={os.getenv('USER', 'root')}
redirect_stderr=false
stdout_logfile={stdout_log}
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
stderr_logfile={stderr_log}
stderr_logfile_maxbytes=50MB
stderr_logfile_backups=10
environment={environment}
priority={priority}
stopasgroup=true
killasgroup=true
stopsignal=TERM
stopwaitsecs=10"""
        
    def _build_start_command(self, service_name: str, port: int) -> str:
        """构建服务启动命令"""
        python_path = sys.executable
        
        # 根据服务类型构建启动命令
        service_module_map = {
            'gate': 'services.gate.gate_server',
            'logic': 'services.logic.logic_server',
            'chat': 'services.chat.chat_server',
            'fight': 'services.fight.fight_server',
            'activity': 'services.activity.activity_server'
        }
        
        module = service_module_map.get(service_name)
        if not module:
            raise ValueError(f"未知的服务类型: {service_name}")
            
        return f'{python_path} -m {module} --port {port}'
        
    def _build_environment(
        self,
        service_name: str,
        instance: Dict,
        settings: Dict
    ) -> str:
        """构建环境变量"""
        env_vars = {
            'PYTHONPATH': str(self.project_root),
            'SERVICE_NAME': service_name,
            'SERVICE_PORT': str(instance['port']),
            'SERVICE_INSTANCE': instance.get('name', f"{service_name}-{instance['port']}"),
            'ENVIRONMENT': config.get('environment', 'development')
        }
        
        # 添加服务特定的环境变量
        for key, value in settings.items():
            env_key = f"SERVICE_{key.upper()}"
            env_vars[env_key] = str(value)
            
        # 格式化为supervisor需要的格式
        env_str = ','.join([f'{k}="{v}"' for k, v in env_vars.items()])
        return env_str
        
    def _generate_group_section(self) -> str:
        """生成服务组配置"""
        # 收集所有进程名
        all_programs = []
        services = config.get('services', {})
        
        for service_name, service_config in services.items():
            instances = service_config.get('instances', [])
            for instance in instances:
                all_programs.append(f"{service_name}_{instance['port']}")
                
        programs_str = ','.join(all_programs)
        
        # 按服务类型分组
        groups = []
        for service_name in services:
            service_programs = [p for p in all_programs if p.startswith(f"{service_name}_")]
            if service_programs:
                groups.append(f"""[group:{service_name}]
programs={','.join(service_programs)}
priority=999""")
                
        # 添加总组
        groups.insert(0, f"""[group:all]
programs={programs_str}
priority=999""")
        
        return '\n\n'.join(groups)