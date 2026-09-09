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
$bearerToken = [Environment]::GetEnvironmentVariable("FLY_BEARER_TOKEN")
if ([string]::IsNullOrWhiteSpace($bearerToken)) {
    throw "FLY_BEARER_TOKEN must be provided through the operator environment"
}

$secretPayload = @(
    "FLY_BEARER_TOKEN=$bearerToken"
    "QUANTUM_MANIFEST_SIGNING_KEY=$signingKey"
) -join "`n"
$secretPayload | fly secrets import --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "API signing-key secret update failed"
}
fly scale count 1 --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "fly scale count failed"
}

fly deploy --config fly.toml --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "fly deploy failed"
}
