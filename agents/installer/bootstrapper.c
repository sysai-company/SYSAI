/* SYSAI-Setup.exe — установка агента SYSAI на ПК в один клик (docs/opo/TASKS.md, ОПО-6.2).
 *
 * Это окно, а не консоль: инженер запускает файл двойным щелчком и видит, что происходит. Внутри себя файл несёт
 * адрес сервера и одноразовый код подключения — SYSAI подставляет их при скачивании (app/net/installer.py, exe()).
 * Кода нет — окно спросит его само. Дальше запускается тот же установщик, что и строка PowerShell
 * (`/agents/api/install.ps1`), а окно показывает его шаги (`SYSAI: …`) и чем всё кончилось.
 *
 * Собирается кросс-компилятором: agents/installer/build.sh (x86_64-w64-mingw32-gcc, -mwindows -municode).
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#define MARK_LEN 12
#define FIELD 512
#define BLOCK (FIELD * 2)
#define MAX_CMD 4096

/* ---------- палитра: та же, что в окне агента (тёплый уголь и глина) ---------- */
#define C_BG      RGB(22, 21, 19)
#define C_BG2     RGB(29, 28, 25)
#define C_CARD    RGB(33, 32, 28)
#define C_LINE    RGB(56, 54, 47)
#define C_LINE2   RGB(72, 69, 60)
#define C_TEXT    RGB(240, 238, 230)
#define C_SOFT    RGB(201, 198, 187)
#define C_MUTED   RGB(143, 140, 130)
#define C_CLAY    RGB(217, 142, 138)
#define C_CLAY2   RGB(228, 162, 158)
#define C_BLUE    RGB(143, 168, 216)
#define C_INK     RGB(35, 20, 18)

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

static char g_server_a[FIELD];
static char g_code_a[FIELD];
static wchar_t g_server[FIELD];
static wchar_t g_code[FIELD];

/* окно */
static HWND g_hwnd, g_edit;
static HBRUSH g_br_bg;
static HFONT g_f_brand, g_f_head, g_f_body, g_f_small, g_f_btn;
static enum { ST_IDLE, ST_RUN, ST_DONE, ST_FAIL } g_state = ST_IDLE;
static wchar_t g_status[512];
static wchar_t g_detail[512];
static float g_phase;
static HANDLE g_proc;

#define W_WIDTH 620
#define W_HEIGHT 420
#define BTN_X 28
#define BTN_Y (W_HEIGHT - 68)
#define BTN_W 190
#define BTN_H 42

/* ---------- своя конфигурация внутри файла ---------- */
static int read_config(void)
{
    char mark[MARK_LEN];
    char path[MAX_PATH];
    DWORD n;
    FILE *f;
    long size;
    char *buf;
    size_t got;
    size_t i;
    int ok = 0;

    for (i = 0; i < MARK_LEN; i++) mark[i] = (char)(MARK_X[i] ^ 0x5A);

    n = GetModuleFileNameA(NULL, path, MAX_PATH);
    if (!n || n >= MAX_PATH) return 0;

    f = fopen(path, "rb");
    if (!f) return 0;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return 0; }
    size = ftell(f);
    if (size <= 0) { fclose(f); return 0; }
    rewind(f);

    buf = (char *)malloc((size_t)size);
    if (!buf) { fclose(f); return 0; }
    got = fread(buf, 1, (size_t)size, f);
    fclose(f);

    for (i = 0; i + MARK_LEN + BLOCK <= got; i++) {
        if (memcmp(buf + i, mark, MARK_LEN) != 0) continue;
        memcpy(g_server_a, buf + i + MARK_LEN, FIELD);
        memcpy(g_code_a, buf + i + MARK_LEN + FIELD, FIELD);
        g_server_a[FIELD - 1] = 0;
        g_code_a[FIELD - 1] = 0;
        ok = 1;
        break;
    }
    free(buf);
    return ok;
}

static void trim_a(char *s)
{
    size_t len = strlen(s), start = 0;
    while (len && (s[len - 1] == '\n' || s[len - 1] == '\r' || s[len - 1] == ' ' || s[len - 1] == '\t'))
        s[--len] = 0;
    while (s[start] == ' ' || s[start] == '\t') start++;
    if (start) memmove(s, s + start, strlen(s + start) + 1);
}

static void to_wide(const char *src, wchar_t *dst, int cap)
{
    if (!MultiByteToWideChar(CP_UTF8, 0, src, -1, dst, cap)) dst[0] = 0;
    dst[cap - 1] = 0;
}

