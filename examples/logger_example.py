"""
日志系统使用示例

该文件展示了如何使用knight_server的日志系统。
"""

import asyncio
import time
import sys
sys.path.insert(0, '/home/runner/work/knight_server/knight_server')

from common.logger import (
    initialize_logging, 
    logger, 
    sls_logger, 
    battle_logger,
    LoggerFactory,
    LoggerConfig,
    LogLevel
)


def example_basic_usage():
    """基础使用示例"""
    print("=== 基础使用示例 ===")
    
    # 初始化日志系统（可选，延迟初始化也可以）
    initialize_logging(service_type="gate", port=8001)
    
    # 基本日志记录
    logger.info("服务启动", service="gate", port=8001)
    logger.debug("调试信息", user_id=12345, action="login")
    logger.warning("警告信息", message_type="rate_limit")
    logger.error("错误信息", error_code=500, endpoint="/api/user")
    
    # 带上下文的日志记录
    with logger.context(request_id="req_123", user_id=456) as ctx_logger:
        ctx_logger.info("处理用户请求")
        ctx_logger.debug("查询数据库")
        ctx_logger.info("返回响应")


def example_sls_usage():
    """SLS日志使用示例"""
    print("\n=== SLS日志使用示例 ===")
    
    # 用户行为日志
    sls_logger.user_action("user_12345", "login", "用户登录成功", 
                          ip="192.168.1.100", device="mobile")
    
    # 业务事件日志
    sls_logger.business_event("payment", "支付完成", 
                             order_id="ORDER_001", amount=99.99, currency="CNY")
    
    # 性能指标日志
    sls_logger.performance_metric("api_response_time", 150.5, "ms", 
                                 endpoint="/api/login", method="POST")
    
    # 安全事件日志
    sls_logger.security_event("failed_login", "MEDIUM", "连续登录失败", 
                             user_id="user_123", attempts=3)


def example_battle_usage():
    """战斗日志使用示例"""
    print("\n=== 战斗日志使用示例 ===")
    
    battle_id = "BATTLE_001"
    
    # 开始战斗
    battle_logger.start_battle(battle_id)
    
    # 玩家相关事件
    battle_logger.player_join(battle_id, "player_001", player_level=10, class_type="warrior")
    battle_logger.player_join(battle_id, "player_002", player_level=12, class_type="mage")
    
    # 战斗回合
    battle_logger.round_start(battle_id, 1, players=["player_001", "player_002"])
    
    # 技能释放和伤害
    battle_logger.skill_cast(battle_id, "player_001", "sword_slash", "player_002", 
                           mana_cost=10, cooldown=3)
    battle_logger.damage_dealt(battle_id, "player_001", "player_002", 85, "physical",
                              critical=True, armor_reduction=15)
    
    battle_logger.skill_cast(battle_id, "player_002", "fireball", "player_001",
                           mana_cost=25, spell_level=2)
    battle_logger.damage_dealt(battle_id, "player_002", "player_001", 120, "magic",
                              element="fire")
    
    # 移动事件
    battle_logger.player_move(battle_id, "player_001", 0, 0, 5, 3, movement_type="walk")
    
    # 回合结束
    battle_logger.round_end(battle_id, 1, winner="player_002", duration=45.2)
    
    # 结束战斗并保存回放
    replay_file = battle_logger.end_battle(battle_id)
    print(f"战斗回放已保存: {replay_file}")


def example_decorators():
    """装饰器使用示例"""
    print("\n=== 装饰器使用示例 ===")
    
    @logger.catch(reraise=False)
    def risky_function():
        """可能抛出异常的函数"""
        raise ValueError("模拟异常")
        return "不会执行到这里"
    
    @logger.timer("数据处理")
    def process_data():
        """耗时操作"""
        time.sleep(0.1)  # 模拟耗时操作
        return "处理完成"
    
    # 测试异常捕获
    result = risky_function()
    print(f"异常捕获结果: {result}")
    
    # 测试性能计时
    result = process_data()
    print(f"性能计时结果: {result}")


