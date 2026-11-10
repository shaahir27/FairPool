# Merchant Agent SDKs

Generated clients for the ten-operation Merchant Agent API, plus the OpenAPI document they
are generated from. Nothing in this directory is edited by hand (AGENTS.md rule 26).

## Contents

- `merchant-openapi.json` — the exported OpenAPI 3.1 document (ten operations), checked by
  `tools/export_merchant_openapi.py --check`, CI and `gate_check`.
- `python/` — the APIMatic-generated Python SDK (`fairpoolmerchantagentapi`).
- `typescript/` — the APIMatic-generated TypeScript SDK.
- `smoke.py` — imports the generated Python client, builds the contracted bid body and
  asserts the serialized JSON the server expects. With three environment variables it also
  sends one real bid through the generated client.

## Provenance

- Generator: `@apimatic/cli` 1.5.0 (`npm install -g @apimatic/cli@1`), authenticated with
  the project owner's APIMatic account and an active trial/plan (all languages allowed).
- Generated on 2026-11-10 from `merchant-openapi.json` (ten operations, OpenAPI 3.1).
- Licensing: the generator writes an MIT `LICENSE` into each SDK; this repository is MIT.
  APIMatic's own terms apply to the generation service.

## Regenerating

The CLI reads a build directory containing `src/spec`:

```sh
mkdir -p .tmp/apimatic-input/src/spec
cp sdk/merchant-openapi.json .tmp/apimatic-input/src/spec/openapi.json
curl -s https://raw.githubusercontent.com/apimatic/sample-docs-as-code-portal/refs/heads/master/src/spec/APIMATIC-META.json \
  -o .tmp/apimatic-input/src/spec/APIMATIC-META.json
apimatic sdk generate -i .tmp/apimatic-input -l python -d sdk -f
apimatic sdk generate -i .tmp/apimatic-input -l typescript -d sdk -f
```

`make sdk` prints these steps. The exported document states `MerchantApiBidRequest.confirmed`
as `type: boolean` rather than `const: true`: APIMatic reads a boolean `const` as the string
`"True"`, which the server's strict schema rejects. The server still accepts only `true`.

## Smoke

```sh
.venv/Scripts/python.exe sdk/smoke.py
```

It prints PASS/FAIL per check. A live bid is skipped unless all three are set (the key is
read from the environment and never printed):

```sh
FAIRPOOL_SMOKE_BASE_URL=http://127.0.0.1:8000
FAIRPOOL_SMOKE_API_KEY=fpm_...        # a merchant key with bids:write
FAIRPOOL_SMOKE_LOT_ID=<uuid>          # a lot in BIDDING
```

## Portal

`apimatic portal generate` was attempted on 2026-11-10 with this document and, separately,
with APIMatic's own sample input; both failed server-side with "An unexpected error
occurred". No portal is committed and no portal is claimed in the README, the Devpost text
or the video. See `docs/evidence/phase10/sdk.json`.
