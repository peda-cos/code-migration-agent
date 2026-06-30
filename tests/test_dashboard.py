import json
from pathlib import Path

from code_migration_agent.dashboard import render_dashboard, write_dashboard


def _results() -> dict:
    return {
        "corpus": {"kind": "synthetic", "count": 2, "seed": 1},
        "modes": {
            "full": {
                "metrics": {
                    "pass_rate": 0.5,
                    "mean_coverage_delta": 1.25,
                    "cost_per_passing_repo": 0.0,
                    "agent_fix_share": 0.2,
                    "ttfgb_median_s": 1.5,
                }
            },
            "recipes_only": {
                "metrics": {
                    "pass_rate": 0.25,
                    "mean_coverage_delta": 0.5,
                    "cost_per_passing_repo": 0.0,
                    "agent_fix_share": 0.0,
                    "ttfgb_median_s": 1.0,
                }
            },
        },
        "taxonomy": {
            "full": {
                "<script>alert(1)</script>": {
                    "count": 1,
                    "exemplars": [
                        {
                            "repo": "<img src=x onerror=alert(1)>",
                            "reason": "bad <reason>",
                            "diff_excerpt": "-old\n+new",
                        }
                    ],
                }
            }
        },
        "runs": {
            "full": [
                {
                    "name": "<script>repo</script>",
                    "mode": "full",
                    "outcome": "failed",
                    "failure_class": "syntax_edge_case",
                    "coverage_delta": -1.5,
                    "turns": 2,
                    "cost_usd": 0.0,
                    "duration_s": 0.5,
                }
            ]
        },
    }


def test_dashboard_escapes_dynamic_content():
    html = render_dashboard(_results())
    assert "<script>alert(1)</script>" not in html
    assert "<script>repo</script>" not in html
    assert "&lt;script&gt;" in html
    assert "50.0%" in html
    assert "25.0%" in html
    assert "Failure taxonomy" in html
    assert "syntax_edge_case" in html
    assert "1.25 pp" in html


def test_dashboard_writer(tmp_path: Path):
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps(_results()), encoding="utf-8")
    out = write_dashboard(results_path, tmp_path / "dashboard.html")
    assert out.is_file()
    assert "Code Migration Agent" in out.read_text(encoding="utf-8")