/* ---------- мелочи рисования ---------- */
static void fill_gradient(HDC dc, int x, int y, int w, int h, COLORREF a, COLORREF b)
{
    int i;
    for (i = 0; i < h; i++) {
        int t = (h > 1) ? (i * 255 / (h - 1)) : 0;
        int r = GetRValue(a) + (GetRValue(b) - GetRValue(a)) * t / 255;
        int g = GetGValue(a) + (GetGValue(b) - GetGValue(a)) * t / 255;
        int bl = GetBValue(a) + (GetBValue(b) - GetBValue(a)) * t / 255;
        RECT line = { x, y + i, x + w, y + i + 1 };
        HBRUSH br = CreateSolidBrush(RGB(r, g, bl));
        FillRect(dc, &line, br);
        DeleteObject(br);
    }
}

static void round_fill(HDC dc, int x, int y, int w, int h, int r, COLORREF fill, COLORREF line)
{
    HBRUSH br = CreateSolidBrush(fill);
    HPEN pen = CreatePen(PS_SOLID, 1, line);
    HGDIOBJ ob = SelectObject(dc, br);
    HGDIOBJ op = SelectObject(dc, pen);
    RoundRect(dc, x, y, x + w, y + h, r, r);
    SelectObject(dc, ob);
    SelectObject(dc, op);
    DeleteObject(br);
    DeleteObject(pen);
}

static void text_at(HDC dc, const wchar_t *s, int x, int y, int w, int h, HFONT f, COLORREF c, UINT flags)
{
    HGDIOBJ old = SelectObject(dc, f);
    RECT box = { x, y, x + w, y + h };
    SetTextColor(dc, c);
    SetBkMode(dc, TRANSPARENT);
    DrawTextW(dc, s, -1, &box, flags | DT_NOPREFIX);
    SelectObject(dc, old);
}

/* ---------- установка ---------- */
static void redraw(void)
{
    if (g_hwnd) InvalidateRect(g_hwnd, NULL, FALSE);
}

static void set_status(const wchar_t *status, const wchar_t *detail)
{
    if (status) { wcsncpy(g_status, status, 511); g_status[511] = 0; }
    if (detail) { wcsncpy(g_detail, detail, 511); g_detail[511] = 0; }
    redraw();
}

/* Читает вывод установщика и показывает его шаги: строки «SYSAI: …» — это и есть ход работы. */
static DWORD WINAPI reader_thread(LPVOID arg)
{
    HANDLE pipe = (HANDLE)arg;
    char buf[8192];
    size_t used = 0;
    DWORD got;

    while (ReadFile(pipe, buf + used, (DWORD)(sizeof(buf) - used - 1), &got, NULL) && got > 0) {
        char *start = buf;
        used += got;
        buf[used] = 0;
        for (;;) {
            char *nl = strchr(start, '\n');
            char *cr;
            char *line;
            if (!nl) break;
            *nl = 0;
            line = start;
            while (*line == ' ' || *line == '\t') line++;
            if (strncmp(line, "SYSAI: ", 7) == 0) {
                wchar_t w[512];
                cr = strchr(line, '\r');
                if (cr) *cr = 0;
                to_wide(line + 7, w, 512);
                set_status(w, NULL);
            }
            start = nl + 1;
        }
        used = strlen(start);
        memmove(buf, start, used + 1);
        if (used > sizeof(buf) - 64) used = 0;  /* строку без конца не копим бесконечно */
    }
    return 0;
}

