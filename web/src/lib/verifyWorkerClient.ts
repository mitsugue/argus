// Isolated worker constructor. This is the only module that references
// import.meta (required by Vite's worker bundling); Node-side test loaders
// that transpile TS to CommonJS never import it because the caller checks for
// the Worker global first.
export function createVerifyWorker(): Worker | null {
  try {
    return new Worker(
      new URL('./verify.worker.ts', import.meta.url), { type: 'module' });
  } catch {
    return null;
  }
}
