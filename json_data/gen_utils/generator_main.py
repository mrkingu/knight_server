"""
Excel配置表生成工具主程序

提供命令行接口，用于将Excel配置表转换为JSON和Python类。
支持批量处理、客户端/服务端过滤、备份等功能。
"""

import os
import sys
import argparse
from typing import List, Optional
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.logger import logger
from .excel_parser import ExcelParser
from .json_generator import JSONGenerator
from .class_generator import ClassGenerator


class GeneratorConfig:
    """生成器配置"""
    
    def __init__(self):
        self.input_dir: str = "excel"
        self.output_json_dir: str = "json_data/json"
        self.output_class_dir: str = "json_data/class_data"
        self.usage: str = "cs"  # c/s/cs
        self.backup: bool = True
        self.validate: bool = True
        self.encoding: str = "utf-8"
        self.verbose: bool = False


class ExcelConfigGenerator:
    """
    Excel配置表生成器
    
    负责协调Excel解析、JSON生成和类生成的完整流程
    """
    
    def __init__(self, config: GeneratorConfig):
        """
        初始化生成器
        
        Args:
            config: 生成器配置
        """
        self.config = config
        self.logger = logger
        
        # 初始化各个组件
        self.excel_parser = ExcelParser(encoding=config.encoding)
        self.json_generator = JSONGenerator(output_dir=config.output_json_dir)
        self.class_generator = ClassGenerator(output_dir=config.output_class_dir)
    
    def generate_from_directory(self, input_dir: str = None) -> bool:
        """
        从目录生成配置文件
        
        Args:
            input_dir: 输入目录路径
            
        Returns:
            bool: 是否成功
        """
        input_dir = input_dir or self.config.input_dir
        
        try:
            self.logger.info(f"开始从目录生成配置文件: {input_dir}")
            
            # 检查输入目录
            if not os.path.exists(input_dir):
                self.logger.error(f"输入目录不存在: {input_dir}")
                return False
            
            # 解析Excel文件
            self.logger.info("解析Excel文件...")
            sheet_infos = self.excel_parser.parse_directory(input_dir)
            
            if not sheet_infos:
                self.logger.warning("没有找到可解析的Excel文件")
                return False
            
            # 生成JSON文件
            self.logger.info("生成JSON配置文件...")
            json_files = self.json_generator.generate_json_files(sheet_infos, self.config.usage)
            
            # 生成Python类文件
            self.logger.info("生成Python类文件...")
            class_files = self.class_generator.generate_class_files(sheet_infos, self.config.usage)
            
            # 验证生成的文件
            if self.config.validate:
                self.logger.info("验证生成的文件...")
                self._validate_generated_files(json_files, class_files)
            
            self.logger.info(f"配置文件生成完成！")
            self.logger.info(f"生成JSON文件: {len(json_files)}个")
            self.logger.info(f"生成Python类文件: {len(class_files)}个")
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成配置文件失败: {str(e)}")
            return False
    
    def generate_from_file(self, file_path: str) -> bool:
        """
        从单个文件生成配置文件
        
        Args:
            file_path: Excel文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            self.logger.info(f"开始从文件生成配置文件: {file_path}")
            
            # 检查文件是否存在
            if not os.path.exists(file_path):
                self.logger.error(f"文件不存在: {file_path}")
                return False
            
            # 解析Excel文件
            self.logger.info("解析Excel文件...")
            sheet_infos = self.excel_parser.parse_excel_file(file_path)
            
            if not sheet_infos:
                self.logger.warning("没有找到可解析的表格")
                return False
            
            # 生成JSON文件
            self.logger.info("生成JSON配置文件...")
            json_files = self.json_generator.generate_json_files(sheet_infos, self.config.usage)
            
            # 生成Python类文件
            self.logger.info("生成Python类文件...")
            class_files = self.class_generator.generate_class_files(sheet_infos, self.config.usage)
            
            # 验证生成的文件
            if self.config.validate:
                self.logger.info("验证生成的文件...")
                self._validate_generated_files(json_files, class_files)
            
            self.logger.info(f"配置文件生成完成！")
            self.logger.info(f"生成JSON文件: {len(json_files)}个")
            self.logger.info(f"生成Python类文件: {len(class_files)}个")
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成配置文件失败: {str(e)}")
            return False
    
    def generate_all_variants(self, input_dir: str = None) -> bool:
        """
        生成所有变体（客户端、服务端、全部）
        
        Args:
            input_dir: 输入目录路径
            
        Returns:
            bool: 是否成功
        """
        input_dir = input_dir or self.config.input_dir
        
        try:
            self.logger.info(f"开始生成所有变体配置文件: {input_dir}")
            
            # 解析Excel文件
            sheet_infos = self.excel_parser.parse_directory(input_dir)
            
            if not sheet_infos:
                self.logger.warning("没有找到可解析的Excel文件")
                return False
            
            # 生成所有JSON文件
            self.logger.info("生成所有JSON配置文件...")
            json_results = self.json_generator.generate_all_json(sheet_infos)
            
            # 生成所有Python类文件
            self.logger.info("生成所有Python类文件...")
            class_results = self.class_generator.generate_all_classes(sheet_infos)
            
            # 统计结果
            total_json = sum(len(files) for files in json_results.values())
            total_class = sum(len(files) for files in class_results.values())
            
            self.logger.info(f"所有变体配置文件生成完成！")
            self.logger.info(f"生成JSON文件: {total_json}个")
            self.logger.info(f"生成Python类文件: {total_class}个")
            
            return True
            
        except Exception as e:
            self.logger.error(f"生成所有变体配置文件失败: {str(e)}")
            return False
    
    def _validate_generated_files(self, json_files: List[str], class_files: List[str]) -> None:
        """
        验证生成的文件
        
        Args:
            json_files: JSON文件列表
            class_files: 类文件列表
        """
        # 验证JSON文件
        json_valid_count = 0
        for json_file in json_files:
            if self.json_generator.validate_json_file(json_file):
                json_valid_count += 1
            else:
                self.logger.warning(f"JSON文件验证失败: {json_file}")
        
        # 验证类文件
        class_valid_count = 0
        for class_file in class_files:
            if self.class_generator.validate_class_file(class_file):
                class_valid_count += 1
            else:
                self.logger.warning(f"类文件验证失败: {class_file}")
        
        self.logger.info(f"文件验证完成: JSON({json_valid_count}/{len(json_files)}), "
                        f"类({class_valid_count}/{len(class_files)})")


def parse_arguments() -> argparse.Namespace:
    """
    解析命令行参数
    
    Returns:
        argparse.Namespace: 解析后的参数
    """
    parser = argparse.ArgumentParser(
        description="Excel配置表生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  %(prog)s --input ./excel --output ./json_data
  %(prog)s --input ./excel --usage c  # 只生成客户端配置
  %(prog)s --input ./excel --usage s  # 只生成服务端配置
  %(prog)s --file hero_config.xlsx   # 处理单个文件
  %(prog)s --all                     # 生成所有变体
        """
    )
    
    # 输入选项
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--input", "-i",
        help="输入目录路径"
    )
    input_group.add_argument(
        "--file", "-f",
        help="输入文件路径"
    )
    
    # 输出选项
    parser.add_argument(
        "--output", "-o",
        default="json_data",
        help="输出目录路径 (默认: json_data)"
    )
    
    # 使用端选项
    parser.add_argument(
        "--usage", "-u",
        choices=["c", "s", "cs"],
        default="cs",
        help="使用端标记: c=客户端, s=服务端, cs=双端 (默认: cs)"
    )
    
    # 功能选项
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="生成所有变体（客户端、服务端、全部）"
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
        "--encoding",
        default="utf-8",
        help="文件编码 (默认: utf-8)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出"
    )
    
    return parser.parse_args()


def create_config_from_args(args: argparse.Namespace) -> GeneratorConfig:
    """
    从命令行参数创建配置
    
    Args:
        args: 命令行参数
        
    Returns:
        GeneratorConfig: 生成器配置
    """
    config = GeneratorConfig()
    
    # 设置输入目录
    if args.input:
        config.input_dir = args.input
    elif args.file:
        config.input_dir = os.path.dirname(args.file)
    
    # 设置输出目录
    config.output_json_dir = os.path.join(args.output, "json")
    config.output_class_dir = os.path.join(args.output, "class_data")
    
    # 设置其他配置
    config.usage = args.usage
    config.backup = not args.no_backup
    config.validate = not args.no_validate
    config.encoding = args.encoding
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
        generator = ExcelConfigGenerator(config)
        
        # 执行生成
        success = False
        
        if args.all:
            # 生成所有变体
            success = generator.generate_all_variants(config.input_dir)
        elif args.file:
            # 处理单个文件
            success = generator.generate_from_file(args.file)
        else:
            # 处理目录
            success = generator.generate_from_directory(config.input_dir)
        
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