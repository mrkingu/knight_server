"""
Filter敏感词过滤服务

该模块实现了敏感词过滤功能的业务服务层，继承自BaseService，
负责处理文本内容过滤、敏感词检测、内容审核、AI辅助过滤等功能。

主要功能：
- 敏感词检测和过滤
- 文本内容审核
- 自定义词库管理
- 多级过滤策略
- AI辅助内容过滤
- 过滤统计和分析
- 白名单管理
- 实时敏感词更新

技术特点：
- 高性能敏感词匹配算法
- 支持正则表达式过滤
- 多种过滤策略（替换、删除、标记）
- 完善的审核日志
- 支持多语言过滤
- 实时词库更新
"""

import asyncio
import re
import time
import json
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import hashlib

from services.base import BaseService, ServiceException, cached, monitored
from common.logger import logger


class FilterLevel(Enum):
    """过滤级别枚举"""
    STRICT = "strict"      # 严格过滤
    NORMAL = "normal"      # 正常过滤
    LOOSE = "loose"        # 宽松过滤


class FilterAction(Enum):
    """过滤动作枚举"""
    REPLACE = "replace"    # 替换敏感词
    DELETE = "delete"      # 删除敏感词
    BLOCK = "block"        # 阻止发送
    MARK = "mark"          # 标记但不过滤


@dataclass
class FilterRule:
    """过滤规则数据结构"""
    word: str
    level: FilterLevel
    action: FilterAction
    replacement: str = "*"
    category: str = "default"
    regex: bool = False
    enabled: bool = True
    created_time: float = 0.0


@dataclass
class FilterResult:
    """过滤结果数据结构"""
    original_text: str
    filtered_text: str
    is_filtered: bool
    matched_words: List[str]
    filter_count: int
    action_taken: FilterAction
    processing_time: float


