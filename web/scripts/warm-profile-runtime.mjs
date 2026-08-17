const DEFAULT_ATTEMPTS = 3;

const cleanError = (error) => String(error?.message || error || 'unknown')
  .replace(/Bearer\s+\S+/gi, 'Bearer [redacted]')
  .replace(/([?&](?:token|key|authorization|auth)=[^&\s]+)/gi, '?redacted')
  .slice(0, 800);

export function runtimeProofReady(value) {
  return value?.serviceWorkerReady === true
    && Array.isArray(value?.databaseNames)
    && value.databaseNames.includes('argus-verified-snapshots')
    && Number.isInteger(value?.verifiedSnapshotRecordCount)
    && value.verifiedSnapshotRecordCount > 0;
}

export async function stabilizeWarmProfileRuntime({
  probe,
  reload,
  attempts = DEFAULT_ATTEMPTS,
}) {
  if (typeof probe !== 'function' || typeof reload !== 'function'
      || !Number.isInteger(attempts) || attempts < 1 || attempts > 3) {
    throw new Error('invalid_warm_profile_runtime_stabilizer');
  }
  const diagnostics = [];
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    let observed;
    try {
      observed = await probe(attempt);
      diagnostics.push({ attempt, observed, status: runtimeProofReady(observed)
        ? 'READY' : 'NOT_READY' });
    } catch (error) {
      diagnostics.push({ attempt, error: cleanError(error), status: 'ERROR' });
    }
    if (runtimeProofReady(observed)) {
      return {
        diagnostics,
        runtimeProof: {
          databaseNames: [...observed.databaseNames].sort(),
          serviceWorkerReady: true,
          verifiedSnapshotRecordCount: observed.verifiedSnapshotRecordCount,
        },
      };
    }
    if (attempt < attempts) await reload(attempt);
  }
  throw new Error(`warm_profile_runtime_unready:${JSON.stringify(diagnostics)}`);
}
