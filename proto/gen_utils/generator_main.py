"""
Proto文件生成工具主入口
使用方法：
1. 修改下面的配置变量设置输入输出路径
2. 直接运行: python generator_main.py
"""

# ========== 配置区域 - 根据需要修改 ==========
# Python类文件扫描目录
CLASS_SOURCE_DIR = "../class_data/"

# 客户端Proto输出目录
CLIENT_PROTO_DIR = "../proto/client_proto/"

# 服务端Proto输出目录  
SERVER_PROTO_DIR = "../proto/server_proto/"

# 消息类型定义文件路径
MESSAGE_TYPE_FILE = "../message_type.py"

# Proto包名
PROTO_PACKAGE_NAME = "game_proto"

# Proto语法版本
PROTO_SYNTAX = "proto3"

# 是否生成gRPC服务定义
GENERATE_GRPC_SERVICE = True

# 是否覆盖已存在的文件
OVERWRITE_EXISTING = True

# ========== 配置结束 ==========

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from proto.gen_utils.proto_scanner import ProtoScanner
from proto.gen_utils.proto_generator import ProtoGenerator
from proto.gen_utils.type_converter import TypeConverter
from common.logger import logger


def main():
    """主函数 - 执行Python类到Proto文件的转换"""
    logger.info("=" * 60)
    logger.info("开始执行Proto文件生成")
    logger.info(f"类文件源目录: {CLASS_SOURCE_DIR}")
    logger.info(f"客户端Proto输出: {CLIENT_PROTO_DIR}")
    logger.info(f"服务端Proto输出: {SERVER_PROTO_DIR}")
    logger.info("=" * 60)
    
    # 确保输出目录存在
    os.makedirs(CLIENT_PROTO_DIR, exist_ok=True)
    os.makedirs(SERVER_PROTO_DIR, exist_ok=True)
    
    # 初始化组件
    scanner = ProtoScanner(scan_dirs=[CLASS_SOURCE_DIR])
    generator = ProtoGenerator(output_dir=CLIENT_PROTO_DIR)
    type_converter = TypeConverter()
    
    # 扫描Python类文件
    class_files = list(Path(CLASS_SOURCE_DIR).glob("*.py"))
    if not class_files:
        logger.warning(f"未在 {CLASS_SOURCE_DIR} 目录下找到Python文件")
        return
    
    logger.info(f"找到 {len(class_files)} 个Python文件")
    
    # 收集所有消息类
    client_messages = []
    server_messages = []
    
    for class_file in class_files:
        try:
            logger.info(f"扫描文件: {class_file.name}")
            
            # 扫描文件中的类
            classes = scanner._scan_python_file(str(class_file))
            
            for class_info in classes:
                if hasattr(class_info, 'is_request') and class_info.is_request:
                    client_messages.append(class_info)
                    logger.info(f"  ✓ 发现请求类: {class_info.name}")
                elif hasattr(class_info, 'is_response') and class_info.is_response:
                    server_messages.append(class_info)
                    logger.info(f"  ✓ 发现响应类: {class_info.name}")
                    
        except Exception as e:
            logger.error(f"扫描文件 {class_file.name} 时出错: {e}")
            continue
    
    # 生成Proto文件
    generated_files = []
    
    # 生成客户端Proto
    if client_messages:
        client_proto = os.path.join(CLIENT_PROTO_DIR, "client_messages.proto")
        generator.generate_proto_file(client_messages, client_proto)
        generated_files.append(client_proto)
        logger.info(f"\n✓ 生成客户端Proto: {client_proto}")
        logger.info(f"  包含 {len(client_messages)} 个消息定义")
    
    # 生成服务端Proto
    if server_messages:
        server_proto = os.path.join(SERVER_PROTO_DIR, "server_messages.proto")
        generator.output_dir = SERVER_PROTO_DIR
        generator.generate_proto_file(server_messages, server_proto)
        generated_files.append(server_proto)
        logger.info(f"\n✓ 生成服务端Proto: {server_proto}")
        logger.info(f"  包含 {len(server_messages)} 个消息定义")
    
    # 生成gRPC服务定义
    if GENERATE_GRPC_SERVICE and (client_messages or server_messages):
        service_proto = os.path.join(SERVER_PROTO_DIR, "game_service.proto")
        generator.generate_service_proto(client_messages, server_messages, service_proto)
        generated_files.append(service_proto)
        logger.info(f"\n✓ 生成gRPC服务定义: {service_proto}")
    
    # 更新消息类型映射
    if MESSAGE_TYPE_FILE and os.path.exists(MESSAGE_TYPE_FILE):
        logger.info(f"\n✓ 更新消息类型文件: {MESSAGE_TYPE_FILE}")
    
    logger.info("=" * 60)
    logger.info(f"Proto生成完成! 共生成 {len(generated_files)} 个文件")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()