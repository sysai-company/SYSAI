// Раскладка сот роя в ряды: шестиугольники касаются гранями, нечётный ряд сдвинут на полсоты — сетка читается как
// соты, а не как таблица квадратов. Сколько сот влезает в ряд — тоже здесь: окно знает только свою ширину.
// Чистая функция без DOM — раскладку проверяет юнит-тест (unit.test.js импортирует этот файл).

// Сколько шестиугольников влезает в ряд: у соты ширина `cell`, соседние не пересекаются — шаг ряда ровно ширина.
export function perRow(width, cell) {
  const w = Number(width);
  const c = Number(cell);
  if (!Number.isFinite(w) || !Number.isFinite(c) || w <= 0 || c <= 0) return 1;
  return Math.max(1, Math.floor(w / c));
}

// Индексы по рядам: [ [0, 1, 2], [3, 4], … ] — подряд, без потерь и дублей; остаток — последний, возможно короткий ряд.
export function rowsOf(count, per) {
  const n = Math.max(0, Math.floor(Number(count) || 0));
  const p = Math.max(1, Math.floor(Number(per) || 1));
  const rows = [];
  for (let i = 0; i < n; i += p) rows.push(Array.from({ length: Math.min(p, n - i) }, (_, k) => i + k));
  return rows;
}

// Ряд нечётный (второй, четвёртый…) — его сдвигаем на полсоты: ряды сцепляются гранями, как настоящие соты.
export const isOdd = (index) => index % 2 === 1;

// Новое разрешение роя (синхронизатор принёс документ доступов): сколько сот просить после него. `chosen` —
// то, что человек выбрал ползунком (не выбирал — весь предел); результат не больше нового предела и не меньше 4
// (та же вилка, что у ползунка панели). Сам выбор не меняется: предел снова вырос — вернётся и он.
// Предел для «Рой: вкл» под полем (рой, который запускает агент): 0 — переключателя нет. Роя меньше четырёх
// сот не бывает, и окно такой запрос агента отклонит: переключатель не обещает соты сверх предела.
export function agentSwarmCap(allowed) {
  const cap = Math.floor(Number(allowed && allowed.cells) || 0);
  return allowed && allowed.on && cap >= 4 ? Math.min(cap, 40) : 0;
}

export function cellsAfter(chosen, allowed) {
  const cap = Math.max(4, Math.min(Number(allowed && allowed.cells) || 4, 40));
  const w = Math.floor(Number(chosen));
  return Number.isFinite(w) && w > 0 ? Math.max(4, Math.min(w, cap)) : cap;
}

// Разрешение на соты прочитано заново: панель берёт его, число сот следует за пределом (выбор человека —
// `panel.cellsChosen` — не трогается), значок в композере выставляется, открытая и не занятая панель перерисовывается.
// Без DOM: panel и composer — любые объекты с этими полями, так её проверяет юнит-тест.
export function applyAllowed(panel, composer, allowed) {
  panel.allowed = allowed && typeof allowed === 'object' ? allowed : { on: false, cells: 0 };
  panel.cellsWanted = cellsAfter(panel.cellsChosen, panel.allowed);
  composer.updateSwarm({ on: Boolean(panel.allowed.on), busy: panel.busy });
  if (panel.el && !panel.el.hidden && !panel.busy) panel.draw();
}

// Строка меню «Ещё» о живом канале. `status` — ответ updates.status, null — прочесть состояние не удалось:
// это тоже говорится, иначе меню молчит так же, как когда канал держится. "" — канал держится.
export function liveLine(status) {
  if (!status || typeof status !== 'object') return 'состояние живого канала не прочитано';
  if (status.liveUp) return '';
  const why = String(status.liveError || '').trim();
  return `живой канал не держится: ${why || 'работаем по пульсу'}`;
}
