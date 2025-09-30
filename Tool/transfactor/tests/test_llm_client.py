import unittest

# 将../transfactor添加到系统路径中
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pydantic import BaseModel, Field

from core.llms.openai_client import OpenAIClient

class TestLLMClient(unittest.TestCase):

    def setUp(self):
        from core.config import Config
        self.llm_client = OpenAIClient(
            llm_config=Config.LLM_CONFIGS[0]
        )

    def test_oai_client(self):
        prompt = """this is a test message. You should say "test"."""
        response = self.llm_client.create(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt},
            ]
        )
        self.assertEqual(response.choices[0].message.content, "test")

    def test_oai_client_with_json_format(self):
        class TempResponse(BaseModel):
            content: str = Field(description="content of the message")

        response = self.llm_client.create(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": """This is a test. You should say "test"."""},
            ],
            json_format=TempResponse
        )
        self.assertEqual(response.format_object, TempResponse(content="test"))


if __name__ == "__main__":
    unittest.main()
