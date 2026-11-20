'use strict';
// Перезапуск окна — в ту сборку, которую поставил синхронизатор.
//
// `app.relaunch()` запускает ровно ту программу, из которой окно сейчас работает. После обновления она старая: сборка
// ставится рядом (`desktop\app-<версия>-<sha>`), в `desktop.json` записывается новая пара exe+app, а окно продолжает
// жить в старой папке. Поэтому «Перезапустить» открывало ту же старую версию — снаружи это выглядело как
// «перезапускается, но ничего не происходит».
const fs = require('node:fs');
const path = require('node:path');

// Что установлено сейчас: <SYSAI>\desktop\desktop.json — его пишет синхронизатор сразу после установки.
function installed(home) {
  if (!home) return null;
  const file = path.join(String(home), 'desktop', 'desktop.json');
  let info;
  try {
    info = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null; // файла нет или он битый — работаем как раньше, обычным relaunch
  }
  if (!info || typeof info.exe !== 'string' || typeof info.app !== 'string') return null;
  // Проверяем, что сборка цела: иначе «перезапуск» в недокачанную папку — это окно, которое не откроется
  if (!info.exe || !fs.existsSync(info.exe)) return null;
  if (!fs.existsSync(path.join(info.app, 'package.json'))) return null;
  return {
    exe: String(info.exe),
    app: String(info.app),
    version: String(info.version || ''),
    installed_at: String(info.installed_at || ''),
  };
}

function same(a, b) {
  try {
    return path.resolve(String(a)).toLowerCase() === path.resolve(String(b)).toLowerCase();
  } catch {
    return false;
  }
}

// Куда перезапускаться: установленная сборка, если она отличается от той, что работает сейчас. null — обычный
// relaunch (мы и так в актуальной копии).
function next(home, running) {
  const got = installed(home);
  if (!got) return null;
  if (running && same(got.app, running)) return null;
  return got;
}

// Аргументы запуска: так же, как это делает синхронизатор (`sysai-agent desktop`).
function command(got) {
  return { exe: got.exe, args: [got.app], cwd: got.app };
}

module.exports = { installed, next, same, command };
