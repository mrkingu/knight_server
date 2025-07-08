# Knight Server 代码生成工具

本项目提供三个核心代码生成工具，用于自动化生成配置类、协议文件和数据仓库类，大幅提升开发效率。

## 工具概述

### 1. json_data/gen_utils - Excel配置表生成工具
- **功能**: 将Excel配置表转换为JSON配置文件和Python类
- **特性**: 支持客户端/服务端字段过滤，生成带中文注释的Python类
- **适用场景**: 游戏配置、系统配置、数据配置等

### 2. proto/gen_utils - Protocol Buffers生成工具
- **功能**: 扫描Python类自动生成Protocol Buffers文件
- **特性**: 支持请求/响应类识别，生成客户端/服务端分离的proto文件
- **适用场景**: 网络通信协议、RPC服务定义等

### 3. models/gen_utils - 数据仓库生成工具
- **功能**: 为文档模型自动生成Repository类
- **特性**: 支持自定义方法保留，生成标准的CRUD操作
- **适用场景**: 数据库访问层、业务逻辑层等

## 快速开始

### 安装依赖
```bash
pip install -r requirements.txt
```

### 使用示例

#### 1. Excel配置表生成
```bash
# 基础用法
python -m json_data.gen_utils.generator_main --input ./excel --output ./json_data

# 只生成客户端配置
python -m json_data.gen_utils.generator_main --input ./excel --usage c

# 生成所有变体
python -m json_data.gen_utils.generator_main --input ./excel --all
```

#### 2. Protocol Buffers生成
```bash
# 基础用法
python -m proto.gen_utils.generator_main --scan ./proto/class_data

# 生成单个proto文件
python -m proto.gen_utils.generator_main --scan ./proto/class_data --no-separate

# 处理指定文件
python -m proto.gen_utils.generator_main --files request.py response.py
```

#### 3. 数据仓库生成
```bash
# 基础用法
python -m models.gen_utils.generator_main --scan ./models/document

# 处理指定文件
python -m models.gen_utils.generator_main --files user_document.py order_document.py

# 不保留自定义方法
python -m models.gen_utils.generator_main --scan ./models/document --no-preserve-custom
```

## 详细说明

### Excel配置表生成工具

#### Excel文件格式
```
第1行: 中文注释    | 英雄ID | 英雄名称 | 职业 | 等级 | 血量 | 攻击力 | 防御力 | 技能列表 | 服务端数据
第2行: 字段名      | hero_id | name | profession | level | hp | attack | defense | skills | server_data
第3行: 数据类型    | int | str | str | int | int | int | int | list | dict
第4行: 使用端标记  | cs | cs | cs | cs | cs | cs | cs | cs | s
第5行起: 实际数据  | 1001 | 剑士 | 战士 | 1 | 100 | 20 | 15 | [1,2,3] | {"drop_rate": 0.1}
```

#### 生成的文件
- **JSON配置文件**: `json_data/json/hero_config.json`
- **Python类文件**: `json_data/class_data/hero_config.py`

#### 配置映射
通过 `json_data/sheet_mapping.json` 配置文件定义Excel表格的映射关系和验证规则。

### Protocol Buffers生成工具

#### 支持的类
- **BaseRequest**: 请求消息基类
- **BaseResponse**: 响应消息基类

#### 示例Python类
```python
@dataclass
class LoginRequest(BaseRequest):
    username: str
    password: str
    platform: Optional[str] = None
```

#### 生成的Proto文件
```protobuf
message LoginRequest {
    string username = 1;
    string password = 2;
    string platform = 3;
}
```

#### 类型转换
| Python类型 | Proto类型 |
|-----------|-----------|
| int       | int32     |
| float     | float     |
| str       | string    |
| bool      | bool      |
| List[T]   | repeated T |
| Dict      | string    |

### 数据仓库生成工具

#### 支持的文档模型
继承自 `BaseDocument` 的数据模型类。

#### 示例文档模型
```python
@dataclass
class UserDocument(BaseDocument):
    username: str
    email: str
    password_hash: str
    profile: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def get_collection_name(cls) -> str:
        return "users"
```

