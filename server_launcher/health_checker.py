"""
健康检查器模块

该模块负责定期检查所有服务的健康状态，支持多种健康检查方式
包括HTTP、gRPC、TCP等。提供健康状态管理、异常告警等功能。

主要功能：
- 多种健康检查方式（HTTP、gRPC、TCP）
- 定期健康检查
- 健康状态管理
- 异常告警通知
- 健康报告生成
"""

import asyncio
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None
import socket
import time
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta

try:
    from common.logger import logger
except ImportError:
    from simple_logger import logger
from .service_config import ServiceConfig, HealthCheckType, HealthCheckConfig
from .utils import check_port_available


class HealthStatus(Enum):
    """健康状态枚举"""
    HEALTHY = "健康"
    UNHEALTHY = "异常"
    WARNING = "警告"
    UNKNOWN = "未知"


@dataclass
class HealthCheckResult:
    """健康检查结果"""
    service_name: str
    status: HealthStatus
    response_time: float
    timestamp: float
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'service_name': self.service_name,
            'status': self.status.value,
            'response_time': self.response_time,
            'timestamp': self.timestamp,
            'message': self.message,
            'details': self.details
        }


@dataclass
class HealthHistory:
    """健康历史记录"""
    service_name: str
    results: List[HealthCheckResult] = field(default_factory=list)
    max_history: int = 100
    
    def add_result(self, result: HealthCheckResult) -> None:
        """添加检查结果"""
        self.results.append(result)
        
        # 保持历史记录数量限制
        if len(self.results) > self.max_history:
            self.results = self.results[-self.max_history:]
    
    def get_latest_result(self) -> Optional[HealthCheckResult]:
        """获取最新结果"""
        return self.results[-1] if self.results else None
    
    def get_success_rate(self, duration_minutes: int = 60) -> float:
        """
        获取成功率
        
        Args:
            duration_minutes: 统计时间段（分钟）
            
        Returns:
            float: 成功率（0-1）
        """
        if not self.results:
            return 0.0
        
        cutoff_time = time.time() - (duration_minutes * 60)
        recent_results = [r for r in self.results if r.timestamp > cutoff_time]
        
        if not recent_results:
            return 0.0
        
        healthy_count = sum(1 for r in recent_results if r.status == HealthStatus.HEALTHY)
        return healthy_count / len(recent_results)
    
    def get_average_response_time(self, duration_minutes: int = 60) -> float:
        """
        获取平均响应时间
        
        Args:
            duration_minutes: 统计时间段（分钟）
            
        Returns:
            float: 平均响应时间（秒）
        """
        if not self.results:
            return 0.0
        
        cutoff_time = time.time() - (duration_minutes * 60)
        recent_results = [r for r in self.results if r.timestamp > cutoff_time]
        
        if not recent_results:
            return 0.0
        
        total_time = sum(r.response_time for r in recent_results)
        return total_time / len(recent_results)


