"""
网络工具模块

该模块提供IP地址工具、端口检测、网络状态检查和带宽限制工具等功能。
"""

import socket
import ipaddress
import subprocess
import platform
import time
import asyncio
import threading
from typing import Optional, List, Dict, Any, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import aiohttp
import requests
from loguru import logger


class NetworkError(Exception):
    """网络相关异常"""
    pass


class NetworkProtocol(Enum):
    """网络协议枚举"""
    TCP = "tcp"
    UDP = "udp"
    HTTP = "http"
    HTTPS = "https"
    WEBSOCKET = "websocket"


@dataclass
class NetworkInterface:
    """网络接口信息"""
    name: str
    ip_address: str
    netmask: str
    broadcast: str
    is_up: bool
    is_loopback: bool


@dataclass
class PortScanResult:
    """端口扫描结果"""
    host: str
    port: int
    is_open: bool
    service: Optional[str] = None
    response_time: Optional[float] = None


@dataclass
class PingResult:
    """Ping结果"""
    host: str
    is_reachable: bool
    response_time: Optional[float] = None
    packet_loss: float = 0.0
    packets_sent: int = 0
    packets_received: int = 0


@dataclass
class BandwidthStats:
    """带宽统计"""
    bytes_sent: int
    bytes_received: int
    packets_sent: int
    packets_received: int
    timestamp: float


class IPUtils:
    """
    IP地址工具类
    
    提供IP地址验证、转换和网络计算功能。
    """
    
    @staticmethod
    def is_valid_ip(ip: str, version: Optional[int] = None) -> bool:
        """
        验证IP地址是否有效
        
        Args:
            ip: IP地址字符串
            version: IP版本 (4 或 6)，None表示任意版本
            
        Returns:
            bool: 是否为有效IP地址
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            if version is None:
                return True
            elif version == 4:
                return isinstance(ip_obj, ipaddress.IPv4Address)
            elif version == 6:
                return isinstance(ip_obj, ipaddress.IPv6Address)
            else:
                return False
        except ValueError:
            return False
    
    @staticmethod
    def is_private_ip(ip: str) -> bool:
        """
        检查是否为私有IP地址
        
        Args:
            ip: IP地址字符串
            
        Returns:
            bool: 是否为私有IP
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.is_private
        except ValueError:
            return False
    
    @staticmethod
    def is_loopback_ip(ip: str) -> bool:
        """
        检查是否为回环IP地址
        
        Args:
            ip: IP地址字符串
            
        Returns:
            bool: 是否为回环IP
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.is_loopback
        except ValueError:
            return False
    
    @staticmethod
    def get_ip_version(ip: str) -> Optional[int]:
        """
        获取IP地址版本
        
        Args:
            ip: IP地址字符串
            
        Returns:
            Optional[int]: IP版本 (4 或 6)，无效时返回None
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            return ip_obj.version
        except ValueError:
            return None
    
    @staticmethod
    def ip_to_int(ip: str) -> Optional[int]:
        """
        将IP地址转换为整数
        
        Args:
            ip: IP地址字符串
            
        Returns:
            Optional[int]: 整数形式的IP地址
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            return int(ip_obj)
        except ValueError:
            return None
    
    @staticmethod
    def int_to_ip(ip_int: int, version: int = 4) -> str:
        """
        将整数转换为IP地址
        
        Args:
            ip_int: 整数形式的IP地址
            version: IP版本
            
        Returns:
            str: IP地址字符串
        """
        try:
            if version == 4:
                return str(ipaddress.IPv4Address(ip_int))
            elif version == 6:
                return str(ipaddress.IPv6Address(ip_int))
            else:
                raise ValueError(f"不支持的IP版本: {version}")
        except Exception as e:
            raise NetworkError(f"整数转IP地址失败: {e}")
    
    @staticmethod
    def get_network_range(network: str) -> List[str]:
        """
        获取网络范围内的所有IP地址
        
        Args:
            network: 网络地址 (如 "192.168.1.0/24")
            
        Returns:
            List[str]: IP地址列表
        """
        try:
            network_obj = ipaddress.ip_network(network, strict=False)
            return [str(ip) for ip in network_obj.hosts()]
        except ValueError as e:
            raise NetworkError(f"无效的网络地址: {e}")
    
    @staticmethod
    def is_ip_in_network(ip: str, network: str) -> bool:
        """
        检查IP是否在指定网络范围内
        
        Args:
            ip: IP地址
            network: 网络地址
            
        Returns:
            bool: 是否在网络范围内
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            network_obj = ipaddress.ip_network(network, strict=False)
            return ip_obj in network_obj
        except ValueError:
            return False
    
    @staticmethod
    def get_local_ip() -> str:
        """
        获取本地IP地址
        
        Returns:
            str: 本地IP地址
        """
        try:
            # 创建一个UDP套接字连接到外部地址
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
    
    @staticmethod
    def get_public_ip() -> Optional[str]:
        """
        获取公网IP地址
        
        Returns:
            Optional[str]: 公网IP地址
        """
        try:
            # 使用多个服务获取公网IP
            services = [
                "https://api.ipify.org",
                "https://icanhazip.com",
                "https://ident.me"
            ]
            
            for service in services:
                try:
                    response = requests.get(service, timeout=5)
                    if response.status_code == 200:
                        ip = response.text.strip()
                        if IPUtils.is_valid_ip(ip):
                            return ip
                except Exception:
                    continue
            
            return None
        except Exception:
            return None


