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
  "scripts/check_argus_mission_timer.sh|${ROOT}/scripts/check_argus_mission_timer.sh|0755"
  "ops/systemd/argus-mission-tick.service|/etc/systemd/system/argus-mission-tick.service|0644"
  "ops/systemd/argus-mission-tick.timer|/etc/systemd/system/argus-mission-tick.timer|0644"
)

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
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
      *.py) python3 -m py_compile "$source" ;;
      *.service|*.timer)
        if command -v systemd-analyze >/dev/null 2>&1; then
          systemd-analyze verify "$source"
        fi
        ;;
    esac
  done
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

[[ -f /etc/argus-bridge.env ]] || {
  echo "missing /etc/argus-bridge.env; existing secret management is required" >&2
  exit 1
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${BACKUP_ROOT}/${timestamp}"
sudo install -d -o root -g root -m 0700 "$backup_dir"
manifest_tmp="$(mktemp)"
trap 'rm -f "$manifest_tmp"' EXIT

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

echo "install complete backup=$timestamp"
echo "systemctl daemon-reload is required but was not executed"
echo "no service enable/start/restart/POST/heartbeat was executed"
