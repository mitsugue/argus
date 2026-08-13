#!/usr/bin/env bash
# Staged EC2 installer. It never starts/restarts services or emits a heartbeat.
set -euo pipefail

ROOT="${ARGUS_INSTALL_ROOT:-/opt/argus}"
BACKUP_ROOT="${ARGUS_INSTALL_BACKUP_ROOT:-/var/backups/argus-mission-timer}"
MODE="dry-run"
ROLLBACK_ID=""

usage() {
  echo "usage: $0 [--dry-run|--apply|--rollback BACKUP_ID]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) MODE="dry-run"; shift ;;
    --apply) MODE="apply"; shift ;;
    --rollback)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      MODE="rollback"; ROLLBACK_ID="$2"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

FILES=(
  "scripts/production_release_manifest.py|${ROOT}/scripts/production_release_manifest.py|0755"
  "scripts/argus_build_identity.py|${ROOT}/scripts/argus_build_identity.py|0755"
  "scripts/argus_mission_tick.py|${ROOT}/scripts/argus_mission_tick.py|0755"
  "scripts/argus_remote_journal_rearm.py|${ROOT}/scripts/argus_remote_journal_rearm.py|0755"
  "scripts/check_argus_mission_timer.sh|${ROOT}/scripts/check_argus_mission_timer.sh|0755"
  "ops/systemd/argus-mission-tick.service|/etc/systemd/system/argus-mission-tick.service|0644"
  "ops/systemd/argus-mission-tick.timer|/etc/systemd/system/argus-mission-tick.timer|0644"
  "ops/systemd/argus-remote-journal-rearm.service|/etc/systemd/system/argus-remote-journal-rearm.service|0644"
  "ops/systemd/argus-remote-journal-rearm.timer|/etc/systemd/system/argus-remote-journal-rearm.timer|0644"
)

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

validate_systemd_unit_shape() {
  local source="$1"
  grep -q '^\[Unit\]$' "$source" || {
    echo "invalid systemd unit: missing [Unit]: $source" >&2
    return 1
  }
  grep -q '^\[Install\]$' "$source" || {
    echo "invalid systemd unit: missing [Install]: $source" >&2
    return 1
  }
  case "$source" in
    *.service)
      grep -q '^\[Service\]$' "$source" || {
        echo "invalid systemd service: missing [Service]: $source" >&2
        return 1
      }
      grep -q '^ExecStart=' "$source" || {
        echo "invalid systemd service: missing ExecStart: $source" >&2
        return 1
      }
      ;;
    *.timer)
      grep -q '^\[Timer\]$' "$source" || {
        echo "invalid systemd timer: missing [Timer]: $source" >&2
        return 1
      }
      grep -q '^OnCalendar=' "$source" || {
        echo "invalid systemd timer: missing OnCalendar: $source" >&2
        return 1
      }
      ;;
  esac
}

validate_sources() {
  local row source destination mode
  for row in "${FILES[@]}"; do
    IFS='|' read -r source destination mode <<< "$row"
    [[ -f "$source" ]] || {
      echo "missing source: $source" >&2
      return 1
    }
    echo "validated source=$(sha256 "$source") file=$source destination=$destination mode=$mode"
    case "$source" in
      *.py)
        python3 -c \
          'import pathlib, sys; path = pathlib.Path(sys.argv[1]); compile(path.read_bytes(), str(path), "exec")' \
          "$source"
        ;;
      *.service|*.timer)
        validate_systemd_unit_shape "$source"
      ;;
    esac
  done
}

verify_installed_systemd_units() {
  command -v systemd-analyze >/dev/null 2>&1 || return 0
  local row source destination mode
  local -a installed_units=()
  for row in "${FILES[@]}"; do
    IFS='|' read -r source destination mode <<< "$row"
    case "$source" in
      *.service|*.timer) installed_units+=("$destination") ;;
    esac
  done
  # Verify only after ExecStart helpers and units have been copied.  This
  # avoids a false first-install failure and does not reload or start units.
  systemd-analyze verify "${installed_units[@]}"
}

