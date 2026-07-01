# Code Migration Agent

A repository-level Python 2→3 migration pipeline: a deterministic libcst substrate applies mechanical rewrites, a sandboxed agent loop fixes the failures that diagnostics can classify, and a build/test/coverage gate emits either a green git branch plus PR bundle or a failure-taxonomy record. It ships with a reproducible 50-repository local benchmark, a dependency-free HTML dashboard, and an optional OpenAI-compatible policy.

The project is an original implementation of the capstone brief, adapted for deterministic local execution. It does **not** claim MigrationBench numbers: the 50 measured repositories are a generated local corpus, not Amazon's benchmark. See [Measured results](#measured-results) and [Limitations](#limitations).

## What it does

Given a Python-2-era repository, `cma migrate`:

1. measures a target-runtime coverage baseline (after the semantics-preserving legacy-syntax pass);
2. applies token-position rewrites for Python-2-only syntax and libcst recipes for moved imports, builtin aliases, and dict methods, then commits a `recipe:` change;
3. runs the build (compile + import check) and the unittest suite in a local sandbox;
4. hands classified failures to a budgeted agent loop with tools `run_build`, `read_file`, `edit_file`, `run_test`, `git_diff`, `apply_fixer`, and `give_up`;
5. enforces test invariance, the coverage-preservation gate, and the 20-turn / 30-minute / $8 budgets; and
6. writes `pr.md` on success (`migration/py3` branch) or `failure.md` with a taxonomy class and evidence on failure.

No tests are modified by the agent. Coverage may not drop by more than 2 percentage points.

## Architecture

```
target repo
   │
   ├─ stage 0: legacy Python-2 syntax normalizer (only unparsable files)
   ├─ libcst recipes: moved imports, builtin aliases, dict methods
   │      └─ commit: "recipe: apply N deterministic rewrites"
   │
   ├─ LocalSandbox (subprocess; workspace + process-group timeout)
   │      ├─ build: compile + import every module
   │      └─ tests: unittest discover + coverage.py
   │
   ├─ agent loop (deterministic policy by default; optional LLM)
   │      ├─ classify: dep / build-tool / syntax / metaclass / flake
   │      ├─ act: apply_fixer or edit_file
   │      ├─ commit: "agent: <fixer> for <class>"
   │      └─ budgets: 20 turns, 1800 s, $8
   │
   └─ gates: tests green · test tree unchanged · coverage Δ ≥ −2 pp
          ├─ pass → migration/py3 + pr.md
          └─ fail → failure taxonomy class + failure.md + diff
```

Key modules:

| Path | Responsibility |
|---|---|
| `recipes/legacy_syntax.py` | Token-position `print`, `except E, e`, `raise E, msg`, backticks, `<>`, octal, long suffix, simple `exec` |
| `recipes/imports.py`, `builtins.py`, `dicts.py` | libcst recipes; URL modules are deliberately reserved for the agent |
| `runtime/sandbox.py` | Workspace-confined subprocess runner, process-group timeout, output truncation |
| `build.py`, `coverage_gate.py`, `gate.py` | Build trial, unittest + coverage, flake detection, test digests, coverage gate |
| `agent/loop.py`, `policy.py`, `tools.py` | Budgeted loop, deterministic diagnostic policy, confined tools |
| `agent/llm.py` | Optional OpenAI-compatible `/chat/completions` policy with token cost accounting |
| `corpus/` | 16 archetypes, 50-repo deterministic generator, local manifest loader |
| `migrate.py`, `pr.py`, `bench.py`, `dashboard.py` | Orchestration, PR/failure bundles, metrics, static HTML dashboard |

## Quickstart

Requirements: Linux/macOS, `uv`, `git`, Python ≥ 3.11 (the measured host is CPython 3.14). First install needs network access for pinned wheels.

```bash
./verify.sh                       # uv sync + mypy + 65 tests
uv run cma migrate examples/legacy_service --out .cache/quickstart
```

The quickstart prints recipe/build/test/PR stages and writes `.cache/quickstart/repos/legacy_service/pr.md`. The tracked example is copied first, so its source is never modified.

Run the published benchmark and open the dashboard:

```bash
uv run cma bench --count 50 --seed 20261123 --out .cache/bench50
uv run cma dashboard .cache/bench50/results.json --out .cache/bench50/dashboard-check.html
```

`reports/results.json` and `reports/dashboard.html` are the committed artifacts from the measured run below.

Useful commands:

```bash
uv run cma recipes
uv run cma migrate /path/to/repo --package app --test-dir tests
uv run cma migrate /path/to/repo --mode recipes-only --json
uv run cma bench --corpus manifest --manifest repos.json --jobs 2
```

A benchmark manifest is local JSON; paths are resolved relative to the manifest:

