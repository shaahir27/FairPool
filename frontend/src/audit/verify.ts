/**
 * Browser-side recomputation of the published draw (T09B01, fairness-and-hashing.md).
 *
 * Every function here mirrors one function in `backend/src/fairpool/domain/hashing.py`
 * byte for byte, so a visitor with the published list, the seed and their own receipt
 * can arrive at the same numbers without trusting this page or the server that served
 * it. SHA-256 and Ed25519 come from Web Crypto, so there is no hashing dependency.
 *
 * Deliberate limits:
 * - the audit payload publishes the whole sorted commitment list, so the page rebuilds
 *   the Merkle root over all of it. That is a stronger check than a single inclusion
 *   proof, and it needs no proof endpoint.
 * - rank is "1 + the number of smaller rank_hash values". A tie on rank_hash would be
 *   broken by entry_id (fairness §5), which the published list does not carry, so the
 *   page says so instead of pretending the number is always exact.
 */

const COMMIT_PREFIX = "fairpool/commit/v1";
const RANK_PREFIX = "fairpool/rank/v1";
const DEMO_SEED_PREFIX = "fairpool/demo-seed/v1";
const EMPTY_PREFIX = "fairpool/empty/v1";

const HEX64 = /^[0-9a-f]{64}$/;

export type MerkleStep = {side: "L" | "R"; hash: string};

function requireHex64(value: string, field: string): string {
  if (!HEX64.test(value)) {
    throw new Error(`${field} must be 64 lowercase hex characters`);
  }
  return value;
}

/**
 * Canonical JSON: sorted keys, no whitespace, non-ASCII values preserved. Matches
 * `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.
 *
 * Python sorts object keys by Unicode code point and JS `sort()` compares UTF-16 code
 * units; the contract keeps keys ASCII-only (`_validate_canonical`), so both agree.
 * Floats and unsafe integers are refused because money is integer cents (BD-14) and a
 * float would serialise differently in each language.
 */
export function canonicalJson(value: unknown): string {
  return JSON.stringify(encode(value, "$"));
}

type Encoded = string | number | boolean | null | Encoded[] | {[key: string]: Encoded};

function encode(value: unknown, path: string): Encoded {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) {
      throw new Error(`only integers are canonical at ${path}`);
    }
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item, index) => encode(item, `${path}[${index}]`));
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const out: Record<string, Encoded> = {};
    for (const key of Object.keys(record).sort()) {
      if (key.charCodeAt(0) > 126 && ![...key].every((char) => char < "\x80")) {
        throw new Error(`non-ASCII key at ${path}: ${key}`);
      }
      out[key] = encode(record[key], `${path}.${key}`);
    }
    return out;
  }
  throw new Error(`unsupported type at ${path}`);
}

export async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bufferOf(new TextEncoder().encode(text)));
  return bytesToHex(new Uint8Array(digest));
}

/** SHA-256 over raw bytes, for the Merkle prefixes which are byte constants. */
async function sha256Bytes(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bufferOf(bytes));
  return bytesToHex(new Uint8Array(digest));
}

function bytesToHex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

/**
 * Web Crypto in this toolchain takes ArrayBuffer-backed views, and `TextEncoder`,
 * `Uint8Array.from` and `new Uint8Array(n)` are all typed `ArrayBufferLike`. One copy
 * per conversion keeps the types honest without changing a byte of what is hashed.
 */
function bufferOf(source: Uint8Array): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(new ArrayBuffer(source.length));
  out.set(source);
  return out;
}

function hexToBytes(hex: string): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(new ArrayBuffer(hex.length / 2));
  for (let index = 0; index < out.length; index += 1) {
    out[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return out;
}

function concat(left: Uint8Array, right: Uint8Array): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(new ArrayBuffer(left.length + right.length));
  out.set(left, 0);
  out.set(right, left.length);
  return out;
}

export async function leafHash(commitment: string): Promise<string> {
  return sha256Bytes(concat(new Uint8Array([0x00]), hexToBytes(requireHex64(commitment, "commitment"))));
}

export async function parentHash(left: string, right: string): Promise<string> {
  const bytes = concat(
    new Uint8Array([0x01]),
    concat(hexToBytes(requireHex64(left, "left")), hexToBytes(requireHex64(right, "right"))),
  );
  return sha256Bytes(bytes);
}

/** `sha256("fairpool/empty/v1")`, the root of a pool with no entries. */
export async function emptyMerkleRoot(): Promise<string> {
  return sha256Hex(EMPTY_PREFIX);
}

