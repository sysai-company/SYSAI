'use strict';
// Рой: N агентов разом на одну проверку. Планировщик делит работу на части, каждая сота получает свою часть и
// строгую рубрику ответа (что проверил, что нашёл, чего нет, где именно), потом ответы сводятся механически —
// расхождения на одном и том же ключе становятся «спорными», а не затираются последним ответом.
//
// Модуль ничего не знает про Electron и Hermes: отправка задания внедряется (`ask`), поэтому весь рой проверяется
// тестами без запуска настоящих агентов. Ставит он только одно — сессии и файлы отчёта.
const fs = require('node:fs');
const path = require('node:path');
const { EventEmitter } = require('node:events');

const MIN_CELLS = 4;
const MAX_CELLS = 40;
const DEFAULT_CELLS = 8;
const DEFAULT_MINUTES = 5;
const CONCURRENCY = 6; // больше шести разом — очередь у провайдера и путаница в логах, а не скорость

const ANSWER_RULE = [
  'Отвечай строго одним блоком, без рассуждений вокруг:',
  '<answer>{"checked": сколько_проверил,"found":[{"key":"что","value":"значение","where":"файл:стр"}],',
  '"missing":[{"key":"чего_нет","why":"почему_так_думаешь"}],"notes":"одна-две фразы, если нужно"}</answer>',
  'В `where` — файл и место (лист, страница, номер окна). Если проверить не удалось — пустой `found`, причина в `notes`.',
  'Работай только со своей частью. Ты — один из нескольких проверяющих: полноту даёт сводка, а не ты.',
  'Только чтение: ничего не записывай и не меняй в проекте.',
].join('\n');

function clampCells(n) {
  const v = Number.parseInt(n, 10);
  if (!Number.isFinite(v)) return DEFAULT_CELLS;
  return Math.max(MIN_CELLS, Math.min(MAX_CELLS, v));
}

// Что разрешено рою по подписанным доступам (раздел swarm): включён ли, сколько сот и сколько из них разом. Документ
// старого SYSAI «at» не называет — тогда как было: CONCURRENCY. Разом никогда не больше, чем сот.
function allowedOf(rules) {
  const sw = (rules && typeof rules.swarm === 'object' && rules.swarm) || {};
  const cells = Number.parseInt(sw.cells, 10) > 0 ? Number.parseInt(sw.cells, 10) : 0;
  const said = Number.parseInt(sw.at, 10);
  const at = Math.max(1, Math.min(Number.isFinite(said) && said > 0 ? said : CONCURRENCY, cells || MAX_CELLS));
  return { on: Boolean(sw.on), cells, at };
}

function group(items, cells) {
  const list = items.filter((x) => String(x || '').trim());
  if (!list.length) return [];
  const n = Math.max(1, Math.min(cells, list.length));
  const per = Math.ceil(list.length / n);
  const out = [];
  for (let i = 0; i < list.length; i += per) out.push(list.slice(i, i + per));
  return out;
}

// Что делим: явный список (файлы, механизмы, пункты ТЗ) — пачками; иначе сам вопрос по строкам; иначе одна часть.
function chunk({ question, items = [], cells = DEFAULT_CELLS }) {
  const groups = group(items, cells);
  if (groups.length) {
    return groups.map((g, i) => ({
      title: g.length === 1 ? String(g[0]) : `${g[0]} … ${g[g.length - 1]} (${g.length})`,
      items: g,
      prompt: `Проверь: ${g.join('; ')}`,
    }));
  }
  const lines = String(question || '').split(/\n+/).map((s) => s.trim()).filter((s) => s.length > 3);
  if (lines.length > 2) {
    return group(lines, cells).map((g, i) => ({ title: `пункты ${i + 1}: ${g[0].slice(0, 60)}`, items: g, prompt: g.join('\n') }));
  }
  return [{ title: 'вся задача', items: [], prompt: String(question || '') }];
}

function cellPrompt({ question, part, index, total }) {
  return [
    `Ты — сота ${index + 1} из ${total} в рое агентов SYSAI.`,
    `Общая задача: ${question}`,
    `Твоя часть: ${part.title}`,
    part.prompt ? `Что делать: ${part.prompt}` : '',
    ANSWER_RULE,
  ].filter(Boolean).join('\n\n');
}