```json
{"repos": [{"name": "service-a", "path": "../service-a", "package": "app", "test_dir": "tests",
            "budgets": {"max_turns": 20, "max_seconds": 1800, "max_cost_usd": 8}}]}
```

Tests must be discoverable by `python -m unittest discover -s tests` and coverage is measured with `coverage run --source app`. This is the adapter boundary for exported real repositories.

## What runs offline

Everything in the default path is offline and deterministic:

- deterministic stage-0 rewrites, recipes, fixers, classification, gates, git operations, benchmark and dashboard;
- the agent uses no model: the deterministic policy maps observed diagnostics to a fixer;
- tests never use sockets, and the test suite uses an injected fake LLM client;
- the measured 50-repo run costs $0.00 and does not contact Daytona, GitHub, Hugging Face, or a model provider.

There is no GPU path; this task does not need one.

## Optional real provider mode

The LLM policy is implemented, including JSON action validation, tool-argument validation, token usage, illustrative price defaults, and budget enforcement. It is **not** exercised live in this repository because no provider key is available. Configure an OpenAI-compatible chat-completions endpoint:

```bash
export CMA_LLM_BASE_URL=https://your-provider.example/v1
export CMA_LLM_API_KEY=test_only_replace_me
export CMA_LLM_MODEL=your-model
export CMA_PRICE_IN_PER_MTOK=3.0       # set to the provider's current price
export CMA_PRICE_OUT_PER_MTOK=15.0     # illustrative default, not a claim
uv run cma migrate /path/to/repo --policy llm --out .cache/llm-run
```

The policy receives the failure class, diagnostics, a source excerpt, file list, history, and the allowed fixers/tools. It may return `edit_file`, `apply_fixer`, an observation tool, or `give_up`; malformed output is a clean `invalid_llm_action` failure, and cost is charged against the $8 cap. For Daytona or another hosted sandbox, replace the `LocalSandbox` construction in `migrate.py` with an adapter implementing the small `Sandbox` protocol in `runtime/sandbox.py` (`run(args, cwd, env, timeout_s) -> CommandResult`); the loop and gates stay provider-neutral. The current implementation uses the local subprocess sandbox, not Daytona. The operating playbook is `outputs/skill-migration-agent.md`.

PR opening is local by design: each run keeps a real git branch and a `pr.md` bundle. A production adapter can push that branch and call `gh pr create --title ... --body-file pr.md`; no push/remote is performed here.

## Measured results

Measured locally with the checked-in code and generated corpus, seed `20261123`, 50 repositories, host CPython 3.14, target semantics Python 3.12+. These are **local synthetic-corpus results**, not MigrationBench results. Times are wall-clock on the measurement host; cost is the deterministic policy's actual model cost.

| Metric | Recipes only | Full pipeline |
|---|---:|---:|
| Repositories passing build + tests + coverage + integrity | 17/50 (34.0%) | 35/50 (70.0%) |
| Mean coverage delta (runs with measured baseline) | +7.60 pp (n=43) | +9.41 pp (n=46) |
| Cost per passing repo | $0.00 | $0.00 |
| Agent-authored fix share | 0.0% | 14.7% |
| Median time to green | 0.58 s | 0.66 s |

Full-pipeline failure taxonomy:

| Class | Count | Meaning |
|---|---:|---|
| `custom_annotation` | 3 | Python-2 `__metaclass__` semantics silently ignored; no safe automatic rewrite |
| `dep_upgrade_required` | 3 | Third-party dependency unavailable offline |
| `test_flake` | 2 | Test suite failed once and passed on an unchanged rerun; not accepted as a migration |
| `coverage_regression` | 2 | Tests green but the agent's fix added uncovered code and dropped coverage >2 pp |
| `syntax_edge_case` | 3 | Unsupported Python-2 `exec` form or an integer-division semantic change with no safe rewrite |
| `budget_exhausted` | 2 | Two sequential fixes with a per-repo `max_turns=1` budget slice |

The two tight-budget repositories intentionally use a smaller budget to exercise the cap path; all other corpus entries use 20 turns / 1800 s / $8. The recipes-only baseline files more failures because URL-module migrations, `reduce`, `cmp` sorting, dict-key indexing, and packaging drift are intentionally reserved for the agent (`syntax_edge_case` 12, `dep_upgrade_required` 9, `unclassified_failure` 4, `build_tool_drift` 3, `custom_annotation` 3, `test_flake` 2).

Why coverage deltas are positive on average: a baseline is measured after only the semantics-preserving legacy-syntax pass, while the original suite often fails before exercising all lines. A positive mean is therefore not evidence of test improvement; the enforced requirement is per-repository preservation within −2 pp. Two repos demonstrably fail that gate, and their exemplar diffs are in `reports/dashboard.html`.

