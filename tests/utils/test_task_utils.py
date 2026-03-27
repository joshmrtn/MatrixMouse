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
from matrixmouse.utils.task_utils import detect_cycles, validate_branch_slug


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

    def test_no_cycle_parallel_chains(self):
        # Two independent chains: A->B->C and D->E->F
        # Proposing C blocks D is safe — no connection between chains
        get_blocked_by = make_graph({
            "B": ["A"],
            "C": ["B"],
            "E": ["D"],
            "F": ["E"],
        })
        assert detect_cycles("C", "D", get_blocked_by) is False

    def test_cycle_across_chains(self):
        # Two chains that would merge into a cycle
        # A->B and C->D, proposing B blocks C and D blocks A
        # After B->C exists: A->B->C->D->A would cycle
        get_blocked_by = make_graph({
            "B": ["A"],
            "D": ["C"],
        })
        # B blocks C is safe (no connection yet)
        assert detect_cycles("B", "C", get_blocked_by) is False
        # Now simulate B->C existing, check D->A would cycle
        get_blocked_by_extended = make_graph({
            "B": ["A"],
            "C": ["B"],
            "D": ["C"],
        })
        assert detect_cycles("D", "A", get_blocked_by_extended) is True

    def test_long_chain_no_cycle(self):
        # Chain of 10 nodes — no cycle
        edges = {chr(ord('A') + i): [chr(ord('A') + i - 1)] for i in range(1, 9)}
        get_blocked_by = make_graph(edges)
        # Extending the chain further is safe
        assert detect_cycles("Z", "A", get_blocked_by) is False
        # Proposing A blocks Z is also safe
        assert detect_cycles("A", "Z", get_blocked_by) is False

    def test_long_chain_cycle_at_root(self):
        # Same chain of 10 nodes — closing it creates a cycle
        edges = {chr(ord('A') + i): [chr(ord('A') + i - 1)] for i in range(1, 9)}
        get_blocked_by = make_graph(edges)
        # J is the last node (chr(ord('A')+9) = 'J')
        # Proposing J blocks A — A is the root upstream of J
        # Wait: in this graph 'J' = chr(73) = 'I', let's use indices
        # edges: B:[A], C:[B], D:[C], E:[D], F:[E], G:[F], H:[G], I:[H]
        # Proposing I blocks A would cycle: A->B->...->I->A
        assert detect_cycles("I", "A", get_blocked_by) is True

    def test_wide_graph_no_cycle(self):
        # One root blocking many leaves — no cycles possible
        edges = {f"leaf{i}": ["root"] for i in range(20)}
        get_blocked_by = make_graph(edges)
        # Adding another leaf is safe
        assert detect_cycles("leaf_new", "root", get_blocked_by) is False
        # Adding leaf0 as blocker of leaf1 is safe (siblings)
        assert detect_cycles("leaf0", "leaf1", get_blocked_by) is False

    def test_wide_graph_cycle(self):
        # One root blocking many leaves — making root blocked by a leaf cycles
        edges = {f"leaf{i}": ["root"] for i in range(20)}
        get_blocked_by = make_graph(edges)
        assert detect_cycles("leaf5", "root", get_blocked_by) is True

    def test_proposed_blocked_not_in_graph(self):
        # proposed_blocked_id has never been seen in the graph
        # Adding a dependency on an unknown node is always safe
        get_blocked_by = make_graph({"B": ["A"]})
        assert detect_cycles("A", "unknown", get_blocked_by) is False

    def test_both_nodes_unknown(self):
        # Neither node exists — safe
        get_blocked_by = make_graph({})
        assert detect_cycles("X", "Y", get_blocked_by) is False

    def test_shared_descendant_no_cycle(self):
        # Two roots both blocking the same node — common in task graphs
        # where two independent tasks must complete before a third starts.
        # root1 -> shared, root2 -> shared
        # Proposing shared blocks new_task is safe
        get_blocked_by = make_graph({
            "shared": ["root1", "root2"],
        })
        assert detect_cycles("shared", "new_task", get_blocked_by) is False
        # Proposing root1 blocks root2 is also safe (siblings)
        assert detect_cycles("root1", "root2", get_blocked_by) is False

    def test_node_blocks_itself_transitively(self):
        # Pre-existing cycle in data: A->B->A (corrupt state).
        # detect_cycles must terminate without infinite looping
        # thanks to the visited set.
        get_blocked_by = make_graph({
            "B": ["A"],
            "A": ["B"],  # pre-existing cycle — corrupt data
        })
        # DFS from A traverses the A<->B cycle but visited set stops it.
        # A is already upstream of B (and vice versa), so any edge
        # completing the cycle is detected — but more importantly,
        # the function terminates rather than looping forever.
        assert detect_cycles("A", "B", get_blocked_by) is True  # direct
        assert detect_cycles("B", "A", get_blocked_by) is True  # direct

        # C is isolated — adding C as blocker of A is genuinely safe
        # even with the corrupt A<->B cycle present
        assert detect_cycles("C", "A", get_blocked_by) is False


