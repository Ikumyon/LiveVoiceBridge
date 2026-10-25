[CmdletBinding()]
param([string]$Python = 'python')

. (Join-Path $PSScriptRoot 'build_common.ps1')
exit (Invoke-ProjectBuild -Python $Python -Target 'python')
