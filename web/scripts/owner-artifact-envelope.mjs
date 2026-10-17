import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { pipeline } from 'node:stream/promises';
import { Transform } from 'node:stream';
import { pathToFileURL } from 'node:url';

// CI transport only. Never use an owner password or an administrative token as this key.
export const LIMITS = Object.freeze({ files: 10000, bytes: 512 * 1024 * 1024, manifest: 4 * 1024 * 1024 });
const MAGIC = Buffer.from('ARGUS-AE1');
const fail = () => { throw new Error('owner_artifact_invalid'); };
function keyBytes(text) {
  if (!/^[0-9a-f]{64}$/.test(text || '')) fail();
  return Buffer.from(text, 'hex');
}
function contextBytes(c) {
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(c.repository || '')
      || !/^[0-9a-f]{40}$/.test(c.candidate || '') || !/^[1-9][0-9]*$/.test(c.run || '')
      || !['profile', 'seed-evidence', 'consumer-evidence', 'mobile-evidence'].includes(c.kind)) fail();
  return Buffer.from(JSON.stringify(['argus-owner-artifact-v1', c.repository, c.candidate, c.run, c.kind]));
}
function aad(context, record) { return Buffer.concat([context, Buffer.from(`\n${record}`)]); }
function safeName(name) {
  if (typeof name !== 'string' || Buffer.byteLength(name) > 4096 || name.includes('\\')
      || /[\x00-\x1f\x7f]/.test(name) || name.split('/').some(p => !p || p === '.' || p === '..' || p.includes(':'))) fail();
  return name;
}
async function privateParent(target) {
  const parent = path.dirname(path.resolve(target));
  if (await fsp.realpath(parent) !== parent) fail();
  if (await fsp.lstat(target).then(() => true, e => { if (e.code === 'ENOENT') return false; throw e; })) fail();
  return parent;
}
async function regular(file) {
  const handle = await fsp.open(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  const stat = await handle.stat();
  if (!stat.isFile() || stat.nlink !== 1) { await handle.close(); fail(); }
  return { handle, stat };
}
function bound(maximum) {
  let count = 0;
  return new Transform({ transform(chunk, _encoding, next) {
    count += chunk.length;
    if (count > maximum) next(new Error('owner_artifact_invalid')); else next(null, chunk);
  } });
}
async function encryptFile(input, output, key, associated, size) {
  const { handle, stat } = await regular(input);
  try {
    if (stat.size !== size) fail();
    const nonce = crypto.randomBytes(12);
    const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce);
    cipher.setAAD(associated);
    await fsp.writeFile(output, Buffer.concat([MAGIC, nonce]), { flag: 'wx', mode: 0o600 });
    await pipeline(handle.createReadStream({ autoClose: false }), bound(size), cipher, fs.createWriteStream(output, { flags: 'a' }));
    const after = await handle.stat();
    if (after.size !== size || after.mtimeMs !== stat.mtimeMs || after.ctimeMs !== stat.ctimeMs) fail();
    await fsp.appendFile(output, cipher.getAuthTag());
  } finally { await handle.close(); }
}
async function decryptFile(input, output, key, associated, maximum) {
  const { handle, stat } = await regular(input);
  try {
    if (stat.size < MAGIC.length + 28 || stat.size > maximum + MAGIC.length + 28) fail();
    const header = Buffer.alloc(MAGIC.length + 12), tag = Buffer.alloc(16);
    await handle.read(header, 0, header.length, 0);
    await handle.read(tag, 0, 16, stat.size - 16);
    if (!header.subarray(0, MAGIC.length).equals(MAGIC)) fail();
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, header.subarray(MAGIC.length));
    decipher.setAAD(associated); decipher.setAuthTag(tag);
    // output stays in a private staging directory until EVERY tag and record passes.
    if (stat.size === header.length + 16) {
      await fsp.writeFile(output, decipher.final(), { flag: 'wx', mode: 0o600 });
    } else {
      await pipeline(handle.createReadStream({ start: header.length, end: stat.size - 17, autoClose: false }),
        decipher, bound(maximum), fs.createWriteStream(output, { flags: 'wx', mode: 0o600 }));
    }
  } finally { await handle.close(); }
}
async function inventory(root) {
  if (await fsp.realpath(root) !== path.resolve(root) || !(await fsp.lstat(root)).isDirectory()) fail();
  const entries = []; let bytes = 0;
  async function walk(relative) {
    for (const name of (await fsp.readdir(path.join(root, relative))).sort()) {
      const rel = safeName(relative ? `${relative}/${name}` : name);
      const stat = await fsp.lstat(path.join(root, rel));
      if (entries.length >= LIMITS.files || stat.isSymbolicLink()) fail();
      if (stat.isDirectory()) { entries.push({ path: rel, directory: true }); await walk(rel); }
      else if (stat.isFile() && stat.nlink === 1) {
        bytes += stat.size; if (bytes > LIMITS.bytes) fail();
        entries.push({ path: rel, size: stat.size, mode: stat.mode & 0o700 });
      } else fail();
    }
  }
  await walk('');
  return entries;
}
export async function seal(source, destination, keyText, context) {
  const key = keyBytes(keyText), associated = contextBytes(context);
  const parent = await privateParent(destination);
  const entries = await inventory(source);
  const body = Buffer.from(JSON.stringify({ schema: 'argus-owner-artifact-v1', entries }));
  if (body.length > LIMITS.manifest) fail();
  const stage = await fsp.mkdtemp(path.join(parent, '.owner-seal-'));
  try {
    for (let i = 0; i < entries.length; i++) {
      const e = entries[i]; if (e.directory) continue;
      await encryptFile(path.join(source, e.path), path.join(stage, `${i}.bin`), key, aad(associated, `${i}:${e.path}`), e.size);
    }
    if (JSON.stringify(await inventory(source)) !== JSON.stringify(entries)) fail();
    // The private temporary manifest is removed before publishing the sealed directory.
    const manifest = path.join(stage, 'manifest.private');
    await fsp.writeFile(manifest, body, { flag: 'wx', mode: 0o600 });
    await encryptFile(manifest, path.join(stage, 'manifest.bin'), key, aad(associated, 'manifest'), body.length);
    await fsp.unlink(manifest);
    await privateParent(destination); await fsp.rename(stage, destination);
  } finally { await fsp.rm(stage, { recursive: true, force: true }); key.fill(0); }
}
export async function unseal(source, destination, keyText, context) {
  const key = keyBytes(keyText), associated = contextBytes(context);
  const parent = await privateParent(destination);
  if (await fsp.realpath(source) !== path.resolve(source)) fail();
  const stage = await fsp.mkdtemp(path.join(parent, '.owner-open-'));
  try {
    const manifest = path.join(stage, 'manifest.private');
    await decryptFile(path.join(source, 'manifest.bin'), manifest, key, aad(associated, 'manifest'), LIMITS.manifest);
    const data = JSON.parse(await fsp.readFile(manifest, 'utf8')); await fsp.unlink(manifest);
    if (data.schema !== 'argus-owner-artifact-v1' || !Array.isArray(data.entries) || data.entries.length > LIMITS.files
        || Object.keys(data).sort().join() !== 'entries,schema') fail();
    const seen = new Set(), expected = ['manifest.bin']; let total = 0;
    for (let i = 0; i < data.entries.length; i++) {
      const e = data.entries[i]; safeName(e.path);
      if (seen.has(e.path)) fail();
      const parentName = path.posix.dirname(e.path);
      if (parentName !== '.' && !seen.has(`${parentName}/`)) fail();
      seen.add(e.path);
      if (e.directory === true && Object.keys(e).sort().join() === 'directory,path') seen.add(`${e.path}/`);
      else {
        if (Object.keys(e).sort().join() !== 'mode,path,size' || !Number.isSafeInteger(e.size) || e.size < 0
            || !Number.isInteger(e.mode) || e.mode < 0 || e.mode > 0o700 || (e.mode & 0o077)) fail();
        total += e.size; if (total > LIMITS.bytes) fail();
        expected.push(`${i}.bin`);
      }
    }
    if (JSON.stringify((await fsp.readdir(source)).sort()) !== JSON.stringify(expected.sort())) fail();
    for (let i = 0; i < data.entries.length; i++) {
      const e = data.entries[i], target = path.join(stage, e.path);
      if (e.directory) await fsp.mkdir(target, { mode: 0o700 });
      else {
        await decryptFile(path.join(source, `${i}.bin`), target, key, aad(associated, `${i}:${e.path}`), e.size);
        if ((await fsp.stat(target)).size !== e.size) fail();
        await fsp.chmod(target, e.mode);
      }
    }
    await privateParent(destination); await fsp.rename(stage, destination);
  } finally { await fsp.rm(stage, { recursive: true, force: true }); key.fill(0); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const [command, source, destination, kind, candidate, run] = process.argv.slice(2);
    if (command === 'check') {
      if (!['0', '1'].includes(process.env.ARGUS_ACCEPTANCE_OWNER_AUTH)) fail();
      if (process.env.ARGUS_ACCEPTANCE_OWNER_AUTH === '1') keyBytes(process.env.ARGUS_OWNER_ARTIFACT_KEY).fill(0);
      console.log('owner_artifact_configuration_valid');
    } else {
    if (!['seal', 'unseal'].includes(command) || !source || !destination) fail();
    await (command === 'seal' ? seal : unseal)(source, destination, process.env.ARGUS_OWNER_ARTIFACT_KEY,
      { repository: process.env.GITHUB_REPOSITORY, candidate, run, kind });
    console.log('owner_artifact_complete');
    }
  } catch { console.error('owner_artifact_failed'); process.exitCode = 1; }
}
