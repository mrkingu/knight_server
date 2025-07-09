"""
common/monitor 模块

该模块提供了monitor相关的功能实现。
"""

class MockMonitor:
    """Mock监控器实现"""
    def __init__(self):
        self.metrics = {}
        
    def inc(self, metric_name, value=1, labels=None):
        """增加计数器"""
        pass
        
    def dec(self, metric_name, value=1, labels=None):
        """减少计数器"""
        pass
        
    def set(self, metric_name, value, labels=None):
        """设置度量值"""
        pass
        
    def histogram(self, metric_name, value, labels=None):
        """记录直方图"""
        pass
        
    def summary(self, metric_name, value, labels=None):
        """记录摘要统计"""
        pass

# 创建全局监控器实例
_monitor = MockMonitor()

def get_monitor():
    """获取监控器实例"""
    return _monitor
