"""
tests/utils/test_task_utils.py

Tests for matrixmouse.utils.task_utils — detect_cycles.

Coverage:
    detect_cycles:
        - Self-loop is always a cycle
        - Direct cycle: A blocks B, propose B blocks A
        - Transitive cycle: A->B->C, propose C->A
        - Deep transitive cycle
        - No cycle: independent tasks
        - No cycle: diamond dependency (A->B, A->C, B->D, C->D)
        - Empty graph: no existing edges
        - Single node with no edges
        - Proposed edge to unknown task (not in get_blocked_by) is safe
"""

import pytest
from matrixmouse.utils.task_utils import detect_cycles


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_graph(edges: dict[str, list[str]]):
    """
    Build a get_blocked_by callable from a dict of
    blocked_id -> [blocking_id, ...] edges.

    Any task not in the dict returns an empty list.
    """
    def get_blocked_by(task_id: str) -> list[str]:
        return edges.get(task_id, [])
    return get_blocked_by


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDetectCycles:
    def test_self_loop_is_cycle(self):
        get_blocked_by = make_graph({})
        assert detect_cycles("A", "A", get_blocked_by) is True

    def test_direct_cycle(self):
        # A blocks B. Proposing B blocks A would cycle.
        # blocked_by["B"] = ["A"]  (A is blocking B)
        get_blocked_by = make_graph({"B": ["A"]})
        assert detect_cycles("B", "A", get_blocked_by) is True

    def test_no_cycle_independent_tasks(self):
        get_blocked_by = make_graph({})
        assert detect_cycles("A", "B", get_blocked_by) is False

    def test_transitive_cycle(self):
        # A -> B -> C (A blocks B, B blocks C)
        # blocked_by["B"] = ["A"], blocked_by["C"] = ["B"]
        # Proposing C -> A (C blocks A) would create A->B->C->A
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["B"],
        })
        assert detect_cycles("C", "A", get_blocked_by) is True

    def test_deep_transitive_cycle(self):
        # Chain: A->B->C->D->E
        # Proposing E->A would cycle
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["B"],
            "D": ["C"],
            "E": ["D"],
        })
        assert detect_cycles("E", "A", get_blocked_by) is True

    def test_no_cycle_chain_extension(self):
        # A->B->C, proposing C->D is safe
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["B"],
        })
        assert detect_cycles("C", "D", get_blocked_by) is False

    def test_diamond_no_cycle(self):
        # Diamond: A->B, A->C, B->D, C->D
        # blocked_by["B"] = ["A"], blocked_by["C"] = ["A"]
        # blocked_by["D"] = ["B", "C"]
        # Proposing A->D (A blocks D) is not a cycle
        # (A is already above D, but that's fine —
        #  the question is whether D can reach A)
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["A"],
            "D": ["B", "C"],
        })
        assert detect_cycles("A", "D", get_blocked_by) is False

    def test_diamond_would_cycle(self):
        # Same diamond. Proposing D->A (D blocks A) would cycle:
        # A->B->D->A or A->C->D->A
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["A"],
            "D": ["B", "C"],
        })
        assert detect_cycles("D", "A", get_blocked_by) is True

    def test_empty_graph(self):
        get_blocked_by = make_graph({})
        assert detect_cycles("A", "B", get_blocked_by) is False

    def test_unknown_task_is_safe(self):
        # proposed_blocked_id has no edges in the graph
        get_blocked_by = make_graph({"A": ["B"]})
        assert detect_cycles("X", "Y", get_blocked_by) is False

    def test_multiple_blockers_traversed(self):
        # D is blocked by both B and C, both of which are blocked by A.
        # A -> B -> D and A -> C -> D
        # Proposing D blocks A would cycle (A is upstream of D).
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["A"],
            "D": ["B", "C"],
        })
        # D -> A would cycle
        assert detect_cycles("D", "A", get_blocked_by) is True
        # A -> D is safe (A is already upstream, adding A as blocker of D
        # means A blocks D which is already the case transitively — but
        # no cycle is introduced since D does not reach A)
        assert detect_cycles("A", "D", get_blocked_by) is False

    def test_already_visited_nodes_not_revisited(self):
        # Graph with shared ancestors — verify visited set prevents
        # infinite loops on graphs with shared nodes
        # B blocked by A, C blocked by A and B
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["A", "B"],
        })
        # Proposing C blocks D is safe
        assert detect_cycles("C", "D", get_blocked_by) is False