static void start_install(void)
{
    wchar_t cmd[MAX_CMD];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    SECURITY_ATTRIBUTES sa;
    HANDLE rd = NULL, wr = NULL;

    if (g_state == ST_RUN) return;

    if (g_edit) {
        GetWindowTextW(g_edit, g_code, FIELD);
        while (g_code[0] == L' ') memmove(g_code, g_code + 1, wcslen(g_code) * sizeof(wchar_t));
    }
    if (!g_code[0]) {
        g_state = ST_FAIL;
        set_status(L"Нужен код подключения",
                   L"Он на странице агента в SYSAI, в карточке этого компьютера. Вставьте код в поле выше.");
        return;
    }

    g_state = ST_RUN;
    g_phase = 0;
    set_status(L"Начинаю установку…", L"Закрывать окно не нужно: это займёт несколько минут.");

    swprintf(cmd, MAX_CMD,
             L"powershell -NoProfile -ExecutionPolicy Bypass -Command "
             L"\"$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
             L"$env:SYSAI_CODE='%ls'; irm '%ls/agents/api/install.ps1' | iex\"",
             g_code, g_server);

    ZeroMemory(&sa, sizeof(sa));
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;
    if (!CreatePipe(&rd, &wr, &sa, 0)) {
        g_state = ST_FAIL;
        set_status(L"Не удалось запустить установку", L"Система не дала создать канал для вывода.");
        return;
    }
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = wr;
    si.hStdError = wr;
    ZeroMemory(&pi, sizeof(pi));

    if (!CreateProcessW(NULL, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi)) {
        CloseHandle(rd);
        CloseHandle(wr);
        g_state = ST_FAIL;
        set_status(L"Не удалось запустить PowerShell",
                   L"Откройте PowerShell от имени администратора и выполните строку установки со страницы агента.");
        return;
    }
    CloseHandle(wr);
    g_proc = pi.hProcess;
    CloseHandle(pi.hThread);
    {
        HANDLE th = CreateThread(NULL, 0, reader_thread, rd, 0, NULL);
        if (th) CloseHandle(th);
    }
    SetTimer(g_hwnd, 1, 40, NULL);
    SetTimer(g_hwnd, 2, 400, NULL);
}

static void finish(void)
{
    DWORD code = 1;
    if (!g_proc) return;
    GetExitCodeProcess(g_proc, &code);
    CloseHandle(g_proc);
    g_proc = NULL;
    KillTimer(g_hwnd, 1);
    KillTimer(g_hwnd, 2);
    if (code == 0) {
        g_state = ST_DONE;
        set_status(L"Готово — агент установлен",
                   L"На рабочем столе ярлык «Агент SYSAI»; синхронизация включается при входе в Windows.");
    } else {
        g_state = ST_FAIL;
        set_status(L"Установка не закончилась",
                   L"Проверьте, что код не истёк (он живёт 10 минут), и запустите файл снова — он продолжит с того же "
                   L"места. Журнал: %LOCALAPPDATA%\\SYSAI\\logs\\install.log");
    }
}

