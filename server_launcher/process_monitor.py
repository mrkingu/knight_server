"""
进程监控器模块

该模块负责监控所有服务进程的运行状态，包括资源使用情况、
进程健康状态检测、异常处理和自动重启等功能。

主要功能：
- 实时监控进程状态
- 收集进程资源使用情况
- 检测进程异常
- 自动重启机制
- 性能统计和报告
"""

import asyncio
import time
import signal
import threading
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger
from .utils import get_process_info, is_process_running, kill_process_tree


@dataclass
class ProcessMetrics:
    """进程指标数据类"""
    pid: int
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_rss: int
    memory_vms: int
    num_threads: int
    num_fds: int
    io_read_bytes: int
    io_write_bytes: int
    connections: int
    status: str
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'pid': self.pid,
            'timestamp': self.timestamp,
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'memory_rss': self.memory_rss,
            'memory_vms': self.memory_vms,
            'num_threads': self.num_threads,
            'num_fds': self.num_fds,
            'io_read_bytes': self.io_read_bytes,
            'io_write_bytes': self.io_write_bytes,
            'connections': self.connections,
            'status': self.status
        }


@dataclass
class ProcessMonitorConfig:
    """进程监控配置"""
    monitor_interval: int = 5  # 监控间隔（秒）
    metrics_history_size: int = 1000  # 指标历史记录大小
    cpu_threshold: float = 80.0  # CPU使用率阈值
    memory_threshold: float = 80.0  # 内存使用率阈值
    restart_on_failure: bool = True  # 失败时自动重启
    restart_delay: int = 5  # 重启延迟（秒）
    max_restart_attempts: int = 3  # 最大重启尝试次数
    restart_window: int = 300  # 重启窗口时间（秒）
    enable_performance_alerts: bool = True  # 启用性能告警
    
    def __post_init__(self):
        """初始化后验证"""
        if self.monitor_interval < 1:
            self.monitor_interval = 1
        if self.metrics_history_size < 10:
            self.metrics_history_size = 10
        if self.cpu_threshold < 0 or self.cpu_threshold > 100:
            self.cpu_threshold = 80.0
        if self.memory_threshold < 0 or self.memory_threshold > 100:
            self.memory_threshold = 80.0


@dataclass
class MonitoredProcess:
    """被监控的进程"""
    pid: int
    name: str
    service_name: str
    start_time: float
    restart_count: int = 0
    last_restart_time: float = 0.0
    metrics_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    last_metrics: Optional[ProcessMetrics] = None
    restart_attempts: List[float] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    
    def add_metrics(self, metrics: ProcessMetrics) -> None:
        """添加指标数据"""
        self.metrics_history.append(metrics)
        self.last_metrics = metrics
    
    def get_average_cpu(self, duration_seconds: int = 60) -> float:
        """获取平均CPU使用率"""
        if not self.metrics_history:
            return 0.0
        
        cutoff_time = time.time() - duration_seconds
        recent_metrics = [m for m in self.metrics_history if m.timestamp > cutoff_time]
        
        if not recent_metrics:
            return 0.0
        
        return sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
    
    def get_average_memory(self, duration_seconds: int = 60) -> float:
        """获取平均内存使用率"""
        if not self.metrics_history:
            return 0.0
        
        cutoff_time = time.time() - duration_seconds
        recent_metrics = [m for m in self.metrics_history if m.timestamp > cutoff_time]
        
        if not recent_metrics:
            return 0.0
        
        return sum(m.memory_percent for m in recent_metrics) / len(recent_metrics)
    
    def can_restart(self, max_attempts: int, window_seconds: int) -> bool:
        """检查是否可以重启"""
        current_time = time.time()
        
        # 清理过期的重启记录
        self.restart_attempts = [t for t in self.restart_attempts 
                               if current_time - t < window_seconds]
        
        return len(self.restart_attempts) < max_attempts
    
    def record_restart(self) -> None:
        """记录重启时间"""
        current_time = time.time()
        self.restart_attempts.append(current_time)
        self.restart_count += 1
        self.last_restart_time = current_time
    
    def is_alive(self) -> bool:
        """检查进程是否存活"""
        return is_process_running(self.pid)
    
    def get_uptime(self) -> float:
        """获取运行时间"""
        if self.last_restart_time > 0:
            return time.time() - self.last_restart_time
        return time.time() - self.start_time