The full pipeline's 35/50 is not a claim about real-world pass rates. It is the measured result of this exact 50-repo local corpus, reproducible with the command above. The agent adds 18 passing repos over the deterministic-only baseline, while the deterministic substrate accounts for the majority of individual edits.

## Failure taxonomy

The six capstone classes are retained, plus three harness classes:

- `dep_upgrade_required` — missing/reserved dependency or stdlib module.
- `build_tool_drift` — legacy `distutils`, `use_2to3`, or Python-2 `requires-python`.
- `custom_annotation` — metaclass/decorator semantics with no generic safe rewrite.
- `test_flake` — failure followed by success on an unchanged rerun.
- `syntax_edge_case` — unsupported Python-2 syntax or semantic edge cases.
- `budget_exhausted` — turn, wall-clock, or cost cap breached; current diff retained.
- `coverage_regression` — green tests but coverage below the base by more than 2 pp.
- `test_integrity` — test tree changed (forbidden by tools; verified by digest).
- `unclassified_failure` — residual; zero in the measured full run.

Every failed repository keeps `failure.md`, `evidence/trace.jsonl`, build/test tails, and a diff excerpt. The dashboard renders counts and up to three exemplar diffs per class.

## Design decisions

- **Deterministic first.** Stage 0 exists only because libcst cannot parse Python-2-only syntax; it is gated on `ast.parse` failure and works from token positions, never free-text regex. All subsequent code rewrites are libcst node transformations.
- **Reserve ambiguity for the agent.** `urllib2`/`urlparse` are deliberately excluded from the automatic recipe; URL/request semantics deserve a classified fix. The same applies to `reduce`, `cmp=` sorting, dict-key indexing, packaging drift, and the removed `commands` module.
- **Tests are held out.** The tool layer rejects any write under the test directory, and `gate.py` compares a SHA-256 digest of the test tree with the baseline. Benchmark criteria also require test invariance and a non-decreasing test count; the digest enforces the stronger local rule.
- **Real subprocess execution.** Builds and tests actually run; coverage is measured with coverage.py. The sandbox is an isolation boundary and a plug point, not a mock.
- **PR is a local artifact.** The branch and bundle are real git state; publishing is an explicit integration step outside this offline project.
- **Synthetic corpus is labeled as such.** Reproducibility and zero credentials outweigh a misleadingly named benchmark.

## Testing

`./verify.sh` runs `uv sync --frozen`, strict mypy on `src`, and pytest. The 65 tests cover tokenizer guards, each recipe and fixer, sandbox confinement/timeouts, build/coverage parsing, classification, gate boundaries, test-digest integrity, flaky detection, budget caps, LLM JSON/cost handling, corpus determinism, manifest loading, end-to-end migrations (recipe-only and agent-assisted), coverage-regression filing, benchmark metrics/taxonomy, dashboard escaping, and CLI exit codes. No test opens a network connection.

## Limitations

- No real MigrationBench/Poly-MigrationBench dataset or real Java migration was executed; measured numbers are for the 50-repo generated corpus.
- The sandbox is local subprocess isolation, not Daytona/E2B/Docker. A hostile repository is not a security boundary; use a container or hosted sandbox for untrusted code.
- The harness executes on CPython 3.14 while requiring target semantics `>=3.12`; no separate 3.12 interpreter is provisioned.
- Test execution is unittest-discovery based; pytest-style repositories need a test-command adapter. Coverage is line coverage over the configured package.
- The deterministic policy's fixers are intentionally narrow; the optional LLM path has not been run against a live provider here.
- Failure classes `unclassified_failure` and `test_integrity` are residual/harness classes beyond the six named in the brief.
- The dashboard is generated static HTML, not a TypeScript application (the brief's primary-language rule selects Python).

## References

1. AWS DevOps Blog, “Amazon introduces two benchmark datasets for evaluating AI agents’ ability on code migration” — https://aws.amazon.com/blogs/devops/amazon-introduces-two-benchmark-datasets-for-evaluating-ai-agents-ability-on-code-migration/
2. MigrationBench project and evaluation criteria — https://amazon-science.github.io/MigrationBench/ (used for build/tests/test-invariance framing)
3. LibCST tutorial, “Parsing and Visiting” — https://libcst.readthedocs.io/en/latest/tutorial.html (transformer/metadata patterns; `parse_module`, `Module.code`)
4. OpenAI Cookbook, “Migrate a Legacy Codebase with Sandbox Agents” — https://developers.openai.com/cookbook/examples/agents_sdk/sandboxed-code-migration/sandboxed_code_migration_agent.md (harness outside sandbox; scoped workspace; patch/report artifacts)
5. coverage.py command reference (`run`, `json`) — https://coverage.readthedocs.io/en/latest/commands/index.html

## License

MIT © 2026 Pedro Monteiro. See `LICENSE`.
