/* SYSAI-Setup.exe — установка агента SYSAI на ПК в один клик (docs/opo/TASKS.md, ОПО-6.2).
 *
 * Маленький консольный загрузчик. Внутри себя он несёт адрес сервера и одноразовый код подключения:
 * SYSAI подставляет их в файл при скачивании (app/net/installer.py, exe()). Кода нет — загрузчик
 * спросит его сам. Дальше он запускает тот же подписанный установщик, что и строка PowerShell
 * (`/agents/api/install.ps1`), и показывает, чем всё кончилось.
 *
 * Собирается кросс-компилятором: agents/installer/build.sh (x86_64-w64-mingw32-gcc).
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MARK_LEN 12
#define FIELD 512
#define BLOCK (FIELD * 2)
#define MAX_CMD 4096

/* Блок конфигурации: метка и 1024 байта (адрес сервера + код), которые заполняет сервер.
   Метка ищется в файле по XOR-копии ниже, поэтому в двоичном коде она встречается ровно один раз. */
__attribute__((used))
static const unsigned char CONFIG_BLOCK[MARK_LEN + BLOCK] = {
    'S', 'Y', 'S', 'A', 'I', '-', 'C', 'F', 'G', '-', 'V', '1'
    /* остальное — нули, их и заменяет сервер */
};

/* «SYSAI-CFG-V1», закодированная: в файле этой строки нет, кроме самого блока. */
static const unsigned char MARK_X[MARK_LEN] = {
    'S' ^ 0x5A, 'Y' ^ 0x5A, 'S' ^ 0x5A, 'A' ^ 0x5A, 'I' ^ 0x5A, '-' ^ 0x5A,
    'C' ^ 0x5A, 'F' ^ 0x5A, 'G' ^ 0x5A, '-' ^ 0x5A, 'V' ^ 0x5A, '1' ^ 0x5A
};

static char g_server[FIELD];
static char g_code[FIELD];

/* Читает свой файл и достаёт блок конфигурации, который положил сервер. */
static int read_config(void)
{
    char mark[MARK_LEN];
    for (int i = 0; i < MARK_LEN; i++) mark[i] = (char)(MARK_X[i] ^ 0x5A);

    char path[MAX_PATH];
    DWORD n = GetModuleFileNameA(NULL, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;

    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return 0; }
    long size = ftell(f);
    if (size <= 0) { fclose(f); return 0; }
    rewind(f);

    char *buf = (char *)malloc((size_t)size);
    if (!buf) { fclose(f); return 0; }
    size_t got = fread(buf, 1, (size_t)size, f);
    fclose(f);

    int ok = 0;
    for (size_t i = 0; i + MARK_LEN + BLOCK <= got; i++) {
        if (memcmp(buf + i, mark, MARK_LEN) != 0) continue;
        const char *p = buf + i + MARK_LEN;
        memcpy(g_server, p, FIELD);
        memcpy(g_code, p + FIELD, FIELD);
        g_server[FIELD - 1] = 0;
        g_code[FIELD - 1] = 0;
        ok = 1;
        break;
    }
    free(buf);
    return ok;
}

static void trim(char *s)
{
    size_t len = strlen(s);
    while (len && (s[len - 1] == '\n' || s[len - 1] == '\r' || s[len - 1] == ' ' || s[len - 1] == '\t'))
        s[--len] = 0;
    size_t start = 0;
    while (s[start] == ' ' || s[start] == '\t') start++;
    if (start) memmove(s, s + start, strlen(s + start) + 1);
}

static void banner(void)
{
    printf("\n");
    printf("  ============================================\n");
    printf("   SYSAI  -  установка агента на этот ПК\n");
    printf("  ============================================\n\n");
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    SetConsoleTitleA("SYSAI - установка агента");

    banner();

    if (!read_config() || !g_server[0]) {
        printf("  Этот файл повреждён: в нём нет адреса сервера SYSAI.\n");
        printf("  Скачайте установщик заново со страницы агента в SYSAI.\n\n");
        system("pause");
        return 2;
    }

    /* Код можно передать аргументом: SYSAI-Setup.exe 7K2M-9QXA */
    if (argc > 1 && argv[1][0]) {
        strncpy(g_code, argv[1], FIELD - 1);
        g_code[FIELD - 1] = 0;
    }
    trim(g_code);

    if (!g_code[0]) {
        char line[128];
        printf("  Код подключения со страницы агента в SYSAI.\n");
        printf("  Код: ");
        if (!fgets(line, sizeof(line), stdin)) return 3;
        trim(line);
        strncpy(g_code, line, FIELD - 1);
        g_code[FIELD - 1] = 0;
        if (!g_code[0]) {
            printf("\n  Без кода установка не начнётся: получите его на странице агента.\n\n");
            system("pause");
            return 3;
        }
    }

    printf("  Сервер: %s\n", g_server);
    printf("  Ставлю агента. Это займёт несколько минут, окно закрывать не нужно.\n\n");

    char cmd[MAX_CMD];
    snprintf(cmd, sizeof(cmd),
             "powershell -NoProfile -ExecutionPolicy Bypass -Command "
             "\"$ErrorActionPreference='Stop'; "
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             "$env:SYSAI_CODE='%s'; "
             "irm '%s/agents/api/install.ps1' | iex\"",
             g_code, g_server);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessA(NULL, cmd, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) {
        printf("  Не удалось запустить PowerShell (код %lu).\n", (unsigned long)GetLastError());
        printf("  Откройте PowerShell и выполните:\n\n");
        printf("  $env:SYSAI_CODE='%s'; irm '%s/agents/api/install.ps1' | iex\n\n", g_code, g_server);
        system("pause");
        return 4;
    }

    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);

    printf("\n");
    if (code == 0) {
        printf("  Готово. Агент SYSAI установлен: ярлык «Агент SYSAI» на рабочем столе.\n");
        printf("  Синхронизация включена при входе в Windows.\n\n");
    } else {
        printf("  Установка не закончилась (код %lu). Что делать:\n", (unsigned long)code);
        printf("  - проверьте, что код не истёк (он живёт 10 минут) и получен заново;\n");
        printf("  - запустите установщик ещё раз: он продолжит с того же места;\n");
        printf("  - журнал: %%LOCALAPPDATA%%\\SYSAI\\logs\\install.log\n\n");
    }
    system("pause");
    return (int)code;
}
