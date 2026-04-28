$ErrorActionPreference = "Stop"

$repo = "E:\codemain\github\GenericAgent"
$python = Join-Path $repo ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "GenericAgent venv not found. Expected: $python"
}

if (-not $env:OPENROUTER_API_KEY) {
    throw "OPENROUTER_API_KEY is not set. GenericAgent needs a model API key before it can run."
}

Push-Location $repo
try {
    & $python agentmain.py
}
finally {
    Pop-Location
}