/* ---------- отрисовка окна ---------- */
static void paint(HDC target)
{
    HDC dc = CreateCompatibleDC(target);
    HBITMAP bm = CreateCompatibleBitmap(target, W_WIDTH, W_HEIGHT);
    HGDIOBJ old = SelectObject(dc, bm);
    int bx = 28;

    fill_gradient(dc, 0, 0, W_WIDTH, W_HEIGHT, C_BG, C_BG2);

    /* шапка: логотип-плитка и словцо */
    round_fill(dc, bx, 26, 34, 34, 10, RGB(26, 25, 22), C_BLUE);
    {
        HBRUSH b1 = CreateSolidBrush(C_CLAY);
        RECT d1 = { bx + 9, 36, bx + 14, 51 };
        RECT d2 = { bx + 17, 34, bx + 22, 53 };
        RECT d3 = { bx + 25, 39, bx + 30, 48 };
        FillRect(dc, &d1, b1);
        FillRect(dc, &d2, b1);
        FillRect(dc, &d3, b1);
        DeleteObject(b1);
    }
    text_at(dc, L"SYSAI", bx + 46, 24, 200, 24, g_f_brand, C_TEXT, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
    text_at(dc, L"установка агента", bx + 46, 46, 260, 18, g_f_small, C_MUTED, DT_LEFT | DT_SINGLELINE);

    /* крестик */
    {
        HPEN pen = CreatePen(PS_SOLID, 2, C_MUTED);
        HGDIOBJ op = SelectObject(dc, pen);
        MoveToEx(dc, W_WIDTH - 46, 32, NULL);
        LineTo(dc, W_WIDTH - 32, 46);
        MoveToEx(dc, W_WIDTH - 32, 32, NULL);
        LineTo(dc, W_WIDTH - 46, 46);
        SelectObject(dc, op);
        DeleteObject(pen);
    }

    /* карточка с ходом работы */
    round_fill(dc, bx, 88, W_WIDTH - bx * 2, 212, 16, C_CARD, C_LINE);
    text_at(dc, L"Агент SYSAI на этом компьютере", bx + 22, 104, W_WIDTH - bx * 2 - 44, 26, g_f_head, C_TEXT,
            DT_LEFT | DT_SINGLELINE);
    text_at(dc, g_status, bx + 22, 138, W_WIDTH - bx * 2 - 44, 26, g_f_body, C_SOFT,
            DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);

    /* полоса: пока идёт установка — мягкое дыхание, иначе честно заполнена или пуста */
    {
        int px = bx + 22, py = 174, pw = W_WIDTH - bx * 2 - 44, ph = 6;
        round_fill(dc, px, py, pw, ph, 6, C_BG, C_LINE);
        if (g_state == ST_RUN) {
            int seg = pw / 3;
            int pos = (int)((pw - seg) * g_phase);
            HRGN clip = CreateRoundRectRgn(px, py, px + pw + 1, py + ph + 1, 6, 6);
            SelectClipRgn(dc, clip);
            fill_gradient(dc, px + pos, py, seg, ph, C_CLAY, C_BLUE);
            SelectClipRgn(dc, NULL);
            DeleteObject(clip);
        } else if (g_state == ST_DONE) {
            round_fill(dc, px, py, pw, ph, 6, C_CLAY, C_CLAY);
        }
    }
    if (g_edit) {
        text_at(dc, L"Код подключения", bx + 22, 190, 200, 16, g_f_small, C_MUTED, DT_LEFT | DT_SINGLELINE);
        text_at(dc, g_detail, bx + 22, 240, W_WIDTH - bx * 2 - 44, 48, g_f_small, C_MUTED,
                DT_LEFT | DT_WORDBREAK | DT_EDITCONTROL);
    } else {
        text_at(dc, g_detail, bx + 22, 194, W_WIDTH - bx * 2 - 44, 96, g_f_small, C_MUTED,
                DT_LEFT | DT_WORDBREAK | DT_EDITCONTROL);
    }

    /* кнопка — нарисована здесь же: отдельный контрол поверх полотна мигал бы и спорил за цвет */
    round_fill(dc, BTN_X, BTN_Y, BTN_W, BTN_H, 12, g_state == ST_RUN ? C_CARD : C_CLAY,
               g_state == ST_RUN ? C_LINE2 : C_CLAY2);
    text_at(dc, g_state == ST_RUN ? L"Устанавливаю…" : (g_state == ST_DONE ? L"Закрыть" : (g_state == ST_FAIL ? L"Повторить" : L"Установить")),
            BTN_X, BTN_Y, BTN_W, BTN_H, g_f_btn, g_state == ST_RUN ? C_MUTED : C_INK,
            DT_CENTER | DT_VCENTER | DT_SINGLELINE);

    text_at(dc, L"Сервер", BTN_X + BTN_W + 16, BTN_Y + 6, 60, 16, g_f_small, C_MUTED, DT_LEFT | DT_SINGLELINE);
    text_at(dc, g_server, BTN_X + BTN_W + 74, BTN_Y + 6, 240, 16, g_f_small, C_SOFT,
            DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
    text_at(dc, L"Окно можно свернуть — установка продолжится.", BTN_X + BTN_W + 16, BTN_Y + 24, 320, 16, g_f_small,
            C_MUTED, DT_LEFT | DT_SINGLELINE);

    BitBlt(target, 0, 0, W_WIDTH, W_HEIGHT, dc, 0, 0, SRCCOPY);
    SelectObject(dc, old);
    DeleteObject(bm);
    DeleteDC(dc);
}

static void make_fonts(void)
{
    g_f_brand = CreateFontW(-22, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_f_head = CreateFontW(-19, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Georgia");
    g_f_body = CreateFontW(-15, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_f_small = CreateFontW(-12, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
    g_f_btn = CreateFontW(-15, 0, 0, 0, FW_SEMIBOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Segoe UI");
}

static LRESULT CALLBACK wndproc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    switch (msg) {
    case WM_CTLCOLOREDIT: {
        HDC dc = (HDC)wp;
        SetTextColor(dc, C_TEXT);
        SetBkColor(dc, C_BG2);
        return (LRESULT)g_br_bg;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        paint(dc);
        EndPaint(hwnd, &ps);
        return 0;
    }
    case WM_TIMER:
        if (wp == 1) {
            g_phase += 0.035f;
            if (g_phase > 1.0f) g_phase = 0.0f;
            redraw();
        } else if (wp == 2 && g_proc) {
            DWORD code = 0;
            if (GetExitCodeProcess(g_proc, &code) && code != STILL_ACTIVE) finish();
        }
        return 0;
    case WM_KEYDOWN:
        if (wp == VK_RETURN) {
            if (g_state == ST_DONE) DestroyWindow(hwnd);
            else start_install();
            return 0;
        }
        return 0;
    case WM_LBUTTONDOWN: {
        int x = (short)LOWORD(lp), y = (short)HIWORD(lp);
        if (x > W_WIDTH - 56 && y < 62) { DestroyWindow(hwnd); return 0; }
        if (y < 74) { SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0); return 0; }
        if (x >= BTN_X && x <= BTN_X + BTN_W && y >= BTN_Y && y <= BTN_Y + BTN_H) {
            if (g_state == ST_DONE) DestroyWindow(hwnd);
            else start_install();
            return 0;
        }
        return 0;
    }
    case WM_SETCURSOR:
        if (LOWORD(lp) == HTCLIENT) {
            POINT p;
            GetCursorPos(&p);
            ScreenToClient(hwnd, &p);
            if ((p.x >= BTN_X && p.x <= BTN_X + BTN_W && p.y >= BTN_Y && p.y <= BTN_Y + BTN_H) ||
                (p.x > W_WIDTH - 56 && p.y < 62))
                SetCursor(LoadCursor(NULL, IDC_HAND));
            else
                SetCursor(LoadCursor(NULL, IDC_ARROW));
            return TRUE;
        }
        break;
    case WM_DESTROY:
        if (g_proc) {
            TerminateProcess(g_proc, 1);
            CloseHandle(g_proc);
            g_proc = NULL;
        }
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR cmdline, int show)
{
    WNDCLASSEXW wc;
    MSG msg;
    int argc = 0;
    LPWSTR *argv;

    (void)prev;
    (void)cmdline;
    (void)show;

    if (!read_config() || !g_server_a[0]) {
        MessageBoxW(NULL,
                    L"Этот файл повреждён: в нём нет адреса сервера SYSAI.\n"
                    L"Скачайте установщик заново со страницы агента в SYSAI.",
                    L"SYSAI — установка агента", MB_ICONERROR | MB_OK);
        return 2;
    }
    trim_a(g_code_a);
    to_wide(g_server_a, g_server, FIELD);
    to_wide(g_code_a, g_code, FIELD);

    /* Код можно передать аргументом: SYSAI-Setup.exe 7K2M-9QXA */
    argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv) {
        if (argc > 1 && argv[1][0]) {
            wcsncpy(g_code, argv[1], FIELD - 1);
            g_code[FIELD - 1] = 0;
        }
        LocalFree(argv);
    }

    make_fonts();
    g_br_bg = CreateSolidBrush(C_BG2);

    ZeroMemory(&wc, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.lpszClassName = L"SYSAISetup";
    RegisterClassExW(&wc);

    g_hwnd = CreateWindowExW(WS_EX_APPWINDOW, L"SYSAISetup", L"SYSAI — установка агента",
                             WS_POPUP, CW_USEDEFAULT, CW_USEDEFAULT, W_WIDTH, W_HEIGHT, NULL, NULL, inst, NULL);
    if (!g_hwnd) return 1;
    {
        HRGN rgn = CreateRoundRectRgn(0, 0, W_WIDTH + 1, W_HEIGHT + 1, 18, 18);
        SetWindowRgn(g_hwnd, rgn, TRUE);
    }
    {
        RECT work;
        SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
        SetWindowPos(g_hwnd, NULL,
                     work.left + ((work.right - work.left) - W_WIDTH) / 2,
                     work.top + ((work.bottom - work.top) - W_HEIGHT) / 2,
                     0, 0, SWP_NOSIZE | SWP_NOZORDER);
    }

    if (!g_code[0]) {
        g_edit = CreateWindowExW(0, L"EDIT", L"", WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
                                 BTN_X + 22, 208, 300, 26, g_hwnd, NULL, inst, NULL);
        if (g_edit) SendMessageW(g_edit, WM_SETFONT, (WPARAM)g_f_body, TRUE);
    }

    ShowWindow(g_hwnd, SW_SHOW);
    UpdateWindow(g_hwnd);
    SetFocus(g_edit ? g_edit : g_hwnd);

    set_status(g_code[0] ? L"Готов к установке" : L"Вставьте код подключения",
               g_code[0] ? L"Нажмите «Установить»: агент встанет на этот компьютер и появится на рабочем столе."
                         : L"Код — на странице агента в SYSAI, в карточке этого компьютера.");

    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}
