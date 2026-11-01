"""Offline tests for src/tree_stats.py on a small hand-made tree.

The tree (status in brackets):

    base [ok]
    ├── merge [multi_parent]
    │   ├── m_child [ok]           blocked by merge
    │   │   └── m_grandchild [ok]  blocked by merge (two levels down)
    │   └── m_quant [ok]           blocked by merge
    ├── empty [no_weight_files]
    │   └── e_child [ok]           blocked by empty
    └── ft [ok]
        └── ft_copy [ok]           same weights as ft -> duplicate_weights
            └── copy_child [ok]    registrable: attaches to ft, so nothing blocks it
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hf_lineage import Node, plan_registrations  # noqa: E402
from tree_stats import ancestor_root_causes, blocking_ancestor, tree_stats  # noqa: E402


def node(model_id, parent_id, depth, status="ok", weights=None):
    weights = weights or "0x" + hashlib.sha256(model_id.encode()).hexdigest()
    return Node(
        model_id=model_id, parent_id=parent_id, relation="base" if not parent_id else "finetune",
        depth=depth, revision="r", created_at="", weights_hash=weights, data_ref_hash="",
        n_weight_files=1, datasets="", n_declared_parents=1, status=status,
        uri=f"hf://{model_id}@r",
    )


SAME = "0x" + "ab" * 32

NODES = [
    node("base", "", 0),
    node("merge", "base", 1, status="multi_parent"),
    node("empty", "base", 1, status="no_weight_files"),
    node("ft", "base", 1, weights=SAME),
    node("m_child", "merge", 2),
    node("m_quant", "merge", 2),
    node("e_child", "empty", 2),
    node("ft_copy", "ft", 2, weights=SAME),
    node("m_grandchild", "m_child", 3),
    node("copy_child", "ft_copy", 3),
]


def test_blocking_ancestor_finds_the_nearest_real_cause():
    _, excluded = plan_registrations(NODES)
    by_id = {n.model_id: n for n in NODES}
    assert blocking_ancestor("m_child", by_id, excluded) == "merge"
    assert blocking_ancestor("m_grandchild", by_id, excluded) == "merge"  # walks past m_child
    assert blocking_ancestor("e_child", by_id, excluded) == "empty"


def test_duplicates_do_not_block_their_children():
    plan, excluded = plan_registrations(NODES)
    assert excluded["ft_copy"] == "duplicate_weights"
    assert "copy_child" in [n.model_id for n, _ in plan]


def test_root_causes_count_every_blocked_model_once():
    _, excluded = plan_registrations(NODES)
    causes = ancestor_root_causes(NODES, excluded)
    assert causes["by_reason"] == {"multi_parent": 3, "no_weight_files": 1}
    assert causes["top_blocking_models"][0] == {
        "model_id": "merge", "reason": "multi_parent", "descendants_blocked": 3,
    }
    blocked_total = sum(c["descendants_blocked"] for c in causes["top_blocking_models"])
    assert blocked_total == sum(r == "ancestor_not_registered" for r in excluded.values())


def test_tree_stats_includes_root_causes():
    stats = tree_stats(NODES)
    assert stats["n_models"] == 10
    assert stats["excluded_by_reason"]["ancestor_not_registered"] == 4
    assert stats["ancestor_not_registered_root_causes"]["by_reason"]["multi_parent"] == 3
