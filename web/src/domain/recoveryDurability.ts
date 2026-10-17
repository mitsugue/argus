export type RecoveryDurabilityState =
  | 'no_local_data'
  | 'existing_envelope_restorable'
  | 'changes_after_envelope'
  | 'no_envelope';

export interface RecoveryDurability {
  state: RecoveryDurabilityState;
  existingEnvelopeRestorable: boolean;
  newerChangesRemoteProtected: boolean;
  newerChangesProtectedByLocalExport: boolean;
  localExportRequired: boolean;
}

/** Transport-truth projection for owner copy. An existing encrypted envelope
 *  is a read-only recovery point; it never protects later browser edits. */
export function buildRecoveryDurability(input: {
  hasLocalData: boolean;
  existingEnvelopeAt: number | null;
  lastLocalEditAt: number | null;
  lastLocalExportAt?: number | null;
}): RecoveryDurability {
  const envelopeAt = input.existingEnvelopeAt ?? 0;
  const localEditAt = input.lastLocalEditAt ?? 0;
  const existingEnvelopeRestorable = envelopeAt > 0;
  const localExportAt = input.lastLocalExportAt ?? 0;
  const newerChangesProtectedByLocalExport = localExportAt > 0
    && (localEditAt === 0 || localExportAt >= localEditAt);

  if (!input.hasLocalData) {
    return {
      state: 'no_local_data', existingEnvelopeRestorable,
      newerChangesRemoteProtected: false, newerChangesProtectedByLocalExport,
      localExportRequired: false,
    };
  }
  if (!existingEnvelopeRestorable) {
    return {
      state: 'no_envelope', existingEnvelopeRestorable: false,
      newerChangesRemoteProtected: false, newerChangesProtectedByLocalExport,
      localExportRequired: !newerChangesProtectedByLocalExport,
    };
  }
  if (localEditAt > envelopeAt) {
    return {
      state: 'changes_after_envelope', existingEnvelopeRestorable: true,
      newerChangesRemoteProtected: false, newerChangesProtectedByLocalExport,
      localExportRequired: !newerChangesProtectedByLocalExport,
    };
  }
  return {
    state: 'existing_envelope_restorable', existingEnvelopeRestorable: true,
    newerChangesRemoteProtected: false, newerChangesProtectedByLocalExport,
    localExportRequired: false,
  };
}
