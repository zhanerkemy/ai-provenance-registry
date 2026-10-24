// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// The parts of our registries that another contract would call to check a record.
interface IModelRegistry {
    function verifyWeights(uint256 id, bytes32 weightsHash) external view returns (bool);
    function getLineage(uint256 id) external view returns (uint256[] memory);
}

interface IMerkleRegistry {
    function verifyRecord(
        uint256 batchId,
        bytes32 weightsHash,
        bytes32 dataHash,
        bytes32 parentWeightsHash,
        string calldata uri,
        bytes32[] calldata proof
    ) external view returns (bool);
}

/// @title VerifyProbe
/// @notice Measures how much gas a verification costs when ANOTHER CONTRACT does it,
///         for example a marketplace that only lists registered models.
/// @dev    `estimate_gas` on a direct call prices it as a whole transaction: it adds the
///         21,000 base cost of every transaction and the cost of the call data. A contract
///         that checks a record inside its own logic pays neither. Here we read gasleft()
///         just before and just after the call; the difference is what the check itself
///         costs, including the CALL to the registry (2,600 gas the first time an address
///         is touched in a transaction) and the cold storage reads (2,100 gas per slot).
///
///         The functions are `view`, so Python calls them with eth_call: no transaction,
///         no ETH, and every call starts "cold", like the first check in a transaction.
///         Event-only registration has no probe: its records are in logs, and the EVM
///         gives contracts no way to read logs.
contract VerifyProbe {
    /// @notice Storage design: does model `id` have these weights?
    function probeVerifyWeights(IModelRegistry registry, uint256 id, bytes32 weightsHash)
        external
        view
        returns (bool ok, uint256 gasUsed)
    {
        uint256 before = gasleft();
        ok = registry.verifyWeights(id, weightsHash);
        gasUsed = before - gasleft();
    }

    /// @notice Storage design: read the whole lineage of model `id` (id, parent, ..., base).
    function probeLineage(IModelRegistry registry, uint256 id)
        external
        view
        returns (uint256 length, uint256 gasUsed)
    {
        uint256 before = gasleft();
        uint256[] memory lineage = registry.getLineage(id);
        gasUsed = before - gasleft();
        length = lineage.length;
    }

    /// @notice Merkle design: is this record in batch `batchId`, given its proof?
    function probeVerifyRecord(
        IMerkleRegistry registry,
        uint256 batchId,
        bytes32 weightsHash,
        bytes32 dataHash,
        bytes32 parentWeightsHash,
        string calldata uri,
        bytes32[] calldata proof
    ) external view returns (bool ok, uint256 gasUsed) {
        uint256 before = gasleft();
        ok = registry.verifyRecord(batchId, weightsHash, dataHash, parentWeightsHash, uri, proof);
        gasUsed = before - gasleft();
    }
}