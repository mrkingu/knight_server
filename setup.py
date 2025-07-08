"""
分布式游戏服务器安装配置

该文件定义了项目的安装配置、依赖管理和脚本入口点。
"""

from setuptools import setup, find_packages
import os

# 读取版本信息
def get_version():
    """从版本文件获取版本号"""
    version_file = os.path.join(os.path.dirname(__file__), 'VERSION')
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return '1.0.0'

# 读取README文件
def get_long_description():
    """获取长描述"""
    readme_file = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_file):
        with open(readme_file, 'r', encoding='utf-8') as f:
            return f.read()
    return ''

# 读取依赖文件
def get_requirements():
    """获取依赖列表"""
    requirements_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    if os.path.exists(requirements_file):
        with open(requirements_file, 'r', encoding='utf-8') as f:
            requirements = []
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    requirements.append(line)
            return requirements
    return []

# 开发依赖
dev_requirements = [
    'pytest>=7.4.0',
    'pytest-asyncio>=0.21.0',
    'pytest-cov>=4.1.0',
    'black>=23.11.0',
    'flake8>=6.1.0',
    'mypy>=1.7.0',
    'pre-commit>=3.6.0',
    'sphinx>=7.1.0',
    'sphinx-rtd-theme>=1.3.0',
]

# 生产依赖
prod_requirements = [
    'gunicorn>=21.2.0',
    'supervisor>=4.2.5',
    'nginx-python-module>=1.0.0',
]

# 监控依赖
monitoring_requirements = [
    'prometheus-client>=0.19.0',
    'jaeger-client>=4.8.0',
    'grafana-api>=1.0.3',
    'elasticsearch>=8.11.0',
]

setup(
    # 基本信息
    name='knight-server',
    version=get_version(),
    description='高并发、高性能、低延迟的分布式游戏服务器框架',
    long_description=get_long_description(),
    long_description_content_type='text/markdown',
    
    # 作者信息
    author='Knight Server Team',
    author_email='admin@knightserver.com',
    maintainer='Knight Server Team',
    maintainer_email='admin@knightserver.com',
    
    # 项目信息
    url='https://github.com/mrkingu/knight_server',
    download_url='https://github.com/mrkingu/knight_server/archive/main.zip',
    
    # 分类信息
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Games/Entertainment',
        'Topic :: Internet :: WWW/HTTP :: HTTP Servers',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: System :: Distributed Computing',
        'Topic :: System :: Networking',
    ],
    
    # 关键词
    keywords=[
        'game server', 'distributed system', 'microservices', 
        'websocket', 'real-time', 'scalable', 'high-performance',
        'async', 'multiplayer', 'mmorpg', 'gaming'
    ],
    
    # 许可证
    license='MIT',
    
    # Python版本要求
    python_requires='>=3.8',
    
    # 包信息
    packages=find_packages(exclude=['tests*', 'docs*', 'scripts*']),
    include_package_data=True,
    package_data={
        'knight_server': [
            'setting/server_config/*',
            'json_data/json/*',
            'proto/proto/**/*',
            'docs/*',
        ],
    },
    
    # 依赖信息
    install_requires=get_requirements(),
    extras_require={
        'dev': dev_requirements,
        'prod': prod_requirements,
        'monitoring': monitoring_requirements,
        'full': dev_requirements + prod_requirements + monitoring_requirements,
    },
    
    # 脚本入口点
    entry_points={
        'console_scripts': [
            # 服务启动脚本
            'knight-server=server_launcher.launcher:main',
            'knight-gate=services.gate.gate_server:main',
            'knight-logic=services.logic.logic_server:main',
            'knight-chat=services.chat.chat_server:main',
            'knight-fight=services.fight.fight_server:main',
            
            # 工具脚本
            'knight-tools=scripts.tools:main',
            'knight-migrate=scripts.migrate:main',
            'knight-backup=scripts.backup:main',
            'knight-deploy=scripts.deploy:main',
            
            # 代码生成脚本
            'knight-gen-proto=proto.gen_utils.proto_generator:main',
            'knight-gen-model=models.gen_utils.repository_generator:main',
            'knight-gen-config=json_data.gen_utils.class_generator:main',
        ],
        'knight_server.plugins': [
            # 插件系统入口点
            'auth=common.security.jwt_auth:AuthPlugin',
            'rate_limit=common.security.rate_limiter:RateLimitPlugin',
            'circuit_breaker=common.security.circuit_breaker:CircuitBreakerPlugin',
            'metrics=common.monitor.metrics:MetricsPlugin',
            'tracing=common.monitor.tracer:TracingPlugin',
        ],
    },
    
    # 项目URLs
    project_urls={
        'Bug Reports': 'https://github.com/mrkingu/knight_server/issues',
        'Source': 'https://github.com/mrkingu/knight_server',
        'Documentation': 'https://knight-server.readthedocs.io/',
        'Changelog': 'https://github.com/mrkingu/knight_server/blob/main/CHANGELOG.md',
    },
    
    # ZIP安全
    zip_safe=False,
    
    # 测试套件
    test_suite='tests',
    tests_require=[
        'pytest>=7.4.0',
        'pytest-asyncio>=0.21.0',
        'pytest-cov>=4.1.0',
    ],
    
    # 数据文件
    data_files=[
        ('config', ['setting/development.py', 'setting/production.py']),
        ('docs', ['README.md', 'CHANGELOG.md', 'LICENSE']),
        ('scripts', ['scripts/start.sh', 'scripts/stop.sh', 'scripts/restart.sh']),
    ],
    
    # 其他选项
    options={
        'bdist_wheel': {
            'universal': False,
        },
        'build_py': {
            'compile': True,
            'optimize': 2,
        },
    },
)

# 安装后钩子
def post_install():
    """安装后执行的操作"""
    import os
    import stat
    
    # 创建必要的目录
    dirs_to_create = [
        'logs',
        'data',
        'cache',
        'uploads',
        'temp',
        'backups',
    ]
    
    for dir_name in dirs_to_create:
        os.makedirs(dir_name, exist_ok=True)
        print(f"创建目录: {dir_name}")
    
    # 设置脚本执行权限
    script_files = [
        'scripts/start.sh',
        'scripts/stop.sh',
        'scripts/restart.sh',
        'scripts/deploy.sh',
        'scripts/backup.sh',
    ]
    
    for script_file in script_files:
        if os.path.exists(script_file):
            st = os.stat(script_file)
            os.chmod(script_file, st.st_mode | stat.S_IEXEC)
            print(f"设置执行权限: {script_file}")
    
    print("\n安装完成！")
    print("使用 'knight-server --help' 查看可用命令")
    print("使用 'knight-server start' 启动服务器")

# 如果直接运行此文件，执行安装后操作
if __name__ == '__main__':
    import sys
    if 'install' in sys.argv:
        import atexit
        atexit.register(post_install)