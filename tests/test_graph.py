import unittest

import galleries.galleryms


class TestImplicationGraph(unittest.TestCase):
    def _assert_cycle(self, graph, cycle):
        ig = galleries.galleryms.ImplicationGraph()
        for node, implies in graph.items():
            ig.add_edge(node, *implies)
        err = ig.find_cycle()
        self.assertEqual(cycle, err)

    def test_cycle(self):
        # Self cycle
        self._assert_cycle({1: {1}}, [1, 1])
        # Simple cycle
        self._assert_cycle({1: {2}, 2: {1}}, [1, 2, 1])
        # Indirect cycle
        self._assert_cycle({1: {2}, 2: {3}, 3: {1}}, [1, 2, 3, 1])
        # not all elements involved in a cycle
        self._assert_cycle({1: {2}, 2: {3}, 3: {1}, 5: {4}, 4: {6}}, [1, 2, 3, 1])
        # Multiple cycles
        self._assert_cycle({1: {2}, 2: {1}, 3: {4}, 4: {5}, 6: {7}, 7: {6}}, [1, 2, 1])
        # Cycle in the middle of the graph
        self._assert_cycle({1: {2}, 2: {3}, 3: {2, 4}, 4: {5}}, [2, 3, 2])


if __name__ == "__main__":
    unittest.main()
