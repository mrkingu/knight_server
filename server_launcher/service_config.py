"""
服务配置管理模块

该模块负责管理服务启动器的配置，包括服务定义、启动参数、依赖关系、
环境变量等。支持从YAML文件加载配置，并提供配置验证功能。

主要功能：
- 服务配置类定义
- 配置文件加载和验证
- 启动命令生成
- 环境变量管理
- 依赖关系解析
"""

import os
import sys
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger
try:
    from setting.env_manager import get_config
except ImportError:
    def get_config():
        return None


class ServiceType(Enum):
    """服务类型枚举"""
    GATE = "gate"
    LOGIC = "logic"
    CHAT = "chat"
    FIGHT = "fight"
    CUSTOM = "custom"


class HealthCheckType(Enum):
    """健康检查类型枚举"""
    HTTP = "http"
    GRPC = "grpc"
    TCP = "tcp"
    CUSTOM = "custom"


@dataclass
class HealthCheckConfig:
    """健康检查配置"""
    type: HealthCheckType
    endpoint: Optional[str] = None
    method: Optional[str] = None
    interval: int = 10
    timeout: int = 5
    retries: int = 3
    expected_status: Optional[int] = None
    
    def __post_init__(self):
        """初始化后验证"""
        if isinstance(self.type, str):
            self.type = HealthCheckType(self.type)


