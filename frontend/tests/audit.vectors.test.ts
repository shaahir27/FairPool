/**
 * T09B01: the browser recompute must produce the same bytes as the backend.
 *
 * These assertions run against `docs/contracts/vectors/fairness_v1.json`, the same
 * frozen vectors the Python tests use, and against Node's real Web Crypto rather than
 * a stub: a mocked hash would prove nothing about matching the server.
 */
import {readFileSync} from "node:fs";
import path from "node:path";

import {describe, expect, it} from "vitest";

import {
  canonicalJson,
  checkPlace,
  commitment,
  demoSeed,
  merkleRoot,
  rankHash,
  rulesHash,
  verifyEd25519,
  verifyInclusionProof,
} from "../src/audit/verify";

const vectors = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../docs/contracts/vectors/fairness_v1.json"), "utf8"),
) as {
  canonical_json_cases: {input: unknown; output: string}[];
  entries: {
    entry_id: string;
    salt_hex: string;
    canonical_request: {pool_id: string};
    request_hash: string;
    commitment: string;
    rank_hash: string;
  }[];
  sorted_commitments: string[];
  inclusion_proof: {commitment: string; steps: {side: "L" | "R"; hash: string}[]};
  merkle_root: string;
  seed_hex: string;
  order: string[];
  demo_seed: string;
  receipt: {payload: unknown; signature_b64url: string; public_key_b64url: string};
  rules: {document: unknown; canonical_json: string; sha256: string};
};

describe("canonical JSON matches the Python encoder", () => {
  for (const [index, testCase] of vectors.canonical_json_cases.entries()) {
    it(`encodes case ${index + 1} byte for byte`, () => {
      expect(canonicalJson(testCase.input)).toBe(testCase.output);
    });
  }

  it("refuses a float and an unsafe integer instead of rounding one", () => {
    expect(() => canonicalJson({amount: 12.5})).toThrow(/integers/);
    expect(() => canonicalJson({amount: Number.MAX_SAFE_INTEGER + 1})).toThrow(/integers/);
  });
});

describe("domain hashes match the frozen vectors", () => {
  it("recomputes every entry commitment", async () => {
    for (const entry of vectors.entries) {
      expect(
        await commitment(
          entry.canonical_request.pool_id,
          entry.entry_id,
          entry.request_hash,
          entry.salt_hex,
        ),
      ).toBe(entry.commitment);
    }
  });

  it("recomputes every rank hash", async () => {
    for (const entry of vectors.entries) {
      expect(await rankHash(vectors.seed_hex, entry.commitment)).toBe(entry.rank_hash);
    }
  });

  it("sorts the published list into the vector's draw order", async () => {
    // The browser holds only commitments, so it orders by rank_hash; the vector's
    // `order` is the entry ids in that same sequence. A rank_hash tie would need the
    // entry id (fairness §5), which the published list does not carry -- these vectors
    // contain no tie, and the page states the limit rather than hiding it.
    const entryOf = new Map(vectors.entries.map((entry) => [entry.commitment, entry.entry_id]));
    const ordered = await Promise.all(
      vectors.sorted_commitments.map(async (item) => [await rankHash(vectors.seed_hex, item), item] as const),
    );
    ordered.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
    expect(ordered.map(([, item]) => entryOf.get(item))).toEqual(vectors.order);

    const place = await checkPlace(vectors.seed_hex, vectors.sorted_commitments, vectors.entries[0]!.commitment);
    expect(place.found).toBe(true);
    expect(place.rankHash).toBe(vectors.entries[0]!.rank_hash);
    expect(place.rank).toBe(vectors.order.indexOf(vectors.entries[0]!.entry_id) + 1);
  });

  it("rebuilds the Merkle root from the published list", async () => {
    expect(await merkleRoot(vectors.sorted_commitments)).toBe(vectors.merkle_root);
  });

  it("verifies a published inclusion proof and rejects a tampered root", async () => {
    const proof = vectors.inclusion_proof;
    expect(await verifyInclusionProof(proof.commitment, proof.steps, vectors.merkle_root)).toBe(true);
    expect(await verifyInclusionProof(proof.commitment, proof.steps, "0".repeat(64))).toBe(false);
  });

  it("derives the labelled demo seed", async () => {
    expect(await demoSeed("11111111-1111-4111-8111-111111111111")).toBe(vectors.demo_seed);
  });

  it("hashes the rules document to its vector", async () => {
    expect(canonicalJson(vectors.rules.document)).toBe(vectors.rules.canonical_json);
    expect(await rulesHash(vectors.rules.document)).toBe(vectors.rules.sha256);
  });

  it("verifies an Ed25519 signature over canonical bytes", async () => {
    const receipt = vectors.receipt;
    expect(
      await verifyEd25519(receipt.payload, receipt.signature_b64url, receipt.public_key_b64url),
    ).toBe(true);
    const tampered = {...(receipt.payload as Record<string, unknown>), entry_id: "0".repeat(36)};
    expect(await verifyEd25519(tampered, receipt.signature_b64url, receipt.public_key_b64url)).toBe(false);
  });
});
