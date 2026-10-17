#!/usr/bin/env bash
# ARGUS ops — shared redaction filter (v11.5.9).
# Pipe ANY process/log output through `redact` before it reaches a terminal,
# a doc, or a chat. Covers OpenD CLI args and generic credential shapes.
redact() {
  sed -E \
    -e 's/(-login_account=)[^[:space:]]*/\1[REDACTED]/g' \
    -e 's/(-login_pwd[a-z_0-9]*=)[^[:space:]]*/\1[REDACTED]/g' \
    -e 's/([Tt][Oo][Kk][Ee][Nn][=: ]+)[^[:space:]"'"'"']+/\1[REDACTED]/g' \
    -e 's/([Ss][Ee][Cc][Rr][Ee][Tt][=: ]+)[^[:space:]"'"'"']+/\1[REDACTED]/g' \
    -e 's/([Hh][Mm][Aa][Cc][a-zA-Z_]*[=: ]+)[^[:space:]"'"'"']+/\1[REDACTED]/g' \
    -e 's/([Aa][Uu][Tt][Hh][a-zA-Z_]*[=: ]+)[^[:space:]"'"'"']+/\1[REDACTED]/g' \
    -e 's/([Pp][Aa][Ss][Ss][Ww][Oo][Rr][Dd][a-zA-Z_]*[=: ]+)[^[:space:]"'"'"']+/\1[REDACTED]/g'
}
