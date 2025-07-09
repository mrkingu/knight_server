"""
服务启动器工具函数模块

该模块提供服务启动器使用的各种工具函数，包括系统信息获取、
进程管理、端口检查、资源格式化等功能。

主要功能：
- 系统信息获取和格式化
- 进程管理相关工具
- 端口可用性检查
- 字节和时间格式化
- 进程树终止
"""

import os
import sys
import time
import signal
import socket
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None
import platform
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger


def get_system_info() -> Dict[str, Any]:
    """
    获取系统信息
    
    Returns:
        Dict[str, Any]: 系统信息字典
    """
    if not PSUTIL_AVAILABLE:
        return {
            'system': {
                'platform': platform.system(),
                'platform_version': platform.version(),
                'architecture': platform.machine(),
                'hostname': socket.gethostname(),
                'python_version': platform.python_version(),
                'boot_time': 'N/A (psutil not available)',
                'uptime': 'N/A (psutil not available)'
            },
            'cpu': {
                'count': 'N/A (psutil not available)',
                'percent': 0.0,
                'load_avg': [0.0, 0.0, 0.0]
            },
            'memory': {
                'total': 0,
                'available': 0,
                'percent': 0.0,
                'used': 0,
                'free': 0,
                'total_str': 'N/A (psutil not available)',
                'available_str': 'N/A (psutil not available)',
                'used_str': 'N/A (psutil not available)'
            },
            'disk': {
                'total': 0,
                'used': 0,
                'free': 0,
                'percent': 0.0,
                'total_str': 'N/A (psutil not available)',
                'used_str': 'N/A (psutil not available)',
                'free_str': 'N/A (psutil not available)'
            },
            'network': {
                'bytes_sent': 0,
                'bytes_recv': 0,
                'packets_sent': 0,
                'packets_recv': 0,
                'bytes_sent_str': 'N/A (psutil not available)',
                'bytes_recv_str': 'N/A (psutil not available)'
            }
        }
    
    try:
        # 获取CPU信息
        cpu_count = psutil.cpu_count()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 获取内存信息
        memory = psutil.virtual_memory()
        
        # 获取磁盘信息
        disk = psutil.disk_usage('/')
        
        # 获取网络信息
        network = psutil.net_io_counters()
        
        # 获取系统信息
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        
        return {
            'system': {
                'platform': platform.system(),
                'platform_version': platform.version(),
                'architecture': platform.machine(),
                'hostname': socket.gethostname(),
                'python_version': platform.python_version(),
                'boot_time': boot_time.strftime('%Y-%m-%d %H:%M:%S'),
                'uptime': format_uptime(uptime.total_seconds())
            },
            'cpu': {
                'count': cpu_count,
                'percent': cpu_percent,
                'load_avg': os.getloadavg() if hasattr(os, 'getloadavg') else [0.0, 0.0, 0.0]
            },
            'memory': {
                'total': memory.total,
                'available': memory.available,
                'percent': memory.percent,
                'used': memory.used,
                'free': memory.free,
                'total_str': format_bytes(memory.total),
                'available_str': format_bytes(memory.available),
                'used_str': format_bytes(memory.used)
            },
            'disk': {
                'total': disk.total,
                'used': disk.used,
                'free': disk.free,
                'percent': (disk.used / disk.total) * 100,
                'total_str': format_bytes(disk.total),
                'used_str': format_bytes(disk.used),
                'free_str': format_bytes(disk.free)
            },
            'network': {
                'bytes_sent': network.bytes_sent,
                'bytes_recv': network.bytes_recv,
                'packets_sent': network.packets_sent,
                'packets_recv': network.packets_recv,
                'bytes_sent_str': format_bytes(network.bytes_sent),
                'bytes_recv_str': format_bytes(network.bytes_recv)
            }
        }
    except Exception as e:
        logger.error(f"获取系统信息失败: {e}")
        return {}


def format_bytes(bytes_value: int) -> str:
    """
    格式化字节数为易读格式
    
    Args:
        bytes_value: 字节数
        
    Returns:
        str: 格式化后的字符串
    """
    if bytes_value == 0:
        return "0 B"
    
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    i = 0
    while bytes_value >= 1024 and i < len(units) - 1:
        bytes_value /= 1024
        i += 1
    
    return f"{bytes_value:.2f} {units[i]}"


def format_uptime(seconds: float) -> str:
    """
    格式化运行时间
    
    Args:
        seconds: 运行时间（秒）
        
    Returns:
        str: 格式化后的时间字符串
    """
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}天 {hours}小时 {minutes}分钟"
    elif hours > 0:
        return f"{hours}小时 {minutes}分钟"
    elif minutes > 0:
        return f"{minutes}分钟 {seconds}秒"
    else:
        return f"{seconds}秒"


