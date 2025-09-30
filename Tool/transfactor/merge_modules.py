import os
import re
import time
import json
import selectors
import subprocess
from argparse import ArgumentParser
from typing import Any, Dict, Optional
from core.utils.rust_utils import cargo_test
import toml

def cargo_check(project_dir: str, filepaths: Optional[list[str]] = None, ignore_codes: Optional[list[str]] = None) -> Dict[str, Any]:
    """运行 cargo check 命令进行代码检查"""
    ignore_codes = ignore_codes or []
    # 要在 os.chdir 之前转为绝对路径
    filepaths = [
        os.path.relpath(filepath, project_dir)
        for filepath in filepaths
    ] if filepaths is not None else []
    cargo_check_command = ["cargo", "check", "--message-format", "json"]
    try:
        cargo_check_process = subprocess.run(
            cargo_check_command,
            capture_output=True,
            text=True,
            cwd=os.path.abspath(project_dir)
        )
        cargo_check_stderr = cargo_check_process.stderr
        output_lines = cargo_check_process.stdout.split("\n")
        compile_errors = []

        for output_line in output_lines:
            if output_line.strip() == "":
                continue
            try:
                cargo_check_output = json.loads(output_line)
                if cargo_check_output["reason"] == "compiler-message":
                    compiler_message = cargo_check_output
                    if compiler_message["message"]["level"] != "error":
                        continue
                    if compiler_message["message"]["code"] and compiler_message["message"]["code"]["code"] in ignore_codes:
                        continue
                    # Rust 文件相对路径
                    is_record = False
                    for span in compiler_message["message"]["spans"]:
                        if not filepaths:
                            is_record = True
                            break
                        if span["file_name"] in filepaths:
                            is_record = True
                            break
                    if not is_record:
                        continue
                    # TODO：这里目前忽略模块信息，仅针对单模块进行检查
                    compile_errors.append({
                        "rendered": compiler_message["message"]["rendered"],
                        "message_type": compiler_message["message"]["$message_type"],
                        "children": compiler_message["message"]["children"],
                        "code": compiler_message["message"]["code"],
                        "level": compiler_message["message"]["level"],
                        "message": compiler_message["message"]["message"],
                        "spans": compiler_message["message"]["spans"],
                    })
            except Exception as e:
                # TODO: 解析错误，详细错误处理
                raise e
        # compile_errors = deduplicate_by_key(compile_errors, lambda x: x["rendered"])
        return {
            "success": len(compile_errors) == 0,
            "output": cargo_check_stderr,
            "errors": compile_errors,
        }
    except Exception as e:
        # TODO: 解析错误，详细错误处理
        raise e

def extract_error_output(test_case_name, cargo_test_stdout):
    """
    从输出中提取指定测试用例的错误信息
    通过测试名称（如 test_max_heap）查找并提取该测试的错误输出直到空行
    """
    # 捕获所有在 '---- test_case_name stdout ----' 后的内容，直到下一个空行或下一个测试的输出
    pattern = rf"----\s*(?:tests::)?{test_case_name}\s*stdout\s*----\s*(.*?)\s*(?=----|\Z)"

    # 使用 re.DOTALL 让 '.' 匹配换行符
    match = re.search(pattern, cargo_test_stdout, re.DOTALL)

    if match:
        return match.group(1).strip()

    return ""