function planPrompt({ question, items, cells }) {
  return [
    'Ты — планировщик роя агентов SYSAI. Раздели работу на независимые части — по одной на агента.',
    `Задача: ${question}`,
    items && items.length ? `Что есть: ${items.slice(0, 200).join('; ')}` : '',
    `Частей нужно: ${cells}. Части не должны пересекаться и не должны требовать общего состояния.`,
    'Ответ строго: <answer>{"chunks":[{"title":"коротко","prompt":"что именно проверить"}]}</answer>',
  ].filter(Boolean).join('\n\n');
}

const ANSWER_RE = /<answer>([\s\S]*?)<\/answer>/i;
const FENCE_RE = /```(?:json)?\s*([\s\S]*?)```/i;

function jsonOf(text) {
  const raw = String(text || '');
  for (const m of [ANSWER_RE.exec(raw), FENCE_RE.exec(raw)]) {
    if (!m) continue;
    try {
      return JSON.parse(m[1].trim());
    } catch { /* не JSON — пойдём дальше */ }
  }
  const first = raw.indexOf('{');
  const last = raw.lastIndexOf('}');
  if (first >= 0 && last > first) {
    try {
      return JSON.parse(raw.slice(first, last + 1));
    } catch { /* остаётся свободный текст */ }
  }
  return null;
}

// Ответ соты: либо разобранная рубрика, либо свободный текст — он не пропадает, а становится заметкой.
function parseAnswer(text) {
  const data = jsonOf(text);
  if (!data || typeof data !== 'object') {
    const said = String(text || '').trim();
    return { checked: 0, found: [], missing: [], notes: said.slice(0, 2000), parsed: false };
  }
  const arr = (v) => (Array.isArray(v) ? v.filter((x) => x && typeof x === 'object') : []);
  return {
    checked: Number(data.checked) || arr(data.found).length,
    found: arr(data.found).map((f) => ({ key: String(f.key ?? ''), value: String(f.value ?? ''), where: String(f.where ?? '') })),
    missing: arr(data.missing).map((m) => ({ key: String(m.key ?? ''), why: String(m.why ?? '') })),
    notes: String(data.notes ?? '').slice(0, 2000),
    parsed: true,
  };
}

// Спорное: один и тот же ключ, разные значения у разных сот. Молча взять последнее — потерять вопрос инженеру.
function conflicts(cells) {
  const by = new Map();
  for (const cell of cells) {
    for (const f of (cell.answer && cell.answer.found) || []) {
      const key = f.key.trim().toLowerCase();
      if (!key) continue;
      if (!by.has(key)) by.set(key, new Map());
      const values = by.get(key);
      const value = f.value.trim();
      if (!values.has(value)) values.set(value, []);
      values.get(value).push({ cell: cell.i, where: f.where });
    }
  }
  const out = [];
  for (const [key, values] of by) {
    if (values.size < 2) continue;
    out.push({ key, values: [...values].map(([value, cells2]) => ({ value, cells: cells2 })) });
  }
  return out;
}

function report({ question, cells, conflicts: bad, startedAt, endedAt, error = '', stopped = false }) {
  const done = cells.filter((c) => c.state === 'done');
  const bad2 = cells.filter((c) => c.state === 'error');
  const late = cells.filter((c) => c.state === 'timeout');
  const found = cells.reduce((n, c) => n + ((c.answer && c.answer.found) || []).length, 0);
  const missing = cells.reduce((n, c) => n + ((c.answer && c.answer.missing) || []).length, 0);
  const secs = Math.max(1, Math.round(((endedAt || Date.now()) - startedAt) / 1000));
  const lines = [];
  lines.push(`# Рой: ${question}`, '');
  lines.push(`${cells.length} сот · ${secs} с · ${done.length} ответили, ${bad2.length} с ошибкой, ${late.length} не успели`);
  lines.push(`${found} находок · ${missing} «нет» · ${bad.length} спорных`, '');
  if (error) lines.push(`> ${error}`, '');
  if (stopped) lines.push('> Рой остановлен человеком: ниже то, что успели.', '');

  const rows = [];
  for (const cell of cells) {
    for (const f of (cell.answer && cell.answer.found) || []) {
      rows.push(`| ${f.key} | ${f.value} | ${f.where} | ${cell.i + 1} |`);
    }
  }
  if (rows.length) {
    lines.push('## Найдено', '', '| что | значение | где | сота |', '| --- | --- | --- | --- |', ...rows, '');
  }
  const notFound = [];
  for (const cell of cells) {
    for (const m of (cell.answer && cell.answer.missing) || []) notFound.push(`| ${m.key} | ${m.why} | ${cell.i + 1} |`);
  }
  if (notFound.length) {
    lines.push('## Не найдено', '', '| что | почему | сота |', '| --- | --- | --- |', ...notFound, '');
  }
  if (bad.length) {
    lines.push('## Спорное — проверить человеку', '');
    for (const c of bad) {
      lines.push(`- **${c.key}**: ${c.values.map((v) => `«${v.value}» (соты ${v.cells.map((x) => x.cell + 1).join(', ')})`).join('; ')}`);
    }
    lines.push('');
  }
  lines.push('## Соты', '', '| # | часть | состояние | проверил | находок |', '| --- | --- | --- | --- | --- |');
  for (const c of cells) {
    const state = { idle: 'не начинал', working: 'работает', done: 'готово', error: 'ошибка', timeout: 'не успел' }[c.state] || c.state;
    lines.push(`| ${c.i + 1} | ${c.title.replace(/\|/g, '/')} | ${state}${c.error ? `: ${c.error.replace(/\|/g, '/').slice(0, 80)}` : ''} | ${c.answer ? c.answer.checked : 0} | ${c.answer ? c.answer.found.length : 0} |`);
  }
  lines.push('');
  return lines.join('\n');
}