def example_dynamic_configuration():
    """动态配置示例"""
    print("\n=== 动态配置示例 ===")
    
    # 获取工厂实例
    factory = LoggerFactory()
    
    # 查看当前配置
    info = factory.get_logger_info()
    print(f"当前工厂信息: {info}")
    
    # 动态调整日志级别
    logger.info("这条消息会显示（INFO级别）")
    
    factory.set_global_level("ERROR")
    logger.info("这条消息不会显示（级别提升到ERROR）")
    logger.error("这条错误消息会显示")
    
    # 恢复级别
    factory.set_global_level("INFO")
    logger.info("级别恢复，这条消息会显示")


def example_custom_logger():
    """自定义日志器示例"""
    print("\n=== 自定义日志器示例 ===")
    
    # 创建自定义配置
    custom_config = LoggerConfig(
        level=LogLevel.DEBUG,
        log_dir="logs/custom",
        enable_json_format=True,
        service_name="custom_service",
        service_port=9999
    )
    
    # 创建自定义日志器
    factory = LoggerFactory()
    custom_logger = factory.create_custom_logger("custom", custom_config)
    
    # 使用自定义日志器
    custom_logger.debug("自定义日志器调试信息")
    custom_logger.info("自定义日志器信息", component="auth", action="validate")


async def example_async_usage():
    """异步使用示例"""
    print("\n=== 异步使用示例 ===")
    
    async def async_task(task_id: int):
        """异步任务"""
        logger.info(f"异步任务 {task_id} 开始")
        await asyncio.sleep(0.1)  # 模拟异步操作
        logger.info(f"异步任务 {task_id} 完成")
        return f"任务{task_id}结果"
    
    # 并发执行多个异步任务
    tasks = [async_task(i) for i in range(5)]
    results = await asyncio.gather(*tasks)
    
    logger.info("所有异步任务完成", results=results)


def example_performance_monitoring():
    """性能监控示例"""
    print("\n=== 性能监控示例 ===")
    
    # 模拟一系列操作
    with logger.context(operation="data_processing") as ctx_logger:
        
        # 步骤1：数据加载
        start_time = time.time()
        time.sleep(0.05)  # 模拟加载时间
        load_time = time.time() - start_time
        ctx_logger.info("数据加载完成", step="load", duration=load_time)
        
        # 步骤2：数据处理
        start_time = time.time()
        time.sleep(0.1)  # 模拟处理时间
        process_time = time.time() - start_time
        ctx_logger.info("数据处理完成", step="process", duration=process_time)
        
        # 步骤3：结果保存
        start_time = time.time()
        time.sleep(0.03)  # 模拟保存时间
        save_time = time.time() - start_time
        ctx_logger.info("结果保存完成", step="save", duration=save_time)
        
        # 总体统计
        total_time = load_time + process_time + save_time
        sls_logger.performance_metric("total_processing_time", total_time * 1000, "ms",
                                     operation="data_processing")


def main():
    """运行所有示例"""
    print("🚀 Knight Server 日志系统使用示例\n")
    
    # 基础功能示例
    example_basic_usage()
    example_sls_usage()
    example_battle_usage()
    example_decorators()
    example_dynamic_configuration()
    example_custom_logger()
    
    # 异步示例
    asyncio.run(example_async_usage())
    
    # 性能监控示例
    example_performance_monitoring()
    
    print("\n✅ 所有示例运行完成！")
    
    # 显示统计信息
    factory = LoggerFactory()
    print(f"\n📊 最终统计信息:")
    print(f"- 工厂信息: {factory.get_logger_info()}")
    print(f"- 战斗统计: {battle_logger.get_battle_stats()}")
    print(f"- SLS统计: {sls_logger.get_sls_stats()}")


if __name__ == "__main__":
    main()