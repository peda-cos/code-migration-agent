# Measured artifacts

`results.json` and `dashboard.html` are the copied outputs of:

```bash
uv run cma bench --count 50 --seed 20261123 --out .cache/bench50
```

Measured locally against the checked-in code on the host CPython 3.14, target semantics Python 3.12+. Corpus is the generated 50-repository local corpus, not Amazon MigrationBench. The dashboard is fully self-contained; open it in a browser.

Key recorded metrics: full pipeline 35/50 passes (70.0%), recipes-only 17/50 (34.0%), mean coverage delta +9.41 pp over 46 measured-baseline runs (full), median time to green 0.66 s, and $0.00 model cost for the offline deterministic policy.

Regenerate after code changes and copy the two artifacts back here:

```bash
rm -rf .cache/bench50
uv run cma bench --count 50 --seed 20261123 --out .cache/bench50
cp .cache/bench50/results.json reports/results.json
cp .cache/bench50/dashboard.html reports/dashboard.html
```

The generated corpus and per-repository workspaces live under `.cache/` and are intentionally not tracked. Results are deterministic in outcomes; timings vary. Do not edit the JSON by hand.
