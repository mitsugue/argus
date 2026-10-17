// Snapshot verification worker (v13.5.1). Multi-megabyte JSON parsing,
// canonical sorting, and SHA-256 hashing previously ran on the main thread
// and froze input for seconds on real phones. The IDENTICAL verification
// logic (verifySnapshot from verifiedSnapshot.ts) now runs here; the main
// thread only transfers text/objects and receives the verified result.
// Data-integrity semantics are unchanged — only the executing thread moved.
import { verifySnapshot, type SnapshotExpectation } from './verifiedSnapshot';

interface VerifyRequest {
  requestId: number;
  expectation: SnapshotExpectation;
  /** Raw response text (preferred: parsing happens off-thread too) … */
  rawText?: string;
  /** … or an already-materialized candidate object (IndexedDB read-back). */
  candidate?: unknown;
}

self.onmessage = async (event: MessageEvent<VerifyRequest>) => {
  const { requestId, expectation, rawText, candidate } = event.data;
  try {
    let value: unknown = candidate;
    if (rawText != null) {
      value = JSON.parse(rawText);
    }
    const result = await verifySnapshot(value, expectation);
    (self as unknown as Worker).postMessage({ requestId, result });
  } catch (error) {
    (self as unknown as Worker).postMessage({
      requestId,
      result: {
        ok: false,
        reason: `worker_${error instanceof Error ? error.name : 'error'}`,
      },
    });
  }
};
