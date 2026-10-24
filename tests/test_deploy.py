"""scripts/deploy.sh with stub gcloud, curl and uv: which env vars it would deploy, no network."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "deploy.sh"
BOOTSTRAP = Path(__file__).parent.parent / "scripts" / "bootstrap.sh"
STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ -n "${FAIL_ON:-}" && "$*" == *"$FAIL_ON"* ]]; then
  printf '%s\\n' "${FAIL_MESSAGE:-fake gcloud error}" >&2
  exit 1
fi
if [[ "$*" == *"secrets versions describe"* ]]; then
  if [[ -n "${DISABLED_MATCH:-}" && "$*" == *"$DISABLED_MATCH"* ]]; then
    printf 'DISABLED\\n'
  else
    printf 'ENABLED\\n'
  fi
fi
[[ "$*" == *"services describe"* ]] && printf 'https://x.run.app\\trev-1\\n'
exit 0
"""


def deploy(tmp_path, dotenv="", **env):
    repo, bin_ = tmp_path / "repo", tmp_path / "bin"
    (repo / "scripts").mkdir(parents=True)
    bin_.mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "deploy.sh")
    # newline="\n": bash reads a CRLF stub's shebang as `bash\r` on Windows
    (repo / ".gitignore").write_text(".env\n", newline="\n")
    (repo / ".env").write_text(dotenv, newline="\n")
    for tool in ("gcloud", "curl", "uv"):
        (bin_ / tool).write_text(STUB, newline="\n")
        (bin_ / tool).chmod(0o755)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    calls = tmp_path / "calls"
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(
            ("VOICE_", "GIT_", "PRODUCER_", "CONVERSE_", "MUBIT_", "ELEVENLABS_", "DAILY_BUDGET_")
        )
    }
    run_env = {**base, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "CALLS": str(calls)}
    run_env |= {"PROJECT": "p", "DEPLOY_AS_SELF": "1", **env}
    done = subprocess.run(
        ["bash", "scripts/deploy.sh"], cwd=repo, env=run_env, capture_output=True, text=True
    )
    made = calls.read_text().splitlines() if calls.exists() else []  # none: stopped first
    deployed = next((c for c in made if "run deploy" in c), "")
    return done, deployed


def bootstrap(tmp_path, *, optional_missing=False, **env):
    repo, bin_ = tmp_path / "repo", tmp_path / "bin"
    (repo / "scripts").mkdir(parents=True)
    bin_.mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / "deploy.sh")
    shutil.copy(BOOTSTRAP, repo / "scripts" / "bootstrap.sh")
    calls, secret_data = tmp_path / "calls", tmp_path / "secret-data"
    stub = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$CALLS"
if [[ "${OPTIONAL_MISSING:-}" == 1 && \
  "$*" == *"secrets describe converse-llm-secret"* ]]; then
  exit 1
fi
if [[ -n "${FAIL_ON:-}" && "$*" == *"$FAIL_ON"* ]]; then
  printf '%s\\n' "${FAIL_MESSAGE:-fake gcloud error}" >&2
  exit 1
