"""Tests for src/merkle_tree.py. Run from the repository root:  python -m pytest test/test_merkle_tree.py -v"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from merkle_tree import (  # noqa: E402
    ZERO32,
    MerkleTree,
    hash_pair,
    keccak256,
    leaf_hash,
    to_bytes32,
    verify,
)


def leaves(n):
    return [leaf_hash(keccak256(f"w{i}".encode()), ZERO32, ZERO32, f"hf://m/{i}") for i in range(n)]


def test_keccak_matches_ethereum_reference_values():
    # Well-known values: keccak256("") and keccak256("abc") as Ethereum computes them.
    assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert keccak256(b"abc").hex() == "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"


def test_keccak_is_not_sha256():
    import hashlib

    assert keccak256(b"abc") != hashlib.sha3_256(b"abc").digest()  # different padding


def test_to_bytes32():
    assert to_bytes32("") == ZERO32
    assert to_bytes32("0x" + "ab" * 32) == bytes([0xAB]) * 32
    with pytest.raises(ValueError):
        to_bytes32("0x1234")


def test_hash_pair_order_does_not_matter():
    a, b = keccak256(b"a"), keccak256(b"b")
    assert hash_pair(a, b) == hash_pair(b, a)


def test_single_leaf_tree_root_is_the_leaf():
    (leaf,) = leaves(1)
    tree = MerkleTree([leaf])
    assert tree.root == leaf
    assert tree.proof(0) == []


def test_two_leaf_root_by_hand():
    a, b = leaves(2)
    assert MerkleTree([a, b]).root == hash_pair(a, b)


def test_three_leaves_last_one_is_carried_up():
    a, b, c = leaves(3)
    tree = MerkleTree([a, b, c])
    assert tree.root == hash_pair(hash_pair(a, b), c)
    assert tree.proof(2) == [hash_pair(a, b)]  # one hash shorter than the others


@pytest.mark.parametrize("n", list(range(1, 18)) + [32, 100, 128])
def test_every_leaf_verifies_for_many_tree_sizes(n):
    ls = leaves(n)
    tree = MerkleTree(ls)
    for i, leaf in enumerate(ls):
        proof = tree.proof(i)
        assert verify(leaf, proof, tree.root)
        assert len(proof) <= (n - 1).bit_length()  # about log2(n) hashes


def test_wrong_leaf_or_wrong_proof_fails():
    ls = leaves(8)
    tree = MerkleTree(ls)
    assert not verify(ls[0], tree.proof(1), tree.root)  # proof of a different leaf
    assert not verify(keccak256(b"fake"), tree.proof(0), tree.root)


def test_changing_any_field_changes_the_leaf():
    w, d, p = keccak256(b"w"), keccak256(b"d"), keccak256(b"p")
    base = leaf_hash(w, d, p, "hf://a")
    assert leaf_hash(keccak256(b"x"), d, p, "hf://a") != base
    assert leaf_hash(w, ZERO32, p, "hf://a") != base
    assert leaf_hash(w, d, ZERO32, "hf://a") != base
    assert leaf_hash(w, d, p, "hf://b") != base


def test_empty_tree_and_bad_index_are_errors():
    with pytest.raises(ValueError):
        MerkleTree([])
    with pytest.raises(IndexError):
        MerkleTree(leaves(2)).proof(2)