@dataclass
class ServiceConfig:
    """
    服务配置类
    
    管理单个服务的配置信息，包括启动参数、健康检查、依赖关系等
    """
    name: str
    service_type: ServiceType
    port: int
    process_count: int = 1
    auto_restart: bool = True
    dependencies: List[str] = field(default_factory=list)
    health_check: Optional[HealthCheckConfig] = None
    env_vars: Dict[str, str] = field(default_factory=dict)
    start_command: Optional[str] = None
    working_directory: Optional[str] = None
    startup_timeout: int = 30
    shutdown_timeout: int = 30
    restart_delay: int = 5
    max_restarts: int = 5
    restart_window: int = 300  # 5分钟
    priority: int = 0
    enabled: bool = True
    
    def __post_init__(self):
        """初始化后处理"""
        if isinstance(self.service_type, str):
            self.service_type = ServiceType(self.service_type)
        
        # 设置默认环境变量
        self.env_vars.setdefault('SERVICE_NAME', self.name)
        self.env_vars.setdefault('SERVICE_TYPE', self.service_type.value)
        self.env_vars.setdefault('SERVICE_PORT', str(self.port))
    
    def validate(self) -> List[str]:
        """
        验证配置的有效性
        
        Returns:
            List[str]: 错误信息列表
        """
        errors = []
        
        # 验证服务名称
        if not self.name or not self.name.strip():
            errors.append("服务名称不能为空")
        
        # 验证端口
        if not (1 <= self.port <= 65535):
            errors.append(f"端口号 {self.port} 不在有效范围 [1, 65535] 内")
        
        # 验证进程数量
        if self.process_count < 1:
            errors.append("进程数量必须大于0")
        
        # 验证超时时间
        if self.startup_timeout < 1:
            errors.append("启动超时时间必须大于0")
        
        if self.shutdown_timeout < 1:
            errors.append("关闭超时时间必须大于0")
        
        # 验证重启配置
        if self.max_restarts < 0:
            errors.append("最大重启次数不能为负数")
        
        if self.restart_window < 1:
            errors.append("重启窗口时间必须大于0")
        
        # 验证健康检查配置
        if self.health_check:
            if self.health_check.type == HealthCheckType.HTTP:
                if not self.health_check.endpoint:
                    errors.append("HTTP健康检查必须指定endpoint")
            elif self.health_check.type == HealthCheckType.GRPC:
                if not self.health_check.method:
                    errors.append("gRPC健康检查必须指定method")
        
        return errors
    
    def get_start_command(self) -> str:
        """
        获取启动命令
        
        Returns:
            str: 启动命令
        """
        if self.start_command:
            return self.start_command
        
        # 根据服务类型生成默认启动命令
        python_path = sys.executable
        
        if self.service_type == ServiceType.GATE:
            return f"{python_path} -m services.gate.gate_server --port {self.port}"
        elif self.service_type == ServiceType.LOGIC:
            return f"{python_path} -m services.logic.logic_server --port {self.port}"
        elif self.service_type == ServiceType.CHAT:
            return f"{python_path} -m services.chat.chat_server --port {self.port}"
        elif self.service_type == ServiceType.FIGHT:
            return f"{python_path} -m services.fight.fight_server --port {self.port}"
        else:
            return f"{python_path} -m services.custom_server --port {self.port}"
    
    def get_env_vars(self) -> Dict[str, str]:
        """
        获取环境变量
        
        Returns:
            Dict[str, str]: 环境变量字典
        """
        env_vars = os.environ.copy()
        env_vars.update(self.env_vars)
        return env_vars
    
    def get_working_directory(self) -> str:
        """
        获取工作目录
        
        Returns:
            str: 工作目录路径
        """
        if self.working_directory:
            return self.working_directory
        
        # 使用项目根目录作为默认工作目录
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典
        
        Returns:
            Dict[str, Any]: 配置字典
        """
        data = {
            'name': self.name,
            'service_type': self.service_type.value,
            'port': self.port,
            'process_count': self.process_count,
            'auto_restart': self.auto_restart,
            'dependencies': self.dependencies,
            'env_vars': self.env_vars,
            'start_command': self.start_command,
            'working_directory': self.working_directory,
            'startup_timeout': self.startup_timeout,
            'shutdown_timeout': self.shutdown_timeout,
            'restart_delay': self.restart_delay,
            'max_restarts': self.max_restarts,
            'restart_window': self.restart_window,
            'priority': self.priority,
            'enabled': self.enabled
        }
        
        if self.health_check:
            data['health_check'] = {
                'type': self.health_check.type.value,
                'endpoint': self.health_check.endpoint,
                'method': self.health_check.method,
                'interval': self.health_check.interval,
                'timeout': self.health_check.timeout,
                'retries': self.health_check.retries,
                'expected_status': self.health_check.expected_status
            }
        
        return data


@dataclass
class LauncherConfig:
    """启动器配置"""
    name: str = "Knight Server Launcher"
    version: str = "1.0.0"
    log_level: str = "INFO"
    max_workers: int = 10
    health_check_interval: int = 30
    process_monitor_interval: int = 5
    pid_file_dir: str = "/tmp/knight_server"
    log_file_dir: str = "./logs"
    backup_count: int = 5
    
    def __post_init__(self):
        """初始化后处理"""
        # 确保目录存在
        os.makedirs(self.pid_file_dir, exist_ok=True)
        os.makedirs(self.log_file_dir, exist_ok=True)


@dataclass
class StartupConfig:
    """启动配置"""
    sequence: List[str] = field(default_factory=list)
    timeout: int = 60
    retry_count: int = 3
    parallel_start: bool = False
    wait_for_dependencies: bool = True
    dependency_timeout: int = 30


class ServiceConfigManager:
    """
    服务配置管理器
    
    负责管理所有服务的配置，包括加载、验证、查询等功能
    """
    
    def __init__(self):
        """初始化配置管理器"""
        self.launcher_config = LauncherConfig()
        self.startup_config = StartupConfig()
        self.services: Dict[str, ServiceConfig] = {}
        self.service_groups: Dict[str, List[str]] = {}
        self.config_file_path: Optional[str] = None
        
    def load_from_file(self, config_path: str) -> None:
        """
        从文件加载配置
        
        Args:
            config_path: 配置文件路径
        """
        try:
            config_path = Path(config_path)
            if not config_path.exists():
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
            
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML 不可用，无法解析配置文件")
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            self.config_file_path = str(config_path)
            self._parse_config(config_data)
            
            logger.info(f"成功加载配置文件: {config_path}")
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise
    
    def _parse_config(self, config_data: Dict[str, Any]) -> None:
        """
        解析配置数据
        
        Args:
            config_data: 配置数据字典
        """
        # 解析启动器配置
        launcher_data = config_data.get('launcher', {})
        self.launcher_config = LauncherConfig(**launcher_data)
        
        # 解析启动配置
        startup_data = config_data.get('startup', {})
        self.startup_config = StartupConfig(**startup_data)
        
        # 解析服务配置
        services_data = config_data.get('services', {})
        self.services.clear()
        self.service_groups.clear()
        
        for service_group, service_list in services_data.items():
            self.service_groups[service_group] = []
            
            for service_data in service_list:
                # 解析健康检查配置
                health_check_data = service_data.get('health_check')
                health_check = None
                if health_check_data:
                    health_check = HealthCheckConfig(**health_check_data)
                
                # 创建服务配置
                service_config = ServiceConfig(
                    name=service_data['name'],
                    service_type=service_data['service_type'],
                    port=service_data['port'],
                    process_count=service_data.get('process_count', 1),
                    auto_restart=service_data.get('auto_restart', True),
                    dependencies=service_data.get('dependencies', []),
                    health_check=health_check,
                    env_vars=service_data.get('env_vars', {}),
                    start_command=service_data.get('start_command'),
                    working_directory=service_data.get('working_directory'),
                    startup_timeout=service_data.get('startup_timeout', 30),
                    shutdown_timeout=service_data.get('shutdown_timeout', 30),
                    restart_delay=service_data.get('restart_delay', 5),
                    max_restarts=service_data.get('max_restarts', 5),
                    restart_window=service_data.get('restart_window', 300),
                    priority=service_data.get('priority', 0),
                    enabled=service_data.get('enabled', True)
                )
                
                self.services[service_config.name] = service_config
                self.service_groups[service_group].append(service_config.name)
    
    def get_service_config(self, service_name: str) -> Optional[ServiceConfig]:
        """
        获取服务配置
        
        Args:
            service_name: 服务名称
            
        Returns:
            Optional[ServiceConfig]: 服务配置
        """
        return self.services.get(service_name)
    
    def get_all_configs(self) -> Dict[str, ServiceConfig]:
        """
        获取所有服务配置
        
        Returns:
            Dict[str, ServiceConfig]: 所有服务配置
        """
        return self.services.copy()
    
    def get_service_group(self, group_name: str) -> List[str]:
        """
        获取服务组
        
        Args:
            group_name: 服务组名称
            
        Returns:
            List[str]: 服务名称列表
        """
        return self.service_groups.get(group_name, [])
    
    def get_all_service_groups(self) -> Dict[str, List[str]]:
        """
        获取所有服务组
        
        Returns:
            Dict[str, List[str]]: 所有服务组
        """
        return self.service_groups.copy()
    
    def get_startup_sequence(self) -> List[str]:
        """
        获取启动顺序
        
        Returns:
            List[str]: 启动顺序列表
        """
        if self.startup_config.sequence:
            return self.startup_config.sequence
        
        # 如果没有指定启动顺序，按优先级排序
        services = list(self.services.values())
        services.sort(key=lambda s: (-s.priority, s.name))
        return [s.name for s in services if s.enabled]
    
    def resolve_dependencies(self, service_name: str) -> List[str]:
        """
        解析服务依赖
        
        Args:
            service_name: 服务名称
            
        Returns:
            List[str]: 依赖服务列表（按启动顺序）
        """
        visited = set()
        result = []
        
        def _resolve(name: str):
            if name in visited:
                return
            
            visited.add(name)
            service = self.services.get(name)
            if not service:
                return
            
            for dep in service.dependencies:
                _resolve(dep)
            
            result.append(name)
        
        _resolve(service_name)
        return result[:-1]  # 除去自己
    
    def validate_all_configs(self) -> Dict[str, List[str]]:
        """
        验证所有配置
        
        Returns:
            Dict[str, List[str]]: 验证错误信息
        """
        errors = {}
        
        # 验证每个服务配置
        for service_name, service_config in self.services.items():
            service_errors = service_config.validate()
            if service_errors:
                errors[service_name] = service_errors
        
        # 验证依赖关系
        for service_name, service_config in self.services.items():
            for dep in service_config.dependencies:
                if dep not in self.services:
                    errors.setdefault(service_name, []).append(f"依赖服务 {dep} 不存在")
        
        # 验证端口冲突
        port_map = {}
        for service_name, service_config in self.services.items():
            if service_config.port in port_map:
                error_msg = f"端口 {service_config.port} 与服务 {port_map[service_config.port]} 冲突"
                errors.setdefault(service_name, []).append(error_msg)
            else:
                port_map[service_config.port] = service_name
        
        return errors
    
    def save_to_file(self, config_path: Optional[str] = None) -> None:
        """
        保存配置到文件
        
        Args:
            config_path: 配置文件路径，如果为None则使用原路径
        """
        if not config_path:
            config_path = self.config_file_path
        
        if not config_path:
            raise ValueError("没有指定配置文件路径")
        
        try:
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML 不可用，无法保存配置文件")
            
            config_data = {
                'launcher': {
                    'name': self.launcher_config.name,
                    'version': self.launcher_config.version,
                    'log_level': self.launcher_config.log_level,
                    'max_workers': self.launcher_config.max_workers,
                    'health_check_interval': self.launcher_config.health_check_interval,
                    'process_monitor_interval': self.launcher_config.process_monitor_interval,
                    'pid_file_dir': self.launcher_config.pid_file_dir,
                    'log_file_dir': self.launcher_config.log_file_dir,
                    'backup_count': self.launcher_config.backup_count
                },
                'startup': {
                    'sequence': self.startup_config.sequence,
                    'timeout': self.startup_config.timeout,
                    'retry_count': self.startup_config.retry_count,
                    'parallel_start': self.startup_config.parallel_start,
                    'wait_for_dependencies': self.startup_config.wait_for_dependencies,
                    'dependency_timeout': self.startup_config.dependency_timeout
                },
                'services': {}
            }
            
            # 按服务组保存服务配置
            for group_name, service_names in self.service_groups.items():
                config_data['services'][group_name] = []
                for service_name in service_names:
                    service_config = self.services[service_name]
                    config_data['services'][group_name].append(service_config.to_dict())
            
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
            
            logger.info(f"配置已保存到: {config_path}")
            
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            raise


# 创建默认配置文件的函数
def create_default_config() -> str:
    """
    创建默认配置文件内容
    
    Returns:
        str: 默认配置文件内容
    """
    return """
