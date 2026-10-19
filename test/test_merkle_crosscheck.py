"""Cross-check: trees and proofs built in Python must verify in the Solidity contract.

If Python and Solidity disagreed on even one byte (hash function, field order, how
pairs are sorted, what happens to an odd node) every proof would fail, so this test
guards the whole Merkle design. It needs Anvil and `forge build`; otherwise it skips.

Run from the repository root:  python -m pytest test/test_merkle_crosscheck.py -v
"""

import random

import pytest

from chain import deploy, send
from merkle_tree import ZERO32, MerkleTree, keccak256, leaf_hash


def random_records(n, seed):
    rng = random.Random(seed)  # fixed seed: the same "random" records every run
    records = []
    for i in range(n):
        weights = rng.randbytes(32)
        data = rng.choice([ZERO32, rng.randbytes(32)])
        parent = ZERO32 if i == 0 else records[rng.randrange(i)][0]
        records.append((weights, data, parent, f"hf://user{i}/model@{rng.randbytes(20).hex()}"))
    return records


@pytest.fixture(scope="module")
def registry(w3):
    contract, _ = deploy(w3, "MerkleRegistry")
    return contract


def test_leaf_hash_matches_solidity(registry):
    for weights, data, parent, uri in random_records(10, seed=1):
        on_chain = registry.functions.leafHash(weights, data, parent,
                                               keccak256(uri.encode())).call()
        assert bytes(on_chain) == leaf_hash(weights, data, parent, uri)


@pytest.mark.parametrize("n", [1, 2, 3, 5, 8, 13, 32])
def test_every_python_proof_verifies_on_chain(w3, registry, n):
    records = random_records(n, seed=n)
    tree = MerkleTree([leaf_hash(*r) for r in records])
    send(w3, registry.functions.anchorBatch(tree.root, n, f"crosscheck-{n}"))
    batch_id = registry.functions.batchCount().call()

    for i, record in enumerate(records):
        assert registry.functions.verifyRecord(batch_id, *record, tree.proof(i)).call()


def test_tampered_uri_fails_on_chain(w3, registry):
    records = random_records(4, seed=99)
    tree = MerkleTree([leaf_hash(*r) for r in records])
    send(w3, registry.functions.anchorBatch(tree.root, 4, "crosscheck-tamper"))
    batch_id = registry.functions.batchCount().call()

    weights, data, parent, _ = records[2]
    assert not registry.functions.verifyRecord(
        batch_id, weights, data, parent, "hf://attacker/model", tree.proof(2)).call()