function writeOut(dir, state) {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'result.md'), state.result.markdown, 'utf8');
  fs.writeFileSync(path.join(dir, 'state.json'), JSON.stringify({
    id: state.id, question: state.question, stage: state.stage, startedAt: state.startedAt, endedAt: state.endedAt,
    counters: state.counters, cells: state.cells,
  }, null, 2), 'utf8');
  for (const cell of state.cells) {
    const said = cell.raw || (cell.answer ? JSON.stringify(cell.answer, null, 2) : cell.error || '');
    fs.writeFileSync(path.join(dir, `cell-${String(cell.i + 1).padStart(2, '0')}.md`), `# Сота ${cell.i + 1}: ${cell.title}\n\n${said}\n`, 'utf8');
  }
  return path.join(dir, 'result.md');
}

class Swarm extends EventEmitter {
  constructor({ question, items = [], cells = DEFAULT_CELLS, minutes = DEFAULT_MINUTES, ask, root = '',
    plan = true, arbiter = true, concurrency = CONCURRENCY, now = () => Date.now() } = {}) {
    super();
    this.question = String(question || '').trim();
    this.items = Array.isArray(items) ? items : [];
    this.cells = clampCells(cells);
    // минуты — срок роя; дробные допускаются, чтобы тест мог проверить таймаут за секунды, а не за пять минут
    this.minutes = Math.max(0.02, Math.min(30, Number(minutes) || DEFAULT_MINUTES));
    this.ask = ask;
    this.root = root;
    this.plan = plan;
    this.arbiter = arbiter;
    this.concurrency = Math.max(1, concurrency);
    this.now = now;
    this.aborted = false;
    this.state = {
      id: `swarm-${this.now()}`,
      question: this.question,
      stage: 'idle',
      startedAt: this.now(),
      endedAt: 0,
      cells: [],
      counters: { cells: this.cells, working: 0, done: 0, error: 0, timeout: 0, found: 0, missing: 0 },
      result: { markdown: '', conflicts: [], path: '' },
      error: '',
    };
  }

  get counters() {
    const c = this.state.cells;
    return {
      cells: c.length || this.cells,
      working: c.filter((x) => x.state === 'working').length,
      done: c.filter((x) => x.state === 'done').length,
      error: c.filter((x) => x.state === 'error').length,
      timeout: c.filter((x) => x.state === 'timeout').length,
      found: c.reduce((n, x) => n + ((x.answer && x.answer.found) || []).length, 0),
      missing: c.reduce((n, x) => n + ((x.answer && x.answer.missing) || []).length, 0),
      checked: c.reduce((n, x) => n + ((x.answer && x.answer.checked) || 0), 0),
    };
  }

  emitState(stage) {
    if (stage) this.state.stage = stage;
    this.state.counters = this.counters;
    this.emit('state', this.snapshot());
  }

  snapshot() {
    return JSON.parse(JSON.stringify(this.state));
  }

  abort() {
    this.aborted = true;
  }

  async parts() {
    if (!this.plan) return chunk({ question: this.question, items: this.items, cells: this.cells });
    const said = await this.ask({ prompt: planPrompt({ question: this.question, items: this.items, cells: this.cells }),
      cell: { i: -1, title: 'планировщик' } });
    const data = jsonOf(said);
    const list = data && Array.isArray(data.chunks) ? data.chunks.filter((c) => c && c.prompt) : [];
    if (!list.length) return chunk({ question: this.question, items: this.items, cells: this.cells });
    return list.slice(0, MAX_CELLS).map((c, i) => ({
      title: String(c.title || `часть ${i + 1}`).slice(0, 120),
      items: [],
      prompt: String(c.prompt),
    }));
  }

