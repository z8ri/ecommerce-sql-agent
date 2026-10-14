"""
Embedding 客户端管理器

负责按配置初始化 Embedding 服务客户端，并为字段、指标和用户问题的向量化
提供统一访问入口
"""

import asyncio
from typing import Optional

from huggingface_hub import AsyncInferenceClient, InferenceClient
from langchain_core.embeddings import Embeddings
from langchain_huggingface import HuggingFaceEndpointEmbeddings
from langchain_openai import OpenAIEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    """管理 Embedding 服务客户端的初始化与复用"""

    def __init__(self, config: EmbeddingConfig):
        self.client: Optional[Embeddings] = None
        self.config = config

    def _get_url(self) -> str:
        """拼接 Embedding 服务地址"""
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        """显式初始化客户端，避免模块导入时立即建立外部连接"""
        if self.config.provider == "openai":
            # 云端 OpenAI 兼容接口（如百炼 text-embedding-v4）：
            # 服务端单次最多 10 条文本，且不接受 token 数组形式的输入，所以限制批大小并关闭本地分词
            self.client = OpenAIEmbeddings(
                model=self.config.model,
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                chunk_size=10,
                check_embedding_ctx_length=False,
            )
            return

        # LangChain 的 model 参数使用模型 ID，本地 TEI 地址交给底层推理客户端。
        self.client = HuggingFaceEndpointEmbeddings(model=self.config.model)
        endpoint_url = f"{self._get_url()}/embed"
        self.client.client = InferenceClient(model=endpoint_url)
        self.client.async_client = AsyncInferenceClient(model=endpoint_url)


# 模块级单例，供整个项目复用同一套 Embedding 客户端管理器
embedding_client_manager = EmbeddingClientManager(app_config.embedding)


if __name__ == "__main__":
    embedding_client_manager.init()
    client = embedding_client_manager.client

    async def test():
        """执行一次最小化向量化调用，验证服务是否可用"""
        text = "What is deep learning?"
        query_result = await client.aembed_query(text)
        print(query_result[:3])

    asyncio.run(test())