class ProcessMonitor:
    """
    进程监控器
    
    负责监控所有服务进程的运行状态，提供资源监控、异常检测、自动重启等功能
    """
    
    def __init__(self, config: Optional[ProcessMonitorConfig] = None):
        """
        初始化进程监控器
        
        Args:
            config: 监控配置
        """
        self.config = config or ProcessMonitorConfig()
        self.monitored_processes: Dict[int, MonitoredProcess] = {}
        self.process_lock = threading.Lock()
        
        # 监控相关
        self.monitor_task: Optional[asyncio.Task] = None
        self.running = False
        
        # 回调函数
        self.restart_callbacks: List[Callable[[str, int], None]] = []
        self.alert_callbacks: List[Callable[[str, str, Dict[str, Any]], None]] = []
        
        # 统计信息
        self.stats = {
            'total_processes': 0,
            'active_processes': 0,
            'total_restarts': 0,
            'total_alerts': 0,
            'average_cpu': 0.0,
            'average_memory': 0.0,
            'last_monitor_time': 0.0,
            'monitor_errors': 0
        }
        
        logger.info(f"进程监控器已创建，监控间隔: {self.config.monitor_interval}秒")
    
    def register_process(self, pid: int, name: str, service_name: str) -> None:
        """
        注册进程监控
        
        Args:
            pid: 进程ID
            name: 进程名称
            service_name: 服务名称
        """
        with self.process_lock:
            if pid in self.monitored_processes:
                logger.warning(f"进程 {pid} 已被监控")
                return
            
            process = MonitoredProcess(
                pid=pid,
                name=name,
                service_name=service_name,
                start_time=time.time(),
                metrics_history=deque(maxlen=self.config.metrics_history_size)
            )
            
            self.monitored_processes[pid] = process
            self.stats['total_processes'] += 1
            
            logger.info(f"已注册进程监控: {service_name} (PID: {pid})")
    
    def unregister_process(self, pid: int) -> None:
        """
        取消注册进程监控
        
        Args:
            pid: 进程ID
        """
        with self.process_lock:
            if pid in self.monitored_processes:
                process = self.monitored_processes[pid]
                del self.monitored_processes[pid]
                logger.info(f"已取消注册进程监控: {process.service_name} (PID: {pid})")
    
    def add_restart_callback(self, callback: Callable[[str, int], None]) -> None:
        """
        添加重启回调函数
        
        Args:
            callback: 回调函数 (service_name, pid)
        """
        self.restart_callbacks.append(callback)
    
    def add_alert_callback(self, callback: Callable[[str, str, Dict[str, Any]], None]) -> None:
        """
        添加告警回调函数
        
        Args:
            callback: 回调函数 (service_name, alert_message, details)
        """
        self.alert_callbacks.append(callback)
    
    async def start_monitoring(self) -> None:
        """启动监控"""
        if self.running:
            logger.warning("进程监控器已在运行")
            return
        
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("进程监控器已启动")
    
    async def stop_monitoring(self) -> None:
        """停止监控"""
        if not self.running:
            logger.warning("进程监控器未在运行")
            return
        
        self.running = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("进程监控器已停止")
    
    async def _monitor_loop(self) -> None:
        """监控循环"""
        logger.info("进程监控循环已启动")
        
        while self.running:
            try:
                await self._monitor_processes()
                await asyncio.sleep(self.config.monitor_interval)
                
            except Exception as e:
                logger.error(f"进程监控循环异常: {e}")
                self.stats['monitor_errors'] += 1
                await asyncio.sleep(self.config.monitor_interval)
        
        logger.info("进程监控循环已停止")
    
    async def _monitor_processes(self) -> None:
        """监控所有进程"""
        current_time = time.time()
        active_processes = 0
        total_cpu = 0.0
        total_memory = 0.0
        
        # 复制进程列表以避免在监控过程中修改
        with self.process_lock:
            processes_to_monitor = list(self.monitored_processes.values())
        
        for process in processes_to_monitor:
            try:
                # 检查进程是否存活
                if not process.is_alive():
                    await self._handle_process_death(process)
                    continue
                
                # 获取进程指标
                metrics = await self._collect_process_metrics(process.pid)
                if metrics:
                    process.add_metrics(metrics)
                    active_processes += 1
                    total_cpu += metrics.cpu_percent
                    total_memory += metrics.memory_percent
                    
                    # 检查性能告警
                    if self.config.enable_performance_alerts:
                        await self._check_performance_alerts(process, metrics)
                
            except Exception as e:
                logger.error(f"监控进程失败 ({process.service_name}, PID: {process.pid}): {e}")
        
        # 更新统计信息
        self.stats['active_processes'] = active_processes
        self.stats['last_monitor_time'] = current_time
        
        if active_processes > 0:
            self.stats['average_cpu'] = total_cpu / active_processes
            self.stats['average_memory'] = total_memory / active_processes
    
    async def _collect_process_metrics(self, pid: int) -> Optional[ProcessMetrics]:
        """
        收集进程指标
        
        Args:
            pid: 进程ID
            
        Returns:
            Optional[ProcessMetrics]: 进程指标
        """
        try:
            if not PSUTIL_AVAILABLE:
                return None
                
            process_info = get_process_info(pid)
            if not process_info:
                return None
            
            # 获取IO信息
            io_info = process_info.get('io_counters', {})
            
            return ProcessMetrics(
                pid=pid,
                timestamp=time.time(),
                cpu_percent=process_info.get('cpu_percent', 0.0),
                memory_percent=process_info.get('memory_percent', 0.0),
                memory_rss=process_info.get('memory_info', {}).get('rss', 0),
                memory_vms=process_info.get('memory_info', {}).get('vms', 0),
                num_threads=process_info.get('num_threads', 0),
                num_fds=process_info.get('num_fds', 0),
                io_read_bytes=io_info.get('read_bytes', 0) if io_info else 0,
                io_write_bytes=io_info.get('write_bytes', 0) if io_info else 0,
                connections=process_info.get('connections', 0),
                status=process_info.get('status', 'unknown')
            )
            
        except Exception as e:
            logger.error(f"收集进程指标失败 (PID: {pid}): {e}")
            return None
    
    async def _check_performance_alerts(self, process: MonitoredProcess, 
                                      metrics: ProcessMetrics) -> None:
        """
        检查性能告警
        
        Args:
            process: 监控的进程
            metrics: 进程指标
        """
        alerts = []
        
        # CPU使用率告警
        if metrics.cpu_percent > self.config.cpu_threshold:
            alert_msg = f"CPU使用率过高: {metrics.cpu_percent:.1f}%"
            alerts.append(alert_msg)
        
        # 内存使用率告警
        if metrics.memory_percent > self.config.memory_threshold:
            alert_msg = f"内存使用率过高: {metrics.memory_percent:.1f}%"
            alerts.append(alert_msg)
        
        # 僵尸进程告警
        if metrics.status == 'zombie':
            alert_msg = "进程状态异常: 僵尸进程"
            alerts.append(alert_msg)
        
        # 触发告警
        for alert in alerts:
            await self._trigger_alert(process, alert, metrics.to_dict())
    
    async def _handle_process_death(self, process: MonitoredProcess) -> None:
        """
        处理进程死亡
        
        Args:
            process: 死亡的进程
        """
        logger.warning(f"检测到进程死亡: {process.service_name} (PID: {process.pid})")
        
        # 移除监控
        self.unregister_process(process.pid)
        
        # 检查是否需要重启
        if (self.config.restart_on_failure and 
            process.can_restart(self.config.max_restart_attempts, self.config.restart_window)):
            
            logger.info(f"准备重启服务: {process.service_name}")
            await self._restart_service(process)
        else:
            logger.error(f"服务 {process.service_name} 已达到最大重启次数限制")
            await self._trigger_alert(
                process, 
                "服务已达到最大重启次数限制", 
                {'restart_count': process.restart_count}
            )
    
    async def _restart_service(self, process: MonitoredProcess) -> None:
        """
        重启服务
        
        Args:
            process: 要重启的进程
        """
        try:
            # 等待重启延迟
            if self.config.restart_delay > 0:
                await asyncio.sleep(self.config.restart_delay)
            
            # 记录重启
            process.record_restart()
            self.stats['total_restarts'] += 1
            
            # 调用重启回调
            for callback in self.restart_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(process.service_name, process.pid)
                    else:
                        callback(process.service_name, process.pid)
                except Exception as e:
                    logger.error(f"重启回调失败: {e}")
            
            logger.info(f"服务重启完成: {process.service_name}")
            
        except Exception as e:
            logger.error(f"重启服务失败 ({process.service_name}): {e}")
    
    async def _trigger_alert(self, process: MonitoredProcess, 
                           alert_message: str, details: Dict[str, Any]) -> None:
        """
        触发告警
        
        Args:
            process: 相关进程
            alert_message: 告警消息
            details: 详细信息
        """
        process.alerts.append(alert_message)
        self.stats['total_alerts'] += 1
        
        logger.warning(f"进程告警 - {process.service_name}: {alert_message}")
        
        # 调用告警回调
        for callback in self.alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(process.service_name, alert_message, details)
                else:
                    callback(process.service_name, alert_message, details)
            except Exception as e:
                logger.error(f"告警回调失败: {e}")
    
    def get_process_info(self, pid: int) -> Optional[Dict[str, Any]]:
        """
        获取进程信息
        
        Args:
            pid: 进程ID
            
        Returns:
            Optional[Dict[str, Any]]: 进程信息
        """
        with self.process_lock:
            if pid not in self.monitored_processes:
                return None
            
            process = self.monitored_processes[pid]
            
            return {
                'pid': process.pid,
                'name': process.name,
                'service_name': process.service_name,
                'start_time': process.start_time,
                'uptime': process.get_uptime(),
                'restart_count': process.restart_count,
                'last_restart_time': process.last_restart_time,
                'is_alive': process.is_alive(),
                'last_metrics': process.last_metrics.to_dict() if process.last_metrics else None,
                'average_cpu_1min': process.get_average_cpu(60),
                'average_memory_1min': process.get_average_memory(60),
                'alerts': process.alerts[-10:],  # 最近10个告警
                'metrics_count': len(process.metrics_history)
            }
    
    def get_all_processes_info(self) -> Dict[int, Dict[str, Any]]:
        """
        获取所有进程信息
        
        Returns:
            Dict[int, Dict[str, Any]]: 所有进程信息
        """
        with self.process_lock:
            return {pid: self.get_process_info(pid) 
                   for pid in self.monitored_processes.keys()}
    
    def get_process_metrics_history(self, pid: int, 
                                  limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取进程指标历史
        
        Args:
            pid: 进程ID
            limit: 返回数量限制
            
        Returns:
            List[Dict[str, Any]]: 指标历史
        """
        with self.process_lock:
            if pid not in self.monitored_processes:
                return []
            
            process = self.monitored_processes[pid]
            metrics_list = list(process.metrics_history)
            
            if limit > 0:
                metrics_list = metrics_list[-limit:]
            
            return [metrics.to_dict() for metrics in metrics_list]
    
    def check_process_health(self, pid: int) -> Dict[str, Any]:
        """
        检查进程健康状态
        
        Args:
            pid: 进程ID
            
        Returns:
            Dict[str, Any]: 健康状态报告
        """
        with self.process_lock:
            if pid not in self.monitored_processes:
                return {'status': 'unknown', 'message': '进程未监控'}
            
            process = self.monitored_processes[pid]
            
            if not process.is_alive():
                return {'status': 'dead', 'message': '进程已死亡'}
            
            # 检查性能指标
            cpu_avg = process.get_average_cpu(60)
            memory_avg = process.get_average_memory(60)
            
            health_score = 100.0
            issues = []
            
            # CPU检查
            if cpu_avg > self.config.cpu_threshold:
                health_score -= 30
                issues.append(f"CPU使用率过高: {cpu_avg:.1f}%")
            
            # 内存检查
            if memory_avg > self.config.memory_threshold:
                health_score -= 30
                issues.append(f"内存使用率过高: {memory_avg:.1f}%")
            
            # 重启次数检查
            if process.restart_count > 3:
                health_score -= 20
                issues.append(f"重启次数过多: {process.restart_count}")
            
            # 告警检查
            if process.alerts:
                health_score -= 10
                issues.append(f"存在告警: {len(process.alerts)}")
            
            # 确定健康状态
            if health_score >= 80:
                status = 'healthy'
            elif health_score >= 60:
                status = 'warning'
            else:
                status = 'unhealthy'
            
            return {
                'status': status,
                'health_score': health_score,
                'issues': issues,
                'cpu_avg': cpu_avg,
                'memory_avg': memory_avg,
                'restart_count': process.restart_count,
                'alert_count': len(process.alerts)
            }
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取监控统计信息
        
        Returns:
            Dict[str, Any]: 统计信息
        """
        return self.stats.copy()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start_monitoring()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.stop_monitoring()
        return False


# 默认回调函数
def default_restart_callback(service_name: str, pid: int) -> None:
    """
    默认重启回调函数
    
    Args:
        service_name: 服务名称
        pid: 进程ID
    """
    logger.info(f"进程重启通知 - {service_name} (PID: {pid})")


def default_alert_callback(service_name: str, alert_message: str, 
                         details: Dict[str, Any]) -> None:
    """
    默认告警回调函数
    
    Args:
        service_name: 服务名称
        alert_message: 告警消息
        details: 详细信息
    """
    logger.warning(f"进程告警 - {service_name}: {alert_message}")
    if details:
        logger.debug(f"告警详情: {details}")


# 创建进程监控器实例
def create_process_monitor(config: Optional[ProcessMonitorConfig] = None) -> ProcessMonitor:
    """
    创建进程监控器实例
    
    Args:
        config: 监控配置
        
    Returns:
        ProcessMonitor: 进程监控器实例
    """
    monitor = ProcessMonitor(config)
    monitor.add_restart_callback(default_restart_callback)
    monitor.add_alert_callback(default_alert_callback)
    return monitor