class TestValidateBranchSlug:
    def test_valid_simple_slug(self):
        assert validate_branch_slug("refactor-foobar", "mm") == \
               "mm/refactor-foobar"

    def test_valid_slug_with_path(self):
        assert validate_branch_slug("refactor/foobar", "mm") == \
               "mm/refactor/foobar"

    def test_valid_slug_with_deep_path(self):
        assert validate_branch_slug("feature/auth/add-oauth", "mm") == \
               "mm/feature/auth/add-oauth"

    def test_valid_single_word(self):
        assert validate_branch_slug("fix", "mm") == "mm/fix"

    def test_valid_numbers_in_slug(self):
        assert validate_branch_slug("fix-issue-42", "mm") == \
               "mm/fix-issue-42"

    def test_valid_custom_prefix(self):
        assert validate_branch_slug("refactor/foo", "bot") == \
               "bot/refactor/foo"

    def test_rejects_empty_slug(self):
        with pytest.raises(ValueError, match="empty"):
            validate_branch_slug("", "mm")

    def test_rejects_slug_too_long(self):
        long_slug = "a" * 51
        with pytest.raises(ValueError, match="50"):
            validate_branch_slug(long_slug, "mm")

    def test_slug_at_max_length_accepted(self):
        slug = "a" * 50
        assert validate_branch_slug(slug, "mm") == f"mm/{slug}"

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_branch_slug("Refactor-Foobar", "mm")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_branch_slug("refactor foobar", "mm")

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError, match="invalid characters"):
            validate_branch_slug("refactor@foobar", "mm")

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError, match="slash"):
            validate_branch_slug("/refactor/foobar", "mm")

    def test_rejects_trailing_slash(self):
        with pytest.raises(ValueError, match="slash"):
            validate_branch_slug("refactor/foobar/", "mm")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="hyphen"):
            validate_branch_slug("-refactor-foobar", "mm")

    def test_rejects_trailing_hyphen(self):
        with pytest.raises(ValueError, match="hyphen"):
            validate_branch_slug("refactor-foobar-", "mm")

    def test_rejects_consecutive_slashes(self):
        with pytest.raises(ValueError, match="consecutive slashes"):
            validate_branch_slug("refactor//foobar", "mm")

    def test_rejects_consecutive_hyphens(self):
        with pytest.raises(ValueError, match="consecutive hyphens"):
            validate_branch_slug("refactor--foobar", "mm")

    def test_rejects_segment_starting_with_hyphen(self):
        with pytest.raises(ValueError, match="hyphen"):
            validate_branch_slug("refactor/-foobar", "mm")

    def test_rejects_segment_ending_with_hyphen(self):
        with pytest.raises(ValueError, match="hyphen"):
            validate_branch_slug("refactor/foobar-", "mm")

    def test_full_branch_name_not_subject_to_length_limit(self):
        # The 50-char limit applies to the slug only, not the full branch name
        # including prefix. A 50-char slug with a 2-char prefix gives 53 chars.
        slug = "a" * 50
        full = validate_branch_slug(slug, "mm")
        assert len(full) == 53  # "mm/" + 50 chars

    def test_single_char_segment_valid(self):
        assert validate_branch_slug("a/b/c", "mm") == "mm/a/b/c"

    def test_digits_only_segment_valid(self):
        assert validate_branch_slug("fix/42", "mm") == "mm/fix/42"