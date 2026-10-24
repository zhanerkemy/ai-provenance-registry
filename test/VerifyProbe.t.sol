// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "lib/forge-std/src/Test.sol";
import {ModelRegistry} from "../src/ModelRegistry.sol";
import {MerkleRegistry} from "../src/MerkleRegistry.sol";
import {VerifyProbe, IModelRegistry, IMerkleRegistry} from "../src/VerifyProbe.sol";

/// @notice Tests for VerifyProbe. Run with:  forge test --match-contract VerifyProbe -vv
/// @dev    The probe must (1) return the same answer as calling the registry directly,
///         and (2) report a gas number that makes sense: more than zero, and less than
///         the 21,000 base cost that `estimate_gas` adds to every transaction.
contract VerifyProbeTest is Test {
    ModelRegistry internal models;
    MerkleRegistry internal merkle;
    VerifyProbe internal probe;

    bytes32 internal constant BASE = keccak256("base-weights");
    bytes32 internal constant FT = keccak256("ft-weights");
    bytes32 internal constant FT2 = keccak256("ft2-weights");
    bytes32 internal constant DATA = keccak256("data");

    function setUp() public {
        models = new ModelRegistry();
        merkle = new MerkleRegistry();
        probe = new VerifyProbe();

        // A three-generation lineage: base (id 1) -> ft (id 2) -> ft2 (id 3).
        models.registerModel(BASE, DATA, 0, "hf://org/base@1");
        models.registerModel(FT, bytes32(0), 1, "hf://a/ft@2");
        models.registerModel(FT2, bytes32(0), 2, "hf://b/ft2@3");
    }

    // ---------------------------------------------------------------- storage design

    function test_ProbeVerifyWeights_SameAnswerAsRegistry() public view {
        (bool ok, uint256 gasUsed) = probe.probeVerifyWeights(IModelRegistry(address(models)), 2, FT);
        assertTrue(ok);
        assertGt(gasUsed, 0);
        assertLt(gasUsed, 21_000); // the check itself is far cheaper than a whole transaction

        (bool wrong,) = probe.probeVerifyWeights(IModelRegistry(address(models)), 2, BASE);
        assertFalse(wrong);
    }

    function test_ProbeVerifyWeights_RevertsForUnknownModel() public {
        vm.expectRevert(abi.encodeWithSelector(ModelRegistry.ModelDoesNotExist.selector, 99));
        probe.probeVerifyWeights(IModelRegistry(address(models)), 99, FT);
    }

    function test_ProbeLineage_LengthIsDepthPlusOne() public view {
        (uint256 len1,) = probe.probeLineage(IModelRegistry(address(models)), 1);
        (uint256 len3,) = probe.probeLineage(IModelRegistry(address(models)), 3);
        assertEq(len1, 1); // the base model is its own lineage
        assertEq(len3, 3); // ft2 -> ft -> base
    }

    function test_ProbeLineage_DeeperModelCostsMore() public {
        (, uint256 gasBase) = probe.probeLineage(IModelRegistry(address(models)), 1);
        // The first call made the registry's address and storage "warm" (cheap to touch
        // again in the same transaction). Without this line the second call is cheaper
        // even though it reads more, which is the cold/warm effect, not a depth effect.
        vm.cool(address(models));
        (, uint256 gasDeep) = probe.probeLineage(IModelRegistry(address(models)), 3);
        assertGt(gasDeep, gasBase); // each generation is one more storage read per pass
    }

    function test_SecondCheckInSameTransactionIsCheaper() public view {
        // Why we measure every check from a cold start (one eth_call each) in Python.
        (, uint256 first) = probe.probeVerifyWeights(IModelRegistry(address(models)), 2, FT);
        (, uint256 second) = probe.probeVerifyWeights(IModelRegistry(address(models)), 2, FT);
        assertLt(second, first);
    }

    // ---------------------------------------------------------------- Merkle design

    function test_ProbeVerifyRecord_SingleRecordBatch() public {
        // With one record the root is the leaf itself and the proof is empty.
        bytes32 leaf = merkle.leafHash(BASE, DATA, bytes32(0), keccak256(bytes("hf://org/base@1")));
        uint256 batchId = merkle.anchorBatch(leaf, 1, "batch-1");

        bytes32[] memory proof = new bytes32[](0);
        (bool ok, uint256 gasUsed) = probe.probeVerifyRecord(
            IMerkleRegistry(address(merkle)), batchId, BASE, DATA, bytes32(0), "hf://org/base@1", proof
        );
        assertTrue(ok);
        assertGt(gasUsed, 0);

        (bool tampered,) = probe.probeVerifyRecord(
            IMerkleRegistry(address(merkle)), batchId, FT, DATA, bytes32(0), "hf://org/base@1", proof
        );
        assertFalse(tampered);
    }

    function test_ProbeVerifyRecord_LongerProofCostsMore() public {
        // Two batches: one record (empty proof) and two records (proof of length 1).
        bytes32 leafA = merkle.leafHash(BASE, DATA, bytes32(0), keccak256(bytes("hf://org/base@1")));
        bytes32 leafB = merkle.leafHash(FT, bytes32(0), BASE, keccak256(bytes("hf://a/ft@2")));
        uint256 single = merkle.anchorBatch(leafA, 1, "batch-1");
        bytes32 root = leafA < leafB ? keccak256(abi.encode(leafA, leafB)) : keccak256(abi.encode(leafB, leafA));
        uint256 pair = merkle.anchorBatch(root, 2, "batch-2");

        bytes32[] memory empty = new bytes32[](0);
        bytes32[] memory one = new bytes32[](1);
        one[0] = leafB;

        (bool ok1, uint256 gas0) = probe.probeVerifyRecord(
            IMerkleRegistry(address(merkle)), single, BASE, DATA, bytes32(0), "hf://org/base@1", empty
        );
        vm.cool(address(merkle)); // start the second check cold too, so only the proof differs
        (bool ok2, uint256 gas1) = probe.probeVerifyRecord(
            IMerkleRegistry(address(merkle)), pair, BASE, DATA, bytes32(0), "hf://org/base@1", one
        );
        assertTrue(ok1 && ok2);
        assertGt(gas1, gas0); // one more keccak256 and 32 more bytes passed to the registry
    }
}