class FilterService(BaseService):
    """
    Filter敏感词过滤服务
    
    负责处理所有内容过滤相关的业务逻辑，包括敏感词检测、
    内容审核、过滤策略管理等功能。
    """
    
    def __init__(self, enable_content_filter: bool = True,
                 filter_level: str = "normal",
                 enable_ai_filter: bool = False):
        """
        初始化Filter服务
        
        Args:
            enable_content_filter: 是否启用内容过滤
            filter_level: 过滤级别
            enable_ai_filter: 是否启用AI过滤
        """
        super().__init__()
        
        self.enable_content_filter = enable_content_filter
        self.filter_level = FilterLevel(filter_level)
        self.enable_ai_filter = enable_ai_filter
        
        # 敏感词库
        self.sensitive_words: Dict[str, FilterRule] = {}
        self.word_patterns: Dict[str, re.Pattern] = {}
        
        # 白名单
        self.whitelist: Set[str] = set()
        
        # 过滤统计
        self.filter_stats = {
            'total_checked': 0,
            'total_filtered': 0,
            'words_blocked': 0,
            'words_replaced': 0,
            'words_deleted': 0,
            'words_marked': 0
        }
        
        # 用户过滤记录
        self.user_filter_records: Dict[str, List[Dict[str, Any]]] = {}
        
        # 缓存
        self.filter_cache: Dict[str, FilterResult] = {}
        self.cache_ttl = 300  # 5分钟缓存
        
        self.logger.info("Filter服务初始化完成",
                        enable_content_filter=enable_content_filter,
                        filter_level=filter_level,
                        enable_ai_filter=enable_ai_filter)
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 初始化基础服务
            await super().initialize()
            
            # 加载默认敏感词库
            await self._load_default_sensitive_words()
            
            # 编译正则表达式
            await self._compile_regex_patterns()
            
            # 启动定时任务
            asyncio.create_task(self._cleanup_expired_cache())
            asyncio.create_task(self._update_word_patterns())
            
            self.logger.info("Filter服务初始化成功")
            
        except Exception as e:
            self.logger.error("Filter服务初始化失败", error=str(e))
            raise ServiceException(f"Filter服务初始化失败: {e}")
    
    @monitored
    async def filter_content(self, content: str, user_id: str = None) -> str:
        """
        过滤内容
        
        Args:
            content: 待过滤内容
            user_id: 用户ID
            
        Returns:
            str: 过滤后的内容
        """
        try:
            start_time = time.time()
            
            # 检查是否启用过滤
            if not self.enable_content_filter:
                return content
            
            # 检查缓存
            content_hash = hashlib.md5(content.encode()).hexdigest()
            cached_result = self.filter_cache.get(content_hash)
            
            if cached_result:
                self.logger.debug("使用缓存过滤结果", content_hash=content_hash)
                return cached_result.filtered_text
            
            # 执行过滤
            result = await self._perform_filtering(content, user_id)
            
            # 缓存结果
            self.filter_cache[content_hash] = result
            
            # 更新统计
            self.filter_stats['total_checked'] += 1
            if result.is_filtered:
                self.filter_stats['total_filtered'] += 1
                self.filter_stats[f'words_{result.action_taken.value}'] += result.filter_count
            
            # 记录用户过滤记录
            if user_id and result.is_filtered:
                await self._record_user_filter(user_id, result)
            
            processing_time = time.time() - start_time
            self.logger.info("内容过滤完成", 
                           is_filtered=result.is_filtered,
                           filter_count=result.filter_count,
                           processing_time=processing_time)
            
            return result.filtered_text
            
        except Exception as e:
            self.logger.error("内容过滤失败", 
                            content_length=len(content),
                            user_id=user_id,
                            error=str(e))
            # 过滤失败时返回原内容
            return content
    
    async def check_content_sensitive(self, content: str) -> FilterResult:
        """
        检查内容敏感词
        
        Args:
            content: 待检查内容
            
        Returns:
            FilterResult: 检查结果
        """
        try:
            return await self._perform_filtering(content, None)
            
        except Exception as e:
            self.logger.error("检查内容敏感词失败", error=str(e))
            return FilterResult(
                original_text=content,
                filtered_text=content,
                is_filtered=False,
                matched_words=[],
                filter_count=0,
                action_taken=FilterAction.REPLACE,
                processing_time=0.0
            )
    
    async def add_sensitive_word(self, word: str, level: FilterLevel = FilterLevel.NORMAL,
                               action: FilterAction = FilterAction.REPLACE,
                               replacement: str = "*", category: str = "custom",
                               regex: bool = False) -> bool:
        """
        添加敏感词
        
        Args:
            word: 敏感词
            level: 过滤级别
            action: 过滤动作
            replacement: 替换字符
            category: 分类
            regex: 是否为正则表达式
            
        Returns:
            bool: 添加是否成功
        """
        try:
            rule = FilterRule(
                word=word,
                level=level,
                action=action,
                replacement=replacement,
                category=category,
                regex=regex,
                enabled=True,
                created_time=time.time()
            )
            
            self.sensitive_words[word] = rule
            
            # 如果是正则表达式，编译模式
            if regex:
                try:
                    self.word_patterns[word] = re.compile(word, re.IGNORECASE)
                except re.error as e:
                    self.logger.error("正则表达式编译失败", 
                                    word=word,
                                    error=str(e))
                    return False
            
            # 清理缓存
            self.filter_cache.clear()
            
            self.logger.info("添加敏感词成功", 
                           word=word,
                           level=level.value,
                           action=action.value)
            
            return True
            
        except Exception as e:
            self.logger.error("添加敏感词失败", 
                            word=word,
                            error=str(e))
            return False
    
    async def remove_sensitive_word(self, word: str) -> bool:
        """
        移除敏感词
        
        Args:
            word: 敏感词
            
        Returns:
            bool: 移除是否成功
        """
        try:
            if word in self.sensitive_words:
                del self.sensitive_words[word]
                
                # 移除正则表达式模式
                if word in self.word_patterns:
                    del self.word_patterns[word]
                
                # 清理缓存
                self.filter_cache.clear()
                
                self.logger.info("移除敏感词成功", word=word)
                return True
            else:
                self.logger.warning("敏感词不存在", word=word)
                return False
                
        except Exception as e:
            self.logger.error("移除敏感词失败", 
                            word=word,
                            error=str(e))
            return False
    
    async def add_to_whitelist(self, word: str) -> bool:
        """
        添加到白名单
        
        Args:
            word: 词汇
            
        Returns:
            bool: 添加是否成功
        """
        try:
            self.whitelist.add(word)
            
            # 清理缓存
            self.filter_cache.clear()
            
            self.logger.info("添加到白名单成功", word=word)
            return True
            
        except Exception as e:
            self.logger.error("添加到白名单失败", 
                            word=word,
                            error=str(e))
            return False
    
    async def remove_from_whitelist(self, word: str) -> bool:
        """
        从白名单移除
        
        Args:
            word: 词汇
            
        Returns:
            bool: 移除是否成功
        """
        try:
            if word in self.whitelist:
                self.whitelist.remove(word)
                
                # 清理缓存
                self.filter_cache.clear()
                
                self.logger.info("从白名单移除成功", word=word)
                return True
            else:
                self.logger.warning("词汇不在白名单中", word=word)
                return False
                
        except Exception as e:
            self.logger.error("从白名单移除失败", 
                            word=word,
                            error=str(e))
            return False
    
    async def get_user_filter_records(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        获取用户过滤记录
        
        Args:
            user_id: 用户ID
            limit: 记录数量限制
            
        Returns:
            List[Dict]: 过滤记录列表
        """
        try:
            records = self.user_filter_records.get(user_id, [])
            
            # 按时间倒序排序
            records = sorted(records, key=lambda x: x['timestamp'], reverse=True)
            
            return records[:limit]
            
        except Exception as e:
            self.logger.error("获取用户过滤记录失败", 
                            user_id=user_id,
                            error=str(e))
            return []
    
    async def _perform_filtering(self, content: str, user_id: str = None) -> FilterResult:
        """执行过滤操作"""
        try:
            start_time = time.time()
            original_text = content
            filtered_text = content
            matched_words = []
            filter_count = 0
            action_taken = FilterAction.REPLACE
            
            # 检查白名单
            if content.lower() in self.whitelist:
                return FilterResult(
                    original_text=original_text,
                    filtered_text=filtered_text,
                    is_filtered=False,
                    matched_words=[],
                    filter_count=0,
                    action_taken=action_taken,
                    processing_time=time.time() - start_time
                )
            
            # 遍历敏感词进行匹配
            for word, rule in self.sensitive_words.items():
                if not rule.enabled:
                    continue
                
                # 检查过滤级别
                if not self._should_filter_by_level(rule.level):
                    continue
                
                # 执行匹配
                matches = await self._match_word(filtered_text, word, rule)
                
                if matches:
                    matched_words.extend(matches)
                    filter_count += len(matches)
                    action_taken = rule.action
                    
                    # 根据动作处理
                    if rule.action == FilterAction.REPLACE:
                        filtered_text = await self._replace_matches(filtered_text, matches, rule.replacement)
                    elif rule.action == FilterAction.DELETE:
                        filtered_text = await self._delete_matches(filtered_text, matches)
                    elif rule.action == FilterAction.BLOCK:
                        # 阻止发送，返回空内容
                        filtered_text = ""
                        break
                    elif rule.action == FilterAction.MARK:
                        # 标记但不修改内容
                        pass
            
            # AI过滤增强
            if self.enable_ai_filter and filtered_text:
                ai_result = await self._ai_filter_content(filtered_text)
                if ai_result:
                    filtered_text = ai_result
                    filter_count += 1
            
            is_filtered = filtered_text != original_text or filter_count > 0
            
            return FilterResult(
                original_text=original_text,
                filtered_text=filtered_text,
                is_filtered=is_filtered,
                matched_words=matched_words,
                filter_count=filter_count,
                action_taken=action_taken,
                processing_time=time.time() - start_time
            )
            
        except Exception as e:
            self.logger.error("执行过滤操作失败", error=str(e))
            return FilterResult(
                original_text=content,
                filtered_text=content,
                is_filtered=False,
                matched_words=[],
                filter_count=0,
                action_taken=FilterAction.REPLACE,
                processing_time=0.0
            )
    
    async def _match_word(self, text: str, word: str, rule: FilterRule) -> List[str]:
        """匹配敏感词"""
        try:
            matches = []
            
            if rule.regex:
                # 正则表达式匹配
                pattern = self.word_patterns.get(word)
                if pattern:
                    found_matches = pattern.findall(text)
                    matches.extend(found_matches)
            else:
                # 简单字符串匹配
                text_lower = text.lower()
                word_lower = word.lower()
                
                start = 0
                while True:
                    pos = text_lower.find(word_lower, start)
                    if pos == -1:
                        break
                    
                    # 检查是否为完整单词（可选）
                    if self._is_complete_word(text, pos, len(word)):
                        matches.append(text[pos:pos+len(word)])
                    
                    start = pos + 1
            
            return matches
            
        except Exception as e:
            self.logger.error("匹配敏感词失败", 
                            word=word,
                            error=str(e))
            return []
    
    async def _replace_matches(self, text: str, matches: List[str], replacement: str) -> str:
        """替换匹配的敏感词"""
        try:
            result = text
            
            for match in matches:
                # 根据匹配词的长度生成替换字符
                if replacement == "*":
                    replacement_text = "*" * len(match)
                else:
                    replacement_text = replacement
                
                result = result.replace(match, replacement_text)
            
            return result
            
        except Exception as e:
            self.logger.error("替换敏感词失败", error=str(e))
            return text
    
    async def _delete_matches(self, text: str, matches: List[str]) -> str:
        """删除匹配的敏感词"""
        try:
            result = text
            
            for match in matches:
                result = result.replace(match, "")
            
            # 清理多余的空格
            result = re.sub(r'\s+', ' ', result).strip()
            
            return result
            
        except Exception as e:
            self.logger.error("删除敏感词失败", error=str(e))
            return text
    
    def _should_filter_by_level(self, word_level: FilterLevel) -> bool:
        """检查是否应该按级别过滤"""
        try:
            level_priority = {
                FilterLevel.LOOSE: 1,
                FilterLevel.NORMAL: 2,
                FilterLevel.STRICT: 3
            }
            
            return level_priority.get(word_level, 2) <= level_priority.get(self.filter_level, 2)
            
        except Exception as e:
            self.logger.error("检查过滤级别失败", error=str(e))
            return True
    
    def _is_complete_word(self, text: str, pos: int, length: int) -> bool:
        """检查是否为完整单词"""
        try:
            # 检查前一个字符
            if pos > 0 and text[pos-1].isalnum():
                return False
            
            # 检查后一个字符
            if pos + length < len(text) and text[pos + length].isalnum():
                return False
            
            return True
            
        except Exception as e:
            self.logger.error("检查完整单词失败", error=str(e))
            return True
    
    async def _ai_filter_content(self, content: str) -> Optional[str]:
        """AI内容过滤"""
        try:
            # 这里应该调用AI服务进行内容过滤
            # 由于没有实际的AI服务，这里只是模拟
            
            # 模拟AI检测到的敏感内容
            ai_sensitive_patterns = [
                r'\b(spam|垃圾|广告)\b',
                r'\b(违法|犯罪|暴力)\b'
            ]
            
            result = content
            
            for pattern in ai_sensitive_patterns:
                result = re.sub(pattern, "[AI过滤]", result, flags=re.IGNORECASE)
            
            return result if result != content else None
            
        except Exception as e:
            self.logger.error("AI内容过滤失败", error=str(e))
            return None
    
    async def _record_user_filter(self, user_id: str, result: FilterResult):
        """记录用户过滤记录"""
        try:
            if user_id not in self.user_filter_records:
                self.user_filter_records[user_id] = []
            
            record = {
                'timestamp': time.time(),
                'original_text': result.original_text,
                'filtered_text': result.filtered_text,
                'matched_words': result.matched_words,
                'filter_count': result.filter_count,
                'action_taken': result.action_taken.value
            }
            
            self.user_filter_records[user_id].append(record)
            
            # 限制记录数量
            if len(self.user_filter_records[user_id]) > 100:
                self.user_filter_records[user_id] = self.user_filter_records[user_id][-100:]
            
        except Exception as e:
            self.logger.error("记录用户过滤记录失败", 
                            user_id=user_id,
                            error=str(e))
    
    async def _load_default_sensitive_words(self):
        """加载默认敏感词库"""
        try:
            # 默认敏感词库
            default_words = [
                # 基础敏感词
                ("傻逼", FilterLevel.NORMAL, FilterAction.REPLACE),
                ("操你妈", FilterLevel.STRICT, FilterAction.REPLACE),
                ("去死", FilterLevel.NORMAL, FilterAction.REPLACE),
                ("垃圾", FilterLevel.LOOSE, FilterAction.REPLACE),
                ("白痴", FilterLevel.NORMAL, FilterAction.REPLACE),
                
                # 广告相关
                ("加微信", FilterLevel.NORMAL, FilterAction.DELETE),
                ("代刷", FilterLevel.NORMAL, FilterAction.BLOCK),
                ("外挂", FilterLevel.STRICT, FilterAction.BLOCK),
                
                # 违法相关
                ("赌博", FilterLevel.STRICT, FilterAction.BLOCK),
                ("色情", FilterLevel.STRICT, FilterAction.BLOCK),
                ("毒品", FilterLevel.STRICT, FilterAction.BLOCK),
                
                # 正则表达式示例
                (r'\b\d{11}\b', FilterLevel.NORMAL, FilterAction.DELETE),  # 手机号
                (r'\b\d{6,}\b', FilterLevel.LOOSE, FilterAction.MARK),     # 长数字
            ]
            
            for word, level, action in default_words:
                is_regex = word.startswith(r'\b') or '\\' in word
                await self.add_sensitive_word(
                    word=word,
                    level=level,
                    action=action,
                    category="default",
                    regex=is_regex
                )
            
            self.logger.info("加载默认敏感词库完成", 
                           count=len(default_words))
            
        except Exception as e:
            self.logger.error("加载默认敏感词库失败", error=str(e))
    
    async def _compile_regex_patterns(self):
        """编译正则表达式模式"""
        try:
            for word, rule in self.sensitive_words.items():
                if rule.regex and word not in self.word_patterns:
                    try:
                        self.word_patterns[word] = re.compile(word, re.IGNORECASE)
                    except re.error as e:
                        self.logger.error("正则表达式编译失败", 
                                        word=word,
                                        error=str(e))
                        # 禁用错误的正则表达式
                        rule.enabled = False
            
            self.logger.info("编译正则表达式模式完成", 
                           count=len(self.word_patterns))
            
        except Exception as e:
            self.logger.error("编译正则表达式模式失败", error=str(e))
    
    async def _cleanup_expired_cache(self):
        """清理过期缓存"""
        while True:
            try:
                await asyncio.sleep(300)  # 5分钟清理一次
                
                current_time = time.time()
                expired_keys = []
                
                for key, result in self.filter_cache.items():
                    if current_time - result.processing_time > self.cache_ttl:
                        expired_keys.append(key)
                
                for key in expired_keys:
                    del self.filter_cache[key]
                
                if expired_keys:
                    self.logger.info("清理过期缓存", count=len(expired_keys))
                    
            except Exception as e:
                self.logger.error("清理过期缓存异常", error=str(e))
    
    async def _update_word_patterns(self):
        """更新词汇模式"""
        while True:
            try:
                await asyncio.sleep(3600)  # 1小时更新一次
                
                # 重新编译正则表达式
                await self._compile_regex_patterns()
                
                # 清理缓存
                self.filter_cache.clear()
                
                self.logger.info("更新词汇模式完成")
                
            except Exception as e:
                self.logger.error("更新词汇模式异常", error=str(e))
    
    async def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        return {
            'filter_stats': self.filter_stats.copy(),
            'word_info': {
                'total_words': len(self.sensitive_words),
                'enabled_words': sum(1 for rule in self.sensitive_words.values() if rule.enabled),
                'regex_patterns': len(self.word_patterns),
                'whitelist_size': len(self.whitelist)
            },
            'cache_info': {
                'cache_size': len(self.filter_cache),
                'user_records': len(self.user_filter_records)
            }
        }
    
    async def cleanup(self):
        """清理服务资源"""
        try:
            # 清理所有数据
            self.sensitive_words.clear()
            self.word_patterns.clear()
            self.whitelist.clear()
            self.filter_cache.clear()
            self.user_filter_records.clear()
            
            # 调用父类清理
            await super().cleanup()
            
            self.logger.info("Filter服务清理完成")
            
        except Exception as e:
            self.logger.error("Filter服务清理失败", error=str(e))