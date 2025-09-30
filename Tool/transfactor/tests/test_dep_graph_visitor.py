import os
import shutil
import unittest

from graphviz import Digraph

from core.graph.dep_graph import DGEdgeType, DGNode, DepGraph
from core.graph.dep_graph_visitor import DepGraphClangNodeVisitor


def print_cursor_ast(root):
    def print_ast(node, indent=0):
        """
        递归遍历 clang AST 的辅助函数。
        :param node: 当前 AST 节点 (cursor)
        :param indent: 当前缩进级别
        """
        # 缩进
        prefix = ' ' * indent

        # 节点种类 (kind)，节点拼写 (spelling)，以及节点类型 (type.spelling)
        kind = str(node.kind).split(".")[1]
        spelling = node.spelling
        node_type = node.type.spelling  # 如果没有类型，则可能为空字符串

        # 打印：缩进 + 节点种类 + 节点拼写 + 节点类型
        print(f"{prefix}{kind} | {spelling} | {node_type} | {node.location}")

        # 递归遍历子节点
        for child in node.get_children():
            print_ast(child, indent + 2)

    print_ast(root)

class TestDepGraph(unittest.TestCase):

    def setUp(self):
        self.base_dir = "../../../Input/02-Medium/src"
        self.graph_dir = "graphs"
        os.makedirs(self.graph_dir, exist_ok=True)

    def tearDown(self):
        ...
        # if os.path.exists(self.graph_dir):
        #     shutil.rmtree(self.graph_dir)

    def save_graph(self, graph: Digraph, name: str):
        graph.render(f"{self.graph_dir}/{name}")

    def traverse_modules(self, graph: DepGraph):
        for model_name, nodes_list_iter in graph.traverse_modules():
            print(f"===============================[{model_name}]===================================")
            for nodes_list in nodes_list_iter:
                print("----------------------------------------")
                for nodes in nodes_list:
                    print(nodes)

    def test_macro_decl(self):
        c = """
        #define MAX(a, b) ((a) > (b) ? (a) : (b))
        
        #define SWAP(a, b) do { int temp = a; a = b; b = temp; } while(0)
        
        #define PRINT_ARRAY(arr, size) \\
            for(int i = 0; i < size; i++) \\
                printf("%d ", arr[i]); \\
            printf("\\n")
        
        #ifdef DEBUG
            // 调试代码
        #else
            // 正式发布代码
        #endif
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "macro_decl")
        self.traverse_modules(graph)

    def test_var_decl(self):
        c = """
        int a;
        int b = 42;
        int c, d;
        int e = 1, f = 2;
        int g[10];
        int h[10] = {1, 2, 3};
        int i[10] = {1, 2, 3, [6] = 42};
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        self.save_graph(visitor.build_graph(), "var_decl")

    def test_struct_decl(self):
        c = """
        typedef struct {} unnamed_struct;
        struct named_struct;
        struct named_struct {};
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        self.save_graph(visitor.build_graph(), "struct_decl")

    def test_union_decl(self):
        c = """
        typedef union {} union_name;
        union undefined_union_name;
        union union_name {};
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        self.save_graph(visitor.build_graph(), "union_decl")

    def test_enum_decl(self):
        c = """
        typedef enum {
            VALUE_ONE
        } enum_name;
        enum undefined_enum_name;
        enum enum_name1 {
            VALUE_TWO
        };
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        self.save_graph(visitor.build_graph(), "enum_decl")

    def test_function_decl(self):
        c = """
        int func_name(int a, int b);
        int func_name(int a, int b) { return 0; }
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        self.save_graph(visitor.build_graph(), "function_decl")

    def test_typedef_decl(self):
        c = """
        // 1. 匿名结构体/联合体/枚举定义
        typedef struct {} unnamed_struct;
        typedef union {} unnamed_union;
        typedef enum {} unnamed_enum;
        // 2. 命名结构体/联合体/枚举定义
        // 2.1 原生类型
        typedef int int_type;
        typedef void *ArrayListValue;
        typedef int (*ArrayListEqualFunc)(ArrayListValue value1, ArrayListValue value2);
        // 2.2 复杂类型
        struct _struct_name {};
        typedef struct _struct_name struct_name;
        union _union_name {};
        typedef union _union_name union_name;
        typedef struct named_struct {} named_struct1;
        // 2.3 引用类型
        typedef struct _struct_name *struct_name_ptr;
        """
        c = """
        struct _struct_name {};
        typedef struct _struct_name struct_name;
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "typedef_decl")
        self.traverse_modules(graph)

    def test_type_ref(self):
        c = """
        // 1. 递归定义引用
        struct struct_name {
            struct struct_name *next;
        };
        // 2. 类型引用
        typedef struct struct_name struct_name;
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "type_ref")

    def test_member_ref_expr(self):
        c = """
        struct struct_name {
            int member;
        };
        void func() {
            struct struct_name obj;
            obj.member = 42;
        }
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "member_ref_expr")

    def test_call_expr(self):
        c = """
        #include <stdio.h>
        // 1. 函数调用
        int func_name(int a, int b) {
            printf("Hello, World!");
            return a + b;
        }
        void func() {
            int result = func_name(1, 2);
        }
        // 2. 递归调用
        void func1() {
            func1();
        }
        // 3. 函数指针调用
        void func2() {
            int (*func_ptr)(int, int) = func_name;
            int result = func_ptr(1, 2);
        }
        // 4. 函数参数调用
        typedef int (*PARAM_FUNC)(int, int);
        int func3(int a, PARAM_FUNC param_func) {
            return param_func(a, 2);
        }
        int func4(int a, int (*param_func1)(int, int)) {
            return param_func1(a, 2);
        }
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "call_expr")

    def test_inline(self):
        c = """
        inline int func_name(int a, int b) {
            return a + b;
        }
        void func() {
            int result = func_name(1, 2);
        }
        """
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(path="test.c", unsaved_files=[("test.c", c)])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "inline")

    # def test_class_decl(self):
    #     cpp = """
    #     class class_name {
    #         public:
    #             int member;
    #             void func() {}
    #     };
    #     class class_decl;
    #     """
    #     visitor = DepGraphClangNodeVisitor.from_language("cpp")
    #     root = visitor.parse(path="test.cpp", unsaved_files=[("test.cpp", cpp)])
    #     visitor.visit(root)
    #     graph = visitor.build_graph()
    #     graph.print()

    # def test_cpp_constructor(self):
    #     cpp = """
    #     class class_name {
    #         public:
    #             class_name() {}
    #             class_name(int a) {}
    #             class_name(int a, int b) {}
    #     };
    #     """
    #     visitor = DepGraphClangNodeVisitor.from_language("cpp")
    #     root = visitor.parse(path="test.cpp", unsaved_files=[("test.cpp", cpp)])
    #     visitor.visit(root)
    #     graph = visitor.build_graph()
    #     graph.print()

    # def test_cpp_destructor(self):
    #     cpp = """
    #     class class_name {
    #         public:
    #             class_name();
    #     };
    #     class_name::~class_name() {}
    #     """
    #     visitor = DepGraphClangNodeVisitor.from_language("cpp")
    #     root = visitor.parse(path="test.cpp", unsaved_files=[("test.cpp", cpp)])
    #     visitor.visit(root)
    #     graph = visitor.build_graph()
    #     graph.print()

    def test_file_visit(self):
        utf8_decoder_filepath = os.path.join(self.base_dir, "utf8-decoder.h")
        visitor = DepGraphClangNodeVisitor.from_language("c")
        root = visitor.parse(utf8_decoder_filepath, args=["-std=c11"])
        visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "utf8-decoder")

    def test_project_visit(self):
        filepaths = [
            os.path.join(self.base_dir, file)
            for file in os.listdir(self.base_dir) if "arraylist" in file
        ]
        visitor = DepGraphClangNodeVisitor.from_language("c")
        for filepath in filepaths:
            root = visitor.parse(filepath, args=["-std=c11"])
            # print_cursor_ast(root)
            visitor.visit(root)
        graph = visitor.build_graph()
        self.save_graph(graph, "project")
        self.traverse_modules(graph)

    def test_traverse_modules(self):
        filepaths = [
            os.path.join(self.base_dir, file)
            for file in os.listdir(self.base_dir) if "tinyexpr" in file
        ]
        visitor = DepGraphClangNodeVisitor.from_language("c")
        for filepath in filepaths:
            root = visitor.parse(filepath, args=["-std=c11"])
            # print_cursor_ast(root)
            visitor.visit(root)
        graph = visitor.build_graph()
        # graph.print()
        self.save_graph(graph, "tinyexpr")
        self.traverse_modules(graph)


if __name__ == "__main__":
    unittest.main()
