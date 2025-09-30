import os
import re
from typing import Optional, OrderedDict

import toml

from core.agents.base import AgentResponseStatus, BaseAgent, AgentResponse, AgentRequest, AgentResponseType
from core.agents.reasoner import Reasoner
from core.translator import Translator
from core.utils.patch import apply_changes, extract_code_block_change_info
from core.utils.prompt_loader import PromptLoader
from core.schema.response import BenchEngineerResponseType
from core.state.state_manager import ModuleTranslation, StateManager, ModuleTranslationStatus
from core.tools.file_tools import read_file_tool
from core.utils.rust_utils import cargo_bench, update_cargo_toml


class BenchEngineer(BaseAgent):
    """
    生成并执行基准测试代码
    """

    ROLE = "bench_engineer"
    DESCRIPTION = "Write code to test the performance of the model."

    def __init__(
            self,
            translator: Translator,
            **kwargs
    ):
        super().__init__(translator.llm_config, **kwargs)
        self.translator = translator
        self.reasoner = Reasoner(translator.reasoner_config, logger=self.logger)
        self.module_translation_id: Optional[str] = None
        # 初始文件内容
        self.raw_files = []
        # benchmark 文件路径（相对路径）
        self.bench_file = None
        # benchmark 名
        self.bench_name = None
        # Rust lib 模块名
        self.crate_name = None
        # 修复次数
        self.fixing_count = 0
        self.modified_files = []

    @property
    def module_translation(self) -> ModuleTranslation:
        module_translation = self.translator.state_manager.get_module_translation_by_id(self.module_translation_id)
        if module_translation is None:
            raise ValueError(f"module translation not found: {self.module_translation_id}")
        return module_translation

    def run(self, agent_response: AgentResponse) -> AgentResponse:
        if agent_response.status == AgentResponseStatus.DONE:
            if agent_response.type == BenchEngineerResponseType.BENCH_PREPARE_DONE:
                return self.generate_benchmark(agent_response)
            elif agent_response.type in [BenchEngineerResponseType.BENCH_COMPLETION, BenchEngineerResponseType.BENCH_FIX_DONE]:
                return self.bench_code(agent_response)
            elif agent_response.type == BenchEngineerResponseType.BENCH_FAILED:
                return self.fix_errors(agent_response)
        elif agent_response.type == AgentResponseStatus.ERROR:
            # TODO: 错误处理
            self.logger.error(f"error occurred in run: {agent_response}")
            return agent_response

    def start(self, module_translation: ModuleTranslation) -> AgentResponse:
        self.logger.info("Bench Engineer started.")
        agent_response = self.prepare_benchmark(module_translation)
        while True:
            agent_response = self.run(agent_response)
            if agent_response is None:
                return AgentResponse.error(self, BenchEngineerResponseType.BENCH_DONE, error={
                    "message": "No response from the agent."
                })
            if agent_response.type == BenchEngineerResponseType.BENCH_DONE:
                return agent_response

    def prepare_benchmark(self, module_translation: ModuleTranslation) -> AgentResponse:
        """准备基准测试

        1. 初始化基准测试文件
        2. 配置基准测试依赖
        """
        # 记录初始化状态
        self.module_translation_id = module_translation.id
        self.logger.info(f"prepare benchmark for module [{self.module_translation.name}]...")
        for file in self.module_translation.related_rust_files:
            with open(os.path.join(self.module_translation.path, file), "r", encoding="utf-8") as f:
                file_content = f.read()
            self.raw_files.append({
                "file": file,
                "content": file_content
            })
        # TODO: 目前只支持一个模块对应一个基准测试文件
        self.bench_name = self.module_translation.name + "_bench"
        self.bench_file = f"benches/{self.bench_name}.rs"
        os.makedirs(os.path.join(self.module_translation.path, "benches"), exist_ok=True)
        # 向 Cargo.toml 中写入基准测试依赖
        update_cargo_toml(
            self.module_translation.path,
            section="dependencies",
            key="criterion",
            value="0.5.1"
        )
        # 向 Cargo.toml 中写入基准测试配置
        cargo_toml_filepath = os.path.join(self.module_translation.path, "Cargo.toml")
        with open(cargo_toml_filepath, "r", encoding="utf-8") as f:
            cargo_toml = toml.load(f, _dict=OrderedDict)
        package = cargo_toml.get('package', {})
        self.crate_name = package.get('name')
        benches = cargo_toml.get("bench", [])
        if self.bench_name not in [bench.get("name") for bench in benches]:
            benches.append({
                "name": self.bench_name,
                "harness": False
            })
        cargo_toml["bench"] = benches
        with open(cargo_toml_filepath, "w", encoding="utf-8") as f:
            toml.dump(cargo_toml, f)
        return AgentResponse.done(self, BenchEngineerResponseType.BENCH_PREPARE_DONE)

    def generate_benchmark(self, pre_response: AgentResponse) -> AgentResponse:
        """生成基准测试代码"""
        self.logger.info(f"generate benchmark code for module [{self.module_translation.name}]...")
        related_rust_files = self.translator.state_manager.state.target_project.list_files(
            show_content=True,
            ignore_func=lambda filepath: filepath not in self.module_translation.related_rust_files,
            relpath=self.module_translation.path
        )
        generate_benchmark_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/generate_benchmark.prompt",
            module_name=self.module_translation.name,
            related_rust_files=related_rust_files,
            translation_tasks=self.module_translation.translation_tasks
        )
        self.logger.debug(f"generate benchmark prompt: \n{generate_benchmark_prompt}")
        generate_benchmark_messages = [{
            "role": "user",
            "content": generate_benchmark_prompt
        }]
        try_count = 0
        while try_count < 3:
            generate_benchmark_response = self.call_llm(generate_benchmark_messages, temperature=0.01)
            generate_benchmark_message_content = generate_benchmark_response.choices[0].message.content
            generate_benchmark_messages.append({"role": "assistant", "content": generate_benchmark_message_content})
            rust_code_blocks = re.findall(r"```rust\s*(.*?)\s*```", generate_benchmark_message_content, re.DOTALL)
            if len(rust_code_blocks) == 0:
                self.logger.error("No Rust code block found in the response.")
                generate_benchmark_messages.append(
                    {"role": "user", "content": "No Rust code block found in the response."})
            else:
                rust_code_block = rust_code_blocks[-1].strip()
                self.logger.debug(f"rust bench code: \n{rust_code_block}")
                bench_code = rust_code_block
                bench_filepath = os.path.join(self.module_translation.path, self.bench_file)
                if bench_code.strip() == "":
                    self.logger.info("no need to generate benchmark code.")
                    with self.translator.file_lock_manager.file_lock(bench_filepath):
                        with open(bench_filepath, "w", encoding="utf-8") as f:
                            f.write("")
                        self.translator.state_manager.state.target_project.vcs.add([bench_filepath])
                        self.translator.state_manager.state.target_project.vcs.commit(f"add benchmark code for module [{self.module_translation.name}].")
                    return AgentResponse.done(self, BenchEngineerResponseType.BENCH_DONE)
                with self.translator.file_lock_manager.file_lock(bench_filepath):
                    with open(bench_filepath, "w", encoding="utf-8") as f:
                        f.write(bench_code)
                    self.translator.state_manager.state.target_project.vcs.add([bench_filepath])
                self.logger.info(f"benchmark code generated: {bench_filepath}")
                return AgentResponse.done(self, BenchEngineerResponseType.BENCH_COMPLETION)
            try_count += 1
        return AgentResponse.error(self, BenchEngineerResponseType.BENCH_DONE, error={
            "message": "failed to generate benchmark code."
        })

    def bench_code(self, pre_response: AgentResponse) -> AgentResponse:
        """执行基准测试"""
        self.logger.info(f"start benchmarking [{self.bench_name}]...")
        bench_output = cargo_bench(self.module_translation.path, self.bench_name)
        if bench_output["success"]:
            self.logger.info(f"[{self.bench_name}] benchmark done.")
            return AgentResponse.done(self, BenchEngineerResponseType.BENCH_DONE)
        else:
            self.logger.debug("benchmark occurred errors: \n" + "\n".join([error["rendered"] for error in bench_output["errors"]]))
            return AgentResponse.done(self, BenchEngineerResponseType.BENCH_FAILED, data={
                "errors": bench_output["errors"]
            })

    def fix_with_reasoner(self, errors: list[str], explanations: list[str] = []) -> AgentResponse:
        """根据 reasoner 修复错误"""
        rust_files = self.translator.state_manager.state.target_project.list_files(
            show_content=True,
            show_line_numbers=True,
            ignore_func=lambda filepath: filepath not in self.module_translation.related_rust_files,
            relpath=self.module_translation.path
        )
        fix_with_reasoner_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/fix_with_reasoner.prompt",
            module_name=self.module_translation.name,
            rust_files=rust_files,
            bench_file=self.bench_file,
            bench_code=read_file_tool(os.path.join(self.module_translation.path, self.bench_file), show_line_number=True),
            errors=errors,
            explanations=explanations
        )
        self.logger.debug(f"fix with reasoner prompt: \n{fix_with_reasoner_prompt}")
        fix_with_reasoner_messages = [
            {"role": "user", "content": fix_with_reasoner_prompt}
        ]
        reasoner_response = self.reasoner.call_llm(messages=fix_with_reasoner_messages)
        reasoner_response_content = reasoner_response.choices[0].message.content
        fix_with_reasoner_messages.append({"role": "assistant", "content": reasoner_response_content})
        reasoner_response_reasoning_content = reasoner_response.choices[0].message.reasoning_content
        code_block_change_info = extract_code_block_change_info(reasoner_response_content)
        for file, changes in code_block_change_info.items():
            filepath = os.path.join(self.module_translation.path, file)
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    old_content = f.read()
            else:
                old_content = ""
            try:
                new_content = apply_changes(old_content, changes)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
            except Exception as e:
                self.logger.error(f"error occurred when applying changes: {e}")
                continue
        return AgentResponse.done(self, BenchEngineerResponseType.BENCH_FIX_DONE)


    def fix_errors(self, pre_response: AgentResponse) -> AgentResponse:
        if self.fixing_count >= 5:
            self.logger.error("failed to fix errors.")
            self.revert_raw_files()
            return AgentResponse.error(self, BenchEngineerResponseType.BENCH_DONE, error={
                "message": "failed to fix errors: exceed maximum fixing count 3."
            })
        compile_errors = pre_response.data.get("errors")
        if len(compile_errors) >= 10:
            compile_errors = compile_errors[:10]
        errors = [
            error["rendered"]
            for error in compile_errors
        ]
        error_document = {}
        for error in compile_errors:
            if error["code"]:
                error_code = error["code"]["code"]
                if error_code not in error_document:
                    error_document[error_code] = error["code"]["explanation"]
        explanations = [
            f"## {error_code}\n{explanation}\n"
            for error_code, explanation in error_document.items()
        ]
        self.fixing_count += 1
        return self.fix_with_reasoner(errors, explanations=explanations)

    def revert_raw_files(self):
        self.logger.info("revert raw files...")
        for file_info in self.raw_files:
            self.logger.info(f"revert file: {file_info['file']}")
            with open(os.path.join(self.module_translation.path, file_info["file"]), "w", encoding="utf-8") as f:
                f.write(file_info["content"])