  async run() {
    if (!this.question) throw new Error('рою нужна задача: что проверять');
    if (typeof this.ask !== 'function') throw new Error('рой без агента: некому отправлять задания');
    this.state.startedAt = this.now();
    this.emitState('plan');

    let parts;
    try {
      parts = await this.parts();
    } catch (err) {
      this.state.error = `планировщик не ответил: ${err.message}`;
      this.emitState('error');
      return this.snapshot();
    }
    if (!parts.length) {
      this.state.error = 'нечего делить: назовите файлы, механизмы или пункты';
      this.emitState('error');
      return this.snapshot();
    }
    this.state.cells = parts.map((p, i) => ({ i, title: p.title, state: 'idle', startedAt: 0, endedAt: 0, error: '', answer: null, raw: '' }));
    this.emitState('work');

    const deadline = this.state.startedAt + this.minutes * 60000;
    let next = 0;
    const worker = async () => {
      for (;;) {
        const cell = this.state.cells[next++];
        if (!cell || this.aborted) return;
        const left = deadline - this.now();
        if (left <= 1000) {
          cell.state = 'timeout';
          cell.error = 'время роя вышло';
          this.emitState();
          continue;
        }
        cell.state = 'working';
        cell.startedAt = this.now();
        this.emitState();
        const part = parts[cell.i];
        const prompt = cellPrompt({ question: this.question, part, index: cell.i, total: parts.length });
        let timer = null;
        try {
          const said = await Promise.race([
            this.ask({ prompt, cell }),
            new Promise((_, rej) => { timer = setTimeout(() => rej(Object.assign(new Error('не успел: время вышло'), { timeout: true })), left); }),
          ]);
          cell.raw = String(said || '');
          cell.answer = parseAnswer(said);
          cell.state = 'done';
        } catch (err) {
          cell.state = err && err.timeout ? 'timeout' : 'error';
          cell.error = String((err && err.message) || err);
        } finally {
          if (timer) clearTimeout(timer);
          cell.endedAt = this.now();
          this.emitState();
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(this.concurrency, this.state.cells.length) }, worker));

    const bad = conflicts(this.state.cells);
    if (this.arbiter && !this.aborted && bad.length === 0) {
      const done = this.state.cells.filter((c) => c.state === 'done' && c.answer);
      if (done.length > 1) {
        this.emitState('merge');
        try {
          const said = await this.ask({
            prompt: ['Ты — арбитр роя SYSAI. Сотрудник уже получил таблицы находок; напиши только короткий вывод (3–5 строк):',
              'что подтвердилось, что осталось открытым, что проверить первым. Без воды и без похвал.',
              `Задача: ${this.question}`,
              `Ответы сот: ${JSON.stringify(done.map((c) => ({ часть: c.title, ответ: c.answer }))).slice(0, 12000)}`,
            ].join('\n\n'),
            cell: { i: -2, title: 'арбитр' },
          });
          this.state.result.summary = String(said || '').trim().slice(0, 4000);
        } catch (err) {
          this.state.result.summary = `арбитр не ответил (${err.message}) — смотрите таблицы ниже`;
        }
      }
    }

    this.state.endedAt = this.now();
    this.state.result.conflicts = bad;
    this.state.result.markdown = report({
      question: this.question, cells: this.state.cells, conflicts: bad,
      startedAt: this.state.startedAt, endedAt: this.state.endedAt,
      error: this.state.error, stopped: this.aborted,
    });
    if (this.state.result.summary) {
      this.state.result.markdown = this.state.result.markdown.replace('\n## Найдено', `\n## Вывод\n\n${this.state.result.summary}\n\n## Найдено`);
    }
    if (this.root) {
      try {
        this.state.result.path = writeOut(path.join(this.root, this.state.id), this.state);
      } catch (err) {
        this.state.error = `отчёт не записался: ${err.message}`;
      }
    }
    this.emitState(this.aborted ? 'stopped' : 'done');
    return this.snapshot();
  }
}

module.exports = {
  Swarm, MIN_CELLS, MAX_CELLS, DEFAULT_CELLS, DEFAULT_MINUTES, CONCURRENCY, ANSWER_RULE,
  clampCells, allowedOf, chunk, cellPrompt, planPrompt, parseAnswer, jsonOf, conflicts, report, writeOut,
};
