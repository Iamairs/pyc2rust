import os.path

from core.translator import Translator
from core.agents.project_manager import ProjectManager
from core.config import Config

from argparse import ArgumentParser


parser = ArgumentParser()
parser.add_argument("--source", type=str, help="Source project directory", default="../../Input/00-Test")
parser.add_argument("--target", type=str, help="Target project directory", default= "../../Output/rust_output")
args = parser.parse_args()

source_project_dir = args.source
target_project_dir = args.target

os.makedirs(target_project_dir, exist_ok=True)

translator = Translator(
    prompt_folders=Config.PROMPT_PATHS,
    rustc_bin=Config.RUSTC_BIN,
    cargo_bin=Config.CARGO_BIN,
    llm_config=Config.LLM_CONFIGS[0],
    rag_config=Config.RAG_CONFIG,
    db_config={
        "url": Config.DB_URL,
        "debug_sql": False
    },
    reasoner_config=Config.LLM_CONFIGS[1],
    state_file=os.path.join(target_project_dir, "states.json")
)

project_manager = ProjectManager(
    translator=translator
)
project_manager.start(
    source_project_dir,
    target_project_dir
)
