"""
签名验证模块

该模块提供请求签名的生成和验证功能，包括：
- HMAC-SHA256签名算法
- 防重放攻击（基于时间戳和nonce）
- 签名缓存机制
- 白名单跳过验证
- 多种签名策略
"""

import hashlib
import hmac
import time
import json
import asyncio
from typing import Dict, Any, Optional, List, Union, Callable
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlencode, parse_qsl

from common.logger import logger


class SignatureMethod(Enum):
    """签名方法枚举"""
    HMAC_SHA256 = "HMAC-SHA256"
    HMAC_SHA1 = "HMAC-SHA1"
    MD5 = "MD5"


class SignatureVersion(Enum):
    """签名版本枚举"""
    V1 = "1.0"
    V2 = "2.0"


@dataclass
class SignatureConfig:
    """签名配置"""
    secret_key: str = "knight_server_signature_secret"
    signature_method: SignatureMethod = SignatureMethod.HMAC_SHA256
    signature_version: SignatureVersion = SignatureVersion.V2
    timestamp_tolerance: int = 300  # 时间戳容差（秒）
    nonce_cache_time: int = 600  # nonce缓存时间（秒）
    enable_nonce_check: bool = True
    enable_timestamp_check: bool = True
    enable_signature_cache: bool = True
    signature_cache_time: int = 60  # 签名缓存时间（秒）
    whitelist_enabled: bool = True
    required_headers: List[str] = None  # 必需的请求头
    ignored_params: List[str] = None  # 忽略的参数


@dataclass
class SignatureRequest:
    """签名请求"""
    method: str
    url: str
    headers: Dict[str, str]
    params: Dict[str, Any]
    body: Optional[str] = None
    timestamp: Optional[int] = None
    nonce: Optional[str] = None
    signature: Optional[str] = None


@dataclass
class SignatureResult:
    """签名结果"""
    signature: str
    timestamp: int
    nonce: str
    signature_method: str
    signature_version: str


class SignatureError(Exception):
    """签名相关异常基类"""
    pass


class TimestampError(SignatureError):
    """时间戳异常"""
    pass


class NonceError(SignatureError):
    """Nonce异常"""
    pass


class SignatureInvalidError(SignatureError):
    """签名无效异常"""
    pass


