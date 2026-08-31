#!/usr/bin/env bash
# Install only the isolated EC2 Watchtower writer runtime and systemd units.
# Activation is deliberately separate: this script never daemon-reloads,
# enables, starts, restarts, or dispatches a workflow.
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUNTIME_ROOT="/opt/argus-watchtower-writer"
STATE_ROOT="/var/lib/argus-watchtower-writer"
SYSTEMD_ROOT="/etc/systemd/system"
BACKUP_ROOT="/var/backups/argus-watchtower-writer"
ENV_FILE="/etc/argus-remote-journal-rearm.env"
SERVICE_USER="argus-rearm"
SERVICE_GROUP="argus-rearm"
EXPECTED_UID="997"
EXPECTED_GID="982"
EXPECTED_HOME="/nonexistent"
EXPECTED_SHELL="/usr/sbin/nologin"
ROOT_UID="0"
ROOT_GID="0"
MODE="source-check"
ROLLBACK_ID=""
PENDING_TEMP=""
TEST_MODE="${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_MODE:-0}"

if [[ "$TEST_MODE" == "1" ]]; then
  test_root="${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_ROOT:?test root required}"
  [[ "$test_root" == /* && "$test_root" != "/" && ! -L "$test_root" ]] || {
    echo "unsafe writer installer test root" >&2
    exit 2
  }
  RUNTIME_ROOT="${test_root}/opt/argus-watchtower-writer"
  STATE_ROOT="${test_root}/var/lib/argus-watchtower-writer"
  SYSTEMD_ROOT="${test_root}/etc/systemd/system"
  BACKUP_ROOT="${test_root}/var/backups/argus-watchtower-writer"
  ENV_FILE="${test_root}/etc/argus-remote-journal-rearm.env"
  EXPECTED_UID="${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_UID:?test uid required}"
  EXPECTED_GID="${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_GID:?test gid required}"
  ROOT_UID="${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_ROOT_UID:?test root uid required}"
  ROOT_GID="${ARGUS_WATCHTOWER_WRITER_INSTALL_TEST_ROOT_GID:?test root gid required}"
fi

# Re-pinned only after the exact candidate source bytes are final.
SCRIPT_SHA256="b25feffa94308f869cae0b855e7af37e068d48bbbc7b1680b364dec811b7dfca"
SERVICE_SHA256="c28b3c947139dfc42776b55124b1ddc14a8cdbd32e7fb5ccc0c854ab6d371b7e"
TIMER_SHA256="45e1980efa5099b8cf3464dddc3418ddf5da2d1674d4f6b85103a2b5388dd7a6"

usage() {
  echo "usage: $0 [--source-check|--dry-run|--apply|--rollback BACKUP_ID]" >&2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-check) MODE="source-check"; shift ;;
    --dry-run) MODE="dry-run"; shift ;;
    --apply) MODE="apply"; shift ;;
    --rollback)
      [[ $# -ge 2 ]] || { usage; exit 2; }
      MODE="rollback"; ROLLBACK_ID="$2"; shift 2 ;;
    *) usage; exit 2 ;;
  esac
done

FILES=(
  "scripts/argus_watchtower_writer_dispatch.py|${RUNTIME_ROOT}/argus_watchtower_writer_dispatch.py|0755|${SCRIPT_SHA256}"
  "ops/systemd/argus-watchtower-writer.service|${SYSTEMD_ROOT}/argus-watchtower-writer.service|0644|${SERVICE_SHA256}"
  "ops/systemd/argus-watchtower-writer.timer|${SYSTEMD_ROOT}/argus-watchtower-writer.timer|0644|${TIMER_SHA256}"
)

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

metadata() {
  python3 - "$1" <<'PY'
import os
import stat
import sys

value = os.lstat(sys.argv[1])
print(f"{value.st_uid}:{value.st_gid}:{stat.S_IMODE(value.st_mode):o}")
PY
}

require_privilege() {
  if [[ "$TEST_MODE" != "1" && "$EUID" -ne 0 ]]; then
    echo "writer installer mutation requires non-interactive root execution" >&2
    return 1
  fi
}

allowed_destination() {
  local candidate="$1" row source destination mode expected
  for row in "${FILES[@]}"; do
    IFS='|' read -r source destination mode expected <<< "$row"
    [[ "$candidate" == "$destination" ]] && return 0
  done
  return 1
}

validate_unit_shape() {
  local source="$1"
  grep -q '^\[Unit\]$' "$source"
  grep -q '^\[Install\]$' "$source"
  case "$source" in
    *.service)
      grep -q '^\[Service\]$' "$source"
      grep -q '^Type=oneshot$' "$source"
      grep -q '^User=argus-rearm$' "$source"
      grep -q '^Group=argus-rearm$' "$source"
      grep -q '^EnvironmentFile=/etc/argus-remote-journal-rearm.env$' "$source"
      grep -q '^ExecStart=/usr/bin/python3 /opt/argus-watchtower-writer/argus_watchtower_writer_dispatch.py$' "$source"
      grep -q '^StateDirectory=argus-watchtower-writer$' "$source"
      ;;
    *.timer)
      grep -q '^\[Timer\]$' "$source"
      grep -q '^OnCalendar=Mon\.\.Fri \*-\*-\* \*:04,11,19,26,34,41,49,56:00 UTC$' "$source"
      grep -q '^OnCalendar=Sat,Sun \*-\*-\* \*:04,34:00 UTC$' "$source"
      grep -q '^Persistent=true$' "$source"
      grep -q '^AccuracySec=1us$' "$source"
      grep -q '^RandomizedDelaySec=0$' "$source"
      grep -q '^Unit=argus-watchtower-writer.service$' "$source"
      ;;
  esac
}

validate_sources() {
  local row relative destination mode expected source actual
  for row in "${FILES[@]}"; do
    IFS='|' read -r relative destination mode expected <<< "$row"
    source="${SOURCE_ROOT}/${relative}"
    [[ -f "$source" && ! -L "$source" ]] || {
      echo "writer source is missing or not a regular file: $relative" >&2
      return 1
    }
    actual="$(sha256 "$source")"
    [[ "$actual" == "$expected" ]] || {
      echo "writer source sha256 mismatch: $relative actual=$actual expected=$expected" >&2
      return 1
    }
    case "$source" in
      *.py)
        PYTHONDONTWRITEBYTECODE=1 python3 -c \
          'import pathlib,sys; p=pathlib.Path(sys.argv[1]); compile(p.read_bytes(), str(p), "exec")' \
          "$source"
        ;;
      *.service|*.timer) validate_unit_shape "$source" ;;
    esac
    echo "validated writer source sha256=$actual file=$relative destination=$destination mode=$mode"
  done
}

validate_identity() {
  local passwd group passwd_name uid gid home shell group_name group_gid
  passwd="$(getent passwd "$SERVICE_USER")" || {
    echo "missing dedicated $SERVICE_USER service user" >&2
    return 1
  }
  group="$(getent group "$SERVICE_GROUP")" || {
    echo "missing dedicated $SERVICE_GROUP service group" >&2
    return 1
  }
  IFS=: read -r passwd_name _ uid gid _ home shell <<< "$passwd"
  IFS=: read -r group_name _ group_gid _ <<< "$group"
  [[ "$passwd_name" == "$SERVICE_USER" && \
     "$group_name" == "$SERVICE_GROUP" && \
     "$uid" == "$EXPECTED_UID" && "$gid" == "$EXPECTED_GID" && \
     "$group_gid" == "$EXPECTED_GID" && "$home" == "$EXPECTED_HOME" && \
     "$shell" == "$EXPECTED_SHELL" ]] || {
    echo "dedicated $SERVICE_USER service identity mismatch" >&2
    return 1
  }
}

validate_credential() {
  local value
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || {
    echo "missing regular writer credential file" >&2
    return 1
  }
  value="$(metadata "$ENV_FILE")"
  case "$value" in
    "${ROOT_UID}:${EXPECTED_GID}:640"|"${ROOT_UID}:${EXPECTED_GID}:440") ;;
    *)
      echo "unsafe writer credential metadata; require root:argus-rearm 0640 or 0440" >&2
      return 1
      ;;
  esac
  awk '
    /^[[:space:]]*($|#)/ { next }
    /^ARGUS_REMOTE_JOURNAL_REARM_PAT=[^[:space:]#]+$/ { allowed += 1; next }
    { invalid += 1 }
    END { exit !(allowed == 1 && invalid == 0) }
  ' "$ENV_FILE" || {
    echo "invalid dedicated writer credential file structure" >&2
    return 1
  }
  if [[ "$TEST_MODE" == "1" ]]; then
    test -r "$ENV_FILE" || {
      echo "writer credential is not readable by service identity" >&2
      return 1
    }
  else
    runuser -u "$SERVICE_USER" -- test -r "$ENV_FILE" || {
      echo "writer credential is not readable by service identity" >&2
      return 1
    }
  fi
}

validate_root() {
  local path="$1" expected="$2" label="$3"
  case "$path" in
    /opt/argus|/opt/argus/*)
      echo "writer $label must never overlap /opt/argus" >&2
      return 1
      ;;
    /opt/argus-rearm|/opt/argus-rearm/*)
      echo "writer $label must never overlap re-arm runtime" >&2
      return 1
      ;;
  esac
  if [[ -e "$path" || -L "$path" ]]; then
    [[ -d "$path" && ! -L "$path" ]] || {
      echo "writer $label has unsafe type" >&2
      return 1
    }
    [[ "$(metadata "$path")" == "$expected" ]] || {
      echo "writer $label metadata mismatch" >&2
      return 1
    }
  fi
}

atomic_install() {
  local source="$1" destination="$2" mode="$3" directory actual
  directory="$(dirname "$destination")"
  PENDING_TEMP="$(mktemp "${directory}/.argus-watchtower-writer-install.XXXXXX")"
  install -o "$ROOT_UID" -g "$ROOT_GID" -m "$mode" "$source" "$PENDING_TEMP"
  actual="$(sha256 "$PENDING_TEMP")"
  [[ "$actual" == "$(sha256 "$source")" ]] || {
    echo "temporary writer install sha256 mismatch" >&2
    return 1
  }
  mv -f "$PENDING_TEMP" "$destination"
  PENDING_TEMP=""
}

restore_manifest() {
  local manifest="$1" destination backup digest owner group mode previous
  local failed=0
  while IFS=$'\t' read -r destination backup digest owner group mode previous; do
    allowed_destination "$destination" || {
      echo "writer rollback destination not allowed: $destination" >&2
      failed=1
      continue
    }
    if [[ "$previous" == "absent" ]]; then
      rm -f -- "$destination" || failed=1
      [[ ! -e "$destination" && ! -L "$destination" ]] || failed=1
      continue
    fi
    if [[ "$previous" != "present" || ! -f "$backup" || -L "$backup" || \
          "$(sha256 "$backup")" != "$digest" ]]; then
      echo "writer rollback artifact invalid: $destination" >&2
      failed=1
      continue
    fi
    PENDING_TEMP="$(mktemp "$(dirname "$destination")/.argus-watchtower-writer-rollback.XXXXXX")"
    install -o "$owner" -g "$group" -m "$mode" "$backup" "$PENDING_TEMP" || failed=1
    mv -f "$PENDING_TEMP" "$destination" || failed=1
    PENDING_TEMP=""
    [[ "$(sha256 "$destination")" == "$digest" ]] || failed=1
  done < "$manifest"
  return "$failed"
}

remove_new_roots() {
  local runtime_state="$1" writer_state="$2"
  if [[ "$writer_state" == "absent" ]]; then
    rmdir "$STATE_ROOT" 2>/dev/null || true
  fi
  if [[ "$runtime_state" == "absent" ]]; then
    rmdir "$RUNTIME_ROOT" 2>/dev/null || true
  fi
}

if [[ "$MODE" == "rollback" ]]; then
  require_privilege
  [[ "$ROLLBACK_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
    echo "invalid writer backup id" >&2
    exit 2
  }
  backup_dir="${BACKUP_ROOT}/${ROLLBACK_ID}"
  manifest="${backup_dir}/manifest.tsv"
  roots="${backup_dir}/root-states"
  [[ -d "$backup_dir" && ! -L "$backup_dir" && \
     -f "$manifest" && ! -L "$manifest" && \
     -f "$roots" && ! -L "$roots" ]] || {
    echo "writer backup metadata missing or unsafe" >&2
    exit 1
  }
  restore_manifest "$manifest"
  IFS=$'\t' read -r runtime_state writer_state < "$roots"
  [[ "$runtime_state" =~ ^(present|absent)$ && \
     "$writer_state" =~ ^(present|absent)$ ]] || {
    echo "invalid writer root backup state" >&2
    exit 1
  }
  remove_new_roots "$runtime_state" "$writer_state"
  echo "writer rollback restored backup=$ROLLBACK_ID"
  echo "systemctl daemon-reload is required but was not executed"
  echo "no daemon-reload/enable/start/restart/dispatch was executed"
  exit 0
fi

validate_sources

if [[ "$MODE" == "source-check" ]]; then
  echo "writer source-check complete: no files changed"
  exit 0
fi

validate_identity
validate_credential
validate_root "$RUNTIME_ROOT" "${ROOT_UID}:${ROOT_GID}:755" "runtime root"
validate_root "$STATE_ROOT" "${EXPECTED_UID}:${EXPECTED_GID}:700" "state root"

if [[ "$MODE" == "dry-run" ]]; then
  echo "writer dry-run complete: prerequisites valid; no files changed"
  echo "no daemon-reload/enable/start/restart/dispatch was executed"
  exit 0
fi

[[ "$MODE" == "apply" ]] || { usage; exit 2; }
require_privilege

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${BACKUP_ROOT}/${timestamp}"
[[ ! -e "$backup_dir" && ! -L "$backup_dir" ]] || {
  echo "writer backup id collision" >&2
  exit 1
}
install -d -o "$ROOT_UID" -g "$ROOT_GID" -m 0700 "$backup_dir"
manifest_tmp="$(mktemp)"
roots_tmp="$(mktemp)"
runtime_state="present"
writer_state="present"
[[ -e "$RUNTIME_ROOT" || -L "$RUNTIME_ROOT" ]] || runtime_state="absent"
[[ -e "$STATE_ROOT" || -L "$STATE_ROOT" ]] || writer_state="absent"
printf '%s\t%s\n' "$runtime_state" "$writer_state" > "$roots_tmp"
apply_in_progress="true"

finish_apply() {
  local status="$1"
  trap - EXIT
  if [[ -n "$PENDING_TEMP" ]]; then
    rm -f -- "$PENDING_TEMP" || true
  fi
  if [[ "$status" -ne 0 && "$apply_in_progress" == "true" ]]; then
    if restore_manifest "$manifest_tmp"; then
      remove_new_roots "$runtime_state" "$writer_state"
      echo "writer apply failed; destinations restored from verified backups" >&2
    else
      echo "writer apply failed; automatic restore was incomplete" >&2
    fi
  fi
  rm -f -- "$manifest_tmp" "$roots_tmp"
  exit "$status"
}
trap 'finish_apply $?' EXIT

install -d -o "$ROOT_UID" -g "$ROOT_GID" -m 0755 "$RUNTIME_ROOT"
install -d -o "$EXPECTED_UID" -g "$EXPECTED_GID" -m 0700 "$STATE_ROOT"

for row in "${FILES[@]}"; do
  IFS='|' read -r relative destination mode expected <<< "$row"
  source="${SOURCE_ROOT}/${relative}"
  if [[ -e "$destination" || -L "$destination" ]]; then
    [[ -f "$destination" && ! -L "$destination" ]] || {
      echo "writer destination has unsafe type: $destination" >&2
      exit 1
    }
    IFS=: read -r owner group previous_mode <<< "$(metadata "$destination")"
    backup="${backup_dir}/$(printf '%s' "$destination" | sed 's#^/##;s#/#__#g')"
    install -o "$ROOT_UID" -g "$ROOT_GID" -m 0600 "$destination" "$backup"
    backup_digest="$(sha256 "$backup")"
    printf '%s\t%s\t%s\t%s\t%s\t%s\tpresent\n' \
      "$destination" "$backup" "$backup_digest" "$owner" "$group" \
      "$previous_mode" >> "$manifest_tmp"
  else
    printf '%s\t-\t-\t%s\t%s\t%s\tabsent\n' \
      "$destination" "$ROOT_UID" "$ROOT_GID" "$mode" >> "$manifest_tmp"
  fi
  atomic_install "$source" "$destination" "$mode"
  [[ "$(sha256 "$destination")" == "$expected" ]] || {
    echo "installed writer sha256 mismatch: $destination" >&2
    exit 1
  }
done

if command -v systemd-analyze >/dev/null 2>&1; then
  systemd-analyze verify \
    "${SYSTEMD_ROOT}/argus-watchtower-writer.service" \
    "${SYSTEMD_ROOT}/argus-watchtower-writer.timer"
fi

install -o "$ROOT_UID" -g "$ROOT_GID" -m 0600 "$manifest_tmp" \
  "${backup_dir}/manifest.tsv"
install -o "$ROOT_UID" -g "$ROOT_GID" -m 0600 "$roots_tmp" \
  "${backup_dir}/root-states"
apply_in_progress="false"

echo "writer install complete backup=$timestamp"
echo "systemctl daemon-reload is required but was not executed"
echo "no daemon-reload/enable/start/restart/dispatch was executed"
