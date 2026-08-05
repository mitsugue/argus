# Checkpoint V2 Stage 1 acceptance closure (v13.4.1 Draft)

This document is a rollout plan, not a deployment approval. It does not
authorize merge, Render/EC2 changes, a restart, authority promotion, a manual
mission tick, or a formal Soak.

## Closed control-plane defects

- A restored running Soak from a different process boot is terminalized as
  `interrupted`; its ID, start time, heartbeats and evidence remain immutable.
  `planned_owner_restart` is possible only with a matching durable marker.
  Otherwise the class is `backend_restart` or `boot_discontinuity`. Lifecycle
  relation remains a separate field. No replacement Soak is created.
- Stage 1 acceptance counts distinct natural `missionWindowId` values.
  `validationWindowCount` is the logical count and `generationCount` is the
  physical generation count. Multiple valid writes in one natural window do
  not advance the three-window gate. Manual generations remain excluded.
- Every physical generation records public-safe process RSS before/peak/after
  and delta, cgroup current before/after and peak when available, generation
  bytes, row/section counts, duration, free disk before/after, pending count,
  writer-lock wait and success/failure. Acceptance requires an observed peak
  below 3 GiB, at least 1 GiB free, zero pending generations and no uncontrolled
  monotonic RSS growth across three distinct natural windows. It also records
  the metadata-only legacy temp count before/after each V2 generation and
  rejects any new legacy temp after baseline without reading incident data.
- Remote Journal evidence is split into lifetime, interrupted-Soak, Stage 1 and
  current epochs. A historical lifetime lag does not by itself fail Stage 1.
  Acceptance requires no unresolved current pending item, Stage 1 lag within
  30 minutes, and an exact verified receipt/WAL sequence match.

## Exact future production rollout

1. Obtain owner approval, then merge the narrow v13.4.1 PR through required
   checks and allow the normal Render deployment path. Do not manually restart.
2. Confirm `checkpointMode=dual_write_validation`, legacy restore authority,
   `v2RestoreAuthority=false`, `formalSoakArmed=false`, and
   `formalSoakState=not_started`.
3. Observe three **distinct natural EC2 mission windows**. Record both logical
   window and physical generation counts plus every generation's resource,
   disk, pending and lock telemetry.
4. Verify the old running Soak is immutable and terminal `interrupted`; confirm
   no replacement Soak and no edited historical timestamps/heartbeats.
5. Perform only the approved isolated read-only V2 restore evidence step and
   compare bounded active sections with legacy authority. Production restore
   authority remains legacy.
6. Confirm current and Stage 1 Remote Journal epoch status with exact receipt
   read-back. Keep the lifetime maximum as historical context.
7. Stop. Do not promote V2 authority or arm/start a formal Soak without a new
   owner approval.
