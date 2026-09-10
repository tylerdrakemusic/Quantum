# Quantum Randomness Service

The `quantum-randomness` Fly.io app exposes bounded JSON primitives at `/v1`.
The `quantum-randomness` app runs one Fly machine in `iad`. Its machine runner
starts Gunicorn with one worker and the refill worker as sibling processes, so
both processes use the same mounted volume and transactional SQLite ledger.
The runner removes IBM and Tigris credentials from the API child environment;
those credentials remain available only to the worker child.

## Using the service

The production base URL is `https://quantum-randomness.fly.dev`. Use HTTPS for
all client traffic; plain HTTP is only suitable for local or temporary
deployment checks. `GET /health` and `GET /v1/status` are public endpoints.
The typed randomness endpoints require the service bearer token in the
`Authorization` header:

```bash
curl https://quantum-randomness.fly.dev/health
curl -H "Authorization: Bearer $FLY_BEARER_TOKEN" \
  "https://quantum-randomness.fly.dev/v1/ints?min=0&max=99"
```

The token is the consumer credential represented by `FLY_BEARER_TOKEN`; keep
it in the caller's secret store and never place its value in source, URLs, or
logs.

## Contract

- `GET /health` is public.
- `GET /v1/status` is public and reports only `current`, `stale`, or
  `unavailable` cache state plus the selected source.
- `GET /v1/bytes?n=1..1024`, `/v1/bits?n=1..8192`, `/v1/ints?min=&max=`, and
  `/v1/bool` require `Authorization: Bearer <FLY_BEARER_TOKEN>`.
- The service accepts one Fly-managed bearer token, compares it in constant
  time, and never emits it, raw cache data, manifest hashes, or provider
  credentials in logs or status responses.
- Production deployment requires both `FLY_BEARER_TOKEN` and
  `QUANTUM_MANIFEST_SIGNING_KEY` in the operator environment. The deployment
  script rejects missing values before invoking Fly and provisions them as
  app secrets without printing or storing either value. `FLY_BEARER_TOKEN` is
  the service credential, not the Fly operator credential.
- Limits are 1 KiB per byte request, 8192 bits per bit request (the same 1 KiB
  byte-equivalent), 10 requests per minute, and 1 MiB per hour.

## Provenance and refill

The verified generation is signed with `QUANTUM_MANIFEST_SIGNING_KEY` using
HMAC-SHA256. The last verified generation remains available if Tigris storage
is temporarily unavailable. The API fetches the worker-published object from
`QUANTUM_MANIFEST_URL`, verifies it, and atomically retains it locally before
serving the request. It is considered `current` for 30 days, then the service
reports `stale` and uses the OS CSPRNG. Tigris/S3 publication uses the fixed
bucket `quantum-randomness-cache` and key `verified/generation.json`, with a
pending object copied into place atomically.

Fresh bytes are reserved through `consumption.sqlite3` in the same mounted
`QUANTUM_CACHE_DIR` as `verified-generation.json`. Each request reserves its
range in a SQLite `BEGIN IMMEDIATE` transaction keyed by generation. The
single machine runner guarantees that the API and refill worker open that one
file, rather than relying on identical volume names across Fly apps. SQLite or
cache I/O failure preserves the existing OS-CSPRNG fallback and provenance
contract. Keep the app at one Fly machine with `fly scale count 1`; the
documented 10 requests per minute and 1 MiB per hour limits rely on one
Gunicorn worker and must not be scaled horizontally without shared limiter
state.

The worker requests a refill when remaining bits are at or below 25 percent of
capacity. IBM credentials remain environment variables and are not part of the
image, manifest, or logs.

## Worker deployment

The refill worker reads the monthly UTC run from
`src/config/execution_policy.json` (`QuantumCacheFill_Monthly`, day 1 at
07:00 UTC). It requires these Fly secrets or environment variables:

- `IBM_CLOUD_API_KEY` and `IBM_QUANTUM_INSTANCE` for IBM Quantum. These are
  read only by the worker process.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` for Tigris S3 compatibility.
- `QUANTUM_MANIFEST_SIGNING_KEY` for HMAC signing.
- `TIGRIS_ENDPOINT` is optional and defaults to Fly Tigris.

Set the IBM and Tigris credentials on the `quantum-randomness` app with `fly
secrets set`; the machine runner strips them before starting the API child and
passes them only to the refill worker. Set both `FLY_BEARER_TOKEN` and
`QUANTUM_MANIFEST_SIGNING_KEY` in the operator environment and run
`tools/deploy_randomness_service.ps1`. The script validates both values before
calling Fly, forwards them to the one app as secrets without storing either in
source, and never uses or provisions the Fly operator credential as an app
secret. Deployment creates exactly one machine and one mounted
`quantum_randomness_data` volume; the machine runner then starts both sibling
processes against that boundary.

`boto3` is used only by the worker adapter. A refill is generated and signed,
uploaded to the pending object, promoted to the stable key, and only then
accepted into the local retained-generation file. Provider or storage failure
therefore leaves the previous verified generation available. The worker logs
only counts and lifecycle state, never credentials, bits, signatures, or
manifest contents.