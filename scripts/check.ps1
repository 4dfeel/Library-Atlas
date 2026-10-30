param([switch]$WithBrowser)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath (Join-Path $PSScriptRoot '..ackend')
try {
    $atlasPython = '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $atlasPython)) { throw 'Backend missing. Run scripts\setup-backend.cmd first.' }
    foreach ($atlasArgs in @(@('-m', 'ruff', 'check', 'app', 'tests'), @('-m', 'ruff', 'format', '--check', 'app', 'tests'), @('-m', 'mypy'), @('-m', 'pytest'))) {
        & $atlasPython @atlasArgs
        if ($LASTEXITCODE -ne 0) { throw "Check failed: $($atlasArgs -join ' ')" }
    }
} finally {
    Pop-Location
}
Push-Location -LiteralPath (Join-Path $PSScriptRoot '..\frontend')
try {
    foreach ($atlasCheck in @('typecheck', 'lint', 'format:check', 'test', 'build')) {
        & npm.cmd run $atlasCheck
        if ($LASTEXITCODE -ne 0) { throw "Check failed: $atlasCheck" }
    }
    if ($WithBrowser) {
        & npm.cmd run test:e2e
        if ($LASTEXITCODE -ne 0) { throw 'Playwright failed' }
    }
} finally {
    Pop-Location
}
