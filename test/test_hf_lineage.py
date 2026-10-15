"""Tests for src/hf_lineage.py. They use a fake Hub, so no internet is needed.

Run from the repository root:  python -m pytest test/test_hf_lineage.py -v
"""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hash_file import hash_directory  # noqa: E402
from hf_lineage import (  # noqa: E402
    ModelMeta,
    Node,
    data_ref_hash,
    plan_registrations,
    read_tree_csv,
    walk_tree,
    write_tree_csv,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FakeHub:
    """Stands in for huggingface.co. `tree` maps (parent, relation) -> child ids."""

    def __init__(self, metas: dict[str, ModelMeta], tree: dict[tuple[str, str], list[str]]):
        self.metas = metas
        self.tree = tree

    def children(self, model_id, relation):
        return list(self.tree.get((model_id, relation), []))

    def meta(self, model_id):
        if model_id not in self.metas:
            raise PermissionError("private or deleted")
        return self.metas[model_id]


def meta(model_id, weights=("model.safetensors",), datasets=(), parents=()):
    """A model page whose weight files have hashes derived from the model id."""
    files = [(f, sha(model_id + f)) for f in weights] + [("tokenizer.json", sha("tok"))]
    return ModelMeta(model_id, "rev-" + model_id, "2026-01-01T00:00:00", files,
                     list(datasets), list(parents))


@pytest.fixture
def small_family():
    """base -> ft1 -> ft1-q (quantized), base -> ft2 (adapter)."""
    metas = {m: meta(m) for m in ["org/base", "a/ft1", "b/ft2", "c/ft1-q"]}
    tree = {
        ("org/base", "finetune"): ["a/ft1"],
        ("org/base", "adapter"): ["b/ft2"],
        ("a/ft1", "quantized"): ["c/ft1-q"],
    }
    return FakeHub(metas, tree)


def test_parents_always_come_before_children(small_family):
    nodes, info = walk_tree(small_family, "org/base")
    order = [n.model_id for n in nodes]
    assert order == ["org/base", "a/ft1", "b/ft2", "c/ft1-q"]
    for n in nodes[1:]:
        assert order.index(n.parent_id) < order.index(n.model_id)
    assert info["truncated"] is False


def test_depth_relation_and_uri(small_family):
    nodes = {n.model_id: n for n in walk_tree(small_family, "org/base")[0]}
    assert (nodes["org/base"].depth, nodes["org/base"].relation) == (0, "base")
    assert (nodes["c/ft1-q"].depth, nodes["c/ft1-q"].relation) == (2, "quantized")
    assert nodes["a/ft1"].uri == "hf://a/ft1@rev-a/ft1"


def test_hub_weights_hash_equals_local_weights_only_hash(tmp_path):
    """Key check: hashing from Hub metadata == hashing the downloaded files locally."""
    folder = tmp_path / "model"
    (folder / "shards").mkdir(parents=True)
    contents = {
        "shards/model-00001.safetensors": b"first shard",
        "shards/model-00002.safetensors": b"second shard",
        "config.json": b"{}",  # not a weight file: must be ignored
    }
    for rel, data in contents.items():
        (folder / rel).write_bytes(data)

    hub_files = [(rel, hashlib.sha256(data).hexdigest()) for rel, data in contents.items()]
    hub = FakeHub({"x/m": ModelMeta("x/m", "r", "", hub_files, [], [])}, {})
    node = walk_tree(hub, "x/m")[0][0]

    assert node.weights_hash == "0x" + hash_directory(folder, weights_only=True)
    assert node.n_weight_files == 2


def test_merge_and_multi_parent_are_flagged():
    metas = {"base": meta("base"), "m/merged": meta("m/merged"),
             "m/two": meta("m/two", parents=["base", "other"])}
    hub = FakeHub(metas, {("base", "merge"): ["m/merged"], ("base", "finetune"): ["m/two"]})
    status = {n.model_id: n.status for n in walk_tree(hub, "base")[0]}
    assert status == {"base": "ok", "m/two": "multi_parent", "m/merged": "multi_parent"}


def test_model_without_weight_files_and_unreadable_model():
    metas = {"base": meta("base"), "no/weights": meta("no/weights", weights=())}
    hub = FakeHub(metas, {("base", "finetune"): ["no/weights", "gone/private"]})
    status = {n.model_id: n.status for n in walk_tree(hub, "base")[0]}
    assert status["no/weights"] == "no_weight_files"
    assert status["gone/private"] == "error"


def test_child_listed_under_two_parents_appears_once(small_family):
    small_family.tree[("b/ft2", "finetune")] = ["a/ft1"]  # a/ft1 also claims b/ft2
    nodes, info = walk_tree(small_family, "org/base")
    assert [n.model_id for n in nodes].count("a/ft1") == 1
    assert info["children_reached_twice"] == 1


def test_max_models_and_max_depth(small_family):
    nodes, info = walk_tree(small_family, "org/base", max_models=2)
    assert len(nodes) == 2 and info["truncated"] is True

    nodes, _ = walk_tree(small_family, "org/base", max_depth=1)
    assert max(n.depth for n in nodes) == 1


def test_data_ref_hash_ignores_order_and_duplicates():
    assert data_ref_hash(["b", "a", "a"]) == data_ref_hash(["a", "b"])
    assert data_ref_hash(["a"]) != data_ref_hash(["b"])


def test_csv_round_trip(small_family, tmp_path):
    nodes, _ = walk_tree(small_family, "org/base")
    path = tmp_path / "tree.csv"
    write_tree_csv(nodes, path)
    assert read_tree_csv(path) == nodes


# --------------------------------------------------------------------------- plan_registrations


def node(model_id, parent="", status="ok", weights=None):
    w = weights if weights is not None else "0x" + sha(model_id)
    return Node(model_id, parent, "finetune" if parent else "base", 0, "", "", w, "", 1, "",
                1, status, "hf://" + model_id)


def test_plan_skips_children_of_unregistrable_models():
    nodes = [node("base"), node("bad", "base", status="multi_parent"), node("kid", "bad")]
    plan, excluded = plan_registrations(nodes)
    assert [n.model_id for n, _ in plan] == ["base"]
    assert excluded == {"bad": "multi_parent", "kid": "ancestor_not_registered"}


def test_plan_attaches_children_of_reuploads_to_the_first_copy():
    nodes = [node("base"), node("copy", "base", weights=node("base").weights_hash),
             node("kid", "copy")]
    plan, excluded = plan_registrations(nodes)
    assert [(n.model_id, parent) for n, parent in plan] == [("base", ""), ("kid", "base")]
    assert excluded == {"copy": "duplicate_weights"}


def test_real_hub_adapter_reads_library_objects(monkeypatch):
    """HfHub.meta must read the huggingface_hub ModelInfo object correctly (no network)."""
    pytest.importorskip("huggingface_hub")
    from hf_lineage import HfHub

    from huggingface_hub.hf_api import ModelInfo

    info = ModelInfo(**{
        "id": "a/ft1",
        "sha": "abc123",
        "createdAt": "2025-03-01T10:00:00.000Z",
        "siblings": [
            {"rfilename": "config.json"},
            {"rfilename": "model.safetensors",
             "lfs": {"sha256": "f" * 64, "size": 10, "pointerSize": 130}},
        ],
        "cardData": {"base_model": "org/base", "datasets": ["d/one", "d/two"]},
    })
    hub = HfHub(pause=0)
    monkeypatch.setattr(hub.api, "model_info", lambda *a, **k: info)

    m = hub.meta("a/ft1")
    assert m.revision == "abc123"
    assert m.lfs_files == [("model.safetensors", "f" * 64)]
    assert m.declared_parents == ["org/base"]
    assert m.datasets == ["d/one", "d/two"]
    assert m.created_at.startswith("2025-03-01")
