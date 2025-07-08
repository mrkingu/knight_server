"""
Protocol Buffers生成工具主程序

提供命令行接口，用于扫描Python类并生成Protocol Buffers文件。
支持客户端和服务端分离生成、消息ID绑定等功能。
"""

import os
import sys
import argparse
from typing import List, Optional
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.logger import logger
from .proto_scanner import ProtoScanner
from .proto_generator import ProtoGenerator
from .type_converter import TypeConverter


class ProtoGeneratorConfig:
    """Proto生成器配置"""
    
    def __init__(self):
        self.scan_dirs: List[str] = ["proto/class_data"]
        self.output_dir: str = "proto/proto"
        self.message_type_file: Optional[str] = None
        self.generate_service: bool = True
        self.separate_files: bool = True
        self.backup: bool = True
        self.validate: bool = True
        self.verbose: bool = False


class ProtoCodeGenerator:
    """
    Protocol Buffers代码生成器
    
    负责协调类扫描和Proto文件生成的完整流程
    """
    
    def __init__(self, config: ProtoGeneratorConfig):
        """
        初始化生成器
        
        Args:
            config: 生成器配置
        """
        self.config = config
        self.logger = logger
        
        # 初始化各个组件
        self.scanner = ProtoScanner(scan_dirs=config.scan_dirs)
        self.generator = ProtoGenerator(output_dir=config.output_dir)
        self.type_converter = TypeConverter()
    
    def generate_proto_files(self) -> bool:
        """
        生成Proto文件
        
        Returns:
            bool: 是否成功
        """
        try:
            self.logger.info("开始生成Proto文件...")
            
            # 扫描Python类
            self.logger.info("扫描Python类...")
            class_infos = self.scanner.scan_directories()
            
            if not class_infos:
                self.logger.warning("没有找到可处理的类")
                return False
            
            # 加载消息类型映射
            self.logger.info("加载消息类型映射...")
            message_types = self.scanner.load_message_types(self.config.message_type_file)
            
            # 更新消息ID
            self.scanner.update_message_ids()
            
            # 验证扫描结果
            if not self.scanner.validate_scanned_classes():
                self.logger.error("类验证失败")
                return False
            
            # 生成Proto文件
            self.logger.info("生成Proto文件...")
            if self.config.separate_files:
                proto_files = self.generator.generate_proto_files(class_infos)
            else:
                proto_file = self.generator.generate_complete_proto(class_infos)
                proto_files = [proto_file]
            
            # 验证生成的文件
            if self.config.validate:
                self.logger.info("验证生成的文件...")
                self._validate_generated_files(proto_files)
            
            self.logger.info(f"Proto文件生成完成！")
            self.logger.info(f"扫描到类: {len(class_infos)}个")
            self.logger.info(f"生成Proto文件: {len(proto_files)}个")
            
            # 显示统计信息
            self._show_generation_stats(class_infos, proto_files)
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成Proto文件失败: {str(e)}")
            return False
    
    def generate_from_specific_classes(self, class_files: List[str]) -> bool:
        """
        从指定的类文件生成Proto文件
        
        Args:
            class_files: 类文件路径列表
            
        Returns:
            bool: 是否成功
        """
        try:
            self.logger.info(f"从指定文件生成Proto文件: {len(class_files)}个文件")
            
            # 扫描指定的文件
            class_infos = []
            for class_file in class_files:
                if os.path.exists(class_file):
                    file_classes = self.scanner._scan_python_file(class_file)
                    if file_classes:
                        class_infos.extend(file_classes)
                else:
                    self.logger.warning(f"文件不存在: {class_file}")
            
            if not class_infos:
                self.logger.warning("没有找到可处理的类")
                return False
            
            # 生成Proto文件
            proto_files = self.generator.generate_proto_files(class_infos)
            
            # 验证生成的文件
            if self.config.validate:
                self._validate_generated_files(proto_files)
            
            self.logger.info(f"Proto文件生成完成！")
            return True
            
        except Exception as e:
            self.logger.error(f"生成Proto文件失败: {str(e)}")
            return False
    
    def _validate_generated_files(self, proto_files: List[str]) -> None:
        """
        验证生成的文件
        
        Args:
            proto_files: Proto文件列表
        """
        valid_count = 0
        for proto_file in proto_files:
            if self.generator.validate_proto_file(proto_file):
                valid_count += 1
            else:
                self.logger.warning(f"Proto文件验证失败: {proto_file}")
        
        self.logger.info(f"文件验证完成: {valid_count}/{len(proto_files)} 个文件有效")
    
    def _show_generation_stats(self, class_infos: List, proto_files: List[str]) -> None:
        """
        显示生成统计信息
        
        Args:
            class_infos: 类信息列表
            proto_files: Proto文件列表
        """
        # 统计类信息
        request_count = len([cls for cls in class_infos if cls.is_request])
        response_count = len([cls for cls in class_infos if cls.is_response])
        
        # 统计字段数量
        total_fields = sum(len(cls.fields) for cls in class_infos)
        
        self.logger.info("=== 生成统计信息 ===")
        self.logger.info(f"请求类: {request_count}个")
        self.logger.info(f"响应类: {response_count}个")
        self.logger.info(f"总字段数: {total_fields}个")
        self.logger.info(f"Proto文件: {len(proto_files)}个")
        
        # 显示生成的文件
        for proto_file in proto_files:
            file_size = os.path.getsize(proto_file)
            self.logger.info(f"  - {proto_file} ({file_size} bytes)")