class SignatureVerifier:
    """签名验证器"""
    
    def __init__(self, config: SignatureConfig, redis_manager=None):
        """
        初始化签名验证器
        
        Args:
            config: 签名配置
            redis_manager: Redis管理器（用于缓存和防重放）
        """
        self.config = config
        self.redis_manager = redis_manager
        self._whitelist: List[str] = []
        self._signature_cache: Dict[str, Any] = {}
        self._nonce_cache: Dict[str, int] = {}
        
        # 初始化默认配置
        if self.config.required_headers is None:
            self.config.required_headers = ['Content-Type', 'User-Agent']
        
        if self.config.ignored_params is None:
            self.config.ignored_params = ['signature', 'access_token']
    
    def add_to_whitelist(self, identifier: str):
        """
        添加到白名单
        
        Args:
            identifier: 标识符（IP地址、API路径等）
        """
        if identifier not in self._whitelist:
            self._whitelist.append(identifier)
            logger.info(f"已添加到签名验证白名单: {identifier}")
    
    def remove_from_whitelist(self, identifier: str):
        """
        从白名单移除
        
        Args:
            identifier: 标识符
        """
        if identifier in self._whitelist:
            self._whitelist.remove(identifier)
            logger.info(f"已从签名验证白名单移除: {identifier}")
    
    def is_whitelisted(self, identifier: str) -> bool:
        """
        检查是否在白名单中
        
        Args:
            identifier: 标识符
            
        Returns:
            bool: 是否在白名单中
        """
        return identifier in self._whitelist
    
    def _generate_nonce(self) -> str:
        """生成随机nonce"""
        import uuid
        return str(uuid.uuid4()).replace('-', '')
    
    def _normalize_params(self, params: Dict[str, Any]) -> str:
        """
        规范化参数
        
        Args:
            params: 参数字典
            
        Returns:
            str: 规范化后的参数字符串
        """
        # 过滤掉忽略的参数
        filtered_params = {
            k: v for k, v in params.items() 
            if k not in self.config.ignored_params
        }
        
        # 按键排序
        sorted_params = sorted(filtered_params.items())
        
        # 构造查询字符串
        normalized = []
        for key, value in sorted_params:
            if value is None:
                continue
            
            # 处理不同类型的值
            if isinstance(value, (list, tuple)):
                for item in value:
                    normalized.append(f"{key}={item}")
            else:
                normalized.append(f"{key}={value}")
        
        return "&".join(normalized)
    
    def _normalize_headers(self, headers: Dict[str, str]) -> str:
        """
        规范化请求头
        
        Args:
            headers: 请求头字典
            
        Returns:
            str: 规范化后的请求头字符串
        """
        # 只包含必需的请求头
        required_headers = {}
        for header in self.config.required_headers:
            header_lower = header.lower()
            for key, value in headers.items():
                if key.lower() == header_lower:
                    required_headers[header] = value
                    break
        
        # 按键排序
        sorted_headers = sorted(required_headers.items())
        
        # 构造头字符串
        header_strings = []
        for key, value in sorted_headers:
            header_strings.append(f"{key}:{value}")
        
        return "|".join(header_strings)
    
    def _build_signature_base_string(self, request: SignatureRequest) -> str:
        """
        构建签名基础字符串
        
        Args:
            request: 签名请求
            
        Returns:
            str: 签名基础字符串
        """
        # 规范化参数
        normalized_params = self._normalize_params(request.params)
        
        # 规范化请求头
        normalized_headers = self._normalize_headers(request.headers)
        
        # 构建基础字符串
        base_string_parts = [
            request.method.upper(),
            request.url,
            normalized_params,
            normalized_headers
        ]
        
        # 添加时间戳和nonce
        if request.timestamp:
            base_string_parts.append(str(request.timestamp))
        
        if request.nonce:
            base_string_parts.append(request.nonce)
        
        # 添加请求体（如果有）
        if request.body:
            if self.config.signature_version == SignatureVersion.V2:
                # V2版本包含请求体
                body_hash = hashlib.sha256(request.body.encode()).hexdigest()
                base_string_parts.append(body_hash)
        
        base_string = "|".join(base_string_parts)
        logger.debug(f"签名基础字符串: {base_string}")
        
        return base_string
    
    def _calculate_signature(self, base_string: str) -> str:
        """
        计算签名
        
        Args:
            base_string: 签名基础字符串
            
        Returns:
            str: 签名值
        """
        if self.config.signature_method == SignatureMethod.HMAC_SHA256:
            signature = hmac.new(
                self.config.secret_key.encode(),
                base_string.encode(),
                hashlib.sha256
            ).hexdigest()
        elif self.config.signature_method == SignatureMethod.HMAC_SHA1:
            signature = hmac.new(
                self.config.secret_key.encode(),
                base_string.encode(),
                hashlib.sha1
            ).hexdigest()
        elif self.config.signature_method == SignatureMethod.MD5:
            signature = hashlib.md5(
                (base_string + self.config.secret_key).encode()
            ).hexdigest()
        else:
            raise SignatureError(f"不支持的签名方法: {self.config.signature_method}")
        
        return signature
    
    def generate_signature(self, request: SignatureRequest) -> SignatureResult:
        """
        生成签名
        
        Args:
            request: 签名请求
            
        Returns:
            SignatureResult: 签名结果
        """
        # 生成时间戳和nonce
        timestamp = request.timestamp or int(time.time())
        nonce = request.nonce or self._generate_nonce()
        
        # 更新请求
        request.timestamp = timestamp
        request.nonce = nonce
        
        # 构建签名基础字符串
        base_string = self._build_signature_base_string(request)
        
        # 计算签名
        signature = self._calculate_signature(base_string)
        
        return SignatureResult(
            signature=signature,
            timestamp=timestamp,
            nonce=nonce,
            signature_method=self.config.signature_method.value,
            signature_version=self.config.signature_version.value
        )
    
    async def _check_timestamp(self, timestamp: int) -> bool:
        """
        检查时间戳
        
        Args:
            timestamp: 时间戳
            
        Returns:
            bool: 时间戳是否有效
        """
        if not self.config.enable_timestamp_check:
            return True
        
        current_time = int(time.time())
        time_diff = abs(current_time - timestamp)
        
        if time_diff > self.config.timestamp_tolerance:
            logger.warning(f"时间戳超出容差: {time_diff}秒")
            return False
        
        return True
    
    async def _check_nonce(self, nonce: str, timestamp: int) -> bool:
        """
        检查nonce
        
        Args:
            nonce: nonce值
            timestamp: 时间戳
            
        Returns:
            bool: nonce是否有效
        """
        if not self.config.enable_nonce_check:
            return True
        
        # 检查Redis缓存
        if self.redis_manager:
            try:
                nonce_key = f"signature_nonce:{nonce}"
                exists = await self.redis_manager.exists(nonce_key)
                
                if exists:
                    logger.warning(f"Nonce已存在: {nonce}")
                    return False
                
                # 添加到缓存
                await self.redis_manager.setex(
                    nonce_key, 
                    self.config.nonce_cache_time, 
                    str(timestamp)
                )
                
                return True
            except Exception as e:
                logger.error(f"检查nonce时Redis操作失败: {e}")
                # 降级到内存缓存
        
        # 内存缓存检查
        current_time = int(time.time())
        
        # 清理过期的nonce
        expired_nonces = [
            n for n, ts in self._nonce_cache.items()
            if current_time - ts > self.config.nonce_cache_time
        ]
        for n in expired_nonces:
            del self._nonce_cache[n]
        
        # 检查nonce是否存在
        if nonce in self._nonce_cache:
            logger.warning(f"Nonce已存在: {nonce}")
            return False
        
        # 添加到缓存
        self._nonce_cache[nonce] = timestamp
        
        return True
    
    async def _check_signature_cache(self, signature: str) -> bool:
        """
        检查签名缓存
        
        Args:
            signature: 签名值
            
        Returns:
            bool: 签名是否在缓存中
        """
        if not self.config.enable_signature_cache:
            return False
        
        # 检查Redis缓存
        if self.redis_manager:
            try:
                cache_key = f"signature_cache:{signature}"
                exists = await self.redis_manager.exists(cache_key)
                return exists
            except Exception as e:
                logger.error(f"检查签名缓存时Redis操作失败: {e}")
        
        # 内存缓存检查
        current_time = int(time.time())
        
        # 清理过期的签名
        expired_signatures = [
            sig for sig, ts in self._signature_cache.items()
            if current_time - ts > self.config.signature_cache_time
        ]
        for sig in expired_signatures:
            del self._signature_cache[sig]
        
        return signature in self._signature_cache
    
    async def _add_signature_to_cache(self, signature: str):
        """
        添加签名到缓存
        
        Args:
            signature: 签名值
        """
        if not self.config.enable_signature_cache:
            return
        
        # 添加到Redis缓存
        if self.redis_manager:
            try:
                cache_key = f"signature_cache:{signature}"
                await self.redis_manager.setex(
                    cache_key, 
                    self.config.signature_cache_time, 
                    str(int(time.time()))
                )
            except Exception as e:
                logger.error(f"添加签名到缓存时Redis操作失败: {e}")
        
        # 添加到内存缓存
        self._signature_cache[signature] = int(time.time())
    
    async def verify_signature(self, request: SignatureRequest, 
                              identifier: str = None) -> bool:
        """
        验证签名
        
        Args:
            request: 签名请求
            identifier: 标识符（用于白名单检查）
            
        Returns:
            bool: 签名是否有效
            
        Raises:
            TimestampError: 时间戳错误
            NonceError: Nonce错误
            SignatureInvalidError: 签名无效
        """
        # 检查白名单
        if identifier and self.is_whitelisted(identifier):
            logger.debug(f"跳过签名验证（白名单）: {identifier}")
            return True
        
        # 检查必需参数
        if not request.signature:
            raise SignatureInvalidError("缺少签名参数")
        
        if not request.timestamp:
            raise TimestampError("缺少时间戳参数")
        
        if not request.nonce:
            raise NonceError("缺少nonce参数")
        
        # 检查时间戳
        if not await self._check_timestamp(request.timestamp):
            raise TimestampError("时间戳无效或超出容差")
        
        # 检查nonce
        if not await self._check_nonce(request.nonce, request.timestamp):
            raise NonceError("Nonce无效或重复")
        
        # 检查签名缓存
        if await self._check_signature_cache(request.signature):
            logger.debug("签名验证命中缓存")
            return True
        
        # 生成预期签名
        expected_result = self.generate_signature(request)
        
        # 比较签名
        if request.signature != expected_result.signature:
            logger.warning(f"签名验证失败: 预期{expected_result.signature}, 实际{request.signature}")
            raise SignatureInvalidError("签名无效")
        
        # 添加到缓存
        await self._add_signature_to_cache(request.signature)
        
        logger.debug("签名验证成功")
        return True
    
    def create_signature_headers(self, result: SignatureResult) -> Dict[str, str]:
        """
        创建签名相关的请求头
        
        Args:
            result: 签名结果
            
        Returns:
            Dict[str, str]: 签名请求头
        """
        return {
            'X-Signature': result.signature,
            'X-Timestamp': str(result.timestamp),
            'X-Nonce': result.nonce,
            'X-Signature-Method': result.signature_method,
            'X-Signature-Version': result.signature_version
        }
    
    def parse_signature_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        解析签名相关的请求头
        
        Args:
            headers: 请求头字典
            
        Returns:
            Dict[str, str]: 解析后的签名信息
        """
        signature_info = {}
        
        # 大小写不敏感的头部查找
        headers_lower = {k.lower(): v for k, v in headers.items()}
        
        mapping = {
            'signature': 'x-signature',
            'timestamp': 'x-timestamp',
            'nonce': 'x-nonce',
            'signature_method': 'x-signature-method',
            'signature_version': 'x-signature-version'
        }
        
        for key, header_name in mapping.items():
            if header_name in headers_lower:
                signature_info[key] = headers_lower[header_name]
        
        return signature_info
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            Dict[str, Any]: 缓存统计信息
        """
        stats = {
            'nonce_cache_size': len(self._nonce_cache),
            'signature_cache_size': len(self._signature_cache),
            'whitelist_size': len(self._whitelist),
            'config': {
                'timestamp_tolerance': self.config.timestamp_tolerance,
                'nonce_cache_time': self.config.nonce_cache_time,
                'signature_cache_time': self.config.signature_cache_time,
                'enable_nonce_check': self.config.enable_nonce_check,
                'enable_timestamp_check': self.config.enable_timestamp_check,
                'enable_signature_cache': self.config.enable_signature_cache,
                'whitelist_enabled': self.config.whitelist_enabled
            }
        }
        
        # 如果有Redis管理器，获取Redis统计
        if self.redis_manager:
            try:
                # 获取nonce缓存数量
                nonce_keys = await self.redis_manager.keys("signature_nonce:*")
                stats['redis_nonce_cache_size'] = len(nonce_keys)
                
                # 获取签名缓存数量
                signature_keys = await self.redis_manager.keys("signature_cache:*")
                stats['redis_signature_cache_size'] = len(signature_keys)
            except Exception as e:
                logger.error(f"获取Redis统计失败: {e}")
                stats['redis_error'] = str(e)
        
        return stats
    
    async def clear_cache(self):
        """清理缓存"""
        # 清理内存缓存
        self._nonce_cache.clear()
        self._signature_cache.clear()
        
        # 清理Redis缓存
        if self.redis_manager:
            try:
                # 清理nonce缓存
                nonce_keys = await self.redis_manager.keys("signature_nonce:*")
                if nonce_keys:
                    await self.redis_manager.delete(*nonce_keys)
                
                # 清理签名缓存
                signature_keys = await self.redis_manager.keys("signature_cache:*")
                if signature_keys:
                    await self.redis_manager.delete(*signature_keys)
                
                logger.info("已清理Redis签名缓存")
            except Exception as e:
                logger.error(f"清理Redis缓存失败: {e}")
        
        logger.info("已清理签名缓存")


# 默认配置实例
default_config = SignatureConfig()

# 默认签名验证器实例
_default_verifier = None


def get_signature_verifier(config: SignatureConfig = None, redis_manager=None) -> SignatureVerifier:
    """
    获取签名验证器实例
    
    Args:
        config: 签名配置
        redis_manager: Redis管理器
        
    Returns:
        SignatureVerifier: 签名验证器实例
    """
    global _default_verifier
    
    if config is None:
        config = default_config
    
    if _default_verifier is None:
        _default_verifier = SignatureVerifier(config, redis_manager)
    
    return _default_verifier


# 便捷函数
async def verify_signature(request: SignatureRequest, identifier: str = None,
                          config: SignatureConfig = None) -> bool:
    """验证签名的便捷函数"""
    verifier = get_signature_verifier(config)
    return await verifier.verify_signature(request, identifier)


def generate_signature(request: SignatureRequest, config: SignatureConfig = None) -> SignatureResult:
    """生成签名的便捷函数"""
    verifier = get_signature_verifier(config)
    return verifier.generate_signature(request)