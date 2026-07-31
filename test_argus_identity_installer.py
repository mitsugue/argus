import pathlib
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
    assert "systemctl daemon-reload is required but was not executed" in source
    for forbidden in (
        "systemctl enable",
        "systemctl start",
        "systemctl restart",
        "enable --now",
    ):
        assert forbidden not in source


def test_installer_has_explicit_files_and_timestamped_backup():
    source = (ROOT / "scripts/install_argus_mission_timer.sh").read_text()
    assert "scripts/production_release_manifest.py|" in source
    assert "argus-mission-tick.service|" in source
    assert "date -u +%Y%m%dT%H%M%SZ" in source
    assert "sha256 mismatch" in source
    assert "rollback destination not allowed" in source
    assert '"$previous_state" == "absent"' in source
    assert 'sudo rm -f -- "$destination"' in source
