import shutil
import unittest
import chromadb
from chromadb import ClientAPI
from chromadb.utils.embedding_functions.openai_embedding_function import OpenAIEmbeddingFunction

from core.config import Config
from core.agents.transpile_memory import l2_normalize


class TestChromaDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client: ClientAPI = chromadb.PersistentClient(
            path=Config.RAG_KNOWLEDGE_DIR
        )
        embedding_function = OpenAIEmbeddingFunction(
            model_name=Config.RAG_CONFIG["model"],
            api_key=Config.RAG_CONFIG["api_key"],
            api_base=Config.RAG_CONFIG["base_url"],
        )
        cls.collection = cls.client.get_or_create_collection(
            "test",
            embedding_function=embedding_function,
            metadata={"hnsw:space": "l2"}
        )

    @classmethod
    def tearDownClass(cls):
        # 清理测试数据
        cls.client.delete_collection(name="test")
        shutil.rmtree(Config.RAG_KNOWLEDGE_DIR)

    def test_add_and_query(self):
        # 添加文档和对应的嵌入向量
        self.collection.add(
            documents=["This is a test document.", "Another document for testing."],
            metadatas=[{"source": "test1"}, {"source": "test2"}],
            ids=["doc1", "doc2"]
        )

        # 查询相似的文档
        results = self.collection.query(
            query_texts=["This is a test document."],
            n_results=1
        )
        ids = results["ids"][0]
        documents = results["documents"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0]
        for id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            print(f"ID: {id}, Document: {doc}, Metadata: {meta}, Distance: {l2_normalize(dist)}")

        # 验证查询结果
        self.assertEqual(len(results["ids"][0]), 1)  # 检查返回的结果数量
        self.assertEqual(results["ids"][0][0], "doc1")  # 检查返回的文档 ID
        self.assertEqual(results["documents"][0][0], "This is a test document.")  # 检查返回的文档内容

