// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {EventRegistry} from "../src/EventRegistry.sol";
import {Test} from "forge-std/Test.sol";

/// @notice Tests for the event-only design. Run with:  forge test --match-contract EventRegistry -vv
contract EventRegistryTest is Test {
    EventRegistry internal registry;

    address internal alice = makeAddr("alice");
    address internal bob = makeAddr("bob");

    bytes32 internal constant BASE_WEIGHTS = keccak256("base-model-weights");
    bytes32 internal constant FT_WEIGHTS = keccak256("finetuned-weights");
    bytes32 internal constant DATA = keccak256("training-data");

    event ModelRegistered(
        uint256 indexed id,
        address indexed owner,
        uint256 indexed parentId,
        bytes32 weightsHash,
        bytes32 dataHash,
        string uri
    );

    function setUp() public {
        registry = new EventRegistry();
    }

    function test_Register_EmitsFullRecord() public {
        vm.expectEmit(true, true, true, true);
        emit ModelRegistered(1, alice, 0, BASE_WEIGHTS, DATA, "hf://alice/base");

        vm.prank(alice);
        uint256 id = registry.registerModel(BASE_WEIGHTS, DATA, 0, "hf://alice/base");
        assertEq(id, 1);
        assertEq(registry.modelCount(), 1);
    }

    function test_DerivedModel_ByAnotherAccount() public {
        vm.prank(alice);
        uint256 base = registry.registerModel(BASE_WEIGHTS, DATA, 0, "hf://alice/base");

        vm.expectEmit(true, true, true, true);
        emit ModelRegistered(2, bob, base, FT_WEIGHTS, bytes32(0), "hf://bob/ft");

        vm.prank(bob);
        registry.registerModel(FT_WEIGHTS, bytes32(0), base, "hf://bob/ft");
    }

    /// The record can be rebuilt from the transaction log alone; this is how an
    /// off-chain auditor reads this design.
    function test_RecordCanBeReadBackFromLogs() public {
        vm.recordLogs();
        vm.prank(alice);
        registry.registerModel(BASE_WEIGHTS, DATA, 0, "hf://alice/base");

        Vm.Log[] memory logs = vm.getRecordedLogs();
        assertEq(logs.length, 1);
        assertEq(logs[0].emitter, address(registry));
        assertEq(uint256(logs[0].topics[1]), 1); // id
        assertEq(address(uint160(uint256(logs[0].topics[2]))), alice); // owner
        assertEq(uint256(logs[0].topics[3]), 0); // parentId

        (bytes32 weights, bytes32 data, string memory uri) = abi.decode(logs[0].data, (bytes32, bytes32, string));
        assertEq(weights, BASE_WEIGHTS);
        assertEq(data, DATA);
        assertEq(uri, "hf://alice/base");
    }

    function test_RevertWhen_WeightsHashIsZero() public {
        vm.expectRevert(EventRegistry.ZeroWeightsHash.selector);
        registry.registerModel(bytes32(0), DATA, 0, "");
    }

    function test_RevertWhen_ParentDoesNotExist() public {
        vm.expectRevert(abi.encodeWithSelector(EventRegistry.ModelDoesNotExist.selector, 1));
        registry.registerModel(FT_WEIGHTS, DATA, 1, "");
    }

    /// Documents a guarantee this design gives up: duplicates are NOT rejected.
    function test_SameWeightsCanBeRegisteredTwice() public {
        registry.registerModel(BASE_WEIGHTS, DATA, 0, "hf://alice/base");
        vm.prank(bob);
        uint256 second = registry.registerModel(BASE_WEIGHTS, DATA, 0, "hf://bob/copy");
        assertEq(second, 2);
    }
}
