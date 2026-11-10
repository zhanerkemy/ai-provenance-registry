# ai-provenance-registry
[![tests](https://github.com/zhanerkemy/ai-provenance-registry/actions/workflows/test.yml/badge.svg)](https://github.com/zhanerkemy/ai-provenance-registry/actions/workflows/test.yml)

Blockchain-based registry for tracking AI model versions, training-data hashes, ownership, and provenance on-chain.

Research project for CSCI 435 Blockchain and Cryptocurrencies, Nazarbayev University, Fall 2026.

## Team
- Ayaulym Zhumagul
- Zhanerke
- Dana

## Repository structure
```
src/            code: smart contracts (.sol) and Python scripts (.py)
test/           Foundry tests (.t.sol) and pytest tests (test_*.py)
data/           the model tree we downloaded, and results/ produced by the scripts
docs/           measurement plan (written before measuring), Sepolia deployments
figures/        figures from src/make_figures.py; tables/ from src/make_tables.py and
                src/make_numbers.py (every number quoted in the paper's text)
notebooks/      results_walkthrough.ipynb: the data behind each claim, step by step
lib/            forge-std (git submodule)
```

## Setup
Requirements: Python 3.11, Git, and [Foundry](https://book.getfoundry.sh/getting-started/installation) (`forge`, `anvil`).

```bash
git clone --recurse-submodules https://github.com/zhanerkemy/ai-provenance-registry.git
cd ai-provenance-registry
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
forge build
```

If you cloned without `--recurse-submodules`, run `git submodule update --init` before `forge build`.

## Data

| | |
|---|---|
| Base model | `HuggingFaceTB/SmolLM2-360M` |
| Pulled | 2026-10-20 (UTC time in `data/hf_tree_meta.json`) |
| Limits | `--max-models 3000 --max-depth 4` (the walk was not truncated) |
| Models in tree | 1,369 (`data/hf_tree.csv`) |
| Compiler | solc 0.8.24, optimizer on, 200 runs (`foundry.toml`) |
| Chain for main runs | local Anvil (chain id 31337) |

## Reproducing results

Start a local blockchain in one terminal and leave it open:

```bash
anvil
```

Then, in a second terminal from the repository root (with the virtual environment active):

| Step | Command | Produces |
|---|---|---|
| 1. Compile contracts | `forge build` | `out/` (not committed) |
| 2. Download the model tree | `python src/hf_lineage.py --base HuggingFaceTB/SmolLM2-360M --max-models 3000 --max-depth 4` | `data/hf_tree.csv`, `data/hf_tree_meta.json` |
| 3. Tree statistics | `python src/tree_stats.py` | `data/results/tree_stats.json` |
| 4. Register under all designs, record gas | `python src/replay.py` | `data/results/gas.csv`, `data/results/run_meta.json` |
| 5. Explain the gas (least-squares fit) | `python src/gas_model.py` | `data/results/gas_model.json` |
| 6. Gas for a contract to verify | `python src/verify_gas.py` | `data/results/verify_gas.csv` |
| 7. Guarantee checks | `python src/audit_checks.py` | `data/results/guarantees.csv` |
| 8. Figures | `python src/make_figures.py` | `figures/*.png` |
| 9. Tables for the paper | `python src/make_tables.py` | `figures/tables/gas_summary.tex`, `guarantees.tex` |
| 10. Numbers for the paper's text | `python src/make_numbers.py` | `figures/tables/numbers.tex` |
| Tests | `forge test` and `python -m pytest` | |

Step 2 reads the live Hugging Face Hub, so re-running it on a later date can give a
different tree. To reproduce our exact numbers, skip step 2 and use the committed
`data/hf_tree.csv` (its pull date is in `data/hf_tree_meta.json`). Steps 3 to 10 are
deterministic on Anvil: running them again gives the same files. Step 4 takes about
7 minutes; the others take seconds. `verify_gas.py` samples models with the fixed seed
435 (`--seed`). `test/test_results.py` checks that the committed results match the
committed tree.

In the paper, `\input{tables/numbers.tex}` once in the preamble, then write
`\result{tree.registrable}` instead of typing 1,071; the keys are listed in the file.
A wrong key prints as **??key** in the PDF.

### One-command check

`python src/reproduce.py` runs steps 1 and 3 to 10 on its own Anvil (no need to open one)
and reports whether any result, table or number differs from the committed version.
Add `--quick` to reuse the committed `gas.csv` and finish in about a minute. Two changes
are expected and allowed: `run_meta.json` (when the run happened, which blocks) and the
PNGs (fonts render differently on each system). `git restore data figures` undoes them.

### Sepolia check (optional, needs test ETH)

The main numbers come from Anvil. To check that a public network charges the same gas,
we replay a small sample on the Sepolia testnet and compare transaction by transaction:

```bash
cp .env.example .env          # then fill in SEPOLIA_RPC_URL and PRIVATE_KEY (a test-only wallet)
python src/replay.py --network sepolia --max-models 24 --batch-sizes 1 8
python src/compare_chains.py
```

This writes `data/results/sepolia/`, `data/results/chain_check.json` and
`docs/deployments.md` (contract addresses and block range). The script estimates the
cost first and stops if the wallet cannot pay for it.

## Exploring the results

`notebooks/results_walkthrough.ipynb` reads the committed results and walks through
the tree, registration gas, verification gas and the guarantees, ending with the list
of every number the paper quotes. It is committed with its outputs, so GitHub shows it
without running anything. To run it yourself: `pip install notebook==7.2.2`, then
`jupyter notebook notebooks/results_walkthrough.ipynb`.

## Reused code

- [forge-std](https://github.com/foundry-rs/forge-std) (MIT / Apache-2.0), the Foundry test library, included as a git submodule in `lib/forge-std` with its own licence files.
- Python libraries listed in `requirements.txt`, used through their public APIs.

All other code in `src/` and `test/` was written for this project.

## Acknowledgements

Parts of the code were drafted with the help of an AI assistant (Claude, Anthropic)
and were reviewed, run, tested and modified by the team, who can explain every part.

## License
MIT. See `LICENSE`.