class HealthChecker:
    """
    健康检查器
    
    负责检查所有服务的健康状态，支持多种检查方式
    """
    
    def __init__(self, check_interval: int = 30):
        """
        初始化健康检查器
        
        Args:
            check_interval: 检查间隔（秒）
        """
        self.check_interval = check_interval
        self.services: Dict[str, ServiceConfig] = {}
        self.health_history: Dict[str, HealthHistory] = {}
        self.alert_handlers: List[Callable[[str, HealthCheckResult], None]] = []
        
        # 异步相关
        self.session: Optional[aiohttp.ClientSession] = None
        self.check_task: Optional[asyncio.Task] = None
        self.running = False
        
        # 统计信息
        self.stats = {
            'total_checks': 0,
            'successful_checks': 0,
            'failed_checks': 0,
            'average_response_time': 0.0,
            'last_check_time': 0.0
        }
        
        logger.info(f"健康检查器已创建，检查间隔: {check_interval}秒")
    
    def register_service(self, service_config: ServiceConfig) -> None:
        """
        注册服务
        
        Args:
            service_config: 服务配置
        """
        if not service_config.health_check:
            logger.warning(f"服务 {service_config.name} 没有配置健康检查")
            return
        
        self.services[service_config.name] = service_config
        self.health_history[service_config.name] = HealthHistory(service_config.name)
        
        logger.info(f"已注册健康检查服务: {service_config.name}")
    
    def unregister_service(self, service_name: str) -> None:
        """
        取消注册服务
        
        Args:
            service_name: 服务名称
        """
        if service_name in self.services:
            del self.services[service_name]
            
        if service_name in self.health_history:
            del self.health_history[service_name]
            
        logger.info(f"已取消注册健康检查服务: {service_name}")
    
    def add_alert_handler(self, handler: Callable[[str, HealthCheckResult], None]) -> None:
        """
        添加告警处理器
        
        Args:
            handler: 告警处理函数
        """
        self.alert_handlers.append(handler)
        logger.info("已添加告警处理器")
    
    async def start(self) -> None:
        """启动健康检查器"""
        if self.running:
            logger.warning("健康检查器已在运行")
            return
        
        try:
            # 创建HTTP会话
            if AIOHTTP_AVAILABLE:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                )
            else:
                self.session = None
                logger.warning("aiohttp 不可用，HTTP健康检查将被禁用")
            
            self.running = True
            
            # 启动检查任务
            self.check_task = asyncio.create_task(self._check_loop())
            
            logger.info("健康检查器已启动")
            
        except Exception as e:
            logger.error(f"启动健康检查器失败: {e}")
            raise
    
    async def stop(self) -> None:
        """停止健康检查器"""
        if not self.running:
            logger.warning("健康检查器未在运行")
            return
        
        try:
            self.running = False
            
            # 停止检查任务
            if self.check_task:
                self.check_task.cancel()
                try:
                    await self.check_task
                except asyncio.CancelledError:
                    pass
            
            # 关闭HTTP会话
            if self.session:
                await self.session.close()
                self.session = None
            
            logger.info("健康检查器已停止")
            
        except Exception as e:
            logger.error(f"停止健康检查器失败: {e}")
            raise
    
    async def check_service_health(self, service_name: str) -> HealthCheckResult:
        """
        检查单个服务健康状态
        
        Args:
            service_name: 服务名称
            
        Returns:
            HealthCheckResult: 健康检查结果
        """
        if service_name not in self.services:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNKNOWN,
                response_time=0.0,
                timestamp=time.time(),
                message="服务未注册"
            )
        
        service_config = self.services[service_name]
        health_config = service_config.health_check
        
        if not health_config:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNKNOWN,
                response_time=0.0,
                timestamp=time.time(),
                message="健康检查未配置"
            )
        
        start_time = time.time()
        
        try:
            # 根据检查类型执行检查
            if health_config.type == HealthCheckType.HTTP:
                result = await self._check_http_health(service_config, health_config)
            elif health_config.type == HealthCheckType.GRPC:
                result = await self._check_grpc_health(service_config, health_config)
            elif health_config.type == HealthCheckType.TCP:
                result = await self._check_tcp_health(service_config, health_config)
            else:
                result = HealthCheckResult(
                    service_name=service_name,
                    status=HealthStatus.UNKNOWN,
                    response_time=0.0,
                    timestamp=time.time(),
                    message="不支持的健康检查类型"
                )
        
        except Exception as e:
            result = HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNHEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message=f"健康检查异常: {str(e)}"
            )
        
        # 记录结果
        self.health_history[service_name].add_result(result)
        
        # 更新统计信息
        self.stats['total_checks'] += 1
        if result.status == HealthStatus.HEALTHY:
            self.stats['successful_checks'] += 1
        else:
            self.stats['failed_checks'] += 1
        
        # 触发告警
        if result.status in [HealthStatus.UNHEALTHY, HealthStatus.WARNING]:
            await self._trigger_alert(service_name, result)
        
        return result
    
    async def _check_http_health(self, service_config: ServiceConfig, 
                               health_config: HealthCheckConfig) -> HealthCheckResult:
        """
        HTTP健康检查
        
        Args:
            service_config: 服务配置
            health_config: 健康检查配置
            
        Returns:
            HealthCheckResult: 检查结果
        """
        url = f"http://localhost:{service_config.port}{health_config.endpoint}"
        start_time = time.time()
        
        if not AIOHTTP_AVAILABLE or not self.session:
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.UNKNOWN,
                response_time=0.0,
                timestamp=time.time(),
                message="aiohttp 不可用，无法执行HTTP健康检查"
            )
        
        try:
            async with self.session.get(url, timeout=health_config.timeout) as response:
                response_time = time.time() - start_time
                
                if health_config.expected_status:
                    expected_status = health_config.expected_status
                else:
                    expected_status = 200
                
                if response.status == expected_status:
                    status = HealthStatus.HEALTHY
                    message = "HTTP健康检查通过"
                else:
                    status = HealthStatus.UNHEALTHY
                    message = f"HTTP状态码错误: {response.status}"
                
                # 尝试获取响应内容
                try:
                    content = await response.text()
                    details = {'response_content': content[:500]}  # 限制长度
                except:
                    details = {}
                
                return HealthCheckResult(
                    service_name=service_config.name,
                    status=status,
                    response_time=response_time,
                    timestamp=time.time(),
                    message=message,
                    details=details
                )
        
        except asyncio.TimeoutError:
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.UNHEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message="HTTP健康检查超时"
            )
        
        except Exception as e:
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.UNHEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message=f"HTTP健康检查失败: {str(e)}"
            )
    
    async def _check_grpc_health(self, service_config: ServiceConfig, 
                               health_config: HealthCheckConfig) -> HealthCheckResult:
        """
        gRPC健康检查
        
        Args:
            service_config: 服务配置
            health_config: 健康检查配置
            
        Returns:
            HealthCheckResult: 检查结果
        """
        # 这里应该实现gRPC健康检查逻辑
        # 由于需要具体的gRPC客户端实现，这里提供一个基本的端口检查
        start_time = time.time()
        
        try:
            # 检查端口是否可用
            if not check_port_available(service_config.port):
                response_time = time.time() - start_time
                return HealthCheckResult(
                    service_name=service_config.name,
                    status=HealthStatus.HEALTHY,
                    response_time=response_time,
                    timestamp=time.time(),
                    message="gRPC端口检查通过"
                )
            else:
                return HealthCheckResult(
                    service_name=service_config.name,
                    status=HealthStatus.UNHEALTHY,
                    response_time=time.time() - start_time,
                    timestamp=time.time(),
                    message="gRPC端口不可用"
                )
        
        except Exception as e:
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.UNHEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message=f"gRPC健康检查失败: {str(e)}"
            )
    
    async def _check_tcp_health(self, service_config: ServiceConfig, 
                              health_config: HealthCheckConfig) -> HealthCheckResult:
        """
        TCP健康检查
        
        Args:
            service_config: 服务配置
            health_config: 健康检查配置
            
        Returns:
            HealthCheckResult: 检查结果
        """
        start_time = time.time()
        
        try:
            # 创建TCP连接
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('localhost', service_config.port),
                timeout=health_config.timeout
            )
            
            # 关闭连接
            writer.close()
            await writer.wait_closed()
            
            response_time = time.time() - start_time
            
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.HEALTHY,
                response_time=response_time,
                timestamp=time.time(),
                message="TCP连接检查通过"
            )
        
        except asyncio.TimeoutError:
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.UNHEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message="TCP连接超时"
            )
        
        except Exception as e:
            return HealthCheckResult(
                service_name=service_config.name,
                status=HealthStatus.UNHEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message=f"TCP连接失败: {str(e)}"
            )
    
    async def _check_loop(self) -> None:
        """健康检查循环"""
        logger.info("健康检查循环已启动")
        
        while self.running:
            try:
                # 检查所有服务
                tasks = []
                for service_name in self.services:
                    task = asyncio.create_task(self.check_service_health(service_name))
                    tasks.append(task)
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # 更新统计信息
                self.stats['last_check_time'] = time.time()
                
                # 计算平均响应时间
                total_response_time = 0.0
                total_checks = 0
                
                for history in self.health_history.values():
                    if history.results:
                        total_response_time += history.results[-1].response_time
                        total_checks += 1
                
                if total_checks > 0:
                    self.stats['average_response_time'] = total_response_time / total_checks
                
                # 等待下次检查
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"健康检查循环异常: {e}")
                await asyncio.sleep(self.check_interval)
        
        logger.info("健康检查循环已停止")
    
    async def _trigger_alert(self, service_name: str, result: HealthCheckResult) -> None:
        """
        触发告警
        
        Args:
            service_name: 服务名称
            result: 检查结果
        """
        try:
            for handler in self.alert_handlers:
                if asyncio.iscoroutinefunction(handler):
                    await handler(service_name, result)
                else:
                    handler(service_name, result)
        
        except Exception as e:
            logger.error(f"触发告警失败: {e}")
    
    def get_health_report(self) -> Dict[str, Any]:
        """
        获取健康报告
        
        Returns:
            Dict[str, Any]: 健康报告
        """
        report = {
            'timestamp': time.time(),
            'total_services': len(self.services),
            'healthy_services': 0,
            'unhealthy_services': 0,
            'warning_services': 0,
            'unknown_services': 0,
            'services': {},
            'statistics': self.stats.copy()
        }
        
        for service_name, history in self.health_history.items():
            latest_result = history.get_latest_result()
            
            if latest_result:
                if latest_result.status == HealthStatus.HEALTHY:
                    report['healthy_services'] += 1
                elif latest_result.status == HealthStatus.UNHEALTHY:
                    report['unhealthy_services'] += 1
                elif latest_result.status == HealthStatus.WARNING:
                    report['warning_services'] += 1
                else:
                    report['unknown_services'] += 1
                
                report['services'][service_name] = {
                    'status': latest_result.status.value,
                    'response_time': latest_result.response_time,
                    'timestamp': latest_result.timestamp,
                    'message': latest_result.message,
                    'success_rate_1h': history.get_success_rate(60),
                    'success_rate_24h': history.get_success_rate(1440),
                    'avg_response_time_1h': history.get_average_response_time(60),
                    'avg_response_time_24h': history.get_average_response_time(1440)
                }
        
        return report
    
    def get_service_health_history(self, service_name: str, 
                                 limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取服务健康历史
        
        Args:
            service_name: 服务名称
            limit: 返回数量限制
            
        Returns:
            List[Dict[str, Any]]: 健康历史记录
        """
        if service_name not in self.health_history:
            return []
        
        history = self.health_history[service_name]
        results = history.results[-limit:] if limit > 0 else history.results
        
        return [result.to_dict() for result in results]
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.stop()
        return False


# 默认告警处理器
def default_alert_handler(service_name: str, result: HealthCheckResult) -> None:
    """
    默认告警处理器
    
    Args:
        service_name: 服务名称
        result: 检查结果
    """
    logger.warning(f"服务健康告警 - {service_name}: {result.status.value} - {result.message}")


async def simple_health_check(service_name: str, port: int, 
                            check_type: str = "tcp") -> HealthCheckResult:
    """
    简单健康检查函数
    
    Args:
        service_name: 服务名称
        port: 端口号
        check_type: 检查类型
        
    Returns:
        HealthCheckResult: 检查结果
    """
    start_time = time.time()
    
    try:
        if check_type.lower() == "tcp":
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection('localhost', port),
                timeout=5
            )
            writer.close()
            await writer.wait_closed()
            
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.HEALTHY,
                response_time=time.time() - start_time,
                timestamp=time.time(),
                message="TCP连接检查通过"
            )
        else:
            return HealthCheckResult(
                service_name=service_name,
                status=HealthStatus.UNKNOWN,
                response_time=0.0,
                timestamp=time.time(),
                message="不支持的检查类型"
            )
    
    except Exception as e:
        return HealthCheckResult(
            service_name=service_name,
            status=HealthStatus.UNHEALTHY,
            response_time=time.time() - start_time,
            timestamp=time.time(),
            message=f"健康检查失败: {str(e)}"
        )