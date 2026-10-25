# Shared environment setup; dot-source from the two build scripts.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Actions and local checks share all build steps in build.py.
function Invoke-ProjectBuild {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][ValidateSet('rust', 'python')][string]$Target
    )

    $previousUtf8 = $env:PYTHONUTF8
    $previousOutputEncoding = $OutputEncoding
    $previousConsoleOutputEncoding = [Console]::OutputEncoding
    try {
        $OutputEncoding = [Text.UTF8Encoding]::new($false)
        [Console]::OutputEncoding = $OutputEncoding
        $env:PYTHONUTF8 = '1'
        & $Python (Join-Path $PSScriptRoot 'build.py') $Target | Out-Host
        return $LASTEXITCODE
    }
    catch {
        Write-Host $_.Exception.Message -ForegroundColor Red
        return 1
    }
    finally {
        $env:PYTHONUTF8 = $previousUtf8
        $OutputEncoding = $previousOutputEncoding
        [Console]::OutputEncoding = $previousConsoleOutputEncoding
    }
}
