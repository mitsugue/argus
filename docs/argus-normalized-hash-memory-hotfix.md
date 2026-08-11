# ARGUS normalized-hash memory hotfix

This document fixes the pre-change counterfactual and the deliberately narrow
contract of the v13.4.12 release candidate.  It contains public-safe scalar
diagnostics only.  It does not contain store payloads, provider data, holdings,
credentials, or an instruction to deploy.

## Production counterfactual

- Diagnostic release: v13.4.11
- Build: `bfe894fe4f992e35e5844320b861474a74f3b5ed`
- Render deployment: `dep-d9te018ae00c73av88cg`
- Boot: `2026-08-11T17:41:58.419334+09:00`
- Natural window: `mw-2026-08-11T09:07:00Z`
- Trigger: `ec2_systemd`, scheduled `09:07:00Z`, started `09:07:01Z`
- Mission record: `tick-2dbc1a571c454823a6f5a105f12eadf4`
- Completed: `2026-08-11T09:08:25.640785Z`
- Checkpoint: verified/read-back verified, 129,096,419 bytes, WAL sequence 4462
- Runtime: restart 0, OOM 0, Stage1 disabled, `legacy_only`, Formal Soak off

The one authorized owner-only read was performed after completion.  The
mission began at RSS 974,536,704 bytes and ended at 1,071,702,016 bytes
(+97,165,312).  The legacy checkpoint pre/post delta was -155,648 bytes.  V2
was not applicable.  The cgroup maximum was 8 GiB and the observed lifetime
peak at the sampled boundaries was 1,321,959,424 bytes.

### Verified store, S7V0-S7V7

| Boundary | RSS bytes | PSS bytes | RssAnon bytes | allocated bytes | metadata truth |
| --- | ---: | ---: | ---: | ---: | --- |
| outer normalize start | 1,062,658,048 | 1,053,843,456 | 1,019,822,080 | 139,011,584 | authoritative alive |
| outer normalize complete | 1,062,658,048 | 1,053,843,456 | 1,019,822,080 | 139,550,368 | current 12, history 0 |
| hash enter | 1,062,658,048 | 1,053,843,456 | 1,019,822,080 | 139,555,696 | raw hash path |
| internal normalize complete | 1,098,752,000 | 1,089,945,600 | 1,055,916,032 | 140,116,608 | RSS +36,093,952 |
| stable tree ready | 1,158,578,176 | 1,149,767,680 | 1,115,742,208 | 140,682,816 | RSS +59,826,176 |
| canonical string ready | 1,160,634,368 | 1,151,819,776 | 1,117,798,400 | 140,123,088 | 27,001,658 chars |
| UTF-8 bytes ready | 1,134,022,656 | 1,125,208,064 | 1,091,186,688 | 140,124,080 | 27,393,092 bytes |
| hash returned | 1,071,435,776 | 1,062,621,184 | 1,028,599,808 | 139,560,400 | peak representations 4 |

The specific first-fix target is the +36,093,952-byte hash-internal store
normalization.  Stable-value transformation and canonical UTF-8 material still
belong to the verified digest contract and are not removed.

### Asset chart store, S7A0-S7A7

| Boundary | RSS bytes | PSS bytes | RssAnon bytes | allocated bytes | metadata truth |
| --- | ---: | ---: | ---: | ---: | --- |
| outer normalize start | 1,071,435,776 | 1,062,621,184 | 1,028,599,808 | 139,562,384 | authoritative alive |
| outer normalize complete | 1,070,538,752 | 1,061,724,160 | 1,027,702,784 | 140,002,032 | records 24, current 22 |
| hash enter | 1,070,538,752 | 1,061,724,160 | 1,027,702,784 | 140,007,360 | raw hash path |
| internal normalize complete | 1,097,728,000 | 1,088,917,504 | 1,054,892,032 | 140,456,208 | RSS +27,189,248 |
| material projection ready | 1,097,736,192 | 1,088,921,600 | 1,054,900,224 | 140,457,984 | cursor/timestamp excluded |
| canonical string ready | 1,097,740,288 | 1,088,925,696 | 1,054,904,320 | 170,164,848 | 14,853,069 chars |
| UTF-8 bytes ready | 1,112,956,928 | 1,104,142,336 | 1,070,120,960 | 140,460,416 | 15,209,855 bytes |
| hash returned | 1,072,906,240 | 1,064,091,648 | 1,030,070,272 | 140,015,840 | peak representations 3 |

The specific first-fix target is the +27,189,248-byte hash-internal store
normalization.  Asset projection, its current NaN behavior, canonical string,
UTF-8 bytes, and 24-hex digest remain unchanged.

### Naturally observed memory-snapshot GET

One provider-free public memory-snapshot GET occurred naturally before the
mission.  The bounded operation aggregate recorded one event, duration
7,756.603 ms, RSS +176,283,648 bytes, arena +33,976,320 bytes, and no abnormal
exit.  The v13.4.12 scope removes only the same verified/asset redundant hash
normalizations inside that response.  It does not redesign or stream the
broader response.

## API and caller boundary

The existing module-specific `state_hash(raw_state)` APIs remain the only APIs
for raw, restored, remote, degraded, or otherwise untrusted state.  Each module
adds its own `state_hash_normalized(normalized_state)` contract.  The new API
skips only store normalization and retains every module-specific operation
after normalization.

Exactly four producer pairs may use it:

1. legacy checkpoint S7 verified snapshots;
2. legacy checkpoint S7 asset chart reports;
3. public memory-snapshot verified snapshots;
4. public memory-snapshot asset chart reports.

Read-back, remote acknowledgement, restore, degraded recovery, M5/M10 state
comparisons, publish/precompute paths, and every other raw caller stay on
`state_hash`.  Contract mismatch takes the tested raw-equivalent fallback; a
false successful digest is not allowed.

## Release claim

This release candidate claims only a semantics-preserving removal of one
proven redundant materialization family.  It does not claim to explain or
remove all retained RSS.  Verified stable-tree construction, canonical JSON,
large public view assembly, restored-store retention, and allocator retention
remain separately ranked contributors.

The candidate must remain Draft, unmerged, and undeployed until its exact head
passes digest compatibility, the full matrix, 32-cycle constrained resource
comparison, legacy checkpoint/WAL/restore/Remote Journal gates, Stage1/V2 and
Formal Soak gates, full pytest, frontend checks, privacy checks, and diff
validation.
