"""
性能测试：日志系统性能验证

该测试验证日志系统能否满足每秒10万+日志写入的性能要求。
"""

import time
import threading
import concurrent.futures
import tempfile
import shutil
import sys
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

from common.logger import initialize_logging, logger, LoggerFactory


def test_logging_performance():
    """测试日志性能"""
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 配置高性能日志
        config = {
            'default': {
                'level': 'INFO',
                'log_dir': temp_dir,
                'enable_async': True,
                'enable_console_logging': False,  # 关闭控制台输出提高性能
                'enable_file_logging': True,
                'enable_sampling': False,  # 关闭采样确保所有日志都被写入
            }
        }
        
        # 初始化日志系统
        initialize_logging("perf_test", 8080, config)
        
        # 测试参数
        num_threads = 10
        logs_per_thread = 10000  # 每线程1万条日志
        total_logs = num_threads * logs_per_thread
        
        print(f"开始性能测试:")
        print(f"- 线程数: {num_threads}")
        print(f"- 每线程日志数: {logs_per_thread}")
        print(f"- 总日志数: {total_logs}")
        
        def worker_thread(thread_id: int):
            """工作线程函数"""
            start_time = time.time()
            
            for i in range(logs_per_thread):
                logger.info(
                    f"高性能测试日志 {i}",
                    thread_id=thread_id,
                    log_index=i,
                    timestamp=time.time(),
                    data=f"some_data_{i}"
                )
            
            end_time = time.time()
            duration = end_time - start_time
            rate = logs_per_thread / duration
            
            return {
                'thread_id': thread_id,
                'duration': duration,
                'rate': rate,
                'logs_count': logs_per_thread
            }
        
        # 开始测试
        overall_start = time.time()
        
        # 使用线程池执行并发日志记录
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_thread, i) for i in range(num_threads)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        overall_end = time.time()
        overall_duration = overall_end - overall_start
        
        # 分析结果
        total_rate = total_logs / overall_duration
        
        print(f"\n性能测试结果:")
        print(f"- 总耗时: {overall_duration:.2f} 秒")
        print(f"- 总日志数: {total_logs}")
        print(f"- 整体吞吐量: {total_rate:.0f} 日志/秒")
        
        # 单线程统计
        thread_rates = [r['rate'] for r in results]
        avg_thread_rate = sum(thread_rates) / len(thread_rates)
        max_thread_rate = max(thread_rates)
        min_thread_rate = min(thread_rates)
        
        print(f"\n单线程统计:")
        print(f"- 平均速率: {avg_thread_rate:.0f} 日志/秒")
        print(f"- 最大速率: {max_thread_rate:.0f} 日志/秒")
        print(f"- 最小速率: {min_thread_rate:.0f} 日志/秒")
        
        # 性能评估
        target_rate = 100000  # 10万/秒目标
        performance_ratio = total_rate / target_rate
        
        print(f"\n性能评估:")
        print(f"- 目标吞吐量: {target_rate:,} 日志/秒")
        print(f"- 实际吞吐量: {total_rate:,.0f} 日志/秒")
        print(f"- 性能比率: {performance_ratio:.2f}x")
        
        if total_rate >= target_rate:
            print("✅ 性能测试通过！达到目标吞吐量")
        else:
            print("⚠️  性能测试警告：未达到目标吞吐量")
        
        # 等待异步日志完成
        print("\n等待异步日志刷新...")
        time.sleep(2)
        
        # 强制刷新日志
        logger.flush()
        
        print("✅ 性能测试完成！")
        
        return {
            'total_logs': total_logs,
            'duration': overall_duration,
            'rate': total_rate,
            'performance_ratio': performance_ratio,
            'target_achieved': total_rate >= target_rate
        }
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_memory_usage():
    """测试内存使用情况"""
    
    try:
        import psutil
        process = psutil.Process()
        
        # 初始内存
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        print(f"\n内存使用测试:")
        print(f"- 初始内存: {initial_memory:.2f} MB")
        
        # 记录大量日志
        num_logs = 50000
        print(f"- 记录 {num_logs} 条日志...")
        
        start_time = time.time()
        for i in range(num_logs):
            logger.info(f"内存测试日志 {i}", index=i, data=f"test_data_{i}" * 10)
        
        end_time = time.time()
        duration = end_time - start_time
        
        # 检查内存使用
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        print(f"- 最终内存: {final_memory:.2f} MB")
        print(f"- 内存增长: {memory_increase:.2f} MB")
        print(f"- 每条日志内存开销: {memory_increase * 1024 / num_logs:.2f} KB")
        print(f"- 记录速率: {num_logs / duration:.0f} 日志/秒")
        
        # 内存使用评估
        memory_per_log = memory_increase * 1024 / num_logs  # KB
        if memory_per_log < 1.0:  # 小于1KB per log
            print("✅ 内存使用效率良好")
        else:
            print("⚠️  内存使用可能需要优化")
            
    except ImportError:
        print("⚠️  psutil不可用，跳过内存测试")


def test_concurrent_logger_types():
    """测试并发使用不同类型的日志器"""
    
    from common.logger import sls_logger, battle_logger
    
    print(f"\n并发日志器测试:")
    
    def general_logger_worker():
        for i in range(1000):
            logger.info(f"通用日志 {i}", worker="general", index=i)
        return "general_complete"
    
    def sls_logger_worker():
        for i in range(1000):
            sls_logger.user_action(f"user_{i}", "test_action", f"SLS日志 {i}")
        return "sls_complete"
    
    def battle_logger_worker():
        battle_id = "concurrent_test"
        battle_logger.start_battle(battle_id)
        for i in range(1000):
            battle_logger.battle_event("test_event", battle_id, event_index=i)
        battle_logger.end_battle(battle_id)
        return "battle_complete"
    
    start_time = time.time()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(general_logger_worker),
            executor.submit(sls_logger_worker),
            executor.submit(battle_logger_worker)
        ]
        
        results = [future.result() for future in concurrent.futures.as_completed(futures)]
    
    end_time = time.time()
    duration = end_time - start_time
    
    print(f"- 并发执行时间: {duration:.2f} 秒")
    print(f"- 总日志数: 3000")
    print(f"- 并发速率: {3000 / duration:.0f} 日志/秒")
    print(f"- 完成状态: {results}")
    print("✅ 并发日志器测试完成！")


def main():
    """运行所有性能测试"""
    print("🚀 开始日志系统性能测试...\n")
    
    # 基础性能测试
    perf_result = test_logging_performance()
    
    # 内存使用测试
    test_memory_usage()
    
    # 并发日志器测试
    test_concurrent_logger_types()
    
    print(f"\n🎯 性能测试总结:")
    print(f"- 吞吐量: {perf_result['rate']:,.0f} 日志/秒")
    print(f"- 性能比率: {perf_result['performance_ratio']:.2f}x")
    print(f"- 目标达成: {'✅' if perf_result['target_achieved'] else '❌'}")
    
    print("\n🏁 所有性能测试完成！")


if __name__ == '__main__':
    main()