import os
import shutil
import unittest
from contextlib import contextmanager
from typing import Generator

from core.utils.vfs import MemoryFileSystem


class TestMemoryFileSystem(unittest.TestCase):
    def setUp(self):
        """每个测试用例执行前的设置"""
        self.fs = MemoryFileSystem()

    def test_normalize_path(self):
        """测试路径规范化"""
        test_cases = [
            # (输入路径, 期望输出)
            ("file.txt", "/file.txt"),
            ("/file.txt", "/file.txt"),
            ("//file.txt", "/file.txt"),
            ("/dir/../file.txt", "/file.txt"),
            ("/dir/./file.txt", "/dir/file.txt"),
            ("/dir/subdir/../../file.txt", "/file.txt"),
            ("dir\\file.txt", "/dir/file.txt"),  # Windows路径转换
            (".", "/"),
            ("", "/"),
        ]

        for input_path, expected in test_cases:
            with self.subTest(input_path=input_path):
                self.assertEqual(
                    self.fs._normalize_path(input_path),
                    expected,
                    f"Path normalization failed for '{input_path}'"
                )

    def test_file_operations(self):
        """测试基本的文件操作"""
        # 测试文件写入和读取
        test_file = "/test.txt"
        test_content = "Hello, World!"

        with self.fs.open(test_file, "w") as f:
            f.write(test_content)

        # 验证文件存在
        self.assertTrue(self.fs.exists(test_file))

        # 验证文件内容
        with self.fs.open(test_file, "r") as f:
            content = f.read()
            self.assertEqual(content, test_content)

        # 测试文件删除
        self.fs.remove(test_file)
        self.assertFalse(self.fs.exists(test_file))

    def test_directory_listing(self):
        """测试目录列表功能"""
        # 创建测试文件结构
        files = [
            "/file1.txt",
            "/dir/file2.txt",
            "/dir/subdir/file3.txt"
        ]

        for filepath in files:
            with self.fs.open(filepath, "w") as f:
                f.write("content")

        # 测试非递归列表
        root_files = self.fs.list_files("/")
        self.assertEqual(set(root_files), {"file1.txt"})

        dir_files = self.fs.list_files("/dir")
        self.assertEqual(set(dir_files), {"file2.txt"})

        # 测试递归列表
        all_files = self.fs.list_files("/", recursive=True)
        expected_files = {"file1.txt", "dir/file2.txt", "dir/subdir/file3.txt"}
        self.assertEqual(set(all_files), expected_files)

    def test_file_modes(self):
        """测试不同的文件打开模式"""
        filepath = "/test.txt"

        # 写入模式
        with self.fs.open(filepath, "w") as f:
            f.write("Hello")

        # 追加模式
        with self.fs.open(filepath, "a") as f:
            f.write(" World")

        # 读取并验证内容
        with self.fs.open(filepath, "r") as f:
            content = f.read()
            self.assertEqual(content, "Hello World")

        # 测试写入模式是否会截断文件
        with self.fs.open(filepath, "w") as f:
            f.write("New")

        with self.fs.open(filepath, "r") as f:
            content = f.read()
            self.assertEqual(content, "New")

    def test_error_handling(self):
        """测试错误处理"""
        filepath = "/test.txt"

        # 测试读取不存在的文件
        with self.assertRaises(FileNotFoundError):
            with self.fs.open(filepath, "r") as f:
                f.read()

        # 测试无效的模式
        with self.assertRaises(ValueError):
            with self.fs.open(filepath, "x") as f:
                pass

        # 创建文件后测试无效操作
        with self.fs.open(filepath, "w") as f:
            f.write("content")

        # 测试在只读模式下写入
        with self.assertRaises(IOError):
            with self.fs.open(filepath, "r") as f:
                f.write("new content")

    def test_concurrent_access(self):
        """测试并发访问"""
        import threading
        import time

        filepath = "/concurrent.txt"
        iterations = 100
        threads = []
        errors = []

        def write_file(thread_id: int):
            try:
                with self.fs.open(filepath, "a") as f:
                    f.write("1")
                    time.sleep(0.001)  # 增加竞争条件的可能性
            except Exception as e:
                errors.append(e)

        # 创建并启动多个线程
        for i in range(iterations):
            t = threading.Thread(target=write_file, args=(i,))
            threads.append(t)
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 验证没有错误发生
        self.assertEqual(len(errors), 0, f"Concurrent access errors: {errors}")

        # 验证文件内容长度
        with self.fs.open(filepath, "r") as f:
            content = f.read()
            self.assertEqual(
                len(content),
                iterations,
                "Some concurrent writes were lost"
            )

    def test_load_and_flush(self):
        """测试 flush 方法"""
        os.makedirs("flush_test", exist_ok=True)
        with open("flush_test/flush_test.txt", "w", encoding="utf-8") as f:
            f.write("before flush\n")
        self.fs.load("flush_test")
        with self.fs.open("flush_test/flush_test.txt", "r") as f:
            content = f.read()
            self.assertEqual(content, "before flush\n")
        with self.fs.open("flush_test/flush_test.txt", "a") as f:
            f.write("after flush\n")
        self.fs.flush()
        with open("flush_test/flush_test.txt", "r") as f:
            content = f.read()
            self.assertEqual(content, "before flush\nafter flush\n")
        shutil.rmtree("flush_test")




if __name__ == '__main__':
    unittest.main()