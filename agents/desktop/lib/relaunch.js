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

// Передача «окно открылось» от новой копии к старой. Без неё старая уходит сразу после запуска новой, а та может
// не открыться (занятый замок, ошибка в сборке) — и на экране не остаётся ничего. Файл пишет новая копия в
// `ready-to-show`, старая ждёт его `waitReady` и только потом выходит.
function readyPath(home) {
  return path.join(String(home), 'desktop', 'relaunch.json');
}

function markReady() {
  const file = process.env.SYSAI_RELAUNCH_READY;
  if (!file) return false;
  delete process.env.SYSAI_RELAUNCH_READY;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    let version = '';
    try { version = require('../package.json').version; } catch { /* необязательно */ }
    fs.writeFileSync(file, JSON.stringify({ pid: process.pid, version, at: new Date().toISOString() }), 'utf8');
    return true;
  } catch {
    return false;
  }
}

// Ждёт окно новой копии: файл от `markReady` (ok), или выход процесса, или срок. Таймаут не «на всякий случай»:
// без него старая копия висела бы вечно, если новая молча не стартует.
function waitReady(file, child, timeoutMs = 20000, step = 120) {
  return new Promise((resolve) => {
    const started = Date.now();
    let stopped = false;
    let exitCode = null;
    let exitAt = 0;
    const read = () => {
      try {
        return JSON.parse(fs.readFileSync(file, 'utf8'));
      } catch {
        return null;
      }
    };
    const timer = setInterval(() => {
      if (stopped) return;
      const got = read();
      if (got && got.pid) return finish({ ok: true, got });
      if (exitCode !== null && Date.now() - exitAt > 250) {
        return finish({ ok: false, error: `новая копия закрылась (код ${exitCode}), окно не открылось` });
      }
      if (Date.now() - started > timeoutMs) {
        return finish({ ok: false, error: `новая копия не открыла окно за ${Math.round(timeoutMs / 1000)} с` });
      }
    }, step);
    function finish(res) {
      if (stopped) return;
      stopped = true;
      clearInterval(timer);
      setTimeout(() => resolve(res), 0);
    }
    if (child && typeof child.on === 'function') {
      child.on('error', (err) => finish({ ok: false, error: `новый процесс не запустился: ${err.message || String(err)}` }));
      child.on('exit', (code) => { exitCode = code; exitAt = Date.now(); });
    }
  });
}

module.exports = { installed, next, same, command, readyPath, markReady, waitReady };
