"""Merkle trees for batch registration, matching src/MerkleRegistry.sol exactly.

A Merkle tree turns many records into one 32-byte "root":
  * each record becomes a leaf hash
  * neighbouring hashes are paired and hashed, level by level, until one is left
Only the root goes on-chain. To prove that one record was in the batch you give the
record plus its "proof": the sibling hash at each level on the way to the root.
The proof has about log2(batch size) hashes, so it stays short even for big batches.

Rules (the Solidity contract uses the same ones, or verification fails):
  * hash function: keccak256, Ethereum's hash (not SHA-256)
  * leaf = keccak256(keccak256(weights || data || parentWeights || keccak256(uri)))
    where || joins the four 32-byte values (this equals Solidity's abi.encode of
    four bytes32 values). Hashing twice keeps leaves distinct from inner nodes.
  * a pair is hashed smaller-first, so proofs need no left/right flags
  * an odd node at the end of a level moves up unchanged

Usage as a library:
    tree = MerkleTree([leaf_hash(w, d, p, uri) for ...])
    tree.root            # bytes, 32 long -> MerkleRegistry.anchorBatch(root, ...)
    tree.proof(i)        # list of bytes   -> MerkleRegistry.verifyRecord(..., proof)
"""

from __future__ import annotations

from Crypto.Hash import keccak  # from the pycryptodome package

ZERO32 = bytes(32)


def keccak256(data: bytes) -> bytes:
    return keccak.new(digest_bits=256, data=data).digest()


def to_bytes32(value: str) -> bytes:
    """'0x' + 64 hex characters -> 32 bytes. An empty string means 'not given' -> zeros."""
    if not value:
        return ZERO32
    raw = bytes.fromhex(value.removeprefix("0x"))
    if len(raw) != 32:
        raise ValueError(f"expected 32 bytes, got {len(raw)}: {value}")
    return raw


def leaf_hash(weights: bytes, data: bytes, parent_weights: bytes, uri: str) -> bytes:
    """Leaf for one model record; equals MerkleRegistry.leafHash(...) in Solidity."""
    for name, v in (("weights", weights), ("data", data), ("parent_weights", parent_weights)):
        if len(v) != 32:
            raise ValueError(f"{name} must be 32 bytes")
    inner = keccak256(weights + data + parent_weights + keccak256(uri.encode("utf-8")))
    return keccak256(inner)


def hash_pair(a: bytes, b: bytes) -> bytes:
    """Hash two nodes, smaller first. Comparing 32-byte strings compares them as numbers."""
    return keccak256(a + b) if a < b else keccak256(b + a)


class MerkleTree:
    def __init__(self, leaves: list[bytes]):
        if not leaves:
            raise ValueError("a Merkle tree needs at least one leaf")
        self.levels: list[list[bytes]] = [list(leaves)]
        while len(self.levels[-1]) > 1:
            level = self.levels[-1]
            parent = [hash_pair(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
            if len(level) % 2 == 1:  # odd one out moves up unchanged
                parent.append(level[-1])
            self.levels.append(parent)

    @property
    def root(self) -> bytes:
        return self.levels[-1][0]

    def proof(self, index: int) -> list[bytes]:
        """Sibling hashes from leaf `index` up to the root."""
        if not 0 <= index < len(self.levels[0]):
            raise IndexError(index)
        proof = []
        for level in self.levels[:-1]:
            sibling = index ^ 1  # the other member of the pair: 4<->5, 7<->6
            if sibling < len(level):  # no sibling = this node was carried up
                proof.append(level[sibling])
            index //= 2
        return proof


def verify(leaf: bytes, proof: list[bytes], root: bytes) -> bool:
    """Same computation as MerkleRegistry.verifyRecord, in Python."""
    node = leaf
    for sibling in proof:
        node = hash_pair(node, sibling)
    return node == root
