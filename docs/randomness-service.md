# Quantum Randomness Service

The `quantum-randomness` Fly.io app exposes bounded JSON primitives at `/v1`.
The API machine runs in `iad` behind Gunicorn. The refill worker is deployed as
the separate `quantum-randomness-worker` app, so IBM and Tigris credentials are
not present in the API app environment.

## Contract

- `GET /health` is public.
- `GET /v1/status` is public and reports only `current`, `stale`, or
  `unavailable` cache state plus the selected source.
- `GET /v1/bytes?n=1..1024`, `/v1/bits?n=1..8192`, `/v1/ints?min=&max=`, and
  `/v1/bool` require `Authorization: Bearer <FLY_BEARER_TOKEN>`.
- The service accepts one Fly-managed bearer token, compares it in constant
  time, and never emits it, raw cache data, manifest hashes, or provider
  credentials in logs or status responses.
- Limits are 1 KiB per request, 10 requests per minute, and 1 MiB per hour.

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
range in a SQLite `BEGIN IMMEDIATE` transaction keyed by generation, so
independently running Gunicorn workers cannot return the same fresh range.
SQLite or cache I/O failure preserves the existing OS-CSPRNG fallback and
provenance contract. The API deployment is intentionally one Fly Machine with
the `quantum_randomness_data` volume attached; do not scale the API app across
machines unless the reservation ledger is moved to a shared transactional
store. The separate refill worker uses its own volume and never serves API
bytes.

The worker requests a refill when remaining bits are at or below 25 percent of
capacity. IBM credentials remain environment variables and are not part of the
image, manifest, or logs.

## Worker deployment

The `quantum-randomness-worker` app reads the monthly UTC run from
`src/config/execution_policy.json` (`QuantumCacheFill_Monthly`, day 1 at
07:00 UTC). It requires these Fly secrets or environment variables:

- `IBM_CLOUD_API_KEY` and `IBM_QUANTUM_INSTANCE` for IBM Quantum. These are
  read only by the worker process.
- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` for Tigris S3 compatibility.
- `QUANTUM_MANIFEST_SIGNING_KEY` for HMAC signing.
- `TIGRIS_ENDPOINT` is optional and defaults to Fly Tigris.

Set those four worker secrets with `fly secrets set --app
quantum-randomness-worker ...`; do not set them on the API app. Keep the API
at one machine with `fly scale count 1 --app quantum-randomness`, then deploy
it with `fly deploy --config fly.toml`; deploy the worker with
`fly deploy --config fly.worker.toml`.

`boto3` is used only by the worker adapter. A refill is generated and signed,
uploaded to the pending object, promoted to the stable key, and only then
accepted into the local retained-generation file. Provider or storage failure
therefore leaves the previous verified generation available. The worker logs
only counts and lifecycle state, never credentials, bits, signatures, or
manifest contents.