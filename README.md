# Order Migration

An original Rice COMP 480/580 verifiable task by Jackson Lieb. This repository contains the plugin, fixtures, verifier and reproducible tests. Historical run evidence belongs in the accompanying PDF, outside this repository.

## Tools

- `pin_reference`: reference-only; pins raw fixture data and independent expectations.
- `inspect_task`: accepts typed scenario/seed and shows task specification, fixture and editable files.
- `edit_files`: accepts a map of allowed candidate paths to complete replacement contents.
- `assess`: runs the controlled executor and returns an artifact-bound assessment receipt.
- Task `migrate-orders`: an agent task using inspect_task, edit_files, assess and the harness-provided submit tool.

All task/tool inputs and outputs are declared in contract.py. The reference tool is excluded from agent tools. The four fixture variants are standard, empty, boundary and invalid; seed ranges from 0 to 9999. The exact behavioral specification is returned by inspect_task and stored in src/plugin/domain.py.

## Layout

- nanoagent.yaml: v0001 manifest, no external network hosts, workspace writes only.
- contract.py: typed structured input and output declarations.
- src/plugin/: MCP tools, pinned fixture generation and controlled executor.
- verifier/: deterministic independent state/protocol oracle and artifact checks.
- tests/: correct solution controls, negative/malformed/boundary/tamper tests.
- ui/ and product/: marketplace output rendering and product metadata.

## Develop and run

Requirements: Linux or macOS (Windows via WSL) with Python 3.12+, Git and uv. The Python workers use POSIX resource limits. Install with `uv sync --frozen --extra dev`, then run `uv run pytest` and `uv run ruff check .`. Use a NanoAgent 0.7.0 checkout pinned at 57714f62880eee11319765854e398af61e67b7b7 to run `nanoagent plugin inspect <this-folder>` and `nanoagent plugin pack <this-folder>`. A fresh task workspace is required for a different input; repeated inspect calls for the same input preserve edits.

For an agent run, configure the official OpenRouter backend with deepseek/deepseek-v4-flash-0731 and a private OPENROUTER_API_KEY. Keys and evidence must never be committed. The delivery bundle includes a runner that accepts this repository, scenario and seed and records the real runtime outputs outside plugin repositories. Local correctness tests and packaging checks do not imply marketplace acceptance or a successful model run.

Evaluator boundary: only named candidate text files are exposed for edits; measurements and receipts are produced by trusted tools. Python candidate code passes an AST allowlist and executes in a separate process with audit hooks, time/resource limits, and no shell, network, direct file I/O or evaluator imports. This resists ordinary evaluator modification and superficial repairs; it is not a hardened OS sandbox against malicious native-code or interpreter exploits. Full host filesystem access is outside the threat model. Receipts bind source and result-file hashes; hashes alone are not authentication. Semantic checks decide validity, rather than a claimed passed flag.

Alternative implementations may pass when they meet the documented contract. No exact patch or source-text match is required. Dependencies and plugin code are pinned by uv.lock; fixtures are generated deterministically from recorded inputs. No LLM is used by the verifier. Test solutions are control implementations, not agent evaluation results.
