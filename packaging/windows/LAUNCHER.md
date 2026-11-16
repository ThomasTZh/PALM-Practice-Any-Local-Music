# Native Windows launcher

`palm_launcher.c` is the Win32 GUI-subsystem source for `PALM.exe`. It locates
the extracted app root from its own path, starts `python\pythonw.exe` (or
`python\python.exe`) with `-m basseparate.launcher --window`, and never creates
a console. It uses wide-character APIs and quoted `CreateProcessW` arguments so
spaces and non-ASCII paths work.

Build it from an x64 Native Tools Command Prompt with:

```powershell
.\build_launcher.ps1
```

`palm.cmd` remains the diagnostic console fallback and invokes the launcher
with `--console`. The control window is the default GUI; the native exe passes
`--window` explicitly. No binary is committed to git; package builders compile
it for the Windows release.
