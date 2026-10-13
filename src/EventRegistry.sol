// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title EventRegistry
/// @notice Design 2 of 3: the cheapest way to record a model. Nothing about the model
///         is kept in contract storage; the record lives only in the transaction's
///         event log, which every Ethereum node keeps and off-chain tools can read.
/// @dev    Same function signature as ModelRegistry.registerModel, so the replay script
///         can register a real tree under both designs and compare gas fairly.
///
///         What this design gives up, compared with ModelRegistry (storage):
///           * no duplicate check: the same weights can be registered many times
///           * no on-chain reads: another contract cannot look up or verify a model
///           * no ownership transfer: there is no stored owner to change
///         What it keeps: an immutable, timestamped, signed record that a model with
///         these hashes and this parent was claimed by this address.
contract EventRegistry {
    /// @notice Number of models registered so far (also the ID of the newest model).
    uint256 public modelCount;

    event ModelRegistered(
        uint256 indexed id,
        address indexed owner,
        uint256 indexed parentId,
        bytes32 weightsHash,
        bytes32 dataHash,
        string uri
    );

    error ZeroWeightsHash();
    error ModelDoesNotExist(uint256 id);

    /// @notice Record a model in the event log. parentId = 0 means "base model".
    /// @dev    The parent check still works without storing records, because IDs are
    ///         handed out in order: every ID from 1 to modelCount has been registered.
    function registerModel(bytes32 weightsHash, bytes32 dataHash, uint256 parentId, string calldata uri)
        external
        returns (uint256 id)
    {
        if (weightsHash == bytes32(0)) revert ZeroWeightsHash();
        if (parentId > modelCount) revert ModelDoesNotExist(parentId);

        id = ++modelCount;
        emit ModelRegistered(id, msg.sender, parentId, weightsHash, dataHash, uri);
    }
}