class PortUtils:
    """
    端口工具类
    
    提供端口检测、扫描和管理功能。
    """
    
    @staticmethod
    def is_port_open(host: str, port: int, timeout: float = 3.0,
                    protocol: NetworkProtocol = NetworkProtocol.TCP) -> bool:
        """
        检查端口是否开放
        
        Args:
            host: 主机地址
            port: 端口号
            timeout: 超时时间
            protocol: 协议类型
            
        Returns:
            bool: 端口是否开放
        """
        try:
            if protocol == NetworkProtocol.TCP:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((host, port))
                sock.close()
                return result == 0
            
            elif protocol == NetworkProtocol.UDP:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(timeout)
                try:
                    sock.sendto(b"test", (host, port))
                    sock.recvfrom(1024)
                    return True
                except socket.timeout:
                    return False
                except Exception:
                    return True  # UDP可能没有响应但端口开放
                finally:
                    sock.close()
            
            else:
                return False
        
        except Exception:
            return False
    
    @staticmethod
    async def is_port_open_async(host: str, port: int, timeout: float = 3.0) -> bool:
        """
        异步检查端口是否开放
        
        Args:
            host: 主机地址
            port: 端口号
            timeout: 超时时间
            
        Returns:
            bool: 端口是否开放
        """
        try:
            future = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(future, timeout=timeout)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False
    
    @staticmethod
    def scan_ports(host: str, ports: List[int], timeout: float = 1.0,
                  max_threads: int = 100) -> List[PortScanResult]:
        """
        扫描多个端口
        
        Args:
            host: 主机地址
            ports: 端口列表
            timeout: 超时时间
            max_threads: 最大线程数
            
        Returns:
            List[PortScanResult]: 扫描结果
        """
        results = []
        
        def scan_port(port: int):
            start_time = time.time()
            is_open = PortUtils.is_port_open(host, port, timeout)
            response_time = time.time() - start_time
            
            service = PortUtils.get_service_name(port) if is_open else None
            
            results.append(PortScanResult(
                host=host,
                port=port,
                is_open=is_open,
                service=service,
                response_time=response_time if is_open else None
            ))
        
        # 使用线程池并发扫描
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            executor.map(scan_port, ports)
        
        return sorted(results, key=lambda x: x.port)
    
    @staticmethod
    async def scan_ports_async(host: str, ports: List[int], 
                              timeout: float = 1.0, max_concurrent: int = 100) -> List[PortScanResult]:
        """
        异步扫描多个端口
        
        Args:
            host: 主机地址
            ports: 端口列表
            timeout: 超时时间
            max_concurrent: 最大并发数
            
        Returns:
            List[PortScanResult]: 扫描结果
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scan_port(port: int):
            async with semaphore:
                start_time = time.time()
                is_open = await PortUtils.is_port_open_async(host, port, timeout)
                response_time = time.time() - start_time
                
                service = PortUtils.get_service_name(port) if is_open else None
                
                return PortScanResult(
                    host=host,
                    port=port,
                    is_open=is_open,
                    service=service,
                    response_time=response_time if is_open else None
                )
        
        tasks = [scan_port(port) for port in ports]
        results = await asyncio.gather(*tasks)
        
        return sorted(results, key=lambda x: x.port)
    
    @staticmethod
    def get_service_name(port: int) -> Optional[str]:
        """
        根据端口号获取服务名称
        
        Args:
            port: 端口号
            
        Returns:
            Optional[str]: 服务名称
        """
        try:
            return socket.getservbyport(port)
        except OSError:
            # 常见端口的手动映射
            common_ports = {
                21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp",
                53: "dns", 80: "http", 110: "pop3", 143: "imap",
                443: "https", 993: "imaps", 995: "pop3s",
                3389: "rdp", 5432: "postgresql", 3306: "mysql",
                6379: "redis", 27017: "mongodb", 8080: "http-alt"
            }
            return common_ports.get(port)
    
    @staticmethod
    def find_free_port(start_port: int = 8000, max_attempts: int = 100) -> Optional[int]:
        """
        查找空闲端口
        
        Args:
            start_port: 起始端口
            max_attempts: 最大尝试次数
            
        Returns:
            Optional[int]: 空闲端口号
        """
        for port in range(start_port, start_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
                    return port
            except OSError:
                continue
        return None
    
    @staticmethod
    def get_listening_ports() -> List[Dict[str, Any]]:
        """
        获取系统监听端口列表
        
        Returns:
            List[Dict[str, Any]]: 监听端口信息
        """
        try:
            import psutil
            
            listening_ports = []
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == psutil.CONN_LISTEN:
                    listening_ports.append({
                        'port': conn.laddr.port,
                        'address': conn.laddr.ip,
                        'family': 'IPv4' if conn.family == socket.AF_INET else 'IPv6',
                        'type': 'TCP' if conn.type == socket.SOCK_STREAM else 'UDP',
                        'pid': conn.pid
                    })
            
            return listening_ports
        
        except ImportError:
            logger.warning("psutil未安装，无法获取监听端口信息")
            return []
        except Exception as e:
            logger.error(f"获取监听端口失败: {e}")
            return []


class NetworkChecker:
    """
    网络状态检查器
    
    提供网络连通性检查和网络质量测试功能。
    """
    
    @staticmethod
    def ping(host: str, count: int = 4, timeout: float = 3.0) -> PingResult:
        """
        Ping主机
        
        Args:
            host: 主机地址
            count: Ping次数
            timeout: 超时时间
            
        Returns:
            PingResult: Ping结果
        """
        try:
            system = platform.system().lower()
            
            if system == "windows":
                cmd = ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]
            else:
                cmd = ["ping", "-c", str(count), "-W", str(int(timeout)), host]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * count + 5)
            
            if result.returncode == 0:
                output = result.stdout
                
                # 解析ping结果
                packets_sent = count
                packets_received = 0
                response_times = []
                
                for line in output.split('\n'):
                    if 'time=' in line or 'time<' in line:
                        packets_received += 1
                        # 提取响应时间
                        import re
                        time_match = re.search(r'time[<=](\d+(?:\.\d+)?)', line)
                        if time_match:
                            response_times.append(float(time_match.group(1)))
                
                packet_loss = (packets_sent - packets_received) / packets_sent * 100
                avg_response_time = sum(response_times) / len(response_times) if response_times else None
                
                return PingResult(
                    host=host,
                    is_reachable=packets_received > 0,
                    response_time=avg_response_time,
                    packet_loss=packet_loss,
                    packets_sent=packets_sent,
                    packets_received=packets_received
                )
            else:
                return PingResult(
                    host=host,
                    is_reachable=False,
                    packet_loss=100.0,
                    packets_sent=count,
                    packets_received=0
                )
        
        except Exception as e:
            logger.error(f"Ping失败: {e}")
            return PingResult(
                host=host,
                is_reachable=False,
                packet_loss=100.0,
                packets_sent=count,
                packets_received=0
            )
    
    @staticmethod
    async def ping_async(host: str, count: int = 4, timeout: float = 3.0) -> PingResult:
        """
        异步Ping主机
        
        Args:
            host: 主机地址
            count: Ping次数
            timeout: 超时时间
            
        Returns:
            PingResult: Ping结果
        """
        try:
            system = platform.system().lower()
            
            if system == "windows":
                cmd = ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]
            else:
                cmd = ["ping", "-c", str(count), "-W", str(int(timeout)), host]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout * count + 5
            )
            
            if process.returncode == 0:
                output = stdout.decode()
                
                # 解析ping结果（同上）
                packets_sent = count
                packets_received = 0
                response_times = []
                
                for line in output.split('\n'):
                    if 'time=' in line or 'time<' in line:
                        packets_received += 1
                        import re
                        time_match = re.search(r'time[<=](\d+(?:\.\d+)?)', line)
                        if time_match:
                            response_times.append(float(time_match.group(1)))
                
                packet_loss = (packets_sent - packets_received) / packets_sent * 100
                avg_response_time = sum(response_times) / len(response_times) if response_times else None
                
                return PingResult(
                    host=host,
                    is_reachable=packets_received > 0,
                    response_time=avg_response_time,
                    packet_loss=packet_loss,
                    packets_sent=packets_sent,
                    packets_received=packets_received
                )
            else:
                return PingResult(
                    host=host,
                    is_reachable=False,
                    packet_loss=100.0,
                    packets_sent=count,
                    packets_received=0
                )
        
        except Exception as e:
            logger.error(f"异步Ping失败: {e}")
            return PingResult(
                host=host,
                is_reachable=False,
                packet_loss=100.0,
                packets_sent=count,
                packets_received=0
            )
    
    @staticmethod
    def check_internet_connection(test_urls: Optional[List[str]] = None,
                                timeout: float = 5.0) -> bool:
        """
        检查互联网连接
        
        Args:
            test_urls: 测试URL列表
            timeout: 超时时间
            
        Returns:
            bool: 是否有互联网连接
        """
        if test_urls is None:
            test_urls = [
                "https://www.google.com",
                "https://www.baidu.com",
                "https://www.github.com"
            ]
        
        for url in test_urls:
            try:
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    return True
            except Exception:
                continue
        
        return False
    
    @staticmethod
    async def check_internet_connection_async(test_urls: Optional[List[str]] = None,
                                            timeout: float = 5.0) -> bool:
        """
        异步检查互联网连接
        
        Args:
            test_urls: 测试URL列表
            timeout: 超时时间
            
        Returns:
            bool: 是否有互联网连接
        """
        if test_urls is None:
            test_urls = [
                "https://www.google.com",
                "https://www.baidu.com",
                "https://www.github.com"
            ]
        
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                for url in test_urls:
                    try:
                        async with session.get(url) as response:
                            if response.status == 200:
                                return True
                    except Exception:
                        continue
            
            return False
        
        except Exception:
            return False


class BandwidthLimiter:
    """
    带宽限制器
    
    提供网络带宽限制和流量控制功能。
    """
    
    def __init__(self, max_bytes_per_second: int):
        """
        初始化带宽限制器
        
        Args:
            max_bytes_per_second: 每秒最大字节数
        """
        self.max_bytes_per_second = max_bytes_per_second
        self.tokens = max_bytes_per_second
        self.last_update = time.time()
        self.lock = threading.Lock()
    
    def consume(self, bytes_count: int) -> bool:
        """
        消费带宽令牌
        
        Args:
            bytes_count: 要消费的字节数
            
        Returns:
            bool: 是否允许传输
        """
        with self.lock:
            now = time.time()
            elapsed = now - self.last_update
            
            # 添加新令牌
            self.tokens = min(
                self.max_bytes_per_second,
                self.tokens + elapsed * self.max_bytes_per_second
            )
            self.last_update = now
            
            # 检查是否有足够令牌
            if self.tokens >= bytes_count:
                self.tokens -= bytes_count
                return True
            else:
                return False
    
    def wait_time(self, bytes_count: int) -> float:
        """
        计算需要等待的时间
        
        Args:
            bytes_count: 要传输的字节数
            
        Returns:
            float: 等待时间（秒）
        """
        with self.lock:
            if self.tokens >= bytes_count:
                return 0.0
            else:
                deficit = bytes_count - self.tokens
                return deficit / self.max_bytes_per_second
    
    async def wait_for_bandwidth(self, bytes_count: int) -> None:
        """
        异步等待带宽可用
        
        Args:
            bytes_count: 要传输的字节数
        """
        wait_time = self.wait_time(bytes_count)
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        
        # 重新检查并消费令牌
        while not self.consume(bytes_count):
            await asyncio.sleep(0.01)  # 短暂等待


# 便捷函数
def get_local_ip() -> str:
    """获取本地IP地址的便捷函数"""
    return IPUtils.get_local_ip()

def get_public_ip() -> Optional[str]:
    """获取公网IP地址的便捷函数"""
    return IPUtils.get_public_ip()

def is_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """检查端口是否开放的便捷函数"""
    return PortUtils.is_port_open(host, port, timeout)

def ping(host: str, count: int = 4) -> PingResult:
    """Ping主机的便捷函数"""
    return NetworkChecker.ping(host, count)

def check_internet() -> bool:
    """检查互联网连接的便捷函数"""
    return NetworkChecker.check_internet_connection()


if __name__ == "__main__":
    # 测试代码
    def test_network_utils():
        """测试网络工具"""
        
        # 测试IP地址工具
        print("测试IP地址工具:")
        local_ip = get_local_ip()
        print(f"本地IP: {local_ip}")
        
        public_ip = get_public_ip()
        print(f"公网IP: {public_ip}")
        
        test_ip = "192.168.1.1"
        print(f"{test_ip} 是否为私有IP: {IPUtils.is_private_ip(test_ip)}")
        print(f"{test_ip} 是否在 192.168.1.0/24 网络: {IPUtils.is_ip_in_network(test_ip, '192.168.1.0/24')}")
        
        # 测试端口工具
        print("\n测试端口工具:")
        print(f"本地80端口是否开放: {is_port_open('localhost', 80)}")
        print(f"本地22端口是否开放: {is_port_open('localhost', 22)}")
        
        free_port = PortUtils.find_free_port()
        print(f"找到空闲端口: {free_port}")
        
        # 测试网络检查
        print("\n测试网络检查:")
        internet_available = check_internet()
        print(f"互联网连接: {internet_available}")
        
        # Ping测试
        ping_result = ping("8.8.8.8", 2)
        print(f"Ping 8.8.8.8: 可达={ping_result.is_reachable}, "
              f"响应时间={ping_result.response_time}ms, "
              f"丢包率={ping_result.packet_loss}%")
        
        # 测试带宽限制器
        print("\n测试带宽限制器:")
        limiter = BandwidthLimiter(1024 * 1024)  # 1MB/s
        
        start_time = time.time()
        for i in range(3):
            can_send = limiter.consume(512 * 1024)  # 512KB
            print(f"第{i+1}次传输 (512KB): {'允许' if can_send else '被限制'}")
            if not can_send:
                wait_time = limiter.wait_time(512 * 1024)
                print(f"需要等待: {wait_time:.2f}秒")
        
        elapsed = time.time() - start_time
        print(f"总耗时: {elapsed:.2f}秒")
    
    test_network_utils()