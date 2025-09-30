import os

from tabulate import tabulate


def count_unsafe_code_lines(code):
    lines = code.split('\n')
    brace_count = 0
    total_unsafe_lines = 0

    in_unsafe_block = False
    unsafe_start_depth = -1  # 记录“进入 unsafe 时的花括号深度”，-1 表示当前没有在 unsafe 块里

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith('//'):
            continue

        # 先统计本行的花括号变化
        open_braces = line.count('{')
        close_braces = line.count('}')

        # 先更新 brace_count（有些人喜欢先检测当前行是不是 `unsafe {` 再更新也可以，
        # 但要注意到时如何处理“同一行里就带了 { 的情况”）
        brace_count += open_braces
        brace_count -= close_braces

        # 如果本行包含 'unsafe'，说明开始了一个新的 unsafe 块
        # （注意：有时候 'unsafe' 并不一定伴随 '{'，例如 `unsafe trait X {`，可以酌情改进判断）
        if 'unsafe' in line and not in_unsafe_block:
            in_unsafe_block = True
            unsafe_start_depth = brace_count  # 在更新完 brace_count 后记录当前深度

        # 如果在 unsafe 块里，就打印并计数
        if in_unsafe_block:
            total_unsafe_lines += 1

        # 检查是否离开了 unsafe 块
        # 如果发现当前的 brace_count 已经回到 unsafe_start_depth 之下，
        # 说明刚刚多打印了本行的某个右花括号 `}` 正好把 unsafe 块关掉了
        if in_unsafe_block and brace_count < unsafe_start_depth:
            in_unsafe_block = False
            unsafe_start_depth = -1

    return total_unsafe_lines

def count_total_code_lines(code):
    lines = code.split('\n')
    total_lines = 0
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('//'):
            continue
        if line.strip().startswith("//!"):
            continue
        if line.strip().startswith("///"):
            continue
        total_lines += 1
    return total_lines

def main(source_dir):
    table_header = ["index", "module", "unsafe"]
    table_data = []
    # 计算 c2rust 结果的 unsafe 行数
    for i, file in enumerate(os.listdir(source_dir)):
        if os.path.isdir(file):
            continue
        if not file.endswith(".rs"):
            continue
        with open(os.path.join(source_dir, file), 'r') as f:
            code = f.read()
        unsafe_code_lines = count_unsafe_code_lines(code)
        total_code_lines = count_total_code_lines(code)
        table_data.append([i, file, f"{unsafe_code_lines}/{total_code_lines} ({unsafe_code_lines/total_code_lines:.2%})"])
    print(tabulate(table_data, headers=table_header, tablefmt="grid"))


if __name__ == '__main__':
    source_dir = "../../Samples/c2rust_output/src"
    main(source_dir)