fi
if [[ "$*" == *"projects describe"* ]]; then printf '123456\\n'; fi
if [[ "$*" == *"secrets create converse-llm-secret"* ]]; then cat > "$SECRET_DATA"; fi
exit 0
"""
    (bin_ / "gcloud").write_text(stub, newline="\n")
    (bin_ / "gcloud").chmod(0o755)
    base = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(
            ("VOICE_", "GIT_", "PRODUCER_", "CONVERSE_", "MUBIT_", "ELEVENLABS_", "DAILY_BUDGET_")
        )
    }
    run_env = {
        **base,
        "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
        "CALLS": str(calls),
        "SECRET_DATA": str(secret_data),
        "PROJECT": "p",
        "DEPLOY_AS": "tester@example.com",
        **({"OPTIONAL_MISSING": "1"} if optional_missing else {}),
        **env,
    }
    done = subprocess.run(
        ["bash", "scripts/bootstrap.sh"], cwd=repo, env=run_env, capture_output=True, text=True
    )
    made = calls.read_text().splitlines() if calls.exists() else []
    return done, made, secret_data


def env_vars(deployed):
    return deployed.split("--set-env-vars ^@^")[1].split(" --labels ")[0].split("@")


def test_unset_voice_vars_keep_the_code_defaults(tmp_path):
    done, deployed = deploy(tmp_path, "MUBIT_API_KEY=sk-LEAK42\nVOICE_FOOTBALL=\n")
    assert done.returncode == 0, done.stderr
    assert env_vars(deployed) == [
        "MODE=cloud",
        "STORE_URL=gs://p-state/night-shift",
        "MUBIT_RECORD=off",
    ]


def test_voice_vars_come_from_env_or_dotenv_and_no_key_rides_along(tmp_path):
    dotenv = "ELEVENLABS_API_KEY=sk-LEAK42\nVOICE_CRICKET='viraj'\nVOICE_FOOTBALL=george\n"
    done, deployed = deploy(
        tmp_path, dotenv, VOICE_FOOTBALL="gU0LNdkMOQCOrPrwtbee", VOICE_MODEL_BASKETBALL="eleven_v3"
    )
    assert done.returncode == 0, done.stderr
    assert set(env_vars(deployed)) == {
        "MODE=cloud",
        "STORE_URL=gs://p-state/night-shift",
        "MUBIT_RECORD=off",  # the demo key: its app trains on none of these lines
        "VOICE_CRICKET=viraj",  # from .env
        "VOICE_FOOTBALL=gU0LNdkMOQCOrPrwtbee",  # the environment wins over .env
        "VOICE_MODEL_BASKETBALL=eleven_v3",
    }
    assert "sk-LEAK42" not in deployed


def test_live_recording_is_off_unless_asked_for(tmp_path):
    done, deployed = deploy(tmp_path, MUBIT_RECORD="on")
    assert done.returncode == 0, done.stderr
    assert "MUBIT_RECORD=on" in env_vars(deployed)


def test_a_bad_recording_setting_stops_the_deploy(tmp_path):
    done, _ = deploy(tmp_path, MUBIT_RECORD="maybe")
    assert done.returncode != 0 and "MUBIT_RECORD must be on or off" in done.stderr


def test_a_label_keeps_its_spaces_and_commas(tmp_path):
    done, deployed = deploy(tmp_path, VOICE_LABEL_CRICKET="Raju, Cricket Commentator")
    assert done.returncode == 0, done.stderr
    assert "VOICE_LABEL_CRICKET=Raju, Cricket Commentator" in env_vars(deployed)


@pytest.mark.parametrize("value", ["a@MUBIT_API_KEY=x", "$(id)", "a=b"])
def test_a_label_that_could_inject_another_var_stops_the_deploy(tmp_path, value):
    done, deployed = deploy(tmp_path, VOICE_LABEL_FOOTBALL=value)
    assert done.returncode == 1 and "VOICE_LABEL_FOOTBALL" in done.stderr and not deployed


@pytest.mark.parametrize("value", ["george,MUBIT_API_KEY=x", "a b", "$(id)"])
def test_a_voice_value_that_could_inject_another_var_stops_the_deploy(tmp_path, value):
    done, deployed = deploy(tmp_path, VOICE_FOOTBALL=value)
    assert done.returncode == 1 and "VOICE_FOOTBALL" in done.stderr and not deployed


def secrets(deployed):
    return deployed.split("--set-secrets ")[1].split(" --set-env-vars ")[0].split(",")


def test_the_owners_key_mounts_as_the_fallback_at_a_pinned_version(tmp_path):
    done, deployed = deploy(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "MUBIT_API_KEY=mubit-api-key:latest" in secrets(deployed)
    assert "MUBIT_FALLBACK_KEY=mubit-api-key:3" in secrets(deployed)


def test_the_fallback_version_can_be_overridden(tmp_path):
    done, deployed = deploy(tmp_path, MUBIT_FALLBACK_VERSION="4")
    assert done.returncode == 0, done.stderr
    assert "MUBIT_FALLBACK_KEY=mubit-api-key:4" in secrets(deployed)


def test_a_bad_fallback_version_stops_the_deploy(tmp_path):
    done, deployed = deploy(tmp_path, MUBIT_FALLBACK_VERSION="3,X=y:latest")
    assert done.returncode == 1 and "MUBIT_FALLBACK_VERSION" in done.stderr and not deployed


def test_one_instance_with_a_gibibyte(tmp_path):
    done, deployed = deploy(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "--max-instances 1 " in deployed and "--memory 1Gi " in deployed


def test_the_producer_token_is_mounted_from_its_secret_never_a_plain_env_var(tmp_path):
    done, deployed = deploy(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "PRODUCER_TOKEN=producer-token:latest" in secrets(deployed)
    assert not [v for v in env_vars(deployed) if v.startswith("PRODUCER_TOKEN")]
    assert "versions describe latest --secret producer-token" in (tmp_path / "calls").read_text()


def test_talk_bearer_is_mounted_as_a_secret_only_when_talk_is_enabled(tmp_path):
    done, deployed = deploy(
        tmp_path,
        CONVERSE_AGENT_ID="agent-1",
        CONVERSE_LLM_SECRET="dummy-talk-bearer",
    )
    assert done.returncode == 0, done.stderr
    assert "CONVERSE_LLM_SECRET=converse-llm-secret:latest" in secrets(deployed)
    assert "CONVERSE_AGENT_ID=agent-1" in env_vars(deployed)
    assert not any(v.startswith("CONVERSE_LLM_SECRET=") for v in env_vars(deployed))
    assert "dummy-talk-bearer" not in deployed + done.stdout + done.stderr

    done, deployed = deploy(tmp_path / "without-talk")
    assert done.returncode == 0, done.stderr
    assert not any(v.startswith("CONVERSE_") for v in env_vars(deployed))
    assert not any(v.startswith("CONVERSE_LLM_SECRET=") for v in secrets(deployed))


def test_bootstrap_skips_an_unconfigured_optional_talk_secret(tmp_path):
    done, calls, _ = bootstrap(tmp_path, optional_missing=True)
    assert done.returncode == 0, done.stderr
    assert any("secrets describe converse-llm-secret" in call for call in calls)
    assert not any("secrets create converse-llm-secret" in call for call in calls)
    assert not any("secrets add-iam-policy-binding converse-llm-secret" in call for call in calls)


def test_bootstrap_gives_deploy_caller_secret_scoped_metadata_viewer_only(tmp_path):
    done, calls, _ = bootstrap(tmp_path)
    assert done.returncode == 0, done.stderr
    viewer = [c for c in calls if "--role roles/secretmanager.viewer" in c]
    assert {c.split("secrets add-iam-policy-binding ")[1].split()[0] for c in viewer} == {
        "mubit-api-key",
        "elevenlabs-api-key",
        "producer-token",
        "converse-llm-secret",
    }
    assert all("--member user:tester@example.com" in c for c in viewer)
    assert not any(
        "projects add-iam-policy-binding" in c and "roles/secretmanager." in c for c in calls
    )
    assert not any(
        "--member user:tester@example.com" in c and "roles/secretmanager.secretAccessor" in c
        for c in calls
    )
    assert any(
        "--member user:tester@example.com" in c and "roles/iam.serviceAccountTokenCreator" in c
        for c in calls
    )


def test_bootstrap_uses_service_account_member_for_metadata_and_token_creator(tmp_path):
    done, calls, _ = bootstrap(tmp_path, DEPLOY_AS="deployer-caller@p.iam.gserviceaccount.com")
    assert done.returncode == 0, done.stderr
    viewer = [c for c in calls if "--role roles/secretmanager.viewer" in c]
    assert viewer and all(
        "--member serviceAccount:deployer-caller@p.iam.gserviceaccount.com" in c for c in viewer
    )
    assert any(
        "--member serviceAccount:deployer-caller@p.iam.gserviceaccount.com" in c
        and "roles/iam.serviceAccountTokenCreator" in c
        for c in calls
    )


def test_bootstrap_does_not_grant_metadata_viewer_for_absent_optional_secret(tmp_path):
    done, calls, _ = bootstrap(tmp_path, optional_missing=True)
    assert done.returncode == 0, done.stderr
    assert not any("secrets add-iam-policy-binding converse-llm-secret" in c for c in calls)


def test_bootstrap_creates_and_grants_the_talk_secret_without_printing_it(tmp_path):
    secret = "dummy-talk-bearer"
    done, calls, secret_data = bootstrap(
        tmp_path, optional_missing=True, CONVERSE_LLM_SECRET=secret
    )
    assert done.returncode == 0, done.stderr
    assert any("secrets create converse-llm-secret" in call for call in calls)
    assert any("secrets add-iam-policy-binding converse-llm-secret" in call for call in calls)
    assert secret_data.read_text() == secret
    assert secret not in done.stdout + done.stderr + "\\n".join(calls)


def test_bootstrap_grants_an_existing_talk_secret_without_recreating_it(tmp_path):
    done, calls, _ = bootstrap(tmp_path)
    assert done.returncode == 0, done.stderr
    assert any("secrets add-iam-policy-binding converse-llm-secret" in call for call in calls)
    assert not any("secrets create converse-llm-secret" in call for call in calls)


def test_a_producer_token_in_the_deploy_environment_never_reaches_the_service(tmp_path):
    done, deployed = deploy(tmp_path, PRODUCER_TOKEN="Zk3-x_9.Q/a+b=")  # a sourced producer.env
    assert done.returncode == 0, done.stderr
    assert "PRODUCER_TOKEN=producer-token:latest" in secrets(deployed)
    assert "Zk3-x_9" not in deployed + done.stderr + done.stdout


def test_the_backup_voice_keys_mount_from_a_pinned_version_that_must_exist(tmp_path):
    done, deployed = deploy(tmp_path)
    assert done.returncode == 0, done.stderr
    assert "ELEVENLABS_API_KEY=elevenlabs-api-key:latest" in secrets(deployed)
    assert "ELEVENLABS_API_KEY_FALLBACKS=elevenlabs-api-key:4" in secrets(deployed)
    calls = (tmp_path / "calls").read_text()
    assert "secrets versions describe 4 --secret elevenlabs-api-key --project p" in calls


def test_the_backup_voice_version_can_be_overridden_or_turned_off(tmp_path):
    done, deployed = deploy(tmp_path / "a", ELEVENLABS_FALLBACK_VERSION="6")
    assert "ELEVENLABS_API_KEY_FALLBACKS=elevenlabs-api-key:6" in secrets(deployed)
    done, deployed = deploy(tmp_path / "b", ELEVENLABS_FALLBACK_VERSION="none")
    assert done.returncode == 0, done.stderr
    assert not any(s.startswith("ELEVENLABS_API_KEY_FALLBACKS") for s in secrets(deployed))
    calls = (tmp_path / "b" / "calls").read_text()
    assert "versions describe latest --secret elevenlabs-api-key" in calls  # still mounted
    assert not re.search(r"versions describe \d+ --secret elevenlabs-api-key", calls)


@pytest.mark.parametrize(
    "env",
    [{"ELEVENLABS_FALLBACK_VERSION": "4,X=y:latest"}, {"FAIL_ON": "secrets versions describe"}],
)
def test_a_bad_or_missing_backup_voice_version_stops_the_deploy(tmp_path, env):
    done, deployed = deploy(tmp_path, **env)
    assert done.returncode == 1 and not deployed
    if "FAIL_ON" in env:
        assert "could not inspect elevenlabs-api-key version 4" in done.stderr
        assert "fake gcloud error" in done.stderr
    else:
        assert "ELEVENLABS_FALLBACK_VERSION" in done.stderr


def test_a_daily_budget_rides_along_only_when_set(tmp_path):
    done, deployed = deploy(tmp_path, DAILY_BUDGET_USD="80")
    assert done.returncode == 0, done.stderr
    assert "DAILY_BUDGET_USD=80" in env_vars(deployed)
    done, deployed = deploy(tmp_path / "unset")
    assert not [v for v in env_vars(deployed) if v.startswith("DAILY_BUDGET_USD")]


@pytest.mark.parametrize(
    "value",
    ["80@PRODUCER_TOKEN=oops", "80=bad", "not-a-number", "-1", "NaN", "Infinity", "1e9999"],
)
def test_a_bad_daily_budget_stops_before_any_gcloud_call(tmp_path, value):
    done, deployed = deploy(tmp_path, DAILY_BUDGET_USD=value)
    assert done.returncode == 1 and "DAILY_BUDGET_USD" in done.stderr
    assert not deployed and not (tmp_path / "calls").exists()


@pytest.mark.parametrize("value", ["0", "1.25", "2e1"])
def test_valid_daily_budget_values_are_forwarded_without_rewriting(tmp_path, value):
    done, deployed = deploy(tmp_path, DAILY_BUDGET_USD=value)
    assert done.returncode == 0, done.stderr
    assert f"DAILY_BUDGET_USD={value}" in env_vars(deployed)


def test_empty_daily_budget_uses_guard_default_and_zero_disables_it():
    from core.guard import Guard

    store = type("EmptyStore", (), {"all": lambda self, _: []})()
    assert Guard(env={}).budget == 50
    guard = Guard(env={"DAILY_BUDGET_USD": "0"})
    assert guard.budget == 0 and not guard.off_air(store)


@pytest.mark.parametrize(
    ("secret", "env"),
    [
        ("converse-llm-secret", {"CONVERSE_AGENT_ID": "agent_1"}),
        ("elevenlabs-api-key", {}),
        ("mubit-api-key", {}),
    ],
)
def test_a_missing_secret_stops_the_deploy_before_the_build(tmp_path, secret, env):
    done, deployed = deploy(tmp_path, FAIL_ON=f"--secret {secret}", **env)
    assert done.returncode == 1 and not deployed
    assert secret in done.stderr


def test_the_converse_secret_is_checked_only_when_it_will_mount(tmp_path):
    done, deployed = deploy(tmp_path, FAIL_ON="--secret converse-llm-secret")
    assert done.returncode == 0 and deployed


@pytest.mark.parametrize(
    "match,env",
    [
        ("latest --secret mubit-api-key", {}),
        ("latest --secret elevenlabs-api-key", {}),
        ("latest --secret producer-token", {}),
        ("3 --secret mubit-api-key", {}),
        ("4 --secret elevenlabs-api-key", {}),
        ("latest --secret converse-llm-secret", {"CONVERSE_AGENT_ID": "agent-1"}),
    ],
)
def test_disabled_mounted_secret_version_stops_before_deploy(tmp_path, match, env):
    done, deployed = deploy(tmp_path, DISABLED_MATCH=match, **env)
    assert done.returncode == 1 and not deployed
    assert "DISABLED" in done.stderr and match.split(" --secret")[1].strip() in done.stderr


def test_metadata_permission_error_is_not_reported_as_missing(tmp_path):
    done, deployed = deploy(
        tmp_path,
        FAIL_ON="secrets versions describe latest --secret mubit-api-key",
        FAIL_MESSAGE="PERMISSION_DENIED: caller lacks secret versions get",
    )
    assert done.returncode == 1 and not deployed
    assert "PERMISSION_DENIED" in done.stderr
    assert "does not exist" not in done.stderr


def test_enabled_mounted_secret_versions_pass(tmp_path):
    done, deployed = deploy(tmp_path)
    assert done.returncode == 0 and deployed
