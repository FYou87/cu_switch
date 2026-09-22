#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shlwapi.h>

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    char dir[MAX_PATH];
    char python[MAX_PATH];
    char command[MAX_PATH * 2];
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;

    (void)inst;
    (void)prev;
    (void)cmd;
    (void)show;

    GetModuleFileNameA(NULL, dir, MAX_PATH);
    PathRemoveFileSpecA(dir);
    wsprintfA(python, "%s\\python\\pythonw.exe", dir);
    if (GetFileAttributesA(python) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxA(NULL, "找不到内置 Python。请完整解压整个 Witch 文件夹后再打开。", "Witch", MB_OK | MB_ICONERROR);
        return 1;
    }
    wsprintfA(command, "\"%s\" -m witch", python);
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    if (!CreateProcessA(python, command, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxA(NULL, "启动失败。", "Witch", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
