"""
用户业务服务

该模块实现了用户相关的业务逻辑服务，继承自BaseService，
负责用户认证、信息管理、会话管理、状态同步等核心功能。

主要功能：
- 用户认证和授权
- 用户信息管理
- 会话管理
- 用户状态同步
- 用户权限管理

业务特点：
- 支持多种登录方式
- 安全的密码处理
- 完善的会话管理
- 实时状态同步
- 用户行为追踪
"""

import asyncio
import hashlib
import time
import json
import uuid
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from services.base import BaseService, ServiceConfig
from services.base import ServiceException, transactional, cached, retry
from common.logger import logger

# 尝试导入加密模块
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    logger.warning("bcrypt模块不可用，使用简单哈希")
    BCRYPT_AVAILABLE = False


class UserStatus(Enum):
    """用户状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    AWAY = "away"
    BUSY = "busy"
    INVISIBLE = "invisible"


class LoginType(Enum):
    """登录类型"""
    PASSWORD = "password"
    TOKEN = "token"
    GUEST = "guest"
    THIRD_PARTY = "third_party"


@dataclass
class UserServiceConfig(ServiceConfig):
    """用户服务配置"""
    # 密码安全配置
    password_min_length: int = 6
    password_max_length: int = 32
    password_require_special: bool = True
    password_hash_rounds: int = 12
    
    # 会话配置
    session_timeout: int = 3600  # 1小时
    max_concurrent_sessions: int = 3
    session_extend_threshold: int = 600  # 10分钟
    
    # 用户限制
    max_username_length: int = 20
    max_nickname_length: int = 30
    max_signature_length: int = 100
    
    # 缓存配置
    user_cache_ttl: int = 300  # 5分钟
    status_cache_ttl: int = 60  # 1分钟
    
    # 安全配置
    login_attempt_limit: int = 5
    login_attempt_window: int = 300  # 5分钟
    enable_ip_whitelist: bool = False
    enable_device_binding: bool = False


class UserService(BaseService):
    """用户业务服务
    
    提供用户相关的所有业务逻辑，包括认证、信息管理、会话管理等。
    """
    
    def __init__(self, 
                 max_concurrent_users: int = 10000,
                 session_timeout: int = 3600,
                 enable_cache: bool = True,
                 config: Optional[UserServiceConfig] = None):
        """
        初始化用户服务
        
        Args:
            max_concurrent_users: 最大并发用户数
            session_timeout: 会话超时时间
            enable_cache: 是否启用缓存
            config: 用户服务配置
        """
        super().__init__(config=config)
        
        self.user_config = config or UserServiceConfig()
        self.max_concurrent_users = max_concurrent_users
        self.session_timeout = session_timeout
        self.enable_cache = enable_cache
        
        # 用户数据存储
        self.users: Dict[str, Dict[str, Any]] = {}
        self.user_sessions: Dict[str, Dict[str, Any]] = {}
        self.user_status: Dict[str, UserStatus] = {}
        
        # 登录尝试记录
        self.login_attempts: Dict[str, List[float]] = {}
        
        # 用户索引
        self.username_to_userid: Dict[str, str] = {}
        self.email_to_userid: Dict[str, str] = {}
        
        # 统计信息
        self.stats = {
            "total_users": 0,
            "active_users": 0,
            "total_logins": 0,
            "failed_logins": 0,
            "active_sessions": 0
        }
        
        self.logger.info("用户服务初始化完成", 
                        max_concurrent_users=max_concurrent_users,
                        session_timeout=session_timeout)
    
    async def initialize(self):
        """初始化用户服务"""
        try:
            await super().initialize()
            
            # 初始化用户存储
            await self._initialize_user_storage()
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_sessions())
            asyncio.create_task(self._cleanup_login_attempts())
            asyncio.create_task(self._sync_user_status())
            
            self.logger.info("用户服务初始化完成")
            
        except Exception as e:
            self.logger.error("用户服务初始化失败", error=str(e))
            raise
    
    async def _initialize_user_storage(self):
        """初始化用户存储"""
        try:
            # 这里应该连接到实际的数据库
            # 现在使用内存存储作为示例
            
            # 创建一些测试用户
            await self._create_test_users()
            
            self.logger.info("用户存储初始化完成")
            
        except Exception as e:
            self.logger.error("用户存储初始化失败", error=str(e))
            raise
    
    async def _create_test_users(self):
        """创建测试用户"""
        test_users = [
            {
                "username": "testuser1",
                "password": "password123",
                "email": "test1@example.com",
                "nickname": "测试用户1"
            },
            {
                "username": "testuser2",
                "password": "password123",
                "email": "test2@example.com",
                "nickname": "测试用户2"
            }
        ]
        
        for user_data in test_users:
            user_id = str(uuid.uuid4())
            password_hash = await self._hash_password(user_data["password"])
            
            user_info = {
                "user_id": user_id,
                "username": user_data["username"],
                "email": user_data["email"],
                "nickname": user_data["nickname"],
                "password_hash": password_hash,
                "level": 1,
                "exp": 0,
                "vip_level": 0,
                "avatar_url": "",
                "gender": 0,
                "birthday": "",
                "signature": "",
                "created_time": time.time(),
                "last_login": 0,
                "login_count": 0,
                "status": UserStatus.OFFLINE.value,
                "is_active": True
            }
            
            self.users[user_id] = user_info
            self.username_to_userid[user_data["username"]] = user_id
            self.email_to_userid[user_data["email"]] = user_id
            self.stats["total_users"] += 1
    
    @transactional
    async def authenticate_user(self, 
                               username: str, 
                               password: str,
                               device_id: Optional[str] = None,
                               client_version: Optional[str] = None,
                               login_type: str = "password") -> Dict[str, Any]:
        """
        用户认证
        
        Args:
            username: 用户名
            password: 密码
            device_id: 设备ID
            client_version: 客户端版本
            login_type: 登录类型
            
        Returns:
            认证结果
        """
        try:
            # 查找用户
            user_id = self.username_to_userid.get(username)
            if not user_id:
                # 尝试通过邮箱查找
                user_id = self.email_to_userid.get(username)
            
            if not user_id:
                self.stats["failed_logins"] += 1
                return {
                    "success": False,
                    "message": "用户不存在",
                    "code": 404
                }
            
            user_info = self.users[user_id]
            
            # 检查用户状态
            if not user_info["is_active"]:
                self.stats["failed_logins"] += 1
                return {
                    "success": False,
                    "message": "用户已被禁用",
                    "code": 403
                }
            
            # 验证密码
            if login_type == "password":
                if not await self._verify_password(password, user_info["password_hash"]):
                    self.stats["failed_logins"] += 1
                    return {
                        "success": False,
                        "message": "密码错误",
                        "code": 401
                    }
            
            # 更新用户登录信息
            user_info["last_login"] = time.time()
            user_info["login_count"] += 1
            
            # 更新统计信息
            self.stats["total_logins"] += 1
            
            # 返回成功结果
            return {
                "success": True,
                "user_info": {
                    "user_id": user_info["user_id"],
                    "username": user_info["username"],
                    "email": user_info["email"],
                    "nickname": user_info["nickname"],
                    "level": user_info["level"],
                    "exp": user_info["exp"],
                    "vip_level": user_info["vip_level"],
                    "avatar_url": user_info["avatar_url"],
                    "last_login": user_info["last_login"],
                    "login_count": user_info["login_count"]
                },
                "is_new_user": user_info["login_count"] == 1
            }
            
        except Exception as e:
            self.logger.error("用户认证失败", error=str(e))
            raise ServiceException(f"用户认证失败: {str(e)}")
    
    async def logout_user(self, user_id: str, session_id: str, logout_type: str = "normal"):
        """
        用户登出
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            logout_type: 登出类型
        """
        try:
            # 移除用户会话
            if session_id in self.user_sessions:
                del self.user_sessions[session_id]
                self.stats["active_sessions"] -= 1
            
            # 更新用户状态
            self.user_status[user_id] = UserStatus.OFFLINE
            
            # 更新统计信息
            if user_id in [status for status in self.user_status.values() if status != UserStatus.OFFLINE]:
                self.stats["active_users"] -= 1
            
            self.logger.info("用户登出成功", user_id=user_id, session_id=session_id)
            
        except Exception as e:
            self.logger.error("用户登出失败", error=str(e))
            raise ServiceException(f"用户登出失败: {str(e)}")
    
    @cached(ttl=300)
    async def get_user_info(self, user_id: str, include_private: bool = False) -> Optional[Dict[str, Any]]:
        """
        获取用户信息
        
        Args:
            user_id: 用户ID
            include_private: 是否包含私人信息
            
        Returns:
            用户信息
        """
        try:
            user_info = self.users.get(user_id)
            if not user_info:
                return None
            
            # 构建返回信息
            result = {
                "user_id": user_info["user_id"],
                "username": user_info["username"],
                "nickname": user_info["nickname"],
                "level": user_info["level"],
                "exp": user_info["exp"],
                "vip_level": user_info["vip_level"],
                "avatar_url": user_info["avatar_url"],
                "gender": user_info["gender"],
                "signature": user_info["signature"],
                "created_time": user_info["created_time"],
                "last_login": user_info["last_login"],
                "login_count": user_info["login_count"],
                "status": user_info["status"]
            }
            
            # 如果包含私人信息
            if include_private:
                result.update({
                    "email": user_info["email"],
                    "birthday": user_info["birthday"],
                    "is_active": user_info["is_active"]
                })
            
            return result
            
        except Exception as e:
            self.logger.error("获取用户信息失败", error=str(e))
            raise ServiceException(f"获取用户信息失败: {str(e)}")
    
    @transactional
    async def update_user_info(self, user_id: str, update_data: Dict[str, Any]) -> List[str]:
        """
        更新用户信息
        
        Args:
            user_id: 用户ID
            update_data: 更新数据
            
        Returns:
            更新的字段列表
        """
        try:
            user_info = self.users.get(user_id)
            if not user_info:
                raise ServiceException("用户不存在")
            
            updated_fields = []
            
            # 可更新的字段
            updatable_fields = [
                "nickname", "avatar_url", "gender", "birthday", "signature"
            ]
            
            for field, value in update_data.items():
                if field in updatable_fields:
                    # 字段验证
                    if field == "nickname" and len(value) > self.user_config.max_nickname_length:
                        raise ServiceException(f"昵称长度不能超过{self.user_config.max_nickname_length}个字符")
                    
                    if field == "signature" and len(value) > self.user_config.max_signature_length:
                        raise ServiceException(f"签名长度不能超过{self.user_config.max_signature_length}个字符")
                    
                    # 更新字段
                    user_info[field] = value
                    updated_fields.append(field)
            
            # 更新修改时间
            user_info["updated_time"] = time.time()
            
            self.logger.info("用户信息更新成功", user_id=user_id, updated_fields=updated_fields)
            
            return updated_fields
            
        except Exception as e:
            self.logger.error("更新用户信息失败", error=str(e))
            raise ServiceException(f"更新用户信息失败: {str(e)}")
    
    @cached(ttl=60)
    async def get_user_status(self, user_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        获取用户状态
        
        Args:
            user_ids: 用户ID列表
            
        Returns:
            用户状态信息
        """
        try:
            result = {}
            
            for user_id in user_ids:
                user_info = self.users.get(user_id)
                if user_info:
                    result[user_id] = {
                        "user_id": user_id,
                        "username": user_info["username"],
                        "nickname": user_info["nickname"],
                        "status": self.user_status.get(user_id, UserStatus.OFFLINE).value,
                        "last_login": user_info["last_login"],
                        "level": user_info["level"]
                    }
            
            return result
            
        except Exception as e:
            self.logger.error("获取用户状态失败", error=str(e))
            raise ServiceException(f"获取用户状态失败: {str(e)}")
    
    async def update_user_status(self, user_id: str, status: str):
        """
        更新用户状态
        
        Args:
            user_id: 用户ID
            status: 状态
        """
        try:
            if status in [s.value for s in UserStatus]:
                old_status = self.user_status.get(user_id, UserStatus.OFFLINE)
                self.user_status[user_id] = UserStatus(status)
                
                # 更新统计信息
                if old_status == UserStatus.OFFLINE and status != UserStatus.OFFLINE.value:
                    self.stats["active_users"] += 1
                elif old_status != UserStatus.OFFLINE and status == UserStatus.OFFLINE.value:
                    self.stats["active_users"] -= 1
                
                # 更新用户信息中的状态
                if user_id in self.users:
                    self.users[user_id]["status"] = status
                
                self.logger.info("用户状态更新成功", user_id=user_id, status=status)
                
        except Exception as e:
            self.logger.error("更新用户状态失败", error=str(e))
            raise ServiceException(f"更新用户状态失败: {str(e)}")
    
    async def save_user_session(self, session_info: Dict[str, Any]):
        """
        保存用户会话
        
        Args:
            session_info: 会话信息
        """
        try:
            session_id = session_info["session_token"]
            self.user_sessions[session_id] = session_info
            self.stats["active_sessions"] += 1
            
            self.logger.info("用户会话保存成功", 
                           user_id=session_info["user_id"],
                           session_id=session_id)
            
        except Exception as e:
            self.logger.error("保存用户会话失败", error=str(e))
            raise ServiceException(f"保存用户会话失败: {str(e)}")
    
    async def _hash_password(self, password: str) -> str:
        """哈希密码"""
        if BCRYPT_AVAILABLE:
            return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        else:
            # 简单哈希（仅用于测试）
            return hashlib.sha256(password.encode('utf-8')).hexdigest()
    
    async def _verify_password(self, password: str, password_hash: str) -> bool:
        """验证密码"""
        if BCRYPT_AVAILABLE:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        else:
            # 简单验证（仅用于测试）
            return hashlib.sha256(password.encode('utf-8')).hexdigest() == password_hash
    
    async def _cleanup_expired_sessions(self):
        """清理过期会话"""
        while True:
            try:
                await asyncio.sleep(300)  # 每5分钟清理一次
                
                current_time = time.time()
                expired_sessions = []
                
                for session_id, session_info in self.user_sessions.items():
                    if current_time > session_info["expires_at"]:
                        expired_sessions.append(session_id)
                
                for session_id in expired_sessions:
                    session_info = self.user_sessions.pop(session_id)
                    self.stats["active_sessions"] -= 1
                    
                    # 更新用户状态
                    user_id = session_info["user_id"]
                    await self.update_user_status(user_id, UserStatus.OFFLINE.value)
                    
                    self.logger.info("清理过期会话", 
                                   session_id=session_id,
                                   user_id=user_id)
                
            except Exception as e:
                self.logger.error("清理过期会话异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _cleanup_login_attempts(self):
        """清理登录尝试记录"""
        while True:
            try:
                await asyncio.sleep(600)  # 每10分钟清理一次
                
                current_time = time.time()
                
                for ip in list(self.login_attempts.keys()):
                    attempts = self.login_attempts[ip]
                    # 清理超过时间窗口的尝试
                    attempts = [t for t in attempts if current_time - t < self.user_config.login_attempt_window]
                    
                    if attempts:
                        self.login_attempts[ip] = attempts
                    else:
                        del self.login_attempts[ip]
                
            except Exception as e:
                self.logger.error("清理登录尝试记录异常", error=str(e))
                await asyncio.sleep(60)
    
    async def _sync_user_status(self):
        """同步用户状态"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟同步一次
                
                # 检查长时间未活动的用户
                current_time = time.time()
                inactive_users = []
                
                for session_id, session_info in self.user_sessions.items():
                    if current_time - session_info["last_active"] > 1800:  # 30分钟未活动
                        inactive_users.append(session_info["user_id"])
                
                for user_id in inactive_users:
                    await self.update_user_status(user_id, UserStatus.AWAY.value)
                
            except Exception as e:
                self.logger.error("同步用户状态异常", error=str(e))
                await asyncio.sleep(60)
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            await super().cleanup()
            
            # 清理所有会话
            self.user_sessions.clear()
            self.login_attempts.clear()
            self.user_status.clear()
            
            self.logger.info("用户服务资源清理完成")
            
        except Exception as e:
            self.logger.error("用户服务资源清理失败", error=str(e))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            **self.stats,
            "service_name": self.__class__.__name__,
            "session_count": len(self.user_sessions),
            "status_count": len(self.user_status),
            "login_attempts": len(self.login_attempts)
        }


def create_user_service(config: Optional[UserServiceConfig] = None) -> UserService:
    """
    创建用户服务实例
    
    Args:
        config: 用户服务配置
        
    Returns:
        UserService实例
    """
    try:
        service = UserService(config=config)
        logger.info("用户服务创建成功")
        return service
        
    except Exception as e:
        logger.error("创建用户服务失败", error=str(e))
        raise