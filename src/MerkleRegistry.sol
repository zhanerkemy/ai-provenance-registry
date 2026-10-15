// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title MerkleRegistry
/// @notice Design 3 of 3: register many models with ONE transaction. The records are
///         hashed into a Merkle tree off-chain (src/merkle_tree.py) and only the tree's
///         32-byte root goes on-chain. Anyone holding a record and its "proof" (the
///         sibling hashes on the path to the root) can later show that the record was
///         part of the batch, without the other records.
/// @dev    Records point to their parent by the parent's weights hash, because models
///         in a batch get no on-chain IDs.
///
///         What this design gives up, compared with ModelRegistry (storage):
///           * no duplicate or parent-existence checks at registration time
///           * verification needs the proof, which must be kept off-chain
///           * ownership is per batch (the submitter), not per model
///         What it gains: cost per model falls roughly as 1 / batch size.
contract MerkleRegistry {
    struct Batch {
        address submitter; // 20 bytes  } these three share one 32-byte storage slot,
        uint64 anchoredAt; //  8 bytes  } which is why the order matters for gas
        uint32 size; //  4 bytes  }
        bytes32 root; // second slot
    }

    /// @notice Number of batches anchored so far (also the ID of the newest batch).
    uint256 public batchCount;

    mapping(uint256 => Batch) private _batches;

    event BatchAnchored(uint256 indexed batchId, address indexed submitter, bytes32 root, uint32 size, string uri);

    error ZeroRoot();
    error EmptyBatch();
    error BatchDoesNotExist(uint256 batchId);

    /// @notice Anchor the Merkle root of `size` model records.
    /// @param uri Where the full batch (records and proofs) is published off-chain.
    function anchorBatch(bytes32 root, uint32 size, string calldata uri) external returns (uint256 batchId) {
        if (root == bytes32(0)) revert ZeroRoot();
        if (size == 0) revert EmptyBatch();

        batchId = ++batchCount;
        _batches[batchId] = Batch({submitter: msg.sender, anchoredAt: uint64(block.timestamp), size: size, root: root});
        emit BatchAnchored(batchId, msg.sender, root, size, uri);
    }

    function getBatch(uint256 batchId) external view returns (Batch memory) {
        if (batchId == 0 || batchId > batchCount) revert BatchDoesNotExist(batchId);
        return _batches[batchId];
    }

    /// @notice The leaf of one model record. Must match leaf_hash() in src/merkle_tree.py.
    /// @dev    Hashed twice ("double hashing") so that a leaf can never be confused with
    ///         an inner node of the tree, a known attack on single-hashed Merkle trees.
    function leafHash(bytes32 weightsHash, bytes32 dataHash, bytes32 parentWeightsHash, bytes32 uriHash)
        public
        pure
        returns (bytes32)
    {
        return keccak256(bytes.concat(keccak256(abi.encode(weightsHash, dataHash, parentWeightsHash, uriHash))));
    }

    /// @notice The audit check: was this exact record part of batch `batchId`?
    /// @param proof Sibling hashes from the leaf up to the root (from src/merkle_tree.py).
    function verifyRecord(
        uint256 batchId,
        bytes32 weightsHash,
        bytes32 dataHash,
        bytes32 parentWeightsHash,
        string calldata uri,
        bytes32[] calldata proof
    ) external view returns (bool) {
        if (batchId == 0 || batchId > batchCount) revert BatchDoesNotExist(batchId);

        bytes32 node = leafHash(weightsHash, dataHash, parentWeightsHash, keccak256(bytes(uri)));
        for (uint256 i = 0; i < proof.length; i++) {
            node = _hashPair(node, proof[i]);
        }
        return node == _batches[batchId].root;
    }

    /// @dev Sorting the pair means a proof does not need to say "left" or "right".
    function _hashPair(bytes32 a, bytes32 b) private pure returns (bytes32) {
        return a < b ? keccak256(abi.encode(a, b)) : keccak256(abi.encode(b, a));
    }
}