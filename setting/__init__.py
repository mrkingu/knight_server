"""
配置模块
提供全局配置访问接口
"""
from .config_loader import ConfigLoader

# 创建全局配置实例
config = ConfigLoader()

# 导出常用配置
__all__ = ['config']
