"""scripts/deploy.sh with stub gcloud, curl and uv: which env vars it would deploy, no network."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "deploy.sh"
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
[[ "$*" == *"services describe"* ]] && printf 'https://x.run.app\\trev-1\\n'
exit 0
"""


def deploy(tmp_path, dotenv="", **env):
    repo, bin_ = tmp_path / "repo", tmp_path / "bin"
    (repo / "scripts").mkdir(parents=True)
    bin_.mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "deploy.sh")
    (repo / ".gitignore").write_text(".env\n")
    (repo / ".env").write_text(dotenv)
    for tool in ("gcloud", "curl", "uv"):
        (bin_ / tool).write_text(STUB)
        (bin_ / tool).chmod(0o755)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    calls = tmp_path / "calls"
    base = {k: v for k, v in os.environ.items() if not k.startswith(("VOICE_", "GIT_"))}
    run_env = {**base, "PATH": f"{bin_}:{os.environ['PATH']}", "CALLS": str(calls)}
    run_env |= {"PROJECT": "p", "DEPLOY_AS_SELF": "1", **env}
    done = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=repo, env=run_env, capture_output=True, text=True
    )
    deployed = next((c for c in calls.read_text().splitlines() if "run deploy" in c), "")
    return done, deployed


def env_vars(deployed):
    return deployed.split("--set-env-vars ")[1].split(" ")[0].split(",")


def test_unset_voice_vars_keep_the_code_defaults(tmp_path):
    done, deployed = deploy(tmp_path, "MUBIT_API_KEY=sk-LEAK42\nVOICE_FOOTBALL=\n")
    assert done.returncode == 0, done.stderr
    assert env_vars(deployed) == ["MODE=cloud", "STORE_URL=gs://p-state/night-shift"]


def test_voice_vars_come_from_env_or_dotenv_and_no_key_rides_along(tmp_path):
    dotenv = "ELEVENLABS_API_KEY=sk-LEAK42\nVOICE_CRICKET='viraj'\nVOICE_FOOTBALL=george\n"
    done, deployed = deploy(
        tmp_path, dotenv, VOICE_FOOTBALL="gU0LNdkMOQCOrPrwtbee", VOICE_MODEL_BASKETBALL="eleven_v3"
    )
    assert done.returncode == 0, done.stderr
    assert set(env_vars(deployed)) == {
        "MODE=cloud",
        "STORE_URL=gs://p-state/night-shift",
        "VOICE_CRICKET=viraj",  # from .env
        "VOICE_FOOTBALL=gU0LNdkMOQCOrPrwtbee",  # the environment wins over .env
        "VOICE_MODEL_BASKETBALL=eleven_v3",
    }
    assert "sk-LEAK42" not in deployed


@pytest.mark.parametrize("value", ["george,MUBIT_API_KEY=x", "a b", "$(id)"])
def test_a_voice_value_that_could_inject_another_var_stops_the_deploy(tmp_path, value):
    done, deployed = deploy(tmp_path, VOICE_FOOTBALL=value)
    assert done.returncode == 1 and "VOICE_FOOTBALL" in done.stderr and not deployed
