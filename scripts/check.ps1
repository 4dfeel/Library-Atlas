param([switch]$WithBrowser)
$ErrorActionPreference = 'Stop'
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
