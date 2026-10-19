// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ModelRegistry
/// @notice Records AI models on-chain: who registered them, fingerprints (hashes) of
///         their weights and training data, and which earlier model each one was
///         derived from. Following the parent links gives a model's lineage.
/// @dev    Only 32-byte hashes and a short URI are stored. The model files themselves
///         stay off-chain (e.g. on Hugging Face). Model IDs start at 1; parentId = 0
///         means "no parent" (a base model trained from scratch).
contract ModelRegistry {
    struct Model {
        address owner; // account that registered (or now owns) the model
        uint64 registeredAt; // block timestamp of registration (seconds since 1970)
        bytes32 weightsHash; // SHA-256 of the model weights; must not be zero
        bytes32 dataHash; // SHA-256 of the training data; zero = not disclosed
        uint256 parentId; // model this one was derived from; 0 = base model
        string uri; // where the files live, e.g. "hf://org/model@revision"
    }

    /// @notice Number of models registered so far (also the ID of the newest model).
    uint256 public modelCount;

    mapping(uint256 => Model) private _models;

    /// @notice Looks up a model ID from its weights hash (0 if never registered).
    mapping(bytes32 => uint256) public idByWeightsHash;

    event ModelRegistered(
        uint256 indexed id,
        address indexed owner,
        uint256 indexed parentId,
        bytes32 weightsHash,
        bytes32 dataHash,
        string uri
    );

    event OwnershipTransferred(uint256 indexed id, address indexed previousOwner, address indexed newOwner);

    error ZeroWeightsHash();
    error AlreadyRegistered(uint256 existingId);
    error ModelDoesNotExist(uint256 id);
    error NotOwner(uint256 id, address caller);
    error ZeroAddress();

    /// @notice Register a model. Anyone may register a model derived from any existing
    ///         model, because fine-tuning someone else's public model is normal practice.
    /// @param weightsHash SHA-256 of the weights (from src/hash_file.py).
    /// @param dataHash    SHA-256 of the training data, or bytes32(0) if not disclosed.
    /// @param parentId    ID of the model this was derived from, or 0 for a base model.
    /// @param uri         Pointer to where the model files are stored.
    /// @return id         The new model's ID.
    function registerModel(bytes32 weightsHash, bytes32 dataHash, uint256 parentId, string calldata uri)
        external
        returns (uint256 id)
    {
        if (weightsHash == bytes32(0)) revert ZeroWeightsHash();

        // The same weights can be registered only once. The first registration wins,
        // so a later copy-and-reregister cannot claim an earlier timestamp.
        uint256 existing = idByWeightsHash[weightsHash];
        if (existing != 0) revert AlreadyRegistered(existing);

        // A parent must already be registered, so every lineage ends at a real base model.
        if (parentId != 0 && !exists(parentId)) revert ModelDoesNotExist(parentId);

        id = ++modelCount;
        _models[id] = Model({
            owner: msg.sender,
            registeredAt: uint64(block.timestamp),
            weightsHash: weightsHash,
            dataHash: dataHash,
            parentId: parentId,
            uri: uri
        });
        idByWeightsHash[weightsHash] = id;

        emit ModelRegistered(id, msg.sender, parentId, weightsHash, dataHash, uri);
    }

    /// @notice Hand a model's record over to another account. Only the current owner can.
    function transferOwnership(uint256 id, address newOwner) external {
        if (!exists(id)) revert ModelDoesNotExist(id);
        if (newOwner == address(0)) revert ZeroAddress();

        address previousOwner = _models[id].owner;
        if (msg.sender != previousOwner) revert NotOwner(id, msg.sender);

        _models[id].owner = newOwner;
        emit OwnershipTransferred(id, previousOwner, newOwner);
    }

    /// @notice True if a model with this ID has been registered.
    function exists(uint256 id) public view returns (bool) {
        return id != 0 && id <= modelCount;
    }

    /// @notice Full record of one model.
    function getModel(uint256 id) external view returns (Model memory) {
        if (!exists(id)) revert ModelDoesNotExist(id);
        return _models[id];
    }

    /// @notice The audit check: does a downloaded file's hash match what was registered?
    function verifyWeights(uint256 id, bytes32 weightsHash) external view returns (bool) {
        if (!exists(id)) revert ModelDoesNotExist(id);
        return _models[id].weightsHash == weightsHash;
    }

    /// @notice Lineage from a model back to its base model: [id, parent, grandparent, ...].
    /// @dev    A view function, so reading it off-chain costs nothing. Its cost grows with
    ///         the depth of the tree, which is one of the things we measure.
    function getLineage(uint256 id) external view returns (uint256[] memory lineage) {
        if (!exists(id)) revert ModelDoesNotExist(id);

        // First pass: count the generations.
        uint256 depth = 0;
        for (uint256 cur = id; cur != 0; cur = _models[cur].parentId) {
            depth++;
        }

        // Second pass: fill the array.
        lineage = new uint256[](depth);
        uint256 i = 0;
        for (uint256 cur = id; cur != 0; cur = _models[cur].parentId) {
            lineage[i++] = cur;
        }
    }
}