async function nextLevel(level: string[]): Promise<string[]> {
  const out: string[] = [];
  for (let index = 0; index < level.length - 1; index += 2) {
    out.push(await parentHash(level[index]!, level[index + 1]!));
  }
  // An odd node is promoted unchanged and adds no proof step (fairness §3.3).
  if (level.length % 2 === 1) {
    out.push(level[level.length - 1]!);
  }
  return out;
}

/** Root over the ascending commitment list, sorted here so a served order cannot lie. */
export async function merkleRoot(commitments: readonly string[]): Promise<string> {
  const sorted = [...commitments].map((item) => requireHex64(item, "commitment")).sort();
  if (sorted.length === 0) {
    return emptyMerkleRoot();
  }
  let level: string[] = [];
  for (const commitment of sorted) {
    level.push(await leafHash(commitment));
  }
  while (level.length > 1) {
    level = await nextLevel(level);
  }
  return level[0]!;
}

/** Recomputes a root from one leaf and its proof steps (fairness §3.5). */
export async function verifyInclusionProof(
  commitment: string,
  proof: readonly MerkleStep[],
  root: string,
): Promise<boolean> {
  const expected = requireHex64(root, "root");
  let node = await leafHash(commitment);
  for (const step of proof) {
    const sibling = requireHex64(step.hash, "sibling hash");
    node = step.side === "L" ? await parentHash(sibling, node) : await parentHash(node, sibling);
  }
  return node === expected;
}

export async function commitment(
  poolId: string,
  entryId: string,
  requestHash: string,
  saltHex: string,
): Promise<string> {
  requireHex64(requestHash, "request_hash");
  requireHex64(saltHex, "salt_hex");
  return sha256Hex(`${COMMIT_PREFIX}|${poolId}|${entryId}|${requestHash}|${saltHex}`);
}

export async function rankHash(seedHex: string, commitmentValue: string): Promise<string> {
  return sha256Hex(
    `${RANK_PREFIX}|${requireHex64(seedHex, "seed_hex")}|${requireHex64(commitmentValue, "commitment")}`,
  );
}

/** The labelled demo seed: FairPool chose it, and every surface that shows it must say so. */
export async function demoSeed(poolId: string): Promise<string> {
  return sha256Hex(`${DEMO_SEED_PREFIX}|${poolId}`);
}

export async function rulesHash(document: unknown): Promise<string> {
  return sha256Hex(canonicalJson(document));
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(padded);
  return bufferOf(Uint8Array.from(binary, (character) => character.charCodeAt(0)));
}

/**
 * Verify a signature over `canonicalJson(payload)` with the key from
 * `GET /api/v1/public/keys`. Returns false rather than throwing: a page that reports a
 * verification result must be able to report a failed one.
 */
export async function verifyEd25519(
  payload: unknown,
  signatureBase64Url: string,
  publicKeyBase64Url: string,
): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey(
      "raw",
      base64UrlToBytes(publicKeyBase64Url),
      {name: "Ed25519", namedCurve: "Ed25519"},
      false,
      ["verify"],
    );
    return await crypto.subtle.verify(
      "Ed25519",
      key,
      base64UrlToBytes(signatureBase64Url),
      bufferOf(new TextEncoder().encode(canonicalJson(payload))),
    );
  } catch {
    return false;
  }
}

/** The same payload minus the signature field, ready for `verifyEd25519`. */
export function withoutSignature<T extends Record<string, unknown>>(value: T): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => key !== "signature"));
}

export type PlaceCheck = {
  found: boolean;
  index: number;
  rank: number;
  rankHash: string;
};

/**
 * The buyer's own position: is their commitment in the published list, and where does
 * it sort once the seed is applied? Ties would break on entry_id (fairness §5), which
 * the public list does not carry, so `rank` is exact unless two rank hashes collide.
 */
export async function checkPlace(
  seedHex: string,
  commitments: readonly string[],
  target: string,
): Promise<PlaceCheck> {
  const ordered = [...commitments].sort();
  const index = ordered.indexOf(target);
  const hashes: string[] = [];
  for (const item of ordered) {
    hashes.push(await rankHash(seedHex, item));
  }
  const mine = hashes[index] ?? "";
  const smaller = hashes.filter((hash) => hash < mine).length;
  return {found: index >= 0, index, rank: smaller + 1, rankHash: mine};
}
