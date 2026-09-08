$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$policy = Get-Content -Raw -Encoding UTF8 "fly.api-policy.json" | ConvertFrom-Json
if ($policy.machine_count -ne 1) {
    throw "quantum-randomness requires exactly one API machine"
}
$signingKey = [Environment]::GetEnvironmentVariable("QUANTUM_MANIFEST_SIGNING_KEY")
if ([string]::IsNullOrWhiteSpace($signingKey)) {
    throw "QUANTUM_MANIFEST_SIGNING_KEY must be provided through the operator environment"
}

fly secrets set --app $policy.app "QUANTUM_MANIFEST_SIGNING_KEY=$signingKey"
if ($LASTEXITCODE -ne 0) {
    throw "API signing-key secret update failed"
}
fly secrets set --app quantum-randomness-worker "QUANTUM_MANIFEST_SIGNING_KEY=$signingKey"
if ($LASTEXITCODE -ne 0) {
    throw "worker signing-key secret update failed"
}

fly scale count 1 --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "fly scale count failed"
}

fly deploy --config fly.toml --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "fly deploy failed"
}

fly deploy --config fly.worker.toml --app quantum-randomness-worker
if ($LASTEXITCODE -ne 0) {
    throw "worker fly deploy failed"
}
