from core.utils.prompt_loader import PromptLoader


class Config:
    CLANG_LIB_FILE = "/usr/lib/llvm-14/lib/libclang.so.1"
    """clang库路径"""

    RUSTC_BIN = "rustc"
    """rustc可执行文件路径"""
    CARGO_BIN = "cargo"
    """cargo 可执行文件路径"""

    PROMPT_PATHS = ["core/prompts"]
    """Prompt模板路径"""

    LOG_LEVEL = "DEBUG"
    LOG_TYPE = "file"
    # LOG_TYPE = "console"
    LOG_DIR = "../../Output/logs"

    LLM_CONFIGS = [
        # 火山引擎
        {
            "provider": "openai",
            "model": "kimi-k2-250905",  # deepseek-v3, ep-20250213154706-429dr
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "28f98910-e044-4de2-b0cf-a52ae07c7811",
            "timeout": 30000,
            "temperature": 0.0,
            "max_tokens": 32768
        },
        # 火山引擎
        {
            "provider": "openai",
            "model": "kimi-k2-250905",  # deepseek-v3, ep-20250213154706-429dr
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "28f98910-e044-4de2-b0cf-a52ae07c7811",
            "timeout": 30000,
            "temperature": 0.6,
            "max_tokens": 32768
        },
        # 腾讯云
        {
            "provider": "openai",
            "model": "kimi-k2-250905",  # deepseek-v3, ep-20250213154706-429dr
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "28f98910-e044-4de2-b0cf-a52ae07c7811",
            "timeout": 30000,
            "temperature": 0.0,
            "max_tokens": 32768
        },
        # DeepSeek
        {
            "provider": "openai",
            "model": "kimi-k2-250905",  # deepseek-v3, ep-20250213154706-429dr
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "28f98910-e044-4de2-b0cf-a52ae07c7811",
            "timeout": 30000,
            "temperature": 0.0,
            "max_tokens": 32768
        },
        # Qwen/Qwen3-235B-A22B-Instruct-2507
        {
            "provider": "openai",
            "model": "Qwen/Qwen3-235B-A22B-Instruct-2507",  # deepseek-v3, ep-20250213154706-429dr
            "base_url": "https://api-inference.modelscope.cn/v1/",
            "api_key": "ms-4a95c7ae-e69a-4099-8b9f-989f2525dedc",
            "timeout": 30000,
            "temperature": 0.6,
            "max_tokens": 81920
        }
    ]

    """LLM配置"""
    RAG_CONFIG = {
        "base_url": "https://api.siliconflow.cn/v1/embeddings",
        "api_key": "sk-wwgxyhhzxhpspmzofquriczxsyoultrohhuzgvtylaapbsmp",
        "model": "Qwen/Qwen3-Embedding-4B",
        "knowledge_dir": "../chromadb"
    }
    """RAG配置, 目前仅支持通过 API 调用生成检索向量，不支持本地模型"""
    RAG_KNOWLEDGE_DIR = "../chromadb"

    DB_URL = "sqlite+aiosqlite:///transfactor.db"


PromptLoader.from_paths(Config.PROMPT_PATHS)
