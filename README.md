# Knight Server - 分布式游戏服务器框架

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen.svg)]()

Knight Server 是一个高并发、高性能、低延迟的分布式游戏服务器框架，专为现代多人在线游戏设计。基于 Python 3.12.6 构建，采用微服务架构，支持水平扩展和云原生部署。

## ✨ 特性

### 🚀 高性能架构
- **异步I/O**: 基于 asyncio 和 uvloop 的高性能异步处理
- **分布式设计**: 微服务架构，支持独立扩展
- **负载均衡**: 智能负载均衡和故障转移
- **连接池**: 高效的数据库和缓存连接池管理

### 🛡️ 安全可靠
- **身份认证**: JWT 令牌认证和授权
- **数据加密**: 端到端加密通信
- **限流保护**: 多层限流和熔断机制
- **监控告警**: 实时监控和智能告警

### 🔧 开发友好
- **代码生成**: 自动生成数据模型和API接口
- **热更新**: 支持配置和代码热更新
- **调试工具**: 完善的调试和性能分析工具
- **文档齐全**: 详细的中文文档和示例

### 📊 可观测性
- **链路追踪**: 分布式链路追踪
- **指标监控**: Prometheus 指标收集
- **日志聚合**: 结构化日志和集中管理
- **性能分析**: 实时性能监控和分析

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                         客户端层                              │
├─────────────────────────────────────────────────────────────┤
│                       API网关 (Gate)                         │
├─────────────────────────────────────────────────────────────┤
│  逻辑服务    │  聊天服务    │  战斗服务    │  其他服务...      │
│  (Logic)    │  (Chat)     │  (Fight)    │                  │
├─────────────────────────────────────────────────────────────┤
│              公共服务层 (Common Services)                     │
│  认证 │ 缓存 │ 消息队列 │ 配置管理 │ 监控 │ 日志 │ ...      │
├─────────────────────────────────────────────────────────────┤
│                      数据存储层                               │
│      Redis 集群        │        MongoDB 集群                │
└─────────────────────────────────────────────────────────────┘
```

## 📦 快速开始

### 环境要求

- Python 3.8+
- Redis 6.0+
- MongoDB 4.4+
- Docker (可选)

### 安装

```bash
# 克隆项目
git clone https://github.com/mrkingu/knight_server.git
cd knight_server

# 安装依赖
pip install -r requirements.txt

# 或使用开发模式安装
pip install -e .

# 安装完整功能
pip install -e .[full]
```

### 配置

```bash
# 复制配置文件
cp setting/development.py.example setting/development.py

# 编辑配置文件
vim setting/development.py
```

### 启动服务

```bash
# 启动所有服务
knight-server start

# 启动单个服务
knight-gate start
knight-logic start
knight-chat start
knight-fight start

# 查看服务状态
knight-server status

# 停止服务
knight-server stop
```

### Docker 部署

```bash
# 构建镜像
docker build -t knight-server .

# 使用 docker-compose 启动
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 📖 使用指南

### 基础配置

```python
# setting/development.py
from setting.config import BaseConfig

class DevelopmentConfig(BaseConfig):
    def get_default_config(self):
        return {
            'redis': {
                'host': 'localhost',
                'port': 6379,
                'password': '',
                'max_connections': 50
            },
            'mongodb': {
                'uri': 'mongodb://localhost:27017',
                'database': 'game_dev'
            },
            'services': {
                'gate': {'host': '0.0.0.0', 'port': 8000},
                'logic': {'host': '0.0.0.0', 'port': 8001}
            }
        }
```

### 创建服务

```python
# services/my_service/my_server.py
from services.base.base_server import BaseServer
from sanic import Sanic, response

class MyServer(BaseServer):
    def __init__(self):
        super().__init__("my_service")
    
    def setup_routes(self, app: Sanic):
        @app.route("/api/hello")
        async def hello(request):
            return response.json({"message": "Hello, Knight Server!"})
    
    async def on_startup(self):
        self.logger.info("我的服务启动成功")
    
    async def on_shutdown(self):
        self.logger.info("我的服务关闭")

if __name__ == "__main__":
    server = MyServer()
    server.run()
```

### 数据模型

```python
# models/document/user_document.py
from common.db.base_document import BaseDocument
from dataclasses import dataclass
from typing import Optional

@dataclass
class UserDocument(BaseDocument):
    collection_name = "users"
    
    user_id: int
    username: str
    email: str
    level: int = 1
    exp: int = 0
    coins: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

### 使用工具类

```python
# 使用ID生成器
from common.utils.id_generator import generate_id, generate_short_id