validate_sources

if [[ "$MODE" == "dry-run" ]]; then
  echo "dry-run complete: no files changed; no daemon-reload/start/restart/POST"
  exit 0
fi

if [[ "$MODE" == "rollback" ]]; then
  [[ "$ROLLBACK_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
    echo "invalid backup id" >&2
    exit 2
  }
  backup_dir="${BACKUP_ROOT}/${ROLLBACK_ID}"
  manifest="${backup_dir}/manifest.tsv"
  [[ -f "$manifest" ]] || { echo "backup manifest missing" >&2; exit 1; }
  while IFS=$'\t' read -r destination backup sha owner group mode previous_state; do
    allowed=false
    for row in "${FILES[@]}"; do
      IFS='|' read -r _ allowed_destination _ <<< "$row"
      [[ "$destination" == "$allowed_destination" ]] && allowed=true
    done
    [[ "$destination" == "/etc/argus-mission-tick.env" ]] && allowed=true
    [[ "$allowed" == "true" ]] || {
      echo "rollback destination not allowed: $destination" >&2
      exit 1
    }
    if [[ "$previous_state" == "absent" ]]; then
      sudo rm -f -- "$destination"
      echo "rollback removed newly installed file: $destination"
      continue
    fi
    [[ "$previous_state" == "present" && -f "$backup" ]] || {
      echo "rollback artifact missing" >&2
      exit 1
    }
    [[ "$(sha256 "$backup")" == "$sha" ]] || {
      echo "rollback sha256 mismatch: $destination" >&2
      exit 1
    }
    sudo install -D -o "$owner" -g "$group" -m "$mode" \
      "$backup" "$destination"
    [[ "$(sha256 "$destination")" == "$sha" ]] || {
      echo "rollback read-back mismatch: $destination" >&2
      exit 1
    }
  done < "$manifest"
  echo "rollback restored backup=$ROLLBACK_ID"
  echo "systemctl daemon-reload is required but was not executed"
  echo "no service start/restart/POST/heartbeat was executed"
  exit 0
fi

[[ "$MODE" == "apply" ]] || {
  echo "explicit --apply is required" >&2
  exit 2
}

[[ -f /etc/argus-bridge.env ]] || {
  echo "missing /etc/argus-bridge.env; existing secret management is required" >&2
  exit 1
}

rearm_env="/etc/argus-remote-journal-rearm.env"
rearm_service_user="argus-rearm"
getent passwd "$rearm_service_user" >/dev/null || {
  echo "missing dedicated $rearm_service_user service user" >&2
  exit 1
}
getent group "$rearm_service_user" >/dev/null || {
  echo "missing dedicated $rearm_service_user service group" >&2
  exit 1
}
[[ -f "$rearm_env" && ! -L "$rearm_env" ]] || {
  echo "missing regular $rearm_env; dedicated workflow credential is required" >&2
  exit 1
}
rearm_owner="$(stat -c '%U' "$rearm_env")"
[[ "$rearm_owner" == "root" ]] || {
  echo "$rearm_env must be owned by root" >&2
  exit 1
}
rearm_group="$(stat -c '%G' "$rearm_env")"
[[ "$rearm_group" == "$rearm_service_user" ]] || {
  echo "$rearm_env must be group-owned by $rearm_service_user" >&2
  exit 1
}
rearm_mode="$(stat -c '%a' "$rearm_env")"
case "$rearm_mode" in
  640|440) ;;
  *)
    echo "unsafe permissions on $rearm_env; require 0640 (or read-only 0440)" >&2
    exit 1
    ;;
