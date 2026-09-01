import pathlib
import hashlib
import os
import re
import shutil
import subprocess


ROOT = pathlib.Path(__file__).parent
REARM_INSTALLER = ROOT / "scripts/install_argus_remote_journal_rearm.sh"
WRITER_INSTALLER = ROOT / "scripts/install_argus_watchtower_writer.sh"


def _rearm_test_environment(tmp_path, *, identity="valid"):
    test_root = tmp_path / "root"
    (test_root / "etc/systemd/system").mkdir(parents=True)
    (test_root / "etc").mkdir(exist_ok=True)
    credential = test_root / "etc/argus-remote-journal-rearm.env"
    credential.write_text(
        "ARGUS_REMOTE_JOURNAL_REARM_PAT=test-secret-never-printed\n",
        encoding="utf-8",
    )
    credential.chmod(0o640)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "if [[ \"${1:-}\" == -u ]]; then shift 2; fi\n"
        "if [[ \"${1:-}\" == install ]]; then\n"
        "  shift\n"
        "  args=()\n"
        "  while [[ $# -gt 0 ]]; do\n"
        "    case \"$1\" in\n"
        "      -o|-g) shift 2 ;;\n"
        "      *) args+=(\"$1\"); shift ;;\n"
        "    esac\n"
        "  done\n"
        "  exec /usr/bin/install \"${args[@]}\"\n"
        "fi\n"
        "if [[ \"${1:-}\" == mv ]]; then\n"
        "  shift\n"
        "  args=()\n"
        "  for value in \"$@\"; do\n"
        "    [[ \"$value\" == -fT ]] && value=-f\n"
        "    args+=(\"$value\")\n"
        "  done\n"
        "  exec /bin/mv \"${args[@]}\"\n"
        "fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)

    fake_getent = fake_bin / "getent"
    fake_getent.write_text(
        "#!/bin/bash\n"
        "if [[ \"${FAKE_GETENT_MODE:-valid}\" == missing ]]; then exit 2; fi\n"
        "uid=\"${ARGUS_REARM_INSTALL_TEST_UID}\"\n"
        "gid=\"${ARGUS_REARM_INSTALL_TEST_GID}\"\n"
        "[[ \"${FAKE_GETENT_MODE:-valid}\" == wrong ]] && uid=$((uid + 1))\n"
        "case \"$1\" in\n"
        "  passwd) echo \"argus-rearm:x:${uid}:${gid}::/nonexistent:/usr/sbin/nologin\" ;;\n"
        "  group) echo \"argus-rearm:x:${gid}:\" ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_getent.chmod(0o755)

    # Normalize GNU stat's formats on both Linux CI and the developer Mac.
    fake_stat = fake_bin / "stat"
    fake_stat.write_text(
        "#!/usr/bin/env python3\n"
        "import grp, os, pwd, stat, sys\n"
        "fmt, path = sys.argv[2], sys.argv[3]\n"
        "value = os.stat(path, follow_symlinks=False)\n"
        "values = {\n"
        "    '%U': pwd.getpwuid(value.st_uid).pw_name,\n"
        "    '%G': grp.getgrgid(value.st_gid).gr_name,\n"
        "    '%u': str(value.st_uid),\n"
        "    '%g': str(value.st_gid),\n"
        "    '%a': format(stat.S_IMODE(value.st_mode), 'o'),\n"
        "}\n"
        "if fmt == '%U:%G:%a':\n"
        "    print(f\"root:root:{values['%a']}\")\n"
        "else:\n"
        "    print(values[fmt])\n",
        encoding="utf-8",
    )
    fake_stat.chmod(0o755)

    fake_systemd_analyze = fake_bin / "systemd-analyze"
    fake_systemd_analyze.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    fake_systemd_analyze.chmod(0o755)

    environment = {
        "PATH": f"{fake_bin}:/usr/local/bin:/usr/bin:/bin",
        "ARGUS_REARM_INSTALL_TEST_MODE": "1",
        "ARGUS_REARM_INSTALL_TEST_ROOT": str(test_root),
        "ARGUS_REARM_INSTALL_TEST_UID": str(os.getuid()),
        "ARGUS_REARM_INSTALL_TEST_GID": str(os.getgid()),
        "ARGUS_REARM_INSTALL_TEST_CREDENTIAL_OWNER": credential.owner(),
        "ARGUS_REARM_INSTALL_TEST_CREDENTIAL_GROUP": credential.group(),
        "FAKE_GETENT_MODE": identity,
    }
    return test_root, credential, environment


def _writer_test_environment(tmp_path, *, identity="valid"):
    test_root = tmp_path / "root"
    (test_root / "etc/systemd/system").mkdir(parents=True)
    (test_root / "etc").mkdir(exist_ok=True)
    credential = test_root / "etc/argus-remote-journal-rearm.env"
    credential.write_text(
        "ARGUS_REMOTE_JOURNAL_REARM_PAT=github_pat_test_secret_never_printed\n",
        encoding="utf-8",
    )
    credential.chmod(0o640)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_getent = fake_bin / "getent"
    fake_getent.write_text(
        "#!/bin/bash\n"
        "if [[ \"${FAKE_GETENT_MODE:-valid}\" == missing ]]; then exit 2; fi\n"
        "uid=\"${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_UID}\"\n"
        "gid=\"${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_GID}\"\n"
        "[[ \"${FAKE_GETENT_MODE:-valid}\" == wrong ]] && uid=$((uid + 1))\n"
        "case \"$1\" in\n"
        "  passwd) echo \"argus-rearm:x:${uid}:${gid}::/nonexistent:/usr/sbin/nologin\" ;;\n"
        "  group) echo \"argus-rearm:x:${gid}:\" ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_getent.chmod(0o755)
    fake_systemd_analyze = fake_bin / "systemd-analyze"
    fake_systemd_analyze.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    fake_systemd_analyze.chmod(0o755)

    environment = {
        "PATH": f"{fake_bin}:/usr/local/bin:/usr/bin:/bin",
        "ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_MODE": "1",
        "ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_ROOT": str(test_root),
        "ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_UID": str(os.getuid()),
        "ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_GID": str(os.getgid()),
        "ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_ROOT_UID": str(os.getuid()),
        "ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_ROOT_GID": str(os.getgid()),
        "FAKE_GETENT_MODE": identity,
    }
    return test_root, credential, environment


def test_installer_dry_run_has_no_service_or_file_mutation(tmp_path):
    completed = subprocess.run(
        ["bash", "scripts/install_argus_mission_timer.sh", "--dry-run"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "ARGUS_INSTALL_ROOT": str(tmp_path)},
    )
    assert "dry-run complete" in completed.stdout
    assert not (tmp_path / "scripts").exists()


def test_installer_requires_explicit_apply_and_never_runs_service_actions():
    source = (ROOT / "scripts/install_argus_mission_timer.sh").read_text()
    assert 'MODE="dry-run"' in source
    assert "compile(path.read_bytes()" in source
    assert "py_compile" not in source
    assert 'validate_systemd_unit_shape "$source"' in source
    assert '"$MODE" == "apply"' in source
    assert "systemctl daemon-reload is required but was not executed" in source
    for forbidden in (
        "systemctl enable",
        "systemctl start",
        "systemctl restart",
        "enable --now",
    ):
        assert forbidden not in source


def test_rearm_credential_is_dedicated_preflight_only_and_secret_safe():
    source = REARM_INSTALLER.read_text()
    mission_installer = (
        ROOT / "scripts/install_argus_mission_timer.sh"
    ).read_text()
    service = (
        ROOT / "ops/systemd/argus-remote-journal-rearm.service"
    ).read_text()
    mission = (ROOT / "ops/systemd/argus-mission-tick.service").read_text()
    credential = "/etc/argus-remote-journal-rearm.env"

    assert f"EnvironmentFile={credential}" in service
    assert credential not in mission
    assert "argus-trigger.env" not in service
    assert "GH_WORKFLOW_PAT" not in service
    assert "GH_WORKFLOW_PAT" not in source
    assert f'ENV_FILE="{credential}"' in source
    assert 'CREDENTIAL_OWNER="root"' in source
    assert 'CREDENTIAL_GROUP="$SERVICE_USER"' in source
    assert "640|440" in source
    assert "^ARGUS_REMOTE_JOURNAL_REARM_PAT=[^[:space:]#]+$" in source
    assert 'sudo -u "$SERVICE_USER" test -r "$ENV_FILE"' in source
    assert 'SERVICE_USER="argus-rearm"' in source
    assert "User=argus-rearm" in service
    assert "Group=argus-rearm" in service

    files_block = source.split("FILES=(", 1)[1].split("\n)", 1)[0]
    assert credential not in files_block
    assert "ARGUS_REMOTE_JOURNAL_REARM_PAT=" not in service
    assert 'echo "$ENV_FILE"' not in source
    assert "ARGUS_REMOTE_JOURNAL_REARM_PAT" not in mission_installer
    assert "argus_remote_journal_rearm.py" not in mission_installer
    assert "argus-remote-journal-rearm.service" not in mission_installer
    assert source.index('ENV_FILE="') < source.index('timestamp="')


def test_rearm_systemd_analyze_runs_only_after_install_copy():
    source = REARM_INSTALLER.read_text()
    validator = source.split("validate_sources() {", 1)[1].split(
        "validate_identity() {", 1
    )[0]
    assert "systemd-analyze verify" not in validator
    assert source.count("systemd-analyze verify") == 1
    assert source.index("systemd-analyze verify") > source.index(
        'installed rearm sha256 mismatch:'
    )
    assert "apply failed; destinations restored" in source


def test_rearm_installer_has_only_explicit_isolated_destinations():
    source = REARM_INSTALLER.read_text()
    files_block = source.split("FILES=(", 1)[1].split("\n)", 1)[0]
    assert "scripts/argus_remote_journal_rearm.py|" in files_block
    assert "/opt/argus-rearm" in source
    assert files_block.count('"') == 6
    assert "bridge/" not in files_block
    assert "argus_mission_tick" not in files_block
    assert "/opt/argus/" not in files_block
    assert "date -u +%Y%m%dT%H%M%SZ" in source
    assert "sha256 mismatch" in source
    assert "rollback destination not allowed" in source
    assert '"$previous" == "absent"' in source
    assert 'sudo rm -f -- "$destination"' in source
    for forbidden in (
        "sudo systemctl daemon-reload",
        "sudo systemctl enable",
        "sudo systemctl start",
        "sudo systemctl restart",
        "workflow_dispatch",
    ):
        assert forbidden not in source


def test_rearm_source_hash_validation_fails_closed(tmp_path):
    source_root = tmp_path / "source"
    shutil.copytree(ROOT / "scripts", source_root / "scripts")
    shutil.copytree(ROOT / "ops/systemd", source_root / "ops/systemd")
    service = source_root / "ops/systemd/argus-remote-journal-rearm.service"
    service.write_text(service.read_text() + "# mutation\n", encoding="utf-8")
    completed = subprocess.run(
        ["bash", str(source_root / "scripts/install_argus_remote_journal_rearm.sh")],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin"},
    )
    assert completed.returncode != 0
    assert "source sha256 mismatch" in completed.stderr


def test_rearm_apply_and_rollback_are_isolated_from_dirty_opt_argus(tmp_path):
    test_root, _, environment = _rearm_test_environment(tmp_path)
    dirty_bridge = test_root / "opt/argus/bridge/moomoo_push.py"
    mission = test_root / "opt/argus/scripts/argus_mission_tick.py"
    dirty_bridge.parent.mkdir(parents=True)
    mission.parent.mkdir(parents=True)
    dirty_bridge.write_text("dirty bridge\n", encoding="utf-8")
    mission.write_text("live mission\n", encoding="utf-8")

    runtime = test_root / "opt/argus-rearm"
    runtime.mkdir()
    destinations = {
        runtime / "argus_remote_journal_rearm.py": "old script\n",
        test_root / "etc/systemd/system/argus-remote-journal-rearm.service":
            "old service\n",
        test_root / "etc/systemd/system/argus-remote-journal-rearm.timer":
            "old timer\n",
    }
    for path, contents in destinations.items():
        path.write_text(contents, encoding="utf-8")

    applied = subprocess.run(
        ["bash", str(REARM_INSTALLER), "--apply"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    backup_id = re.search(r"backup=([0-9]{8}T[0-9]{6}Z)", applied.stdout)
    assert backup_id is not None
    assert "test-secret-never-printed" not in applied.stdout
    assert "test-secret-never-printed" not in applied.stderr
    assert dirty_bridge.read_text(encoding="utf-8") == "dirty bridge\n"
    assert mission.read_text(encoding="utf-8") == "live mission\n"
    assert hashlib.sha256(
        (runtime / "argus_remote_journal_rearm.py").read_bytes()
        ).hexdigest() == "9654ebab669de9d1b33692f13fcc6dc444a7a914e1a28473f3e4309fc325df35"

    rolled_back = subprocess.run(
        ["bash", str(REARM_INSTALLER), "--rollback", backup_id.group(1)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    for path, contents in destinations.items():
        assert path.read_text(encoding="utf-8") == contents
    assert "rollback restored backup=" in rolled_back.stdout
    assert dirty_bridge.read_text(encoding="utf-8") == "dirty bridge\n"
    assert mission.read_text(encoding="utf-8") == "live mission\n"


def test_rearm_preflight_fails_closed_for_credential_and_identity(tmp_path):
    _, credential, environment = _rearm_test_environment(tmp_path)
    credential.unlink()
    missing_credential = subprocess.run(
        ["bash", str(REARM_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment,
    )
    assert missing_credential.returncode != 0
    assert "missing regular" in missing_credential.stderr

    _, credential, environment = _rearm_test_environment(tmp_path / "mode")
    credential.chmod(0o600)
    wrong_metadata = subprocess.run(
        ["bash", str(REARM_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment,
    )
    assert wrong_metadata.returncode != 0
    assert "unsafe permissions" in wrong_metadata.stderr

    _, _, environment = _rearm_test_environment(tmp_path / "missing-user",
                                                 identity="missing")
    missing_identity = subprocess.run(
        ["bash", str(REARM_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment,
    )
    assert missing_identity.returncode != 0
    assert "missing dedicated" in missing_identity.stderr

    _, _, environment = _rearm_test_environment(tmp_path / "wrong-user",
                                                 identity="wrong")
    wrong_identity = subprocess.run(
        ["bash", str(REARM_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment,
    )
    assert wrong_identity.returncode != 0
    assert "identity mismatch" in wrong_identity.stderr


def test_writer_installer_scope_is_isolated_secret_safe_and_inactive():
    source = WRITER_INSTALLER.read_text(encoding="utf-8")
    service = (ROOT / "ops/systemd/argus-watchtower-writer.service").read_text()
    timer = (ROOT / "ops/systemd/argus-watchtower-writer.timer").read_text()
    files_block = source.split("FILES=(", 1)[1].split("\n)", 1)[0]
    assert files_block.count('"') == 6
    assert "scripts/argus_watchtower_writer_dispatch.py|" in files_block
    assert "ops/systemd/argus-watchtower-writer.service|" in files_block
    assert "ops/systemd/argus-watchtower-writer.timer|" in files_block
    assert "/opt/argus-watchtower-writer" in source
    assert "/var/lib/argus-watchtower-writer" in source
    assert "/opt/argus/" not in files_block
    assert "/opt/argus-rearm/" not in files_block
    assert "/etc/argus-remote-journal-rearm.env" not in files_block
    assert "ARGUS_REMOTE_JOURNAL_REARM_PAT=" not in service
    assert "EnvironmentFile=/etc/argus-remote-journal-rearm.env" in service
    assert "User=argus-rearm" in service
    assert "Group=argus-rearm" in service
    assert "Type=oneshot" in service
    assert "StateDirectoryMode=0700" in service
    assert "Persistent=true" in timer
    assert "AccuracySec=1us" in timer
    assert "RandomizedDelaySec=0" in timer
    assert "workflow_dispatch" not in source
    for forbidden in (
        "\nsystemctl daemon-reload", "\nsystemctl enable",
        "\nsystemctl start", "\nsystemctl restart", "enable --now",
        "sudo -v",
    ):
        assert forbidden not in source
    assert "no daemon-reload/enable/start/restart/dispatch was executed" in source
    assert "writer rollback destination not allowed" in source
    assert "writer apply failed; destinations restored" in source


def test_writer_installer_apply_and_rollback_preserve_other_runtimes(tmp_path):
    test_root, _, environment = _writer_test_environment(tmp_path)
    dirty_argus = test_root / "opt/argus/bridge/moomoo_push.py"
    rearm = test_root / "opt/argus-rearm/argus_remote_journal_rearm.py"
    dirty_argus.parent.mkdir(parents=True)
    rearm.parent.mkdir(parents=True)
    dirty_argus.write_text("dirty argus\n", encoding="utf-8")
    rearm.write_text("live rearm\n", encoding="utf-8")

    runtime = test_root / "opt/argus-watchtower-writer"
    runtime.mkdir()
    destinations = {
        runtime / "argus_watchtower_writer_dispatch.py": "old writer\n",
        test_root / "etc/systemd/system/argus-watchtower-writer.service":
            "old service\n",
        test_root / "etc/systemd/system/argus-watchtower-writer.timer":
            "old timer\n",
    }
    for path, contents in destinations.items():
        path.write_text(contents, encoding="utf-8")

    dry_run = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--dry-run"], cwd=ROOT,
        check=True, capture_output=True, text=True, env=environment)
    assert "no files changed" in dry_run.stdout
    assert (runtime / "argus_watchtower_writer_dispatch.py").read_text() == \
        "old writer\n"

    applied = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--apply"], cwd=ROOT,
        check=True, capture_output=True, text=True, env=environment)
    backup_id = re.search(r"backup=([0-9]{8}T[0-9]{6}Z)", applied.stdout)
    assert backup_id is not None
    assert "github_pat_test_secret_never_printed" not in \
        applied.stdout + applied.stderr
    assert dirty_argus.read_text() == "dirty argus\n"
    assert rearm.read_text() == "live rearm\n"
    state_root = test_root / "var/lib/argus-watchtower-writer"
    assert state_root.is_dir()
    assert (state_root.stat().st_mode & 0o777) == 0o700

    rolled_back = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--rollback", backup_id.group(1)],
        cwd=ROOT, check=True, capture_output=True, text=True, env=environment)
    for path, contents in destinations.items():
        assert path.read_text(encoding="utf-8") == contents
    assert not state_root.exists()
    assert "writer rollback restored backup=" in rolled_back.stdout
    assert dirty_argus.read_text() == "dirty argus\n"
    assert rearm.read_text() == "live rearm\n"


def test_writer_installer_preflight_rejects_bad_identity_and_credential(tmp_path):
    _, credential, environment = _writer_test_environment(tmp_path / "mode")
    credential.chmod(0o600)
    wrong_mode = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment)
    assert wrong_mode.returncode != 0
    assert "unsafe writer credential metadata" in wrong_mode.stderr

    _, credential, environment = _writer_test_environment(tmp_path / "shape")
    credential.write_text(
        "ARGUS_REMOTE_JOURNAL_REARM_PAT=secret\nEXTRA=value\n",
        encoding="utf-8")
    credential.chmod(0o640)
    wrong_shape = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment)
    assert wrong_shape.returncode != 0
    assert "invalid dedicated writer credential" in wrong_shape.stderr
    assert "secret" not in wrong_shape.stdout + wrong_shape.stderr

    _, _, environment = _writer_test_environment(
        tmp_path / "identity", identity="wrong")
    wrong_identity = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment)
    assert wrong_identity.returncode != 0
    assert "identity mismatch" in wrong_identity.stderr

    test_root, _, environment = _writer_test_environment(
        tmp_path / "state-mode")
    state_root = test_root / "var/lib/argus-watchtower-writer"
    state_root.mkdir(parents=True, mode=0o755)
    state_root.chmod(0o755)
    wrong_state = subprocess.run(
        ["bash", str(WRITER_INSTALLER), "--dry-run"], cwd=ROOT,
        check=False, capture_output=True, text=True, env=environment)
    assert wrong_state.returncode != 0
    assert "writer state root metadata mismatch" in wrong_state.stderr


def test_writer_source_hash_validation_fails_closed(tmp_path):
    source_root = tmp_path / "source"
    shutil.copytree(ROOT / "scripts", source_root / "scripts")
    shutil.copytree(ROOT / "ops/systemd", source_root / "ops/systemd")
    service = source_root / "ops/systemd/argus-watchtower-writer.service"
    service.write_text(service.read_text() + "# mutation\n", encoding="utf-8")
    completed = subprocess.run(
        ["bash", str(source_root / "scripts/install_argus_watchtower_writer.sh")],
        check=False, capture_output=True, text=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin"})
    assert completed.returncode != 0
    assert "writer source sha256 mismatch" in completed.stderr
