import time
import unittest

from core.utils.tree_search import TreeSearch, TreeSearchNode


class TreeSearchTestCase(unittest.TestCase):

    def setUp(self):

        def expansion_func(node: TreeSearchNode) -> list[dict]:
            return [
                {"value": node.data.get("value", 0) + 1},
                {"value": node.data.get("value", 0) + 2},
                {"value": node.data.get("value", 0) + 3},
            ]

        def simulation_func(node: TreeSearchNode) -> float:
            return node.data.get("value", 0)

        def compare_func(node1: TreeSearchNode, node2: TreeSearchNode) -> bool:
            return node2.data.get("value", 0) > node1.data.get("value", 0)

        self.expansion_func = expansion_func
        self.simulation_func = simulation_func
        self.compare_func = compare_func

        # 目标函数
        self.target_condition = lambda node: node.data.get("value", 0) >= 10

    def test_dfs_search(self):
        from core.utils.tree_search import DFSSearchStrategy
        start_time = time.time()
        strategy = DFSSearchStrategy(
            expansion_func=self.expansion_func,
            simulation_func=self.simulation_func,
            compare_func=self.compare_func,
            max_depth=10,
            max_expansion=1000
        )

        tree_search = TreeSearch(
            root_state={"value": 0},
            search_strategy=strategy
        )
        target_node = tree_search.search(self.target_condition)
        end_time = time.time()
        print(f"DFS Search Time: {end_time - start_time}, Target Node: {target_node.data}")
        tree_search.print()
        self.assertTrue(target_node.data.get("value", 0) >= 10)

    def test_bfs_search(self):
        from core.utils.tree_search import BFSSearchStrategy
        start_time = time.time()
        strategy = BFSSearchStrategy(
            expansion_func=self.expansion_func,
            simulation_func=self.simulation_func,
            compare_func=self.compare_func,
            max_depth=10,
            max_expansion=1000
        )

        tree_search = TreeSearch(
            root_state={"value": 0},
            search_strategy=strategy
        )
        target_node = tree_search.search(self.target_condition)
        end_time = time.time()
        print(f"BFS Search Time: {end_time - start_time}, Target Node: {target_node.data}")
        tree_search.print()
        self.assertTrue(target_node.data.get("value", 0) >= 10)

    def test_greedy_search(self):
        from core.utils.tree_search import GreedySearchStrategy

        def selection_func(children: list[TreeSearchNode]) -> TreeSearchNode:
            return max(children, key=lambda node: node.data.get("value", 0))

        start_time = time.time()
        strategy = GreedySearchStrategy(
            expansion_func=self.expansion_func,
            simulation_func=self.simulation_func,
            compare_func=self.compare_func,
            selection_func=selection_func,
            max_depth=10,
            max_expansion=1000
        )

        tree_search = TreeSearch(
            root_state={"value": 0},
            search_strategy=strategy
        )
        target_node = tree_search.search(self.target_condition)
        end_time = time.time()
        print(f"Greedy Search Time: {end_time - start_time}, Target Node: {target_node.data}")
        tree_search.print()
        self.assertTrue(target_node.data.get("value", 0) >= 10)

    def test_mcts_search(self):
        from core.utils.tree_search import MCTSSearchStrategy

        start_time = time.time()
        strategy = MCTSSearchStrategy(
            expansion_func=self.expansion_func,
            simulation_func=self.simulation_func,
            compare_func=self.compare_func,
            max_depth=10,
            max_expansion=1000
        )

        tree_search = TreeSearch(
            root_state={"value": 0},
            search_strategy=strategy
        )
        target_node = tree_search.search(self.target_condition)
        end_time = time.time()
        print(f"MCTS Search Time: {end_time - start_time}, Target Node: {target_node.data}")
        tree_search.print()
        self.assertTrue(target_node.data.get("value", 0) >= 10)

if __name__ == "__main__":
    unittest.main()