def check_port_available(port: int, host: str = 'localhost') -> bool:
    """
    检查端口是否可用
    
    Args:
        port: 端口号
        host: 主机地址
        
    Returns:
        bool: 端口是否可用
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            return result != 0
    except Exception as e:
        logger.warning(f"检查端口 {port} 可用性失败: {e}")
        return False


def kill_process_tree(pid: int, timeout: int = 30) -> bool:
    """
    终止进程树
    
    Args:
        pid: 进程ID
        timeout: 超时时间（秒）
        
    Returns:
        bool: 是否成功终止
    """
    if not PSUTIL_AVAILABLE:
        # 使用基本的kill命令
        try:
            import os
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(pid, 0)  # 检查进程是否存在
                os.kill(pid, signal.SIGKILL)  # 强制终止
            except ProcessLookupError:
                pass
            return True
        except Exception as e:
            logger.error(f"终止进程失败 (PID: {pid}): {e}")
            return False
    
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        
        # 首先尝试优雅关闭
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        
        try:
            parent.terminate()
        except psutil.NoSuchProcess:
            return True
        
        # 等待进程关闭
        gone, alive = psutil.wait_procs(children + [parent], timeout=timeout)
        
        # 强制终止仍存活的进程
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        
        return True
    except psutil.NoSuchProcess:
        return True
    except Exception as e:
        logger.error(f"终止进程树失败 (PID: {pid}): {e}")
        return False


def get_process_info(pid: int) -> Optional[Dict[str, Any]]:
    """
    获取进程信息
    
    Args:
        pid: 进程ID
        
    Returns:
        Optional[Dict[str, Any]]: 进程信息
    """
    if not PSUTIL_AVAILABLE:
        return None
        
    try:
        process = psutil.Process(pid)
        
        # 获取进程基本信息
        info = {
            'pid': process.pid,
            'name': process.name(),
            'status': process.status(),
            'create_time': process.create_time(),
            'cpu_percent': process.cpu_percent(),
            'memory_percent': process.memory_percent(),
            'num_threads': process.num_threads(),
            'num_fds': process.num_fds() if hasattr(process, 'num_fds') else 0,
            'username': process.username(),
            'cwd': process.cwd(),
            'cmdline': process.cmdline(),
            'connections': len(process.connections()),
            'is_running': process.is_running()
        }
        
        # 获取内存信息
        memory_info = process.memory_info()
        info['memory_info'] = {
            'rss': memory_info.rss,
            'vms': memory_info.vms,
            'rss_str': format_bytes(memory_info.rss),
            'vms_str': format_bytes(memory_info.vms)
        }
        
        # 获取IO信息
        try:
            io_counters = process.io_counters()
            info['io_counters'] = {
                'read_count': io_counters.read_count,
                'write_count': io_counters.write_count,
                'read_bytes': io_counters.read_bytes,
                'write_bytes': io_counters.write_bytes,
                'read_bytes_str': format_bytes(io_counters.read_bytes),
                'write_bytes_str': format_bytes(io_counters.write_bytes)
            }
        except (psutil.AccessDenied, AttributeError):
            info['io_counters'] = None
        
        # 格式化运行时间
        info['uptime'] = format_uptime(time.time() - info['create_time'])
        info['create_time_str'] = datetime.fromtimestamp(info['create_time']).strftime('%Y-%m-%d %H:%M:%S')
        
        return info
        
    except psutil.NoSuchProcess:
        return None
    except Exception as e:
        logger.error(f"获取进程信息失败 (PID: {pid}): {e}")
        return None


def send_signal_to_process(pid: int, sig: int = signal.SIGTERM) -> bool:
    """
    向进程发送信号
    
    Args:
        pid: 进程ID
        sig: 信号类型
        
    Returns:
        bool: 是否成功发送
    """
    try:
        process = psutil.Process(pid)
        process.send_signal(sig)
        return True
    except psutil.NoSuchProcess:
        return True  # 进程不存在，认为成功
    except Exception as e:
        logger.error(f"发送信号到进程失败 (PID: {pid}, Signal: {sig}): {e}")
        return False


def wait_for_process_stop(pid: int, timeout: int = 30) -> bool:
    """
    等待进程停止
    
    Args:
        pid: 进程ID
        timeout: 超时时间（秒）
        
    Returns:
        bool: 进程是否已停止
    """
    try:
        process = psutil.Process(pid)
        process.wait(timeout=timeout)
        return True
    except psutil.NoSuchProcess:
        return True
    except psutil.TimeoutExpired:
        return False
    except Exception as e:
        logger.error(f"等待进程停止失败 (PID: {pid}): {e}")
        return False


def get_available_ports(start_port: int = 8000, count: int = 100) -> List[int]:
    """
    获取可用端口列表
    
    Args:
        start_port: 起始端口
        count: 检查数量
        
    Returns:
        List[int]: 可用端口列表
    """
    available_ports = []
    
    for port in range(start_port, start_port + count):
        if check_port_available(port):
            available_ports.append(port)
    
    return available_ports


def create_pid_file(pid_file: str, pid: int) -> bool:
    """
    创建PID文件
    
    Args:
        pid_file: PID文件路径
        pid: 进程ID
        
    Returns:
        bool: 是否成功创建
    """
    try:
        with open(pid_file, 'w') as f:
            f.write(str(pid))
        return True
    except Exception as e:
        logger.error(f"创建PID文件失败 ({pid_file}): {e}")
        return False


def remove_pid_file(pid_file: str) -> bool:
    """
    删除PID文件
    
    Args:
        pid_file: PID文件路径
        
    Returns:
        bool: 是否成功删除
    """
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
        return True
    except Exception as e:
        logger.error(f"删除PID文件失败 ({pid_file}): {e}")
        return False


def read_pid_file(pid_file: str) -> Optional[int]:
    """
    读取PID文件
    
    Args:
        pid_file: PID文件路径
        
    Returns:
        Optional[int]: 进程ID
    """
    try:
        if os.path.exists(pid_file):
            with open(pid_file, 'r') as f:
                return int(f.read().strip())
        return None
    except Exception as e:
        logger.error(f"读取PID文件失败 ({pid_file}): {e}")
        return None


def is_process_running(pid: int) -> bool:
    """
    检查进程是否运行
    
    Args:
        pid: 进程ID
        
    Returns:
        bool: 进程是否运行
    """
    if not PSUTIL_AVAILABLE:
        # 使用基本的方法检查
        try:
            import os
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except Exception:
            return False
    
    try:
        process = psutil.Process(pid)
        return process.is_running()
    except psutil.NoSuchProcess:
        return False
    except Exception:
        return False