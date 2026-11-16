/*
 * PALM native Windows launcher.
 *
 * Build with the Windows SDK (cl.exe) as a GUI subsystem executable:
 *   cl /nologo /O2 /W4 /DUNICODE /D_UNICODE palm_launcher.c /link /SUBSYSTEM:WINDOWS /OUT:PALM.exe
 *
 * The executable starts the bundled pythonw.exe (falling back to python.exe)
 * with -m basseparate.launcher --window. It never creates a console and uses
 * wide-character Win32 APIs so spaces and non-ASCII paths are preserved.
 * palm.cmd remains the diagnostic console fallback.
 */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

#define COMMAND_CAPACITY 32768

static int file_exists(const wchar_t *path) {
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES && !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static void parent_directory(wchar_t *path) {
    wchar_t *slash = wcsrchr(path, L'\\');
    if (slash != NULL) {
        *slash = L'\0';
    }
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    wchar_t exe_path[MAX_PATH * 4];
    wchar_t app_root[MAX_PATH * 4];
    wchar_t python[MAX_PATH * 4];
    wchar_t command[COMMAND_CAPACITY];
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;

    (void)instance;
    (void)previous;
    (void)command_line;
    (void)show;

    if (GetModuleFileNameW(NULL, exe_path, (DWORD)(sizeof(exe_path) / sizeof(exe_path[0]))) == 0) {
        return 1;
    }
    wcscpy_s(app_root, sizeof(app_root) / sizeof(app_root[0]), exe_path);
    parent_directory(app_root);

    swprintf_s(python, sizeof(python) / sizeof(python[0]), L"%ls\\python\\pythonw.exe", app_root);
    if (!file_exists(python)) {
        swprintf_s(python, sizeof(python) / sizeof(python[0]), L"%ls\\python\\python.exe", app_root);
    }
    if (!file_exists(python)) {
        MessageBoxW(NULL, L"The embedded PALM Python runtime was not found.\nReinstall PALM or use palm.cmd.", L"PALM", MB_ICONERROR | MB_OK);
        return 1;
    }

    swprintf_s(
        command,
        sizeof(command) / sizeof(command[0]),
        L"\"%ls\" -m basseparate.launcher --window",
        python
    );
    ZeroMemory(&startup, sizeof(startup));
    startup.cb = sizeof(startup);
    ZeroMemory(&process, sizeof(process));
    if (!CreateProcessW(
            python,
            command,
            NULL,
            NULL,
            FALSE,
            CREATE_NO_WINDOW,
            NULL,
            app_root,
            &startup,
            &process)) {
        MessageBoxW(NULL, L"PALM could not start its bundled Python runtime.", L"PALM", MB_ICONERROR | MB_OK);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
