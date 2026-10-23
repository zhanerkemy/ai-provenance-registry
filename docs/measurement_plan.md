# Measurement plan

Written before any measurement, as the course requires ("Decide how you will measure
before you measure, not after you see a number you like"). Change it only with a dated
note at the bottom saying what changed and why.

## Gap

Blockchain registries for AI provenance (ProML, ECSA 2022; IBIS, arXiv 2024) are
evaluated on small synthetic workloads and a single on-chain design. None reports what
it costs to record a **real, public model family tree**, or compares designs by both
**gas cost** and **what each design still lets an auditor verify on-chain**.

## Research question

For a real Hugging Face model family, how much gas does on-chain lineage registration
cost under three designs (contract storage, event-only logging, Merkle-batched
anchoring), and which verification guarantees does each design give up?

Sub-questions:
1. What share of a real family tree can be registered at all (weight hashes published,
   single parent, readable)?
2. Gas per registered model for each design, and for Merkle batches of k = 1, 8, 32, 128.
3. Gas for another contract to verify one record, and a model's whole lineage, under
   each design.
4. Which audit checks does each design still support? (Answered by running the checks,
   not by argument; see "Guarantee checks" below.)

Why (our words): We compare three ways of storing lineage on-chain because what you keep on-chain decides how much gas you pay, but the cheaper options also take away checks an auditor could do directly on the chain. If we only looked at gas, the weakest design would always win, so we also write down what each design gives up. We use a real model family instead of made-up data because made-up trees don't show real depth, branching, or models with missing hashes.

## Data

- Source: Hugging Face Hub, through `src/hf_lineage.py`.
- Base model: **`HuggingFaceTB/SmolLM2-360M`** (agreed 2026-10-20, pulled the same day).
- Limits: `--max-models 3000 --max-depth 4`. The walk finished before the limit
  (`"truncated": false` in `data/hf_tree_meta.json`), so the CSV holds the whole tree
  to depth 4: 1,369 models.
- Relations followed: finetune, adapter, quantized, merge.
- Recorded automatically in `data/hf_tree_meta.json`: pull date, limits, library version.

Why this base model (our words): We picked SmolLM2-360M because it is open and not gated, so anyone can pull the same tree without asking for access, and it has a large family on the Hub that is still small enough to replay on a local chain in a few minutes. Its tree to depth 4 has 1,369 models (193 at depth 1, 639 at depth 2, 381 at depth 3, 155 at depth 4), mostly fine-tunes, adapters and quantized versions, so we get real depth and branching. For 98.8% of these models the Hub lists SHA-256 values for the weight files, so we can compute the weights hash without downloading any weights.

## Designs compared

| Design | Contract | Transactions | Kept on-chain | Gives up |
|---|---|---|---|---|
| Storage | `ModelRegistry` | 1 per model | full record | nothing (baseline) |
| Event-only | `EventRegistry` | 1 per model | counter only; record in the log | duplicate check, on-chain reads, ownership transfer |
| Merkle batch | `MerkleRegistry` | 1 per k models | root + submitter + time | registration-time checks; needs off-chain proofs; ownership per batch |

The "Gives up" column is our expectation. The guarantee checks below test it.

Why these three (our words): Storage is our baseline: it keeps the whole record, so everything can be checked on-chain. Event-only puts the record in the log instead, which is much cheaper than a storage slot, but then we lose on-chain reads, the duplicate check and ownership transfer. Merkle batching uses one transaction for k models, but anyone who wants to verify a record needs an off-chain proof. Together they show the trade-off between cost and what can still be verified on-chain.

## Metrics

| Metric | How it is measured | Where it ends up |
|---|---|---|
| Registrable share | `plan_registrations()` rules in `src/hf_lineage.py` | `data/results/tree_stats.json` |
| Gas per model | transaction `gasUsed` from the receipt (Merkle: batch gas / k) | `data/results/gas.csv` |
| Verification gas, transaction | `estimate_gas` of `verifyWeights` / `verifyRecord` sent directly | `data/results/gas.csv` (`verify_gas`) |
| Verification gas, inside a contract | `gasleft()` before and after the call, in `src/VerifyProbe.sol` | `data/results/verify_gas.csv` |
| Lineage verification gas | storage: one `getLineage` call; Merkle: one `verifyRecord` per generation | `data/results/verify_gas.csv` |
| Gas decomposition | least-squares fit, see below | `data/results/gas_model.json` |
| Guarantees | executed checks, see below | `data/results/guarantees.csv` |
| Anvil vs. Sepolia | same transactions on both chains, `gasUsed` compared row by row | `data/results/chain_check.json` |

### Why two verification numbers

`estimate_gas` prices a call as if it were its own transaction, so it includes the
21,000 base cost of every transaction and the cost of the call data. A smart contract
that checks a record inside its own logic (for example, a marketplace that refuses
unregistered models) pays neither. `VerifyProbe` measures only what the check itself
costs. The paper reports the probe numbers for sub-question 3; the `estimate_gas`
numbers stay in `gas.csv` as the cost for an auditor who sends a transaction.

### Gas decomposition

For storage and event registrations we fit, by ordinary least squares,

    gas = a + b * uri_words + c * has_data + d * is_base

- `uri_words`: length of the URI in 32-byte words, rounded up
- `has_data`: 1 if a training-data reference hash was declared, else 0
- `is_base`: 1 for the base model, which is always the first registration in a fresh
  contract: its counter write goes from 0 to 1 (costs more than later increments), and
  in the storage design its parentId is 0, so one storage slot stays empty (costs less)

We report a, b, c, d, R² and the largest residual, and compare b and c with the EVM's
price for writing a new storage slot (20,000 for the write + 2,100 for the first
access to the slot = 22,100 gas). For Merkle batches we report the mean transaction gas
of full batches for each k, and the smallest k at which Merkle costs less per model
than the event design.

### Guarantee checks

Each check is run against a fresh copy of each contract on a local chain, with real
records from our tree. The result is whatever the chain does, recorded as one of:
`yes` (the contract enforces or supports it), `with proof` (only if the auditor also
has the record and its Merkle proof), `off-chain only` (possible by reading event logs
from a node, but no contract can do it), `no`.

| # | Check |
|---|---|
| 1 | A tampered weights hash is detected |
| 2 | Registering the same weights twice is refused |
| 3 | A record whose parent was never registered is refused |
| 4 | An empty (zero) weights hash is refused |
| 5 | Another contract can check a record |
| 6 | A model's lineage can be followed on-chain |
| 7 | The owner of one model can hand it to another account |

### Verification sample

Verification gas does not depend on how many models are registered, only on the
model's depth (lineage) and the batch size (proof length). So we measure it on a sample:
random seed **435**, up to **5** registrable models per depth, plus their ancestors.
Merkle batches are cut exactly as in `src/replay.py`, so proof lengths match the main run.

### Sepolia check

The first **24** registrable models in breadth-first order (a prefix of the plan, so
every parent is included), storage and event designs, Merkle batch sizes **1 and 8**.
Success means every transaction uses exactly the same gas as the same transaction on
Anvil. Any difference is reported in the paper with its explanation, not removed.

## Fixed decisions

- Same models, same order (breadth-first, parents first), fresh contract per design.
- Models left out of all designs equally: several parents, no weight hashes,
  unreadable, ancestor left out, exact re-upload (children attach to the first copy).
- Main runs on local Anvil (gas is deterministic there). A sample on Sepolia
  checks that gas matches; Sepolia's address and block range go in `docs/deployments.md`.
- Gas is reported in gas units, not dollars (prices change daily). If we convert,
  we state the date and price used.
- Compiler 0.8.24, optimizer on, 200 runs (`foundry.toml`).

## Planned figures

1. Models per depth, by relation (`figures/tree_by_depth.png`).
2. Registrable vs. excluded models, by reason (`figures/tree_registrability.png`).
3. **Main figure:** gas per registered model for storage, event-only and Merkle with
   k = 1, 8, 32, 128, for the 1,071 registrable descendants of SmolLM2-360M
   (`figures/gas_per_model.png`).
4. Verification gas inside a contract: one record, and a whole lineage by depth
   (`figures/verify_gas.png`).
5. Storage gas against URI length, split by whether a data hash was declared, with the
   fitted model (`figures/storage_gas_breakdown.png`).

## Known limitations (go into the paper)

- `data_ref_hash` hashes the *names* of declared datasets, not their content; the Hub
  publishes no dataset content hashes.
- One base model and one snapshot date; the Hub changes daily.
- Our contracts record one parent, so merges are excluded rather than represented.
- Registration proves that an address *claimed* these hashes at a time; it does not
  prove the training actually happened (see proof-of-learning literature).
- Verification gas is measured for the first check in a transaction (cold storage
  access). Repeated checks in the same transaction are cheaper.
- Sepolia is checked on a sample only.

## Change log

- 2026-10-13 - Base model not yet agreed; to be filled in before any data is pulled
- 2026-10-20 - Base model agreed: HuggingFaceTB/SmolLM2-360M. `--max-models` raised
  from 300 to 3000 so the walk was not cut off; the full tree to depth 4 has 1,369
  models. (Decided before any gas was measured.)
- 2026-10-23 - Added, before measuring them: verification gas inside a contract
  (VerifyProbe), lineage verification gas, gas decomposition, executed guarantee checks
  (sub-question 4), and the Sepolia sample check. Planned figures 3 to 5 updated.
