export interface BackendRuntimeIdentity {
  backendVersion: string;
  backendSha: string;
  deploymentId: string;
  deployedAt: string;
}

const RELEASE_VERSION = /^\d+\.\d+\.\d+$/;
const PRODUCT_VERSION = /^v[1-9]\d*$/;
const FULL_GIT_SHA = /^[0-9a-f]{40}$/i;
const RENDER_DEPLOYMENT_ID = /^dep-[0-9a-z]+$/;
const ISO_UTC_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseProductionBackendIdentity(payload: unknown): BackendRuntimeIdentity | null {
  if (!isRecord(payload)
      || payload.schema !== 'argus-production-release-manifest-v1'
      || payload.service !== 'argus-backend'
      || payload.environment !== 'production'
      || payload.verifiedHealth !== true
      || payload.verifiedReady !== true) return null;
  const backendVersion = payload.version;
  const backendSha = payload.buildSha;
  const deploymentId = payload.deploymentId;
  const deployedAt = payload.deployedAt;
  if (typeof backendVersion !== 'string' || !RELEASE_VERSION.test(backendVersion)) return null;
  if (typeof backendSha !== 'string' || !FULL_GIT_SHA.test(backendSha)) return null;
  if (typeof deploymentId !== 'string' || !RENDER_DEPLOYMENT_ID.test(deploymentId)) return null;
  if (typeof deployedAt !== 'string'
      || !ISO_UTC_TIMESTAMP.test(deployedAt)
      || Number.isNaN(Date.parse(deployedAt))) return null;
  return {
    backendVersion,
    backendSha: backendSha.toLowerCase(),
    deploymentId,
    deployedAt,
  };
}

export interface RuntimeVersionTruth {
  productVersion: string | null;
  frontendVersion: string;
  frontendBuildSha: string;
  backendVersion: string;
  backendBuildSha: string;
}

function componentVersion(value: string): string {
  return RELEASE_VERSION.test(value) ? value : 'unknown';
}

function buildCoordinate(value: string): string {
  return FULL_GIT_SHA.test(value) || value === 'local' ? value.toLowerCase() : 'unknown';
}

export function runtimeVersionTruth(input: {
  productVersion: string;
  frontendVersion: string;
  frontendBuildSha: string;
  backendVersion: string;
  backendBuildSha: string;
}): RuntimeVersionTruth {
  return {
    productVersion: PRODUCT_VERSION.test(input.productVersion) ? input.productVersion : null,
    frontendVersion: componentVersion(input.frontendVersion),
    frontendBuildSha: buildCoordinate(input.frontendBuildSha),
    backendVersion: componentVersion(input.backendVersion),
    backendBuildSha: buildCoordinate(input.backendBuildSha),
  };
}

export function runtimeVersionLabel(productVersion: string): string {
  return PRODUCT_VERSION.test(productVersion)
    ? productVersion : 'product version unavailable';
}
