import pathlib
import hashlib
import os
import subprocess


ROOT = pathlib.Path(__file__).parent


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
    source = (ROOT / "scripts/install_argus_mission_timer.sh").read_text()
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
    assert f'rearm_env="{credential}"' in source
    assert 'rearm_owner" == "root"' in source
    assert 'rearm_group" == "$rearm_service_user"' in source
    assert "640|440" in source
    assert "^ARGUS_REMOTE_JOURNAL_REARM_PAT=[^[:space:]#]+$" in source
    assert 'sudo -u "$rearm_service_user" test -r "$rearm_env"' in source
    assert 'rearm_service_user="argus-rearm"' in source
    assert "User=argus-rearm" in service
    assert "Group=argus-rearm" in service

    files_block = source.split("FILES=(", 1)[1].split("\n)", 1)[0]
    assert credential not in files_block
    assert "ARGUS_REMOTE_JOURNAL_REARM_PAT=" not in service
    assert 'cat "$rearm_env"' not in source
    assert 'echo "$rearm_env"' not in source
    assert source.index('rearm_env="') < source.index('timestamp="')


def test_systemd_analyze_runs_only_after_first_install_copy():
    source = (ROOT / "scripts/install_argus_mission_timer.sh").read_text()
    validator = source.split("validate_sources() {", 1)[1].split(
        "verify_installed_systemd_units() {", 1
    )[0]
    assert "systemd-analyze verify" not in validator
    assert source.count("systemd-analyze verify") == 1
    assert source.rindex("verify_installed_systemd_units") > source.index(
        'destination_sha="$(sudo sha256sum "$destination"'
    )
    assert "apply failed; installed files restored" in source


def test_installer_has_explicit_files_and_timestamped_backup():
    source = (ROOT / "scripts/install_argus_mission_timer.sh").read_text()
    assert "scripts/production_release_manifest.py|" in source
    assert "argus-mission-tick.service|" in source
    assert "date -u +%Y%m%dT%H%M%SZ" in source
    assert "sha256 mismatch" in source
    assert "rollback destination not allowed" in source
    assert '"$previous_state" == "absent"' in source
    assert 'sudo rm -f -- "$destination"' in source


def test_installer_rollback_restores_allowlisted_file(tmp_path):
    install_root = tmp_path / "install"
    backup_root = tmp_path / "backups"
    backup_id = "20260731T000000Z"
    backup_dir = backup_root / backup_id
    backup_dir.mkdir(parents=True)
    destination = install_root / "scripts/argus_mission_tick.py"
    destination.parent.mkdir(parents=True)
    destination.write_text("new\n", encoding="utf-8")
    backup = backup_dir / "argus_mission_tick.py"
    backup.write_text("old\n", encoding="utf-8")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    uid = os.getuid()
    gid = os.getgid()
    (backup_dir / "manifest.tsv").write_text(
        f"{destination}\t{backup}\t{digest}\t{uid}\t{gid}\t0644\tpresent\n",
        encoding="utf-8",
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sudo = fake_bin / "sudo"
    fake_sudo.write_text(
        "#!/bin/bash\n"
        "if [[ \"$1\" == install ]]; then\n"
        "  args=(\"$@\")\n"
        "  source=\"${args[${#args[@]}-2]}\"\n"
        "  destination=\"${args[${#args[@]}-1]}\"\n"
        "  mkdir -p \"$(dirname \"$destination\")\"\n"
        "  cp \"$source\" \"$destination\"\n"
        "  exit 0\n"
        "fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    fake_sudo.chmod(0o755)
    completed = subprocess.run(
        [
            "bash",
            "scripts/install_argus_mission_timer.sh",
            "--rollback",
            backup_id,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": f"{fake_bin}:/usr/bin:/bin",
            "ARGUS_INSTALL_ROOT": str(install_root),
            "ARGUS_INSTALL_BACKUP_ROOT": str(backup_root),
        },
    )
    assert destination.read_text(encoding="utf-8") == "old\n"
    assert "rollback restored backup=" in completed.stdout
    assert "no service start/restart/POST/heartbeat" in completed.stdout
