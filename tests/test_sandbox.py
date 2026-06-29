import sys

import pytest

from code_migration_agent.runtime.sandbox import LocalSandbox, SandboxError, copy_repo


def test_runs_command_in_workspace(tmp_path):
    sandbox = LocalSandbox(tmp_path)
    result = sandbox.run([sys.executable, "-c", "print('ok')"])
    assert result.returncode == 0
    assert "ok" in result.stdout
    assert not result.timed_out


def test_timeout_kills_process_group(tmp_path):
    sandbox = LocalSandbox(tmp_path, default_timeout_s=0.2)
    result = sandbox.run([sys.executable, "-c", "import time; time.sleep(5)"])
    assert result.timed_out
    assert result.returncode != 0
    assert result.duration_s < 4.0


def test_rejects_cwd_outside_workspace(tmp_path):
    sandbox = LocalSandbox(tmp_path)
    with pytest.raises(SandboxError):
        sandbox.run([sys.executable, "-c", "pass"], cwd=tmp_path.parent)


def test_truncates_large_output(tmp_path):
    sandbox = LocalSandbox(tmp_path)
    result = sandbox.run([sys.executable, "-c", "print('x' * 30000)"])
    assert result.returncode == 0
    assert len(result.stdout) < 30_000
    assert "truncated" in result.stdout


def test_copy_repo_ignores_git_and_pycache(tmp_path):
    source = tmp_path / "source"
    (source / ".git").mkdir(parents=True)
    (source / ".git" / "config").write_text("secret", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "x.pyc").write_bytes(b"x")
    (source / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    destination = tmp_path / "copy"
    copy_repo(source, destination)
    assert (destination / "app.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    assert not (destination / ".git").exists()
    assert not (destination / "__pycache__").exists()