def parse_arguments() -> argparse.Namespace:
    """
    解析命令行参数
    
    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(
        description="Protocol Buffers生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  %(prog)s --scan ./proto/class_data
  %(prog)s --scan ./proto/class_data --output ./proto/proto
  %(prog)s --files request.py response.py  # 处理指定文件
  %(prog)s --no-separate                   # 生成单个Proto文件
  %(prog)s --no-service                    # 不生成服务定义
        """
    )
    
    # 扫描选项
    scan_group = parser.add_mutually_exclusive_group()
    scan_group.add_argument(
        "--scan", "-s",
        nargs="+",
        default=["proto/class_data"],
        help="扫描目录列表 (默认: proto/class_data)"
    )
    scan_group.add_argument(
        "--files", "-f",
        nargs="+",
        help="指定要处理的文件列表"
    )
    
    # 输出选项
    parser.add_argument(
        "--output", "-o",
        default="proto/proto",
        help="输出目录路径 (默认: proto/proto)"
    )
    
    # 消息类型文件
    parser.add_argument(
        "--message-type",
        help="消息类型文件路径 (默认: 自动查找message_type.py)"
    )
    
    # 功能选项
    parser.add_argument(
        "--no-separate",
        action="store_true",
        help="生成单个Proto文件而不是分离的客户端/服务端文件"
    )
    
    parser.add_argument(
        "--no-service",
        action="store_true",
        help="不生成服务定义"
    )
    
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="不备份现有文件"
    )
    
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="不验证生成的文件"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出"
    )
    
    return parser.parse_args()


def create_config_from_args(args: argparse.Namespace) -> ProtoGeneratorConfig:
    """
    从命令行参数创建配置
    
    Args:
        args: 命令行参数
        
    Returns:
        ProtoGeneratorConfig: 生成器配置
    """
    config = ProtoGeneratorConfig()
    
    # 设置扫描目录
    if args.scan:
        config.scan_dirs = args.scan
    
    # 设置输出目录
    config.output_dir = args.output
    
    # 设置消息类型文件
    config.message_type_file = args.message_type
    
    # 设置其他配置
    config.generate_service = not args.no_service
    config.separate_files = not args.no_separate
    config.backup = not args.no_backup
    config.validate = not args.no_validate
    config.verbose = args.verbose
    
    return config


def main():
    """主程序入口"""
    try:
        # 解析命令行参数
        args = parse_arguments()
        
        # 创建配置
        config = create_config_from_args(args)
        
        # 创建生成器
        generator = ProtoCodeGenerator(config)
        
        # 执行生成
        success = False
        
        if args.files:
            # 处理指定文件
            success = generator.generate_from_specific_classes(args.files)
        else:
            # 扫描目录
            success = generator.generate_proto_files()
        
        # 返回结果
        return 0 if success else 1
        
    except KeyboardInterrupt:
        logger.info("用户中断操作")
        return 1
    except Exception as e:
        logger.error(f"程序执行失败: {str(e)}")
        return 1


if __name__ == "__main__":
    exit(main())