# 服务启动器配置文件
launcher:
  name: "Knight Server Launcher"
  version: "1.0.0"
  log_level: "INFO"
  max_workers: 10
  health_check_interval: 30
  process_monitor_interval: 5
  pid_file_dir: "/tmp/knight_server"
  log_file_dir: "./logs"
  backup_count: 5

# 启动配置
startup:
  sequence:
    - "gate-8001"
    - "logic-9001"
    - "chat-9101"
    - "fight-9201"
  timeout: 60
  retry_count: 3
  parallel_start: false
  wait_for_dependencies: true
  dependency_timeout: 30

# 服务配置
services:
  gate:
    - name: "gate-8001"
      service_type: "gate"
      port: 8001
      process_count: 1
      auto_restart: true
      dependencies: []
      health_check:
        type: "http"
        endpoint: "/health"
        interval: 10
        timeout: 5
        retries: 3
        expected_status: 200
      env_vars:
        LOG_LEVEL: "INFO"
      startup_timeout: 30
      shutdown_timeout: 30
      restart_delay: 5
      max_restarts: 5
      restart_window: 300
      priority: 100
      enabled: true

  logic:
    - name: "logic-9001"
      service_type: "logic"
      port: 9001
      process_count: 2
      auto_restart: true
      dependencies: ["gate-8001"]
      health_check:
        type: "grpc"
        method: "HealthCheck"
        interval: 10
        timeout: 5
        retries: 3
      env_vars:
        LOG_LEVEL: "INFO"
      startup_timeout: 30
      shutdown_timeout: 30
      restart_delay: 5
      max_restarts: 5
      restart_window: 300
      priority: 90
      enabled: true

  chat:
    - name: "chat-9101"
      service_type: "chat"
      port: 9101
      process_count: 1
      auto_restart: true
      dependencies: ["logic-9001"]
      health_check:
        type: "tcp"
        interval: 10
        timeout: 5
        retries: 3
      env_vars:
        LOG_LEVEL: "INFO"
      startup_timeout: 30
      shutdown_timeout: 30
      restart_delay: 5
      max_restarts: 5
      restart_window: 300
      priority: 80
      enabled: true

  fight:
    - name: "fight-9201"
      service_type: "fight"
      port: 9201
      process_count: 2
      auto_restart: true
      dependencies: ["logic-9001"]
      health_check:
        type: "grpc"
        method: "HealthCheck"
        interval: 10
        timeout: 5
        retries: 3
      env_vars:
        LOG_LEVEL: "INFO"
      startup_timeout: 30
      shutdown_timeout: 30
      restart_delay: 5
      max_restarts: 5
      restart_window: 300
      priority: 80
      enabled: true
"""