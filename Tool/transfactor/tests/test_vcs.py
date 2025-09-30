import os
import shutil
import pickle
import unittest

from core.version.vcs import VCS, load_object


class TestVCS(unittest.TestCase):

    def setUp(self) -> None:
        self.root_dir = "tmp/rust"
        shutil.rmtree(self.root_dir, ignore_errors=True)
        os.makedirs(self.root_dir, exist_ok=True)
        self.vcs = VCS(self.root_dir)

    def test_init(self):
        print("test_init")
        self.vcs.init()
        self.assertTrue(os.path.exists(self.vcs.vcs_dir))
        self.assertTrue(os.path.exists(self.vcs.objects_dir))
        self.assertTrue(os.path.exists(self.vcs.index_file))
        self.assertTrue(os.path.exists(self.vcs.head_file))
        self.assertTrue(os.path.exists(self.vcs.log_file))

    def test_add(self):
        print("test_add")
        self.vcs.init()
        filepath = os.path.join(self.root_dir, "test.txt")
        with open(filepath, "w") as f:
            f.write("hello world")
        self.vcs.add([filepath])
        with open(self.vcs.index_file, "rb") as f:
            index = pickle.load(f)
        self.assertIn(filepath, index)
        fileoid = index[filepath]
        data = load_object(fileoid, self.vcs.objects_dir)
        self.assertEqual(data, b"hello world")

    def test_commit(self):
        print("test_commit")
        self.vcs.init()
        filepath = os.path.join(self.root_dir, "test.txt")
        with open(filepath, "w") as f:
            f.write("hello world")
        self.vcs.add([filepath])
        self.vcs.commit("add test.txt")
        with open(self.vcs.head_file, "r") as f:
            head = f.read()
        commit_oid = head
        # 检查日志
        with open(self.vcs.log_file, "r") as f:
            log = f.readlines()
        self.assertIn("add test.txt", log[-1])
        # 检查提交对象
        commit_data_serialized = load_object(commit_oid, self.vcs.objects_dir)
        commit_data = pickle.loads(commit_data_serialized)
        self.assertEqual(commit_data["message"], "add test.txt")
        tree_data = load_object(commit_data["tree"], self.vcs.objects_dir)
        tree = pickle.loads(tree_data)
        with open(self.vcs.index_file, "rb") as f:
            index = pickle.load(f)
        self.assertEqual(tree, index)

    def test_rollback(self):
        print("test_rollback")
        self.vcs.init()
        filepath = os.path.join(self.root_dir, "test.txt")
        with open(filepath, "w") as f:
            f.write("hello world")
        self.vcs.add([filepath])
        self.vcs.commit("add test.txt")
        with open(filepath, "w") as f:
            f.write("hello world2")
        self.vcs.add([filepath])
        self.vcs.commit("update test.txt")
        self.vcs.rollback()
        with open(filepath, "r") as f:
            content = f.read()
        self.assertEqual(content, "hello world")

    def test_revert(self):
        print("test_revert")
        self.vcs.init()
        filepath = os.path.join(self.root_dir, "test.txt")
        with open(filepath, "w") as f:
            f.write("hello world")
        self.vcs.add([filepath])
        self.vcs.commit("add test.txt")
        with open(filepath, "w") as f:
            f.write("hello world2")
        self.vcs.add([filepath])
        self.vcs.commit("update test.txt")
        with open(filepath, "w") as f:
            f.write("hello world3")
        self.vcs.add([filepath])
        self.vcs.revert([filepath])
        with open(filepath, "r") as f:
            content = f.read()
        self.assertEqual(content, "hello world2")

    def tearDown(self) -> None:
        shutil.rmtree(self.root_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
