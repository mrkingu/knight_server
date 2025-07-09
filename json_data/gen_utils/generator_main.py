"""
Excel转JSON和Python类生成工具主入口
使用方法：
1. 修改下面的配置变量设置输入输出路径
2. 直接运行: python generator_main.py
"""

# ========== 配置区域 - 根据需要修改 ==========
# Excel文件扫描目录
EXCEL_SOURCE_DIR = "../../excel_data/"

# JSON文件输出目录
JSON_OUTPUT_DIR = "../json/"

# Python类文件输出目录
CLASS_OUTPUT_DIR = "../class_data/"

# Sheet映射配置文件路径
SHEET_MAPPING_FILE = "../sheet_mapping.json"

# 文件编码
FILE_ENCODING = "utf-8"

# 是否生成Python类文件
GENERATE_PYTHON_CLASS = True

# 是否覆盖已存在的文件
OVERWRITE_EXISTING = True

# ========== 配置结束 ==========

import os
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from json_data.gen_utils.excel_parser import ExcelParser
from json_data.gen_utils.json_generator import JSONGenerator
from json_data.gen_utils.class_generator import ClassGenerator
from common.logger import logger


def main():
    """主函数 - 执行Excel到JSON和Python类的转换"""
    logger.info("=" * 60)
    logger.info("开始执行Excel配置表生成")
    logger.info(f"Excel源目录: {EXCEL_SOURCE_DIR}")
    logger.info(f"JSON输出目录: {JSON_OUTPUT_DIR}")
    logger.info(f"类文件输出目录: {CLASS_OUTPUT_DIR}")
    logger.info("=" * 60)
    
    # 确保输出目录存在
    os.makedirs(JSON_OUTPUT_DIR, exist_ok=True)
    os.makedirs(CLASS_OUTPUT_DIR, exist_ok=True)
    
    # 初始化组件
    excel_parser = ExcelParser(encoding=FILE_ENCODING)
    json_generator = JSONGenerator(output_dir=JSON_OUTPUT_DIR)
    class_generator = ClassGenerator(output_dir=CLASS_OUTPUT_DIR)
    
    # 扫描Excel文件
    excel_files = list(Path(EXCEL_SOURCE_DIR).glob("*.xlsx"))
    if not excel_files:
        logger.warning(f"未在 {EXCEL_SOURCE_DIR} 目录下找到Excel文件")
        return
    
    logger.info(f"找到 {len(excel_files)} 个Excel文件")
    
    # 处理每个Excel文件
    success_count = 0
    for excel_file in excel_files:
        try:
            logger.info(f"\n处理文件: {excel_file.name}")
            
            # 解析Excel文件
            sheet_infos = excel_parser.parse_excel_file(str(excel_file))
            
            if not sheet_infos:
                logger.warning(f"文件 {excel_file.name} 中没有找到可解析的表格")
                continue
            
            # 生成JSON文件
            json_files = json_generator.generate_json_files(sheet_infos, "cs")
            for json_file in json_files:
                logger.info(f"  ✓ 生成JSON: {json_file}")
            
            # 生成Python类文件
            if GENERATE_PYTHON_CLASS:
                class_files = class_generator.generate_class_files(sheet_infos, "cs")
                for class_file in class_files:
                    logger.info(f"  ✓ 生成类文件: {class_file}")
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"处理文件 {excel_file.name} 时出错: {e}")
            continue
    
    logger.info("=" * 60)
    logger.info(f"生成完成! 成功处理 {success_count}/{len(excel_files)} 个文件")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()