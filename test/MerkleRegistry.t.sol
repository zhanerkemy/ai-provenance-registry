// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MerkleRegistry} from "../src/MerkleRegistry.sol";

/// @notice Tests for the Merkle-batch design. Run with:  forge test --match-contract MerkleRegistry -vv
/// @dev    The trees here are built by hand with the same rules as src/merkle_tree.py:
///         pairs are hashed in sorted order, and an odd node at the end of a level is
///         carried up unchanged. test/test_merkle_crosscheck.py checks that the Python
///         and Solidity sides agree on random trees.
contract MerkleRegistryTest is Test {
    MerkleRegistry internal registry;
    address internal alice = makeAddr("alice");

    bytes32 internal constant BASE = keccak256("base-weights");
    bytes32 internal constant DATA = keccak256("data");

    // Four example records: one base model and three children.
    bytes32[4] internal weights = [BASE, keccak256("ft-1"), keccak256("ft-2"), keccak256("ft-3")];
    bytes32[4] internal parents = [bytes32(0), BASE, BASE, keccak256("ft-1")];
    string[4] internal uris = ["hf://org/base@1", "hf://a/ft1@2", "hf://b/ft2@3", "hf://c/ft3@4"];

    event BatchAnchored(uint256 indexed batchId, address indexed submitter, bytes32 root, uint32 size, string uri);

    function setUp() public {
        registry = new MerkleRegistry();
    }

    // ---------------------------------------------------------------- helpers

    function _leaf(uint256 i) internal view returns (bytes32) {
        return registry.leafHash(weights[i], DATA, parents[i], keccak256(bytes(uris[i])));
    }

    function _pair(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return a < b ? keccak256(abi.encode(a, b)) : keccak256(abi.encode(b, a));
    }

    function _verify(uint256 batchId, uint256 i, bytes32[] memory proof) internal view returns (bool) {
        return registry.verifyRecord(batchId, weights[i], DATA, parents[i], uris[i], proof);
    }

    function _proof1(bytes32 a) internal pure returns (bytes32[] memory p) {
        p = new bytes32[](1);
        p[0] = a;
    }

    function _proof2(bytes32 a, bytes32 b) internal pure returns (bytes32[] memory p) {
        p = new bytes32[](2);
        (p[0], p[1]) = (a, b);
    }

    // ---------------------------------------------------------------- anchoring

    function test_AnchorBatch_StoresAndEmits() public {
        vm.warp(1_700_000_000);
        bytes32 root = keccak256("some root");

        vm.expectEmit(true, true, true, true);
        emit BatchAnchored(1, alice, root, 4, "ipfs://batch-1");

        vm.prank(alice);
        uint256 id = registry.anchorBatch(root, 4, "ipfs://batch-1");

        MerkleRegistry.Batch memory b = registry.getBatch(id);
        assertEq(id, 1);
        assertEq(b.submitter, alice);
        assertEq(b.anchoredAt, 1_700_000_000);
        assertEq(b.size, 4);
        assertEq(b.root, root);
    }

    function test_RevertWhen_RootIsZero() public {
        vm.expectRevert(MerkleRegistry.ZeroRoot.selector);
        registry.anchorBatch(bytes32(0), 1, "");
    }

    function test_RevertWhen_BatchIsEmpty() public {
        vm.expectRevert(MerkleRegistry.EmptyBatch.selector);
        registry.anchorBatch(keccak256("r"), 0, "");
    }

    function test_RevertWhen_BatchDoesNotExist() public {
        vm.expectRevert(abi.encodeWithSelector(MerkleRegistry.BatchDoesNotExist.selector, 7));
        registry.verifyRecord(7, BASE, DATA, bytes32(0), "", new bytes32[](0));
    }

    // ---------------------------------------------------------------- verification

    function test_SingleRecordBatch_HasEmptyProof() public {
        uint256 id = registry.anchorBatch(_leaf(0), 1, "");
        assertTrue(_verify(id, 0, new bytes32[](0)));
    }

    function test_FourRecordBatch_EveryRecordVerifies() public {
        bytes32[4] memory l = [_leaf(0), _leaf(1), _leaf(2), _leaf(3)];
        bytes32 left = _pair(l[0], l[1]);
        bytes32 right = _pair(l[2], l[3]);
        uint256 id = registry.anchorBatch(_pair(left, right), 4, "");

        assertTrue(_verify(id, 0, _proof2(l[1], right)));
        assertTrue(_verify(id, 1, _proof2(l[0], right)));
        assertTrue(_verify(id, 2, _proof2(l[3], left)));
        assertTrue(_verify(id, 3, _proof2(l[2], left)));
    }

    /// With 3 records the third has no partner on the first level and is carried up,
    /// so its proof is one hash shorter.
    function test_OddBatch_LastRecordIsCarriedUp() public {
        bytes32[3] memory l = [_leaf(0), _leaf(1), _leaf(2)];
        bytes32 left = _pair(l[0], l[1]);
        uint256 id = registry.anchorBatch(_pair(left, l[2]), 3, "");

        assertTrue(_verify(id, 0, _proof2(l[1], l[2])));
        assertTrue(_verify(id, 2, _proof1(left)));
    }

    function test_TamperedRecord_DoesNotVerify() public {
        bytes32 root = _pair(_leaf(0), _leaf(1));
        uint256 id = registry.anchorBatch(root, 2, "");
        bytes32[] memory proof = _proof1(_leaf(1));

        assertTrue(_verify(id, 0, proof));
        // Same proof, but someone claims different weights, data, parent or uri:
        assertFalse(registry.verifyRecord(id, keccak256("fake"), DATA, parents[0], uris[0], proof));
        assertFalse(registry.verifyRecord(id, weights[0], bytes32(0), parents[0], uris[0], proof));
        assertFalse(registry.verifyRecord(id, weights[0], DATA, keccak256("x"), uris[0], proof));
        assertFalse(registry.verifyRecord(id, weights[0], DATA, parents[0], "hf://evil", proof));
    }

    function test_RecordDoesNotVerifyAgainstAnotherBatch() public {
        registry.anchorBatch(_pair(_leaf(0), _leaf(1)), 2, "");
        uint256 other = registry.anchorBatch(_pair(_leaf(2), _leaf(3)), 2, "");
        assertFalse(_verify(other, 0, _proof1(_leaf(1))));
    }
}