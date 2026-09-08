$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
$policy = Get-Content -Raw -Encoding UTF8 "fly.api-policy.json" | ConvertFrom-Json
if ($policy.machine_count -ne 1) {
    throw "quantum-randomness requires exactly one API machine"
}

fly scale count 1 --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "fly scale count failed"
}

fly deploy --config fly.toml --app $policy.app
if ($LASTEXITCODE -ne 0) {
    throw "fly deploy failed"
}