def cargo_test(project_path, timeout=120):
    """
    执行测试，并在超时后返回已产生的输出。
    使用 selectors 进行非阻塞的 I/O 读取。
    """
    # cur_cwd = os.getcwd()
    # os.chdir(project_path)
    env = os.environ.copy()
    env['RUST_BACKTRACE'] = '1'
    cargo_check_command = ["cargo", "test", "--message-format", "json"]

    # 初始化输出缓冲区
    cargo_test_stdout = []
    cargo_test_stderr = []

    # 创建 selectors 对象
    sel = selectors.DefaultSelector()

    try:
        # 启动子进程
        process = subprocess.Popen(
            cargo_check_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,  # 行缓冲
            cwd=os.path.abspath(project_path)
        )

        # 注册 stdout 和 stderr 到 selectors
        sel.register(process.stdout, selectors.EVENT_READ)
        sel.register(process.stderr, selectors.EVENT_READ)

        start_time = time.time()
        timeout_occurred = False

        while True:
            elapsed_time = time.time() - start_time
            remaining_time = timeout - elapsed_time
            if remaining_time <= 0:
                timeout_occurred = True
                break

            events = sel.select(timeout=remaining_time)

            for key, _ in events:
                data = key.fileobj.readline()
                if data:
                    if key.fileobj is process.stdout:
                        cargo_test_stdout.append(data)
                    elif key.fileobj is process.stderr:
                        cargo_test_stderr.append(data)
                else:
                    # EOF
                    sel.unregister(key.fileobj)

            # 检查子进程是否已经结束
            if process.poll() is not None:
                break

        if timeout_occurred:
            # 超时，终止子进程
            process.kill()
            # 继续读取剩余的数据，避免阻塞
            while True:
                events = sel.select(timeout=1)
                if not events:
                    break
                for key, _ in events:
                    data = key.fileobj.readline()
                    if data:
                        if key.fileobj is process.stdout:
                            cargo_test_stdout.append(data)
                        elif key.fileobj is process.stderr:
                            cargo_test_stderr.append(data)
                    else:
                        sel.unregister(key.fileobj)
            filtered_stdout = [line for line in cargo_test_stdout if
                               not (line and (line[0] == "{" or line[0] == "[")) or not json.loads(line)]
            return {
                "success": True,
                "timeout": True,
                "output": "".join(filtered_stdout),
                "errors": [{"message": "Timeout expired during cargo test"}],
            }

        # 读取剩余的数据
        while True:
            events = sel.select(timeout=0)
            if not events:
                break
            for key, _ in events:
                data = key.fileobj.readline()
                if data:
                    if key.fileobj is process.stdout:
                        cargo_test_stdout.append(data)
                    elif key.fileobj is process.stderr:
                        cargo_test_stderr.append(data)
                else:
                    sel.unregister(key.fileobj)

        sel.close()

        # 合并输出
        cargo_test_stdout_str = "".join(cargo_test_stdout)
        cargo_test_stderr_str = "".join(cargo_test_stderr)

        # 检查子进程的返回码
        if process.returncode != 0:
            # 如果因为超时导致的非零退出码已经在前面处理
            pass

        # 正常处理输出
        output_lines = cargo_test_stdout_str.split("\n")
        compile_errors = []
        test_output_lines = []
        test_failed_cases = []
        build_result = False

        for output_line in output_lines:
            if output_line.strip() == "":
                continue
            try:
                cargo_test_output = json.loads(output_line)
                if cargo_test_output["reason"] == "compiler-message":
                    compiler_message = cargo_test_output
                    if compiler_message["message"]["level"] != "error":
                        continue
                    compile_errors.append({
                        "rendered": compiler_message["message"]["rendered"],
                        "message_type": compiler_message["message"]["$message_type"],
                        "children": compiler_message["message"]["children"],
                        "code": compiler_message["message"]["code"],
                        "level": compiler_message["message"]["level"],
                        "message": compiler_message["message"]["message"],
                        "spans": compiler_message["message"]["spans"],
                    })
                if cargo_test_output["reason"] == "build-finished":
                    build_result = cargo_test_output["success"]
            except json.JSONDecodeError:
                # 如果json解析出错，那么该行数据并非json数据
                test_output_lines.append(output_line)
                # 解析出成功和失败的测试用例
                pattern = r"test\s+(?:tests::)?(\w+)\s+\.\.\.\s+(\w+)"
                match = re.match(pattern, output_line)
                if match:
                    test_case_name = match.group(1)
                    result = match.group(2)
                    if result == "FAILED":
                        error_info = extract_error_output(test_case_name, cargo_test_stdout_str)
                        test_failed_cases.append({
                            "test_case_name": test_case_name,
                            "result": result,
                            "error_info": error_info
                        })

        if build_result:
            return {
                "success": True,
                "timeout": False,
                "output": "\n".join(test_output_lines),
                "errors": test_failed_cases
            }
        else:
            return {
                "success": len(compile_errors) == 0,
                "timeout": False,
                "output": cargo_test_stderr_str,
                "errors": compile_errors,
            }

    except Exception as e:
        raise e
    # finally:
    #     os.chdir(cur_cwd)

