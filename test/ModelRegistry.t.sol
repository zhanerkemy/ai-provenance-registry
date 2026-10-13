// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {ModelRegistry} from "../src/ModelRegistry.sol";

/// @notice Unit tests for ModelRegistry. Run with:  forge test -vv
///         Gas per function:                       forge test --gas-report
contract ModelRegistryTest is Test {
    ModelRegistry internal registry;

    // Test accounts. makeAddr gives a fixed, labelled address for each name.
    address internal alice = makeAddr("alice"); // trains the base model
    address internal bob = makeAddr("bob"); // fine-tunes Alice's model
    address internal carol = makeAddr("carol"); // receives ownership later

    // Fake fingerprints. In real use these come from src/hash_file.py.
    bytes32 internal constant BASE_WEIGHTS = keccak256("base-model-weights");
    bytes32 internal constant BASE_DATA = keccak256("base-training-data");
    bytes32 internal constant FT_WEIGHTS = keccak256("finetuned-weights");
    bytes32 internal constant FT_DATA = keccak256("finetune-data");

    // Redeclared here so the tests can check that the contract emits them.
    event ModelRegistered(
        uint256 indexed id,
        address indexed owner,
        uint256 indexed parentId,
        bytes32 weightsHash,
        bytes32 dataHash,
        string uri
    );
    event OwnershipTransferred(uint256 indexed id, address indexed previousOwner, address indexed newOwner);

    // Runs before every test: a fresh, empty registry each time.
    function setUp() public {
        registry = new ModelRegistry();
    }

    // Helper: Alice registers a base model, returns its ID (always 1 on a fresh registry).
    function _registerBase() internal returns (uint256) {
        vm.prank(alice); // the next call is sent "from" Alice
        return registry.registerModel(BASE_WEIGHTS, BASE_DATA, 0, "hf://alice/base");
    }

    // ---------------------------------------------------------------- registration

    function test_RegisterBaseModel_StoresAllFields() public {
        vm.warp(1_700_000_000); // set the block time so registeredAt is predictable
        uint256 id = _registerBase();

        assertEq(id, 1);
        assertEq(registry.modelCount(), 1);

        ModelRegistry.Model memory m = registry.getModel(id);
        assertEq(m.owner, alice);
        assertEq(m.registeredAt, 1_700_000_000);
        assertEq(m.weightsHash, BASE_WEIGHTS);
        assertEq(m.dataHash, BASE_DATA);
        assertEq(m.parentId, 0);
        assertEq(m.uri, "hf://alice/base");
        assertEq(registry.idByWeightsHash(BASE_WEIGHTS), id);
    }

    function test_RegisterModel_EmitsEvent() public {
        vm.expectEmit(true, true, true, true);
        emit ModelRegistered(1, alice, 0, BASE_WEIGHTS, BASE_DATA, "hf://alice/base");
        _registerBase();
    }

    function test_DerivedModel_ByAnotherAccount_IsAllowed() public {
        uint256 base = _registerBase();

        vm.prank(bob);
        uint256 ft = registry.registerModel(FT_WEIGHTS, FT_DATA, base, "hf://bob/finetune");

        ModelRegistry.Model memory m = registry.getModel(ft);
        assertEq(m.owner, bob);
        assertEq(m.parentId, base);
    }

    function test_UndisclosedTrainingData_IsAllowed() public {
        vm.prank(alice);
        uint256 id = registry.registerModel(BASE_WEIGHTS, bytes32(0), 0, "hf://alice/base");
        assertEq(registry.getModel(id).dataHash, bytes32(0));
    }

    function test_RevertWhen_WeightsHashIsZero() public {
        vm.expectRevert(ModelRegistry.ZeroWeightsHash.selector);
        registry.registerModel(bytes32(0), BASE_DATA, 0, "");
    }

    function test_RevertWhen_ParentDoesNotExist() public {
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.ModelDoesNotExist.selector, 42));
        registry.registerModel(FT_WEIGHTS, FT_DATA, 42, "");
    }

    function test_RevertWhen_SameWeightsRegisteredTwice() public {
        uint256 first = _registerBase();

        // Bob tries to claim Alice's exact model as his own.
        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.AlreadyRegistered.selector, first));
        registry.registerModel(BASE_WEIGHTS, bytes32(0), 0, "hf://bob/stolen");
    }

    // ---------------------------------------------------------------- ownership

    function test_OwnerCanTransferOwnership() public {
        uint256 id = _registerBase();

        vm.expectEmit(true, true, true, true);
        emit OwnershipTransferred(id, alice, carol);

        vm.prank(alice);
        registry.transferOwnership(id, carol);
        assertEq(registry.getModel(id).owner, carol);
    }

    function test_RevertWhen_NonOwnerTransfers() public {
        uint256 id = _registerBase();

        vm.prank(bob);
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.NotOwner.selector, id, bob));
        registry.transferOwnership(id, bob);
    }

    function test_RevertWhen_TransferToZeroAddress() public {
        uint256 id = _registerBase();

        vm.prank(alice);
        vm.expectRevert(ModelRegistry.ZeroAddress.selector);
        registry.transferOwnership(id, address(0));
    }

    // ---------------------------------------------------------------- audit and lineage

    function test_VerifyWeights_MatchAndMismatch() public {
        uint256 id = _registerBase();
        assertTrue(registry.verifyWeights(id, BASE_WEIGHTS)); // untouched download
        assertFalse(registry.verifyWeights(id, FT_WEIGHTS)); // tampered or different file
    }

    function test_GetLineage_WalksBackToBaseModel() public {
        uint256 base = _registerBase();

        vm.prank(bob);
        uint256 ft1 = registry.registerModel(FT_WEIGHTS, FT_DATA, base, "hf://bob/ft1");

        vm.prank(carol);
        uint256 ft2 = registry.registerModel(keccak256("ft2"), bytes32(0), ft1, "hf://carol/ft2");

        uint256[] memory lineage = registry.getLineage(ft2);
        assertEq(lineage.length, 3);
        assertEq(lineage[0], ft2);
        assertEq(lineage[1], ft1);
        assertEq(lineage[2], base);
    }

    function test_GetLineage_OfBaseModel_IsJustItself() public {
        uint256 base = _registerBase();
        uint256[] memory lineage = registry.getLineage(base);
        assertEq(lineage.length, 1);
        assertEq(lineage[0], base);
    }

    // ---------------------------------------------------------------- fuzz test

    /// Foundry runs this with many random inputs (256 by default).
    function testFuzz_AnyNonZeroHash_CanBeRegisteredAndVerified(bytes32 weights, bytes32 data) public {
        vm.assume(weights != bytes32(0));
        uint256 id = registry.registerModel(weights, data, 0, "");
        assertTrue(registry.verifyWeights(id, weights));
        assertEq(registry.getModel(id).dataHash, data);
    }
}
