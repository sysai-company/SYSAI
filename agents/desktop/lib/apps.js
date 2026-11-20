// «Открыть в программе»: кнопка формата открывает среду вендора на этом компьютере и сразу кладёт в неё наш
// результат. Файл проекта (ONI, EasyBuilder, Machine Expert) открывается как файл — среда сама его подхватит.
// У Haiwell Happy файла нет (закрытый .gpc), поэтому открываем среду и кладём программу в буфер обмена:
// вставка — F7 (окно STL) → Ctrl+V → F9, и это делает человек или, если включено, сценарий SendKeys.
const path = require('node:path');

const FORMATS = {
  oni: {
    id: 'oni', title: 'ONI Visual Studio', kind: 'hmi', open: 'file',
    exts: ['.wcfg'],
    exe: ['ONI Visual Studio.exe', 'ONIVisualStudio.exe', 'Design.exe'],
    dirs: [['ONI Visual Studio'], ['Flexem', 'ONI Visual Studio']],
  },
  easybuilder: {
    id: 'easybuilder', title: 'EasyBuilder Pro', kind: 'hmi', open: 'file',
    exts: ['.cmtp', '.emtp', '.emt'],
    exe: ['EasyBuilderPro.exe'],
    dirs: [['EBpro'], ['Weintek', 'EasyBuilder Pro']],
  },
  me: {
    id: 'me', title: 'EcoStruxure Machine Expert', kind: 'plc', open: 'file',
    exts: ['.project'],
    exe: ['MachineExpert.exe'],
    dirs: [['Schneider Electric', 'EcoStruxure Machine Expert']],
  },
  hawell: {
    id: 'hawell', title: 'Haiwell Happy', kind: 'plc', open: 'paste',
    exts: ['.il'], names: ['program.il'],
    exe: ['HaiwellHappy.exe'],
    dirs: [['Haiwell', 'HaiwellHappy'], ['Haiwell']],
  },
};

const IDS = Object.keys(FORMATS);
const SKIP = new Set(['_work', 'materials', '.sysai', '.git', 'node_modules']);

function format(id) {
  const f = FORMATS[id];
  if (!f) throw new Error(`нет такого формата: ${id}`);
  return f;
}

// Обычные места установки + имя программы. Порядок важен: сначала «своя» папка вендора, потом общая.
function candidates(id, env = process.env, join = path.join) {
  const f = format(id);
  const roots = [];
  for (const key of ['ProgramFiles(x86)', 'ProgramFiles']) if (env[key]) roots.push(env[key]);
  roots.push('C:\\Program Files (x86)', 'C:\\Program Files');
  const out = [];
  for (const dir of f.dirs) {
    for (const root of roots) for (const name of f.exe) out.push(join(root, ...dir, name));
  }
  if (id === 'easybuilder') for (const name of f.exe) out.push(`C:\\EBpro\\${name}`);
  return [...new Set(out)];
}

// Что в проекте можно открыть: по одному файлу на формат. `hawell/program.il` — первым, он наш собственный.
function detect(dir, { readdir = require('node:fs').readdirSync, stat = require('node:fs').statSync } = {}) {
  const found = {};
  const walk = (base, depth) => {
    let names;
    try {
      names = readdir(base, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of names.slice(0, 4000)) {
      const full = path.join(base, ent.name);
      if (ent.isDirectory()) {
        if (depth > 0 && !SKIP.has(ent.name.toLowerCase())) walk(full, depth - 1);
        continue;
      }
      const low = ent.name.toLowerCase();
      for (const id of IDS) {
        if (found[id]) continue;
        const f = FORMATS[id];
        if (f.names ? f.names.includes(low) : f.exts.some((e) => low.endsWith(e))) {
          found[id] = f.open === 'paste' ? full : projectRoot(id, full, stat);
        }
      }
    }
  };
  walk(dir, 3);                                    // hmi/HMI/Frame/*.wcfg — три уровня ниже корня проекта
  return IDS.filter((id) => found[id]).map((id) => ({
    id, title: FORMATS[id].title, kind: FORMATS[id].kind, open: FORMATS[id].open, file: found[id],
  }));
}

// ONI открывает проект целиком, а .wcfg лежит в HMI/Frame/… — отдаём папку, в которой есть HMI.
function projectRoot(id, file, stat = require('node:fs').statSync) {
  if (id !== 'oni') return file;
  const parts = file.split(path.sep);
  const at = parts.lastIndexOf('HMI');
  if (at > 0) return parts.slice(0, at).join(path.sep);
  try {
    if (stat(file).isDirectory()) return file;
  } catch { /* файла уже нет — пусть откроет среда и скажет сама */ }
  return file;
}

// Сценарий вставки для Haiwell: окно среды на передний план, F7 (окно STL), вставка, проверка.
// SendKeys ненадёжен по своей природе — окно должно быть поверх and не перехватывать фокус, поэтому по умолчанию
// выключен (config autoPaste), а человеку показываем те же три клавиши подсказкой.
function pasteScript(exe, { wait = 6, keys = '{F7}', paste = '^v', check = '{F9}' } = {}) {
  const q = (s) => `'${String(s).replace(/'/g, "''")}'`;
  // имя процесса берём из самого пути: path.basename здесь не годится — на не-Windows он не считает «\» разделителем
  const proc = String(exe).split(/[\\/]/).pop().replace(/\.exe$/i, '');
  return [
    '$ErrorActionPreference = "Stop"',
    'Add-Type -AssemblyName System.Windows.Forms',
    `Start-Process -FilePath ${q(exe)}`,
    `Start-Sleep -Seconds ${Number(wait) || 6}`,
    `$p = Get-Process -Name ${q(proc)} -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1`,
    'if (-not $p) { Write-Output "нет окна Haiwell Happy"; exit 1 }',
    '[System.Windows.Forms.SendKeys]::SendWait(' + q(keys) + ')',
    'Start-Sleep -Milliseconds 700',
    '[System.Windows.Forms.SendKeys]::SendWait(' + q(paste) + ')',
    'Start-Sleep -Milliseconds 700',
    '[System.Windows.Forms.SendKeys]::SendWait(' + q(check) + ')',
    'Write-Output "ok"',
  ].join('\r\n');
}

// Что именно произойдёт по нажатию кнопки — без побочных действий, чтобы это можно было проверить тестом.
function plan(id, file) {
  const f = format(id);
  if (!file) throw new Error(`в проекте нет файла для ${f.title}`);
  return { id, kind: f.open, exe: f.exe[0], file, keys: f.open === 'paste' ? ['F7', 'Ctrl+V', 'F9'] : [] };
}

module.exports = { FORMATS, IDS, format, candidates, detect, projectRoot, pasteScript, plan };
