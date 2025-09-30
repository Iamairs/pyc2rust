import os
import re
import traceback
from typing import Optional

from pydantic import BaseModel, Field

from core.agents.base import AgentResponseStatus
from core.agents.reasoner import Reasoner
from core.schema.translation import ModuleTranslation
from core.translator import Translator
from core.utils.patch import apply_changes, extract_code_block_change_info
from core.utils.prompt_loader import PromptLoader
from core.tools.file_tools import read_file_tool
from core.agents.base import AgentResponse, BaseAgent
from core.schema.response import TestEngineerResponseType
from core.utils.rust_utils import cargo_test

class FindTestResponse(BaseModel):
    test_files: list[str] = Field(description="测试文件路径")

class TestEngineer(BaseAgent):
    ROLE = "test_engineer"
    DESCRIPTION = "A powerful and efficient AI assistant that completes tasks accurately and resourcefully, providing translating and generating Rust Test Cases."

    def __init__(
            self,
            translator: Translator,
            **kwargs
    ):
        super().__init__(translator.llm_config, **kwargs)
        self.translator = translator
        self.module_translation_id: Optional[str] = None
        # 源测试文件路径
        self.related_source_files: list[str] = []
        # 测试前所有的相关 Rust 文件
        self.raw_files: list[dict] = []
        # 测试名称
        self.test_name: Optional[str] = None
        self.test_file: Optional[str] = None
        # 修改历史
        self.change_history: list[dict] = []
        self.reasoner = Reasoner(translator.reasoner_config, logger=self.logger)

        # self.c_module_file = None
        # self.rust_test_file = None
        # self.rust_module_file = None
        # self.rust_project_path = None
        # self.module_name = None
        # self.related_rust_files = None
        # self.crate_name = None
        # self.rust_test_code_path = None
        # self.rust_code_path = None
        # self.c_test_code_path = None
        # self.c_project_path = None
        # self.pre_test_case_name = None
        # self.modified_files = []
        self.syntax_max_turn = 20
        self.syntax_current_turn = 0
        self.logic_max_turn = 10
        self.logic_current_turn = 0
        # TODO TEMP
        # self.fix_logic_with_feedback_messages = []
        # self.fix_timeout_messages = []
        # self.rust_module_names = None
        # self.rust_test_report = None
        # self.module_translations = None
        # self.history_index = 0


    @property
    def module_translation(self) -> ModuleTranslation:
        module_translation = self.translator.state_manager.get_module_translation_by_id(self.module_translation_id)
        if module_translation is None:
            raise ValueError(f"module translation not found: {self.module_translation_id}")
        return module_translation

    def run(self, agent_response: AgentResponse) -> AgentResponse:
        if agent_response.status == AgentResponseStatus.DONE:
            if agent_response.type == TestEngineerResponseType.TEST_PREPARE_DONE:
                # 完成测试准备工作，考试转译测试代码
                return self.translate_test_code(agent_response)
            elif agent_response.type in [TestEngineerResponseType.TEST_CODE_TRANSLATION_COMPLETION,
                                       TestEngineerResponseType.TEST_SYNTAX_FIX_COMPLETION,
                                       TestEngineerResponseType.TEST_LOGIC_FIX_COMPLETION]:
                # 在完成测试代码转译、测试语法修复、测试逻辑修复后均需要运行测试
                return self.run_test(agent_response)
            elif agent_response.type == TestEngineerResponseType.TEST_RUN_FAILURE:
                # 测试运行失败需修复语法错误
                return self.fix_syntax_errors(agent_response)
            elif agent_response.type == TestEngineerResponseType.TEST_RUN_DONE:
                # 测试运行成功，尝试修复不通过的测试用例
                return self.fix_logic_errors(agent_response)
        elif agent_response.type == AgentResponseStatus.ERROR:
            # TODO: 错误处理
            self.logger.error(f"error occurred in run: {agent_response}")
            return agent_response

    def start(self, module_translation: ModuleTranslation) -> AgentResponse:
        self.logger.info(f"start Test Engineer [{self.name}] for test task")
        agent_response = self.prepare_test(module_translation)
        last_response = agent_response
        # TODO 删除该语句，当前只是为了跳过生成测试用例的过程
        # agent_response = self.run_test(agent_response)
        while True:
            agent_response = self.run(agent_response)
            if agent_response is None:
                self.logger.error(f"agent response is None, break. last_response: {last_response}")
                return AgentResponse.error(self, TestEngineerResponseType.TEST_PASSED, error={
                    "message": f"agent response is None, break. last_response: {last_response}"
                })
            if agent_response.type == TestEngineerResponseType.TEST_PASSED:
                return agent_response
            if agent_response.type == TestEngineerResponseType.TEST_SYNTAX_FIX_COMPLETION:
                self.syntax_current_turn += 1
            if agent_response.type == TestEngineerResponseType.TEST_LOGIC_FIX_COMPLETION:
                self.syntax_current_turn = 0
                self.logic_current_turn += 1
            if (agent_response.type == TestEngineerResponseType.TEST_RUN_FAILURE
                    and self.syntax_current_turn == self.syntax_max_turn):
                self.logger.info(
                    f"Reached the maximum number of syntax error correction attempts: {self.syntax_max_turn}")
                # 某一次测试运行失败且达到最大语法修错次数，即无法完成语法错误修复
                return AgentResponse.done(self, TestEngineerResponseType.TEST_RUN_FAILURE)
            if (agent_response.type == TestEngineerResponseType.TEST_RUN_DONE
                    and self.logic_current_turn == self.logic_max_turn):
                self.logger.info(
                    f"Reached the maximum number of logical error correction attempts：{self.logic_max_turn}")
                # 某一次测试运行成功且没有通过所有测试用例，即无法完成逻辑错误修复
                return AgentResponse.error(self, TestEngineerResponseType.TEST_FAILED, error={
                    "message": "Reached the maximum number of logical error correction attempts."
                })
            last_response = agent_response

    def prepare_test(self, module_translation: ModuleTranslation) -> AgentResponse:
        self.logger.info(f"prepare test translation for module [{module_translation.name}]")
        self.module_translation_id = module_translation.id
        self.related_source_files = self.find_source_tests()
        # 保留原始文件
        self.raw_files = []
        for filepath in self.module_translation.related_rust_files:
            with open(os.path.join(self.module_translation.path, filepath), "r", encoding="utf-8") as f:
                content = f.read()
            self.raw_files.append({
                "filepath": filepath,
                "content": content
            })
        return AgentResponse.done(self, TestEngineerResponseType.TEST_PREPARE_DONE)

    def find_source_tests(self) -> list[str]:
        """根据模块代码寻找对应的测试文件"""
        project_files = self.translator.state_manager.state.source_project.list_files(
            show_summary=True,
            relpath=self.translator.state_manager.state.source_project.test_path
        )
        find_tests_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/find_tests.prompt",
            module_name=self.module_translation.name,
            module_description=self.module_translation.description,
            project_files=project_files,
            show_file_summary=True
        )
        self.logger.debug(f"find tests prompt: {find_tests_prompt}")
        find_test_messages = [
            {"role": "user", "content": find_tests_prompt}
        ]
        max_try_count = 3
        while max_try_count > 0:
            find_test_response = self.call_llm(messages=find_test_messages, json_format=FindTestResponse)
            find_test_response_content = find_test_response.choices[0].message.content
            find_test_messages.append({"role": "assistant", "content": find_test_response_content})
            find_test_response_obj = find_test_response.format_object
            if find_test_response_obj:
                test_files = find_test_response_obj.test_files
                self.logger.info(f"found source test files: {test_files}")
                return test_files
            max_try_count -= 1
            find_test_messages.append({"role": "user", "content": "解析 JSON 失败，请严格遵守 JSON 格式。"})
        self.logger.error("failed to find test file")
        raise ValueError("failed to find test file")

    def translate_test_code(self, pre_response: AgentResponse) -> AgentResponse:
        source_test_files = self.translator.state_manager.state.source_project.list_files(
            show_content=True,
            ignore_func=lambda filepath: filepath not in self.related_source_files
        )
        related_rust_files = self.translator.state_manager.state.target_project.list_files(
            show_content=True,
            ignore_func=lambda filepath: filepath not in self.module_translation.related_rust_files,
            relpath=self.module_translation.path
        )
        translate_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/translate_test.prompt",
            source_test_files=source_test_files,
            rust_files=related_rust_files,
            module_name=self.module_translation.name,
            translation_tasks=self.module_translation.translation_tasks
        )
        translate_test_messages = [{
            "role": "user",
            "content": translate_prompt
        }]
        self.logger.debug(f"translate test code prompt: {translate_prompt}")
        try_count = 0
        while try_count < 3:
            # response = self.reasoner.call_llm(messages=translate_test_messages)
            response = self.call_llm(messages=translate_test_messages)
            translate_test_message_content = response.choices[0].message.content
            translate_test_messages.append({
                "role": "assistant",
                "content": translate_test_message_content
            })
            self.logger.debug(f"translate test code response content: {translate_test_message_content}")
            code_blocks = re.findall(r'```rust(.*?)```', translate_test_message_content, re.DOTALL)
            if len(code_blocks) == 0:
                self.logger.error("no Rust Code block found in the response.")
                translate_test_messages.append({"role": "user", "content": "no Rust Code found in the response."})
            else:
                rust_code_block = code_blocks[-1].strip()
                self.logger.debug(f"rust test code: {rust_code_block}")
                if "// filepath" in rust_code_block:
                    rust_test_file = rust_code_block.split("\n")[0].split(":")[1].strip()
                    rust_test_code = "\n".join(rust_code_block.split("\n")[1:])
                    rust_test_filepath = os.path.join(self.module_translation.path,
                                                           rust_test_file)

                else:
                    rust_test_file = f"tests/{self.module_translation.name}_tests.rs"
                    rust_test_code = rust_code_block
                rust_test_filepath = os.path.join(self.module_translation.path, rust_test_file)
                self.test_name = os.path.splitext(os.path.basename(rust_test_filepath))[0]
                self.test_file = rust_test_file
                os.makedirs(os.path.dirname(rust_test_filepath), exist_ok=True)
                with open(rust_test_filepath, "w", encoding="utf-8") as f:
                    f.write(rust_test_code)
                return AgentResponse.done(self, TestEngineerResponseType.TEST_CODE_TRANSLATION_COMPLETION)
        return AgentResponse.error(self, TestEngineerResponseType.TEST_CODE_TRANSLATION_COMPLETION,
                                   error={"message": "Failed to parse Rust Code."})

    def fix_syntax_errors_with_reasoner(self, errors: list[dict], explanations: list[str] = []) -> AgentResponse:
        """利用 reasoner 修复错误"""
        self.logger.debug(f"syntax errors: {errors}")
        related_rust_files = self.translator.state_manager.state.target_project.list_files(
            show_content=True,
            show_line_numbers=True,
            ignore_func=lambda filepath: filepath not in self.module_translation.related_rust_files,
            relpath=self.module_translation.path
        )

        fix_with_reasoner_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/fix_syntax_with_reasoner.prompt",
            module_name=self.module_translation.name,
            rust_files=related_rust_files,
            test_filepath=self.test_file,
            test_file=self.test_file,
            test_code=read_file_tool(os.path.join(self.module_translation.path, self.test_file), show_line_number=True),
            errors=errors,
            explanations=explanations,
            show_file_content=True
        )
        self.logger.debug(f"fix with reasoner prompt: {fix_with_reasoner_prompt}")
        fix_with_reasoner_messages = [
            {"role": "user", "content": fix_with_reasoner_prompt}
        ]
        reasoner_response = self.reasoner.call_llm(messages=fix_with_reasoner_messages)
        reasoner_response_content = reasoner_response.choices[0].message.content
        fix_with_reasoner_messages.append({"role": "assistant", "content": reasoner_response_content})
        reasoner_response_reasoning_content = reasoner_response.choices[0].message.reasoning_content
        code_block_change_info = extract_code_block_change_info(reasoner_response_content)
        self.logger.debug(f"fix with reasoner response: {reasoner_response_content}")
        for file, changes in code_block_change_info.items():
            filepath = os.path.join(self.module_translation.path, file)
            with open(filepath, "r", encoding="utf-8") as f:
                old_content = f.read()
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
        return AgentResponse.done(self, TestEngineerResponseType.TEST_SYNTAX_FIX_COMPLETION)

    def fix_syntax_errors(self, pre_response: AgentResponse) -> AgentResponse:
        """
        针对测试代码产生的语法错误进行修复
        """
        self.logger.info("fixing syntax errors")
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
        return self.fix_syntax_errors_with_reasoner(errors, explanations=explanations)

    def run_test(self, pre_response: AgentResponse) -> AgentResponse:
        """
        执行测试用例
        """
        try:
            test_output = cargo_test(self.module_translation.path, self.test_name)
            if test_output["success"]:
                # 测试编译通过
                self.logger.info("compile test code passed")
                # TODO 在全部测试通过或者达到最大逻辑错误修复次数时才写入测试报告
                failed_tests = test_output.get("errors")
                if len(failed_tests) == 0:
                    # 测试用例全部通过，无需进行逻辑错误修复
                    self.logger.info("all test cases passed.")
                    self.generate_test_report(test_output["output"])
                    return AgentResponse.done(self, TestEngineerResponseType.TEST_PASSED)
                self.add_history(logic_errors=failed_tests)
                if self.logic_current_turn == self.logic_max_turn:
                    self.generate_test_report(test_output["output"])
                    self.save_best()
                return AgentResponse.done(self, TestEngineerResponseType.TEST_RUN_DONE, data={
                    "test_output": test_output
                })
            else:
                # 测试编译未通过
                # 回到上一次 commit 的版本（撤销写入的代码）
                self.logger.info("compiling test failed.")
                # self.add_history(syntax_errors=test_output["errors"])
                if self.syntax_current_turn == self.syntax_max_turn:
                    # 未能修复编译错误，也写入测试报告
                    rendered_info = []
                    for error in test_output["errors"]:
                        rendered_info.append(error["rendered"])
                    # self.generate_test_report("\n".join(rendered_info))
                    self.logger.error("failed to fix syntax errors.")
                    # 多次编译失败后，恢复到最初的版本
                    self.save_best()
                    # self.revert_raw_files()
                errors = test_output["errors"]
                return AgentResponse.done(self, TestEngineerResponseType.TEST_RUN_FAILURE, data={
                    "errors": errors
                })
        except Exception as e:
            # TODO: 错误处理
            error_details = traceback.format_exc()
            self.logger.error(f"error occurred when running code check: {e}\ndetails: \n{error_details}")

    def generate_test_report(self, test_console_output):
        """
        生成测试报告
        """
        self.logger.debug(f"test console output: {test_console_output}")

        related_rust_files = self.translator.state_manager.state.target_project.list_files(
            show_content=True,
            ignore_func=lambda filepath: filepath not in self.module_translation.related_rust_files,
            relpath=self.module_translation.path
        )

        with open(os.path.join(self.module_translation.path, self.test_file), "r", encoding="utf-8") as f:
            test_code = f.read()

        report_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/report.prompt",
            module_name=self.module_translation.name,
            is_file_content=True,
            related_rust_files=related_rust_files,
            test_file=self.test_file,
            test_code=test_code,
            console_output=test_console_output
        )
        response = self.call_llm(messages=[{"role": "user", "content": report_prompt}])
        report_content = response.choices[0].message.content
        test_report_filepath = os.path.join(self.module_translation.path, f"{self.test_name}_test_report.md")
        os.makedirs(os.path.dirname(test_report_filepath), exist_ok=True)
        with open(test_report_filepath, "w", encoding="utf-8") as f:
            f.write(report_content)
        self.logger.info("test report generated.")

    def fix_logic_with_reasoner(self, errors: list[dict]) -> AgentResponse:
        """利用reasoner修复逻辑错误
        """
        related_rust_files = self.translator.state_manager.state.target_project.list_files(
            show_content=True,
            show_line_numbers=True,
            ignore_func=lambda filepath: filepath not in self.module_translation.related_rust_files,
            relpath=self.module_translation.path
        )
        fix_with_reasoner_prompt = PromptLoader.get_prompt(
            f"{self.ROLE}/fix_logic_with_reasoner.prompt",
            module_name=self.module_translation.name,
            rust_files=related_rust_files,
            test_file=self.test_file,
            test_code=read_file_tool(os.path.join(self.module_translation.path, self.test_file), show_line_number=True),
            errors=errors
        )
        self.logger.debug(f"fix with reasoner prompt: {fix_with_reasoner_prompt}")
        fix_with_reasoner_messages = [
            {"role": "user", "content": fix_with_reasoner_prompt}
        ]
        reasoner_response = self.reasoner.call_llm(messages=fix_with_reasoner_messages)
        reasoner_response_content = reasoner_response.choices[0].message.content
        fix_with_reasoner_messages.append({"role": "assistant", "content": reasoner_response_content})
        reasoner_response_reasoning_content = reasoner_response.choices[0].message.reasoning_content
        code_block_change_info = extract_code_block_change_info(reasoner_response_content)
        self.logger.debug(f"fix with reasoner response: {reasoner_response_content}")
        for file, changes in code_block_change_info.items():
            filepath = os.path.join(self.module_translation.path, file)
            with open(filepath, "r", encoding="utf-8") as f:
                old_content = f.read()
            try:
                new_content = apply_changes(old_content, changes)
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
            except Exception as e:
                self.logger.error(f"error occurred when applying changes: {e}")
                continue
        return AgentResponse.done(self, TestEngineerResponseType.TEST_LOGIC_FIX_COMPLETION)

    def fix_logic_errors(self, pre_response: AgentResponse) -> AgentResponse:
        """修复逻辑错误
        """
        self.logger.info("fixing logic errors")
        # 获取测试失败的测试函数（以测试函数为修复单位）
        test_output = pre_response.data.get("test_output")
        failed_tests = test_output.get("errors")
        errors = [
            error["error_info"]
            for error in failed_tests
            if "error_info" in error
        ]
        return self.fix_logic_with_reasoner(errors)

    def add_history(self, output: str = "", syntax_errors=None, logic_errors=None):
        """
        维护修改历史
        """
        self.logger.info("adding history.")
        if syntax_errors is None:
            syntax_errors = []
        if logic_errors is None:
            logic_errors = []

        # 如果编译通过，但是有未通过的测试用例，那么就选择一个最少的恢复
        related_files = []
        for filepath in self.module_translation.related_rust_files:
            related_files.append({
                "filepath": filepath,
                "content": read_file_tool(os.path.join(self.module_translation.path, filepath), show_line_number=False)
            })
        self.change_history.append({
            "syntax_errors": syntax_errors,
            "logic_errors": logic_errors,
            "related_files": related_files,
            "test_content": read_file_tool(os.path.join(self.module_translation.path, self.test_file), show_line_number=False),
            "output": output
        })

    def save_best(self):
        """
        如果编译通过，存在不通过的测试用例，则保存最好的结果。
        """
        self.logger.info("saving the best result.")
        if len(self.change_history) == 0:
            self.revert_raw_files()
        else:
            # 寻找最优历史记录
            best_history_index = 0
            min_errors = len(self.change_history[0].get("logic_errors"))
            for index, history in enumerate(self.change_history):
                errors_num = len(history.get("logic_errors"))
                if errors_num < min_errors:
                    best_history_index = index
                    min_errors = errors_num
            # 恢复为最优历史记录
            best_history = self.change_history[best_history_index]
            related_files = best_history.get("related_files")
            test_content = best_history.get("test_content")
            for file in related_files:
                filepath = os.path.join(self.module_translation.path, file.get("filepath"))
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(file.get("content"))
            test_filepath = os.path.join(self.module_translation.path, self.test_file)
            with open(test_filepath, "w", encoding="utf-8") as f:
                f.write(test_content)
            output = ""
            syntax_errors = best_history.get("syntax_errors")
            logic_errors = best_history.get("logic_errors")
            if len(syntax_errors) > 0:
                syntax_errors_str = "\n".join(syntax_errors)
                output += f"## 语法错误：\n{syntax_errors_str}\n"
            if len(logic_errors) > 0:
                logic_errors_str = "\n".join(logic_errors)
                output += f"## 逻辑错误：\n{logic_errors_str}\n"
            if output.strip() != "":
                self.generate_test_report(output)

    def revert_raw_files(self):
        """
        如果测试编译未通过，则恢复到最初的版本
        """
        self.logger.info("reverting to the initial version.")
        # 恢复最初的被测代码
        for file in self.raw_files:
            filepath = os.path.join(self.module_translation.path, file.get("filepath"))
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(file.get("content"))
        test_filepath = os.path.join(self.module_translation.path, self.test_file)
        # 测试文件置为空
        with open(test_filepath, "w", encoding="utf-8") as f:
            f.write("")