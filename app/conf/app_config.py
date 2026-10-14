"""
应用主配置

定义 conf/app_config.yaml 在程序中的结构化配置对象
项目启动后会在这里一次性完成配置文件加载和类型化转换，其他模块只需要导入 app_config
就可以按属性方式读取日志 MySQL Qdrant Embedding Elasticsearch 和 LLM 配置
"""

from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from omegaconf import OmegaConf


@dataclass
class File:
    """文件日志配置"""

    enable: bool
    level: str
    path: str
    rotation: str
    retention: str


@dataclass
class Console:
    """控制台日志配置"""

    enable: bool
    level: str


@dataclass
class LoggingConfig:
    """日志总配置"""

    file: File
    console: Console


@dataclass
class DBConfig:
    """MySQL 连接配置"""

    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class QdrantConfig:
    """Qdrant 连接与向量维度配置"""

    host: str
    port: int
    embedding_size: int


@dataclass
class EmbeddingConfig:
    """Embedding 服务配置

    provider=tei 使用本地 TEI 容器（host/port）；
    provider=openai 使用 OpenAI 兼容的云端接口（base_url/api_key），如阿里云百炼
    """

    model: str
    provider: str = "tei"
    host: str = "localhost"
    port: int = 8081
    base_url: str = ""
    api_key: str = ""


@dataclass
class ESConfig:
    """Elasticsearch 配置"""

    host: str
    port: int
    index_name: str


@dataclass
class LLMConfig:
    """大模型调用配置"""

    model_name: str
    api_key: str
    base_url: str


@dataclass
class AgentConfig:
    """问数 Agent 行为配置"""

    # 数仓数据的截止日期（yyyy-MM-dd）。“今天”“上个月”“最近 30 天”等相对时间以它为基准，
    # 而不是服务器当前时间；为空时才回退到当前日期
    as_of_date: str = ""
    # 表过滤之后，把选中指标依赖的字段补回上下文（见 pin_metric_columns 节点）
    pin_metric_columns: bool = True
    # 相对时间表达（上季度、本月、最近7天）由代码解析成明确日期范围，见 time_resolver
    resolve_time: bool = True
    # 有界的自纠错循环：校验失败、执行出错、结果复核不通过时修正 SQL 并重新校验
    self_correct: bool = True
    # SQL 安全检查（语法树白名单 + 自动补 LIMIT），命中规则的请求直接拒绝，见 sql_guard
    sql_guard: bool = True
    # 单次查询返回行数上限，以及数据库侧的执行超时（毫秒）
    max_rows: int = 1000
    query_timeout_ms: int = 15000
    max_repairs: int = 2


@dataclass
class AppConfig:
    """项目级总配置入口"""

    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    # 问数运行时使用的只读账号：只有 SELECT 权限，与建表/导入数据用的 db_dw 账号分开
    db_dw_readonly: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig
    agent: AgentConfig = field(default_factory=AgentConfig)


# 从当前文件位置回到项目根目录，再定位到 conf/app_config.yaml
project_root = Path(__file__).parents[2]
config_file = project_root / "conf" / "app_config.yaml"

# 先读取本地 .env，让 YAML 中的 ${oc.env:...} 可以解析到敏感配置
load_dotenv(project_root / ".env")

# 读取 YAML 配置内容
context = OmegaConf.load(config_file)

# 根据 AppConfig 生成结构化配置 schema
schema = OmegaConf.structured(AppConfig)

# 把配置结构和配置值合并，再转换成可以直接按属性访问的对象
app_config: AppConfig = OmegaConf.to_object(OmegaConf.merge(schema, context))

if __name__ == "__main__":
    # 简单测试：验证配置是否能正常读取
    print(app_config.es.host)
