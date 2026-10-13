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
3. Gas for another contract to verify one record under each design.

Why (our words): We compare three ways of storing lineage on-chain because what you keep on-chain decides how much gas you pay, but the cheaper options also take away checks an auditor could do directly on the chain. If we only looked at gas, the weakest design would always win, so we also write down what each design gives up. We use a real model family instead of made-up data because made-up trees don't show real depth, branching, or models with missing hashes.

## Data

- Source: Hugging Face Hub, through `src/hf_lineage.py`.
- Base model: **to be agreed** (not decided as of 2026-10-13; it will be set before any data is pulled). Its "Model tree" panel on the Hub
  should show a few hundred descendants; we stop at `--max-models 300 --max-depth 4`.
- Relations followed: finetune, adapter, quantized, merge.
- Recorded automatically in `data/hf_tree_meta.json`: pull date, limits, library version.

Why this base model (our words): We haven't picked it yet. We are looking for a model whose "Model tree" on the Hub has a few hundred descendants over several generations, whose weight files have SHA-256 listed on the Hub, and that isn't gated.

## Designs compared

| Design | Contract | Transactions | Kept on-chain | Gives up |
|---|---|---|---|---|
| Storage | `ModelRegistry` | 1 per model | full record | nothing (baseline) |
| Event-only | `EventRegistry` | 1 per model | counter only; record in the log | duplicate check, on-chain reads, ownership transfer |
| Merkle batch | `MerkleRegistry` | 1 per k models | root + submitter + time | registration-time checks; needs off-chain proofs; ownership per batch |

Why these three (our words): Storage is our baseline: it keeps the whole record, so everything can be checked on-chain. Event-only puts the record in the log instead, which is much cheaper than a storage slot, but then we lose on-chain reads, the duplicate check and ownership transfer. Merkle batching uses one transaction for k models, but anyone who wants to verify a record needs an off-chain proof. Together they show the trade-off between cost and what can still be verified on-chain.

## Metrics

| Metric | How it is measured | Where it ends up |
|---|---|---|
| Registrable share | `plan_registrations()` rules in `src/hf_lineage.py` | `data/results/tree_stats.json` |
| Gas per model | transaction `gasUsed` from the receipt (Merkle: batch gas / k) | `data/results/gas.csv` |
| Verification gas | `estimate_gas` of `verifyWeights` / `verifyRecord` | `data/results/gas.csv` |

## Fixed decisions

- Same models, same order (breadth-first, parents first), fresh contract per design.
- Models left out of all designs equally: several parents, no weight hashes,
  unreadable, ancestor left out, exact re-upload (children attach to the first copy).
- Main runs on local Anvil (gas is deterministic there). A sample on Sepolia
  checks that gas matches; Sepolia's address and block range go in the README.
- Gas is reported in gas units, not dollars (prices change daily). If we convert,
  we state the date and price used.
- Compiler 0.8.24, optimizer on, 200 runs (`foundry.toml`).

## Planned figures

1. Models per depth, by relation (`figures/tree_by_depth.png`).
2. Registrable vs. excluded models, by reason (`figures/tree_registrability.png`).
3. **Main figure:** gas per registered model for storage, event-only and Merkle with
   k = 1, 8, 32, 128, for N real descendants of the chosen base model.

## Known limitations (go into the paper)

- `data_ref_hash` hashes the *names* of declared datasets, not their content; the Hub
  publishes no dataset content hashes.
- One base model and one snapshot date; the Hub changes daily.
- Our contracts record one parent, so merges are excluded rather than represented.
- Registration proves that an address *claimed* these hashes at a time; it does not
  prove the training actually happened (see proof-of-learning literature).

## Change log

- 2026-10-13 - Base model not yet agreed; to be filled in before any data is pulled
