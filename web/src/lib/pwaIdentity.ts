/** Update identity is metadata, never proof of owner authentication. */
export function deployedPwaIdentity(html: string): string | null {
  const names = ['__ARGUS_VERSION__', '__ARGUS_PRODUCT_VERSION__', '__ARGUS_BUILD_SHA__', '__ARGUS_OWNER_AUTH_MODE__'];
  const fields = names.map(name => [...html.matchAll(new RegExp(name + '\\s*=\\s*"([^"\\n]+)"', 'g'))]);
  if (fields.some(matches => matches.length !== 1)) return null;
  const [app, product, sha, mode] = fields.map(matches => matches[0][1]);
  if (!['0', '1'].includes(mode) || [app, product, sha].some(field => field.includes('|'))) return null;
  return `${app}|${product}|${sha}|${mode}`;
}

export function authenticationOnlyUpdate(running: string, deployed: string): boolean {
  const left = running.split('|'), right = deployed.split('|');
  return left.length === 4 && right.length === 4
    && ['0', '1'].includes(left[3]) && ['0', '1'].includes(right[3])
    && left[3] !== right[3] && left.slice(0, 3).every((field, index) => field.length > 0 && field === right[index]);
}

/** The single entry module the served index.html loads (its file name), or null. */
export function deployedEntryScript(html: string): string | null {
  const matches = [...html.matchAll(/<script[^>]*\ssrc="([^"\s]*\/assets\/index-[A-Za-z0-9_-]+\.js)"/g)];
  if (matches.length !== 1) return null;
  return matches[0][1].split('/').pop() ?? null;
}

/** True when the served page carries an older app version than the running
 *  one: an edge still serving the previous release. Reloading into it is not
 *  an update, and since the owner session lives in memory it would only log
 *  the owner out. Unparseable versions never count as behind. */
export function deployedIsBehind(running: string, deployed: string): boolean {
  const parse = (identity: string) => {
    const parts = (identity.split('|')[0] ?? '').split('.');
    return parts.length === 3 && parts.every(part => /^\d+$/.test(part)) ? parts.map(Number) : null;
  };
  const left = parse(running), right = parse(deployed);
  if (!left || !right) return false;
  for (let index = 0; index < 3; index += 1) {
    if (right[index] !== left[index]) return right[index] < left[index];
  }
  return false;
}

/** True when only the build commit differs: the same app version, product
 *  version and authentication mode. A release that changed nothing the page
 *  loads (a backend-only merge) looks like this; the entry module decides. */
export function identityDiffersOnlyInBuildSha(running: string, deployed: string): boolean {
  const left = running.split('|'), right = deployed.split('|');
  return left.length === 4 && right.length === 4 && left[2] !== right[2]
    && [0, 1, 3].every(index => left[index].length > 0 && left[index] === right[index]);
}
