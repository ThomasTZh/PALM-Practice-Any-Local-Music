# Build the native Windows PALM.exe from Win32 source.
# Run from a "x64 Native Tools Command Prompt for VS" (Windows SDK + MSVC).
param(
    [string]$Out = ""
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($Out)) { $Out = Join-Path $here "PALM.exe" }
$Out = [System.IO.Path]::GetFullPath($Out)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
Push-Location $here
try {
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw "cl.exe not found; open an x64 Native Tools Command Prompt for Visual Studio"
    }
    cl.exe /nologo /O2 /W4 /DUNICODE /D_UNICODE palm_launcher.c /link /SUBSYSTEM:WINDOWS "/OUT:$Out"
    if ($LASTEXITCODE -ne 0) { throw "native launcher build failed" }
    if (-not (Test-Path $Out)) { throw "native launcher was not produced: $Out" }
    Write-Host "built $Out"
} finally {
    Pop-Location
}