user_id = generate_id()  # 雪花算法ID
short_id = generate_short_id("USR")  # 短ID：USR8x9Ka2

# 使用加密工具
from common.utils.crypto_utils import HashUtils, PasswordUtils

password_hash, salt = PasswordUtils.hash_password("user_password")
is_valid = PasswordUtils.verify_password("user_password", password_hash, salt)

# 使用异步工具
from common.utils.async_utils import AsyncTaskManager

task_manager = AsyncTaskManager()
results = await task_manager.run_tasks_batch([
    some_async_function(),
    another_async_function()
])
```

## 🔧 开发工具

### 代码生成

```bash
# 生成协议文件
knight-gen-proto --input proto/client_proto --output proto/class_data

# 生成数据模型
knight-gen-model --input models/document --output models/repository

# 生成配置类
knight-gen-config --input json_data/json --output json_data/class_data
```

### 测试

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/unit/test_utils.py

# 生成覆盖率报告
pytest --cov=knight_server --cov-report=html
```

### 代码质量

```bash
# 代码格式化
black knight_server/

# 代码检查
flake8 knight_server/

# 类型检查
mypy knight_server/

# 安装预提交钩子
pre-commit install
```

## 📊 监控和运维

### 监控指标

- **系统指标**: CPU、内存、磁盘、网络使用率
- **应用指标**: 请求量、响应时间、错误率
- **业务指标**: 在线用户数、游戏关键指标

### 日志管理

```python
# 使用结构化日志
from loguru import logger

logger.info("用户登录", extra={
    "user_id": 12345,
    "ip": "192.168.1.1",
    "action": "login"
})
```

### 性能优化

- **数据库优化**: 索引优化、查询优化
- **缓存策略**: 多层缓存、缓存预热
- **连接池**: 合理配置连接池大小
- **负载均衡**: 智能路由和故障转移

## 🤝 贡献指南

我们欢迎所有形式的贡献！

### 贡献流程

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### 代码规范

- 遵循 PEP 8 编码规范
- 添加详细的中文注释
- 编写单元测试
- 更新相关文档

### 问题报告

如果发现问题，请在 [Issues](https://github.com/mrkingu/knight_server/issues) 页面提交，包含：

- 问题描述
- 复现步骤
- 期望行为
- 系统环境

## 📚 文档

- [快速开始](docs/quick-start.md)
- [架构设计](docs/architecture.md)
- [API文档](docs/api.md)
- [部署指南](docs/deployment.md)
- [最佳实践](docs/best-practices.md)
- [常见问题](docs/faq.md)

## 🗂️ 项目结构

```
knight_server/
├── common/                 # 公共模块
│   ├── utils/             # 工具类
│   ├── db/                # 数据库工具
│   ├── security/          # 安全模块
│   └── monitor/           # 监控模块
├── services/              # 微服务
│   ├── base/              # 基础服务类
│   ├── gate/              # 网关服务
│   ├── logic/             # 逻辑服务
│   ├── chat/              # 聊天服务
│   └── fight/             # 战斗服务
├── models/                # 数据模型
├── setting/               # 配置管理
├── proto/                 # 协议定义
├── json_data/             # JSON配置
├── tests/                 # 测试代码
├── scripts/               # 部署脚本
├── docs/                  # 文档
├── requirements.txt       # 依赖列表
├── setup.py              # 安装配置
└── README.md             # 项目说明
```

## 📄 许可证

本项目基于 MIT 许可证开源。详情请参阅 [LICENSE](LICENSE) 文件。

## 🙏 致谢

感谢以下开源项目：

- [Sanic](https://github.com/sanic-org/sanic) - 高性能异步Web框架
- [Redis](https://redis.io/) - 内存数据库
- [MongoDB](https://www.mongodb.com/) - 文档数据库
- [Celery](https://celeryproject.org/) - 分布式任务队列

## 📞 联系我们

- 项目主页: [https://github.com/mrkingu/knight_server](https://github.com/mrkingu/knight_server)
- 问题反馈: [https://github.com/mrkingu/knight_server/issues](https://github.com/mrkingu/knight_server/issues)
- 邮箱: admin@knightserver.com

---

**Knight Server** - 让游戏服务器开发更简单、更高效！🎮