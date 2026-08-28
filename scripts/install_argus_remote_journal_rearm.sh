#!/usr/bin/env bash
# Install only the isolated EC2 Remote Journal re-arm runtime and units.
# Activation is deliberately separate: this script never daemon-reloads,
# enables, starts, restarts, or dispatches a workflow.
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
RUNTIME_ROOT="/opt/argus-rearm"
SYSTEMD_ROOT="/etc/systemd/system"
BACKUP_ROOT="/var/backups/argus-remote-journal-rearm"
ENV_FILE="/etc/argus-remote-journal-rearm.env"
SERVICE_USER="argus-rearm"
EXPECTED_UID="997"
EXPECTED_GID="982"
EXPECTED_HOME="/nonexistent"
EXPECTED_SHELL="/usr/sbin/nologin"
CREDENTIAL_OWNER="root"
CREDENTIAL_GROUP="$SERVICE_USER"
MODE="source-check"
ROLLBACK_ID=""
PENDING_TEMP=""

# The test root is accepted only by the regression suite.  It prefixes every
# mutable destination while leaving the canonical unit bytes unchanged.
if [[ "${ARGUS_REARM_INSTALL_TEST_MODE:-0}" == "1" ]]; then
  test_root="${ARGUS_REARM_INSTALL_TEST_ROOT:?test root required}"
  [[ "$test_root" == /* && "$test_root" != "/" && ! -L "$test_root" ]] || {
    echo "unsafe rearm installer test root" >&2
    exit 2
  }
  RUNTIME_ROOT="${test_root}/opt/argus-rearm"
  SYSTEMD_ROOT="${test_root}/etc/systemd/system"
  BACKUP_ROOT="${test_root}/var/backups/argus-remote-journal-rearm"
  ENV_FILE="${test_root}/etc/argus-remote-journal-rearm.env"
  EXPECTED_UID="${ARGUS_REARM_INSTALL_TEST_UID:?test uid required}"
  EXPECTED_GID="${ARGUS_REARM_INSTALL_TEST_GID:?test gid required}"
  CREDENTIAL_OWNER="${ARGUS_REARM_INSTALL_TEST_CREDENTIAL_OWNER:?test owner required}"
  CREDENTIAL_GROUP="${ARGUS_REARM_INSTALL_TEST_CREDENTIAL_GROUP:?test group required}"
fi

SCRIPT_SHA256="2f2f9d7268f4d853c5a5d12b3628cd22201aaf30c5287274daf966967d2295c1"
SERVICE_SHA256="bfb5657ad42ba7d56de7677c70041b4a5bbbe8c2177b10a5bee824c3632237c9"
TIMER_SHA256="569acae1a68b67b555c9d954e5df9ae85159c3612b4329647259ce259bee318b"

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
  "scripts/argus_remote_journal_rearm.py|${RUNTIME_ROOT}/argus_remote_journal_rearm.py|0755|${SCRIPT_SHA256}"
  "ops/systemd/argus-remote-journal-rearm.service|${SYSTEMD_ROOT}/argus-remote-journal-rearm.service|0644|${SERVICE_SHA256}"
  "ops/systemd/argus-remote-journal-rearm.timer|${SYSTEMD_ROOT}/argus-remote-journal-rearm.timer|0644|${TIMER_SHA256}"
)

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

sudo_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sudo sha256sum "$1" | awk '{print $1}'
  else
    sudo shasum -a 256 "$1" | awk '{print $1}'
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
      grep -q '^ExecStart=/usr/bin/python3 /opt/argus-rearm/argus_remote_journal_rearm.py$' "$source"
      ;;
    *.timer)
      grep -q '^\[Timer\]$' "$source"
      grep -q '^OnCalendar=\*-\*-\* \*:13,33,53:00 UTC$' "$source"
      ;;
  esac
}

validate_sources() {
  local row relative destination mode expected source actual
  for row in "${FILES[@]}"; do
    IFS='|' read -r relative destination mode expected <<< "$row"
    source="${SOURCE_ROOT}/${relative}"
    [[ -f "$source" && ! -L "$source" ]] || {
      echo "rearm source is missing or not a regular file: $relative" >&2
      return 1
    }
    actual="$(sha256 "$source")"
    [[ "$actual" == "$expected" ]] || {
      echo "rearm source sha256 mismatch: $relative actual=$actual expected=$expected" >&2
      return 1
    }
    case "$source" in
      *.py)
        python3 -c \
          'import pathlib,sys; p=pathlib.Path(sys.argv[1]); compile(p.read_bytes(), str(p), "exec")' \
          "$source"
        ;;
      *.service|*.timer) validate_unit_shape "$source" ;;
    esac
    echo "validated rearm source sha256=$actual file=$relative destination=$destination mode=$mode"
  done
}

validate_identity() {
  local passwd group passwd_name uid gid home shell group_name group_gid
  passwd="$(getent passwd "$SERVICE_USER")" || {
    echo "missing dedicated $SERVICE_USER service user" >&2
    return 1
  }
  group="$(getent group "$SERVICE_USER")" || {
    echo "missing dedicated $SERVICE_USER service group" >&2
    return 1
  }
  IFS=: read -r passwd_name _ uid gid _ home shell <<< "$passwd"
  IFS=: read -r group_name _ group_gid _ <<< "$group"
  [[ "$passwd_name" == "$SERVICE_USER" && \
     "$group_name" == "$SERVICE_USER" && \
     "$uid" == "$EXPECTED_UID" && "$gid" == "$EXPECTED_GID" && \
     "$group_gid" == "$EXPECTED_GID" && "$home" == "$EXPECTED_HOME" && \
     "$shell" == "$EXPECTED_SHELL" ]] || {
    echo "dedicated $SERVICE_USER service identity mismatch" >&2
    return 1
  }
}

validate_credential() {
  [[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || {
    echo "missing regular $ENV_FILE" >&2
    return 1
  }
  [[ "$(stat -c '%U' "$ENV_FILE")" == "$CREDENTIAL_OWNER" ]] || {
    echo "$ENV_FILE has incorrect owner" >&2
    return 1
  }
  [[ "$(stat -c '%G' "$ENV_FILE")" == "$CREDENTIAL_GROUP" ]] || {
    echo "$ENV_FILE has incorrect group" >&2
    return 1
  }
  case "$(stat -c '%a' "$ENV_FILE")" in
    640|440) ;;
    *)
      echo "unsafe permissions on $ENV_FILE; require 0640 or 0440" >&2
      return 1
      ;;
  esac
  sudo -u "$SERVICE_USER" test -r "$ENV_FILE" || {
    echo "$ENV_FILE is not readable by $SERVICE_USER" >&2
    return 1
  }
  sudo awk '
    /^[[:space:]]*($|#)/ { next }
    /^ARGUS_REMOTE_JOURNAL_REARM_PAT=[^[:space:]#]+$/ { allowed += 1; next }
    { invalid += 1 }
    END { exit !(allowed == 1 && invalid == 0) }
  ' "$ENV_FILE" || {
    echo "invalid dedicated credential file structure" >&2
    return 1
  }
}

validate_runtime_root() {
  case "$RUNTIME_ROOT" in
    /opt/argus|/opt/argus/*)
      echo "isolated runtime must never overlap /opt/argus" >&2
      return 1
      ;;
  esac
  if sudo test -e "$RUNTIME_ROOT"; then
    sudo test -d "$RUNTIME_ROOT" && sudo test ! -L "$RUNTIME_ROOT" || {
      echo "isolated runtime root has unsafe type" >&2
      return 1
    }
    [[ "$(sudo stat -c '%U:%G:%a' "$RUNTIME_ROOT")" == "root:root:755" ]] || {
      echo "isolated runtime root metadata mismatch" >&2
      return 1
    }
  fi
}

atomic_install() {
  local source="$1" destination="$2" mode="$3"
  local directory actual
  directory="$(dirname "$destination")"
  PENDING_TEMP="$(sudo mktemp "${directory}/.argus-rearm-install.XXXXXX")"
  sudo install -o root -g root -m "$mode" "$source" "$PENDING_TEMP"
  actual="$(sudo_sha256 "$PENDING_TEMP")"
  [[ "$actual" == "$(sha256 "$source")" ]] || {
    echo "temporary install sha256 mismatch: $destination" >&2
    return 1
  }
  sudo mv -fT "$PENDING_TEMP" "$destination"
  PENDING_TEMP=""
}

restore_manifest() {
  local manifest="$1" destination backup sha owner group mode previous
  local failed=0
  while IFS=$'\t' read -r destination backup sha owner group mode previous; do
    allowed_destination "$destination" || {
      echo "rollback destination not allowed: $destination" >&2
      failed=1
      continue
    }
    if [[ "$previous" == "absent" ]]; then
      sudo rm -f -- "$destination" || failed=1
      sudo test ! -e "$destination" || failed=1
      continue
    fi
    if [[ "$previous" != "present" ]] || ! sudo test -f "$backup" || \
          sudo test -L "$backup" || \
          [[ "$(sudo_sha256 "$backup")" != "$sha" ]]; then
      echo "rollback artifact invalid: $destination" >&2
      failed=1
      continue
    fi
    PENDING_TEMP="$(sudo mktemp "$(dirname "$destination")/.argus-rearm-rollback.XXXXXX")"
    sudo install -o "$owner" -g "$group" -m "$mode" "$backup" "$PENDING_TEMP" || failed=1
    sudo mv -fT "$PENDING_TEMP" "$destination" || failed=1
    PENDING_TEMP=""
    [[ "$(sudo_sha256 "$destination")" == "$sha" ]] || failed=1
  done < "$manifest"
  return "$failed"
}

if [[ "$MODE" == "rollback" ]]; then
  [[ "$ROLLBACK_ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || {
    echo "invalid rearm backup id" >&2
    exit 2
  }
  backup_dir="${BACKUP_ROOT}/${ROLLBACK_ID}"
  manifest="${backup_dir}/manifest.tsv"
  root_state="${backup_dir}/runtime-root-state"
  sudo test -d "$backup_dir" && sudo test ! -L "$backup_dir" && \
    sudo test -f "$manifest" && sudo test ! -L "$manifest" && \
    sudo test -f "$root_state" && sudo test ! -L "$root_state" || {
      echo "rearm backup metadata missing or unsafe" >&2
      exit 1
    }
  manifest_copy="$(mktemp)"
  root_state_copy="$(mktemp)"
  cleanup_rollback_copies() {
    rm -f "$manifest_copy" "$root_state_copy"
  }
  trap cleanup_rollback_copies EXIT
  sudo cat "$manifest" | tee "$manifest_copy" >/dev/null
  sudo cat "$root_state" | tee "$root_state_copy" >/dev/null
  restore_manifest "$manifest_copy"
  runtime_root_state="$(<"$root_state_copy")"
  [[ "$runtime_root_state" == "present" || \
     "$runtime_root_state" == "absent" ]] || {
    echo "invalid rearm runtime-root backup state" >&2
    exit 1
  }
  if [[ "$runtime_root_state" == "absent" ]]; then
    sudo rmdir "$RUNTIME_ROOT"
  fi
  echo "rearm rollback restored backup=$ROLLBACK_ID"
  echo "systemctl daemon-reload is required but was not executed"
  echo "no daemon-reload/enable/start/restart/dispatch was executed"
  exit 0
fi

validate_sources

if [[ "$MODE" == "source-check" ]]; then
  echo "rearm source-check complete: no files changed"
  exit 0
fi

validate_identity
validate_credential
validate_runtime_root

if [[ "$MODE" == "dry-run" ]]; then
  echo "rearm dry-run complete: prerequisites valid; no files changed"
  echo "no daemon-reload/enable/start/restart/dispatch was executed"
  exit 0
fi

[[ "$MODE" == "apply" ]] || { usage; exit 2; }

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${BACKUP_ROOT}/${timestamp}"
sudo test ! -e "$backup_dir" || {
  echo "rearm backup id collision: $timestamp" >&2
  exit 1
}
sudo install -d -o root -g root -m 0700 "$backup_dir"
manifest_tmp="$(mktemp)"
runtime_root_state="present"
sudo test -e "$RUNTIME_ROOT" || runtime_root_state="absent"
printf '%s\n' "$runtime_root_state" > "${manifest_tmp}.root-state"
apply_in_progress="true"

finish_apply() {
  local status="$1"
  trap - EXIT
  if [[ -n "$PENDING_TEMP" ]]; then
    sudo rm -f -- "$PENDING_TEMP" || true
  fi
  if [[ "$status" -ne 0 && "$apply_in_progress" == "true" ]]; then
    if restore_manifest "$manifest_tmp"; then
      if [[ "$runtime_root_state" == "absent" ]]; then
        sudo rmdir "$RUNTIME_ROOT" 2>/dev/null || true
      fi
      echo "rearm apply failed; destinations restored from verified backups" >&2
    else
      echo "rearm apply failed; automatic restore was incomplete" >&2
    fi
  fi
  rm -f "$manifest_tmp" "${manifest_tmp}.root-state"
  exit "$status"
}
trap 'finish_apply $?' EXIT

sudo install -d -o root -g root -m 0755 "$RUNTIME_ROOT"

for row in "${FILES[@]}"; do
  IFS='|' read -r relative destination mode expected <<< "$row"
  source="${SOURCE_ROOT}/${relative}"
  if sudo test -e "$destination"; then
    sudo test -f "$destination" && sudo test ! -L "$destination" || {
      echo "rearm destination has unsafe type: $destination" >&2
      exit 1
    }
    owner="$(sudo stat -c '%u' "$destination")"
    group="$(sudo stat -c '%g' "$destination")"
    previous_mode="$(sudo stat -c '%a' "$destination")"
    backup="${backup_dir}/$(printf '%s' "$destination" | sed 's#^/##;s#/#__#g')"
    sudo install -o root -g root -m 0600 "$destination" "$backup"
    backup_sha="$(sudo_sha256 "$backup")"
    printf '%s\t%s\t%s\t%s\t%s\t%s\tpresent\n' \
      "$destination" "$backup" "$backup_sha" "$owner" "$group" \
      "$previous_mode" >> "$manifest_tmp"
  else
    printf '%s\t-\t-\troot\troot\t%s\tabsent\n' \
      "$destination" "$mode" >> "$manifest_tmp"
  fi
  atomic_install "$source" "$destination" "$mode"
  [[ "$(sudo_sha256 "$destination")" == "$expected" ]] || {
    echo "installed rearm sha256 mismatch: $destination" >&2
    exit 1
  }
done

if command -v systemd-analyze >/dev/null 2>&1; then
  sudo systemd-analyze verify \
    "${SYSTEMD_ROOT}/argus-remote-journal-rearm.service" \
    "${SYSTEMD_ROOT}/argus-remote-journal-rearm.timer"
fi

sudo install -o root -g root -m 0600 "$manifest_tmp" \
  "${backup_dir}/manifest.tsv"
sudo install -o root -g root -m 0600 "${manifest_tmp}.root-state" \
  "${backup_dir}/runtime-root-state"
apply_in_progress="false"

echo "rearm install complete backup=$timestamp"
echo "systemctl daemon-reload is required but was not executed"
echo "no daemon-reload/enable/start/restart/dispatch was executed"
