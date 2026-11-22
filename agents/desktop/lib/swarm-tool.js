'use strict';
// Рой, который запускает сам агент (инструмент окна swarm_start): можно ли и сколько сот. Решают три вещи, по порядку:
// подписанные доступы (администратор включил рой и дал предел), выбор человека под полем ввода («Рой: вкл» и число
// сот) и то, что рой один на компьютер. Число сот агента не больше выбора человека и не больше предела доступов.
// Без Electron — проверяет юнит-тест.
const { MIN_CELLS, MAX_CELLS } = require('./swarm');

const DEFAULT_PREFS = { on: false, cells: 0 };

// Выбор человека, приведённый к виду: { on, cells } (cells 0 — не выбирал, тогда весь предел доступов).
function prefsOf(raw) {
  const p = raw && typeof raw === 'object' ? raw : {};
  const cells = Number.parseInt(p.cells, 10);
  return { on: Boolean(p.on), cells: Number.isFinite(cells) && cells > 0 ? Math.max(MIN_CELLS, Math.min(MAX_CELLS, cells)) : 0 };
}

// Запрос агента → { ok: true, cells, question, project } или { ok: false, error } — отказ словами для агента.
// allow — swarmAllowed() окна ({ on, cells, at, off }), busy — рой уже идёт.
function decide({ allow, prefs, busy, args }) {
  const a = args && typeof args === 'object' ? args : {};
  const question = String(a.question || '').trim();
  if (!allow || !allow.on) return { ok: false, error: (allow && allow.off) || 'Рой агентов выключен в доступах SYSAI.' };
  const p = prefsOf(prefs);
  if (!p.on) return { ok: false, error: 'Рой выключен в окне: человек не включил «Рой» под полем ввода. Попросите его включить или работайте без роя.' };
  if (busy) return { ok: false, error: 'Рой уже идёт: дождитесь его (swarm_status) или остановите (swarm_stop).' };
  if (!question) return { ok: false, error: 'Нужна задача роя (question): что проверить.' };
  // Swarm не запускает меньше четырёх сот (clampCells): предел ниже — отказ, а не рой сверх предела
  if (!(allow.cells >= MIN_CELLS)) return { ok: false, error: `Предел сот в доступах (${allow.cells || 0}) меньше ${MIN_CELLS}: рой не запускается.` };
  const cap = Math.min(p.cells || allow.cells, allow.cells);
  const said = Number.parseInt(a.cells, 10);
  const cells = Number.isFinite(said) && said > 0 ? Math.min(said, cap) : cap;
  const items = Array.isArray(a.items) ? a.items.map((x) => String(x || '').trim()).filter(Boolean).slice(0, 2000) : [];
  // столько сот, сколько запустит Swarm: не меньше четырёх и не больше предела доступов
  return { ok: true, cells: Math.max(MIN_CELLS, Math.min(cells, allow.cells)), question: question.slice(0, 4000), items,
    project: typeof a.project === 'string' ? a.project.trim() : '' };
}

// Состояние роя коротко — то, что агент читает через swarm_status (без сырых ответов сот).
function brief(state) {
  if (!state) return { stage: 'none', text: 'Роя нет: ни один не запускался с открытия окна.' };
  const c = state.counters || {};
  const out = { id: state.id, stage: state.stage, cells: c.cells || 0, done: c.done || 0, working: c.working || 0,
    error: c.error || 0, timeout: c.timeout || 0, found: c.found || 0, missing: c.missing || 0,
    conflicts: ((state.result && state.result.conflicts) || []).length, report: (state.result && state.result.path) || '' };
  if (state.error) out.failure = state.error;
  return out;
}

module.exports = { DEFAULT_PREFS, prefsOf, decide, brief };
