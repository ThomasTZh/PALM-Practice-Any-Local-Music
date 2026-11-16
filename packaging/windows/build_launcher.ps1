# Build the native Windows PALM.exe from Win32 source.
# Run from a "x64 Native Tools Command Prompt for VS" (Windows SDK + MSVC).
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $here
try {
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw "cl.exe not found; open an x64 Native Tools Command Prompt for Visual Studio"
    }
    cl.exe /nologo /O2 /W4 /DUNICODE /D_UNICODE palm_launcher.c /link /SUBSYSTEM:WINDOWS /OUT:PALM.exe
    if ($LASTEXITCODE -ne 0) { throw "native launcher build failed" }
    Write-Host "built $here\\PALM.exe"
} finally {
    Pop-Location
}
