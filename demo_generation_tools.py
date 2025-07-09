#!/usr/bin/env python3
"""
代码生成工具演示脚本

此脚本演示了三个代码生成工具的基本用法。
"""

import os
import sys
import subprocess
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

def run_command(cmd: str, description: str) -> bool:
    """运行命令并显示结果"""
    print(f"\n{'='*50}")
    print(f"执行: {description}")
    print(f"命令: {cmd}")
    print(f"{'='*50}")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.stdout:
            print("输出:")
            print(result.stdout)
        
        if result.stderr:
            print("错误:")
            print(result.stderr)
        
        success = result.returncode == 0
        print(f"结果: {'成功' if success else '失败'}")
        
        return success
        
    except Exception as e:
        print(f"执行失败: {str(e)}")
        return False

def main():
    """主函数"""
    print("Knight Server 代码生成工具演示")
    print("=================================")
    
    # 确保在正确的目录中运行
    os.chdir(Path(__file__).parent)
    
    # 1. 演示Excel配置表生成工具
    print("\n1. Excel配置表生成工具演示")
    cmd1 = "python -m json_data.gen_utils.generator_main --input ./excel_test --output ./json_data/demo --verbose"
    success1 = run_command(cmd1, "Excel配置表生成")
    
    if success1:
        print("\n生成的文件:")
        if os.path.exists("json_data/demo/json/hero_config.json"):
            print("- JSON配置文件: json_data/demo/json/hero_config.json")
        if os.path.exists("json_data/demo/class_data/hero_config.py"):
            print("- Python类文件: json_data/demo/class_data/hero_config.py")
    
    # 2. 演示Protocol Buffers生成工具
    print("\n2. Protocol Buffers生成工具演示")
    cmd2 = "python -m proto.gen_utils.generator_main --scan ./proto/class_data --output ./proto/demo --verbose"
    success2 = run_command(cmd2, "Protocol Buffers生成")
    
    if success2:
        print("\n生成的文件:")
        if os.path.exists("proto/demo/client_messages.proto"):
            print("- 客户端Proto文件: proto/demo/client_messages.proto")
        if os.path.exists("proto/demo/server_messages.proto"):
            print("- 服务端Proto文件: proto/demo/server_messages.proto")
    
    # 3. 演示数据仓库生成工具
    print("\n3. 数据仓库生成工具演示")
    cmd3 = "python -m models.gen_utils.generator_main --scan ./models/document --output ./models/demo --verbose"
    success3 = run_command(cmd3, "数据仓库生成")
    
    if success3:
        print("\n生成的文件:")
        if os.path.exists("models/demo/user_repository.py"):
            print("- 用户Repository: models/demo/user_repository.py")
        if os.path.exists("models/demo/order_repository.py"):
            print("- 订单Repository: models/demo/order_repository.py")
    
    # 总结
    print("\n" + "="*50)
    print("演示总结")
    print("="*50)
    print(f"Excel配置表生成: {'✓' if success1 else '✗'}")
    print(f"Protocol Buffers生成: {'✓' if success2 else '✗'}")
    print(f"数据仓库生成: {'✓' if success3 else '✗'}")
    
    if success1 and success2 and success3:
        print("\n🎉 所有工具演示成功！")
        print("\n详细文档请查看: CODE_GENERATION_TOOLS.md")
    else:
        print("\n❌ 部分工具演示失败，请检查错误信息")
    
    print("\n演示完成！")

if __name__ == "__main__":
    main()