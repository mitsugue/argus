// Read the actual Fetch response inside Chromium, without consuming the
// application's stream or publishing the body. The CDP reader remains first.
export function installBrowserRateLimitProof() {
  const reads = new Map();
  Object.defineProperty(window, '__argusAcceptanceRateLimitReads', { value: reads });
  const original = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await original(...args);
    if (response.status === 429 && new URL(response.url).pathname === '/api/argus/chart-intelligence') {
      const read = (async () => {
        try {
          const body = await response.clone().json();
          return { status: 429, bodyRead: 'JSON',
            errorField: body?.error === 'rate_limited' ? 'RATE_LIMITED' : 'OTHER_OR_MISSING',
            messageIsString: typeof body?.message === 'string' };
        } catch (error) {
          return { status: 429, bodyRead: error instanceof SyntaxError ? 'INVALID_JSON' : 'BODY_READ_FAILED',
            errorField: 'OTHER_OR_MISSING', messageIsString: false };
        }
      })();
      if (reads.size >= 8) reads.delete(reads.keys().next().value);
      reads.set(response.url, read);
    }
    return response;
  };
}