esac
sudo -u "$rearm_service_user" test -r "$rearm_env" || {
  echo "$rearm_env is not readable by the rearm service user" >&2
  exit 1
}
# Fail closed unless the file contains exactly one non-comment assignment and
# that assignment is the dedicated PAT.  Never print the assignment or value.
awk '
  /^[[:space:]]*($|#)/ { next }
  /^ARGUS_REMOTE_JOURNAL_REARM_PAT=[^[:space:]#]+$/ { allowed += 1; next }
  { invalid += 1 }
  END { exit !(allowed == 1 && invalid == 0) }
' "$rearm_env" || {
  echo "invalid dedicated credential file; require one allowed assignment" >&2
  exit 1
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${BACKUP_ROOT}/${timestamp}"
sudo install -d -o root -g root -m 0700 "$backup_dir"
manifest_tmp="$(mktemp)"
apply_in_progress="true"

restore_partial_apply() {
  local destination backup sha owner group mode previous_state
  local restore_failed=0
  while IFS=$'\t' read -r destination backup sha owner group mode previous_state; do
    if [[ "$previous_state" == "absent" ]]; then
      sudo rm -f -- "$destination" || restore_failed=1
      sudo test ! -e "$destination" || restore_failed=1
      continue
    fi
    if [[ "$previous_state" != "present" || ! -f "$backup" ]] || \
       [[ "$(sha256 "$backup")" != "$sha" ]]; then
      restore_failed=1
      continue
    fi
    sudo install -D -o "$owner" -g "$group" -m "$mode" \
      "$backup" "$destination" || restore_failed=1
    if sudo test -f "$destination"; then
      [[ "$(sudo sha256sum "$destination" | awk '{print $1}')" == "$sha" ]] || \
        restore_failed=1
    else
      restore_failed=1
    fi
  done < "$manifest_tmp"
  return "$restore_failed"
}

finish_apply() {
  local status="$1"
  trap - EXIT
  if [[ "$status" -ne 0 && "$apply_in_progress" == "true" ]]; then
    if restore_partial_apply; then
      echo "apply failed; installed files restored from verified backups" >&2
    else
      echo "apply failed; automatic restore was incomplete" >&2
    fi
  fi
  rm -f "$manifest_tmp"
  exit "$status"
}
trap 'finish_apply $?' EXIT

for row in "${FILES[@]}"; do
  IFS='|' read -r source destination default_mode <<< "$row"
  if sudo test -e "$destination"; then
    owner="$(sudo stat -c '%u' "$destination")"
    group="$(sudo stat -c '%g' "$destination")"
    mode="$(sudo stat -c '%a' "$destination")"
    backup="${backup_dir}/$(printf '%s' "$destination" | sed 's#^/##;s#/#__#g')"
    sudo install -o root -g root -m 0600 "$destination" "$backup"
    backup_sha="$(sudo sha256sum "$backup" | awk '{print $1}')"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$destination" "$backup" "$backup_sha" "$owner" "$group" "$mode" \
      "present" \
      >> "$manifest_tmp"
  else
    owner="root"
    group="root"
    mode="$default_mode"
    printf '%s\t-\t-\t%s\t%s\t%s\tabsent\n' \
      "$destination" "$owner" "$group" "$mode" >> "$manifest_tmp"
  fi
  source_sha="$(sha256 "$source")"
  sudo install -D -o "$owner" -g "$group" -m "$mode" \
    "$source" "$destination"
  destination_sha="$(sudo sha256sum "$destination" | awk '{print $1}')"
  [[ "$source_sha" == "$destination_sha" ]] || {
    echo "installed sha256 mismatch: $destination" >&2
    exit 1
  }
done

verify_installed_systemd_units

sudo install -d -o root -g root -m 0700 /var/lib/argus-build-identity
sudo install -d -o root -g root -m 0755 /run/argus-build-identity
if [[ ! -f /etc/argus-mission-tick.env ]]; then
  printf '%s\t-\t-\troot\troot\t0600\tabsent\n' \
    "/etc/argus-mission-tick.env" >> "$manifest_tmp"
  sudo install -o root -g root -m 0600 \
    ops/systemd/argus-mission-tick.env.example \
    /etc/argus-mission-tick.env
fi
sudo install -o root -g root -m 0600 "$manifest_tmp" \
  "${backup_dir}/manifest.tsv"
apply_in_progress="false"

echo "install complete backup=$timestamp"
echo "systemctl daemon-reload is required but was not executed"
echo "no service enable/start/restart/POST/heartbeat was executed"
