#!/bin/sh
# Собирает SYSAI-Setup.exe — консольный загрузчик установщика агента (bootstrapper.c).
# Нужен кросс-компилятор: apt-get install gcc-mingw-w64-x86-64
# Готовый файл лежит в репозитории: сервер отдаёт его с подставленными адресом и кодом
# (app/net/installer.py, exe()). Пересобирать — только когда меняется bootstrapper.c.
set -e
cd "$(dirname "$0")"
CC=${CC:-x86_64-w64-mingw32-gcc}
command -v "$CC" >/dev/null 2>&1 || { echo "нет $CC: apt-get install gcc-mingw-w64-x86-64" >&2; exit 1; }
"$CC" -O2 -s -Wall -Wextra -o SYSAI-Setup.exe bootstrapper.c
echo "собран SYSAI-Setup.exe ($(wc -c < SYSAI-Setup.exe) байт)"