#### 生成的Repository类
```python
class UserRepository(BaseRepository[UserDocument]):
    def __init__(self):
        super().__init__(
            document_class=UserDocument,
            collection_name="users"
        )
    
    async def find_by_username(self, username: str) -> Optional[UserDocument]:
        return await self.find_one({"username": username})
```

## 配置文件

每个工具都支持YAML配置文件：
- `json_data/gen_utils/config.yaml`
- `proto/gen_utils/config.yaml`
- `models/gen_utils/config.yaml`

## 特性

### 通用特性
- ✅ 命令行接口支持
- ✅ 详细的中文注释
- ✅ 类型提示支持
- ✅ 错误处理和日志记录
- ✅ 文件备份机制
- ✅ 生成结果验证
- ✅ 配置文件支持

### Excel配置表工具特性
- ✅ 客户端/服务端字段过滤
- ✅ 多种数据类型支持
- ✅ 自动类型转换
- ✅ 数据验证
- ✅ 批量处理

### Proto生成工具特性
- ✅ 自动类型转换
- ✅ 消息ID绑定
- ✅ 服务定义生成
- ✅ 多语言支持选项
- ✅ 客户端/服务端分离

### Repository生成工具特性
- ✅ 自动CRUD方法生成
- ✅ 字段查询方法生成
- ✅ 批量操作支持
- ✅ 分页查询支持
- ✅ 自定义方法保留

## 目录结构

```
knight_server/
├── json_data/
│   ├── gen_utils/              # Excel配置表生成工具
│   │   ├── __init__.py
│   │   ├── excel_parser.py     # Excel解析器
│   │   ├── json_generator.py   # JSON生成器
│   │   ├── class_generator.py  # Python类生成器
│   │   ├── generator_main.py   # 主程序
│   │   └── config.yaml         # 配置文件
│   ├── json/                   # 生成的JSON文件
│   ├── class_data/             # 生成的Python类
│   └── sheet_mapping.json      # 映射配置
├── proto/
│   ├── gen_utils/              # Proto生成工具
│   │   ├── __init__.py
│   │   ├── proto_scanner.py    # 类扫描器
│   │   ├── proto_generator.py  # Proto生成器
│   │   ├── type_converter.py   # 类型转换器
│   │   ├── generator_main.py   # 主程序
│   │   └── config.yaml         # 配置文件
│   ├── class_data/             # 源Python类
│   └── proto/                  # 生成的Proto文件
└── models/
    ├── gen_utils/              # Repository生成工具
    │   ├── __init__.py
    │   ├── document_scanner.py # 文档扫描器
    │   ├── repository_generator.py # Repository生成器
    │   ├── generator_main.py   # 主程序
    │   └── config.yaml         # 配置文件
    ├── document/               # 文档模型
    └── repository/             # 生成的Repository类
```

## 开发指南

### 扩展Excel解析器
```python
# 添加新的数据类型支持
def _convert_custom_type(self, value: str) -> Any:
    # 自定义类型转换逻辑
    pass
```

### 扩展Proto类型转换
```python
# 添加新的类型映射
self.type_mapping['custom_type'] = 'string'
```

### 扩展Repository生成
```python
# 添加新的方法生成
def _generate_custom_methods(self, doc_info: DocumentClassInfo) -> List[str]:
    # 自定义方法生成逻辑
    pass
```

## 常见问题

### Q: Excel文件解析失败怎么办？
A: 检查Excel文件格式是否符合要求，确保前4行为元数据，第5行开始为实际数据。

### Q: Proto文件生成后编译失败？
A: 检查生成的字段名是否与Proto保留字冲突，工具会自动处理大部分情况。

### Q: Repository类丢失自定义方法？
A: 使用 `--preserve-custom` 选项保留自定义方法，或在代码中添加自定义方法标记。

## 许可证

本项目采用 MIT 许可证，详见 LICENSE 文件。

## 贡献指南

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/new-feature`)
3. 提交更改 (`git commit -am 'Add new feature'`)
4. 推送到分支 (`git push origin feature/new-feature`)
5. 创建 Pull Request

## 联系方式

如有问题或建议，请通过以下方式联系：
- 提交 Issue: https://github.com/mrkingu/knight_server/issues
- 邮件: support@knight-server.com

---

**注意**: 这些工具是为 Knight Server 项目量身定制的，但设计时考虑了通用性，可以根据需要进行调整和扩展。