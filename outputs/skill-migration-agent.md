# Skill: Migration Agent

Use this skill when a repository needs a language/runtime migration and the result must be evidence-backed rather than a plausible-looking patch. The local implementation targets Python-2-era code to Python 3.12+ semantics; the same loop shape applies to other recipe engines.

## Inputs

- A local repository with a source package and a unittest-discoverable suite.
- Optional: package name and test directory when they are not `app` and `tests`.
- A migration budget. Defaults: 20 agent turns, 1800 seconds, $8. The deterministic policy is offline and costs $0.

## Procedure

1. **Baseline before edits.** Run the suite and measure line coverage. The implementation normalizes only Python-2-only syntax first because CPython 3 cannot import raw Python 2; record the baseline source as `measured_normalized_base` or `unavailable`.
2. **Deterministic pass.** Apply stage-0 syntax normalization and the libcst recipes. Inspect the diff; commit as `recipe: apply N deterministic rewrites`. Never rewrite tests.
3. **Build trial.** Compile every source/test file without writing bytecode, then import the package and every module. Classify packaging drift, syntax errors, and missing modules.
4. **Agent loop (only if red).** Classify the failure, choose one targeted action, apply it, commit any change as `agent: <fixer> for <class>`, and rerun build/tests. Observation tools (`read_file`, `run_build`, `run_test`, `git_diff`) count as turns. Two unchanged turns → give up; do not burn the budget pointlessly.
5. **Gate.** All tests must pass, the test-tree digest must equal the baseline, and coverage must be within −2 percentage points of the baseline. Missing baseline coverage is reported as unmeasured, not treated as a pass with invented data.
6. **Outcome.** On green, keep the `migration/py3` branch and write a PR bundle with recipe counts, agent fixes, commits, coverage delta, turns, cost, and the diff. On red, write a taxonomy record with class, reason, build/test tails, and a diff excerpt. Never publish or push automatically.

## Failure classes

`dep_upgrade_required`, `build_tool_drift`, `custom_annotation`, `test_flake`, `syntax_edge_case`, `budget_exhausted`, `coverage_regression`, `test_integrity`, `unclassified_failure`.

A flaky test is a failure, not a pass: a rerun that succeeds without edits is evidence of nondeterminism. A coverage regression is a failure even when tests are green. A test-tree change is always a failure.

## Commands

```bash
cma migrate REPO --out DIR [--mode full|recipes-only] [--package NAME]
cma bench --count 50 --seed 20261123 --out DIR
cma bench --corpus manifest --manifest repos.json --out DIR
cma dashboard results.json --out dashboard.html
cma recipes
```

Use `--policy llm` only with an OpenAI-compatible endpoint configured through `CMA_LLM_BASE_URL`, `CMA_LLM_API_KEY`, `CMA_LLM_MODEL`, and current price environment variables. Validate the first run manually; model output is untrusted and tool arguments are confined to the repository workspace.

## Evidence to report

Report only measured results. State the corpus, seed, host interpreter, target semantics, number of repositories, pass counts, coverage sample size, cost source, and whether the run was offline. Never compare local generated-corpus numbers to published benchmark numbers. Link `results.json`, `dashboard.html`, and per-repository `pr.md`/`failure.md`.

## Scope boundaries

The local sandbox is subprocess isolation for trusted fixtures; use Daytona/E2B/Docker for untrusted repositories. Test execution is unittest-based. The local corpus is a deterministic adapter, not Amazon MigrationBench.
