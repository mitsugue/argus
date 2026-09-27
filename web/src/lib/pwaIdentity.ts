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
