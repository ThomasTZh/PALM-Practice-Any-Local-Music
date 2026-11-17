/*
 * PALM native Windows launcher.
 *
 * Build with the Windows SDK (cl.exe) as a GUI subsystem executable:
 *   cl /nologo /O2 /W4 /DUNICODE /D_UNICODE palm_launcher.c /link /SUBSYSTEM:WINDOWS /OUT:PALM.exe
 *
 * The executable prepares the packaged environment, starts the bundled
 * pythonw.exe (falling back to python.exe) with -m basseparate.launcher
 * --window, and shows a visible error if the child exits immediately. It never
 * creates a console and uses wide-character Win32 APIs so spaces and non-ASCII
 * paths are preserved. palm.cmd remains the diagnostic console fallback.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>
#include <stdio.h>

#define COMMAND_CAPACITY 32768
#define PATH_CAPACITY (MAX_PATH * 4)
#define STARTUP_CHECK_MS 2500

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

static void set_environment(const wchar_t *name, const wchar_t *value) {
    (void)SetEnvironmentVariableW(name, value);
}

static void set_environment_if_missing(const wchar_t *name, const wchar_t *value) {
    if (GetEnvironmentVariableW(name, NULL, 0) == 0) {
        set_environment(name, value);
    }
}

static void default_data_root(const wchar_t *app_root, wchar_t *destination, size_t capacity) {
    wchar_t local_app_data[PATH_CAPACITY];
    DWORD length = GetEnvironmentVariableW(L"LOCALAPPDATA", local_app_data, (DWORD)(sizeof(local_app_data) / sizeof(local_app_data[0])));
    if (length == 0 || length >= sizeof(local_app_data) / sizeof(local_app_data[0])) {
        swprintf_s(destination, capacity, L"%ls\\data", app_root);
        return;
    }
    swprintf_s(destination, capacity, L"%ls\\palm", local_app_data);
}

static void configure_environment(const wchar_t *app_root) {
    wchar_t python_path[PATH_CAPACITY];
    wchar_t data_root[PATH_CAPACITY];

    swprintf_s(python_path, sizeof(python_path) / sizeof(python_path[0]), L"%ls\\src", app_root);
    default_data_root(app_root, data_root, sizeof(data_root) / sizeof(data_root[0]));

    set_environment(L"PALM_MODE", L"packaged");
    set_environment(L"PALM_APP_ROOT", app_root);
    set_environment_if_missing(L"PALM_DATA_DIR", data_root);
    set_environment(L"PYTHONPATH", python_path);
    set_environment(L"PYTHONUTF8", L"1");
    set_environment(L"PYTHONIOENCODING", L"utf-8");
    set_environment(L"PYTHONDONTWRITEBYTECODE", L"1");
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show) {
    wchar_t exe_path[PATH_CAPACITY];
    wchar_t app_root[PATH_CAPACITY];
    wchar_t python[PATH_CAPACITY];
    wchar_t command[COMMAND_CAPACITY];
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    DWORD wait_result;
    DWORD exit_code = 1;
    wchar_t error_text[1024];

    (void)instance;
    (void)previous;
    (void)command_line;
    (void)show;

    if (GetModuleFileNameW(NULL, exe_path, (DWORD)(sizeof(exe_path) / sizeof(exe_path[0]))) == 0) {
        MessageBoxW(NULL, L"PALM could not determine its application folder.", L"PALM", MB_ICONERROR | MB_OK);
        return 1;
    }
    wcscpy_s(app_root, sizeof(app_root) / sizeof(app_root[0]), exe_path);
    parent_directory(app_root);
    configure_environment(app_root);

    swprintf_s(python, sizeof(python) / sizeof(python[0]), L"%ls\\python\\pythonw.exe", app_root);
    if (!file_exists(python)) {
        swprintf_s(python, sizeof(python) / sizeof(python[0]), L"%ls\\python\\python.exe", app_root);
    }
    if (!file_exists(python)) {
        MessageBoxW(
            NULL,
            L"The embedded PALM Python runtime was not found.\n"
            L"Extract the complete ZIP and keep PALM.exe beside the python folder.\n"
            L"For diagnostics, run palm.cmd --help.",
            L"PALM",
            MB_ICONERROR | MB_OK);
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
        MessageBoxW(
            NULL,
            L"PALM could not start its bundled Python runtime.\n"
            L"Check that the ZIP was fully extracted and that your user account can run PALM.exe.",
            L"PALM",
            MB_ICONERROR | MB_OK);
        return 1;
    }

    wait_result = WaitForSingleObject(process.hProcess, STARTUP_CHECK_MS);
    if (wait_result == WAIT_OBJECT_0) {
        (void)GetExitCodeProcess(process.hProcess, &exit_code);
        swprintf_s(
            error_text,
            sizeof(error_text) / sizeof(error_text[0]),
            L"PALM's Python process exited before the control window opened (exit code %lu).\n"
            L"Open palm.cmd --help for diagnostics or check the logs in the PALM data folder.",
            (unsigned long)exit_code);
        MessageBoxW(NULL, error_text, L"PALM", MB_ICONERROR | MB_OK);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        return 1;
    }
    if (wait_result == WAIT_FAILED) {
        MessageBoxW(
            NULL,
            L"PALM could not verify that its Python process started.\n"
            L"Run palm.cmd --help for diagnostics.",
            L"PALM",
            MB_ICONERROR | MB_OK);
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        return 1;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