def main(project_dir: str):
    # 1. 找到 states.json 文件
    try:
        states_path = os.path.join(project_dir, "states.json")
        with open(states_path, "r") as f:
            states = json.load(f)
    except FileNotFoundError:
        print("states.json not found")
        exit(1)
    except Exception as e:
        print(e)
        exit(1)
    # 2. 找到可编译的 module, 在这一步之前，需要确保父级没有 Cargo.toml 文件
    parent_cargo_toml_filepath = os.path.join(project_dir, "Cargo.toml")
    backup_cargo_toml = ""
    if os.path.exists(parent_cargo_toml_filepath):
        # 备份
        with open(parent_cargo_toml_filepath, "r") as f:
            backup_cargo_toml = f.read()
        # 删除
        os.remove(parent_cargo_toml_filepath)
        if os.path.exists(os.path.join(project_dir, "Cargo.lock")):
            os.remove(os.path.join(project_dir, "Cargo.lock"))
    member_module_translations = []
    module_translations = states["module_translations"]
    for module_translation in module_translations:
        module_name = module_translation["name"]
        module_path = os.path.join(project_dir, module_translation["name"])
        if not (os.path.exists(module_path) or os.path.isdir(module_path)):
            print(f"module [{module_name}] not found")
            continue
        if module_translation["status"] == "done":
            print(f"---------------------{module_name}---------------------")
            # 尝试执行 cargo check, 并获得执行状态
            if not os.path.isdir(module_path):
                print(f"module [{module_name}] not found")
                continue
            if not "Cargo.toml" in os.listdir(module_path):
                print(f"module [{module_name}] is not a rust module")
                continue
            cargo_check_output = cargo_check(module_path)
            if not cargo_check_output["success"]:
                print(f"module [{module_name}] check failed")
                continue
            # 尝试进行 cargo test, 并检查是否有编译错误
            cargo_test_output = cargo_test(module_path)
            print("output: ", cargo_test_output["output"])
            if cargo_test_output["success"]:
                # 编译成功
                test_errors = cargo_test_output["errors"]
                if len(test_errors) == 0:
                    print(f"module [{module_name}] test failed")
                member_module_translations.append(module_translation)

    # 3. 将可编译的 module 加入到父模块的 workspace 中
    # 首先恢复父模块的 Cargo.toml 文件
    if backup_cargo_toml.strip() != "":
        with open(parent_cargo_toml_filepath, "w") as f:
            f.write(backup_cargo_toml)
    members = []
    if os.path.exists(parent_cargo_toml_filepath):
        with open(parent_cargo_toml_filepath, "r") as f:
            project_cargo_toml = toml.load(f)
        if "workspace" in project_cargo_toml:
            members = project_cargo_toml["workspace"]["members"]
        else:
            project_cargo_toml["workspace"] = {}
    else:
        project_cargo_toml = {
            "workspace": {}
        }
    for member_module_translation in member_module_translations:
        members.append(member_module_translation["name"])
    project_cargo_toml["workspace"]["members"] = members
    with open(parent_cargo_toml_filepath, "w") as f:
        toml.dump(project_cargo_toml, f)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--project", "-p", type=str, help="Project directory", required=True)
    args = parser.parse_args()

    project_dir = args.project
    main(project_dir)