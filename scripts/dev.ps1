param([ValidateSet('dev', 'preview')][string]$Mode = 'dev')
$ErrorActionPreference = 'Stop'
$atlasFrontend = Join-Path $PSScriptRoot '..\frontend'
Push-Location -LiteralPath $atlasFrontend
try {
    if (-not (Test-Path -LiteralPath 'node_modules')) {
        throw 'Dependencies missing. Run npm.cmd ci in frontend first.'
    }
    & npm.cmd run $Mode
    if ($LASTEXITCODE -ne 0) { throw "npm $Mode failed ($LASTEXITCODE)" }
} finally {
    Pop-Location
}
