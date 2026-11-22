// Очередь сообщений разговора: человек пишет, пока агент работает, и ход не прерывается. Сообщение ждёт над полем
// ввода и уходит само, когда ход кончился, — в тот разговор, где его написали. После «Остановить» очередь сама не
// уходит: человек остановил агента не для того, чтобы тот сразу взялся за следующее. Без DOM — проверяет юнит-тест.

let seq = 0;

function list(conv) {
  if (!Array.isArray(conv.queue)) conv.queue = [];
  return conv.queue;
}

// Поставить сообщение в очередь разговора; пустое не ставится. Новое сообщение снимает «остановлено»: человек
// снова просит агента работать.
export function enqueue(conv, { text = '', files = [] } = {}) {
  const t = String(text || '');
  const f = Array.isArray(files) ? [...files] : [];
  if (!t.trim() && !f.length) return null;
  const item = { id: `q${Date.now().toString(36)}${(++seq).toString(36)}`, text: t, files: f };
  list(conv).push(item);
  conv.queueHeld = false;
  return item;
}

// Убрать сообщение из очереди до отправки.
export function dequeue(conv, id) {
  const q = list(conv);
  const i = q.findIndex((x) => x.id === id);
  if (i < 0) return null;
  return q.splice(i, 1)[0];
}

// Ход кончился: что отправить следующим. null — нечего, агент ещё занят или ход остановили (очередь ждёт).
export function next(conv, stopReason) {
  const q = list(conv);
  if (stopReason === 'cancelled') conv.queueHeld = true;
  if (!q.length || conv.running || conv.sending || conv.queueHeld) return null;
  return q.shift();
}

// Человек сам отправил сообщение из остановленного разговора: очередь снова идёт сама.
export function release(conv) {
  conv.queueHeld = false;
}

// ---------- очередь переживает падение и перезапуск агента ----------
// Хранилище удержанных очередей: объект разговора `afterReady` выбрасывает при перезапуске агента, а сообщение,
// написанное человеком, пропадать не должно. Ключ — id разговора. Срок 15 минут: запись, чей разговор человек так
// и не открыл (или удалил), не живёт в окне вечно и не считается в плашке после каждого нового рестарта.
const HOLD_MS = 15 * 60 * 1000;
const held = new Map(); // id разговора → { queue: [...], at: Date.now() }

// Агент упал: очередь разговора уходит в хранилище до пересоздания разговора. Возвращает, сколько сообщений
// удержано (плашка говорит число сообщений, не число разговоров). Разговор без очереди не удерживается.
export function hold(conv, now = Date.now()) {
  const q = Array.isArray(conv.queue) ? conv.queue : [];
  if (!q.length) return 0;
  // копия, а не ссылка: умирающий ход может ещё довыполниться и забрать сообщение из очереди — хранилище
  // должно держать снимок того, что человек написал, а не делить массив с разговором, который вот-вот выкинут
  held.set(conv.id, { queue: [...q], at: now });
  return q.length;
}

// Разговор пересоздан (makeConv): его удержанная очередь возвращается в тот же id и ждёт человека — сама не
// уйдёт. Нет записи или она просрочена (человек не открывал разговор 15 минут) — разговора пуст, ничего не вернётся.
// Возвращает удержанную очередь или null.
export function restore(id, now = Date.now()) {
  const got = held.get(id);
  if (!got) return null;
  held.delete(id);
  if (now - got.at > HOLD_MS) return null;
  return got.queue;
}

// Плашка после перезапуска: сколько сообщений ждёт и в каких разговорах. Просроченные записи не считаются
// (и убираются заодно). `title` — имя разговора для текста плашки.
export function heldReport(titles, now = Date.now()) {
  let count = 0;
  const names = [];
  for (const [id, entry] of [...held.entries()]) {
    if (now - entry.at > HOLD_MS) { held.delete(id); continue; }
    count += entry.queue.length;
    names.push((titles && titles(id)) || 'разговор');
  }
  return { count, names, size: held.size };
}

// Разговор удалён: его удержанная очередь не должна ни возвращаться, ни считаться в плашке.
export function forget(id) {
  return held.delete(id);
}

// Русская форма для плашки: «1 сообщение ждёт», «3 сообщения ждут», «5 сообщений ждут», «21 сообщение ждёт».
export function messagesWaiting(n) {
  const last = n % 10;
  const many = n % 100;
  const one = last === 1 && many !== 11;
  const few = last >= 2 && last <= 4 && (many < 10 || many >= 20);
  return `${n} ${one ? 'сообщение' : few ? 'сообщения' : 'сообщений'} ${one ? 'ждёт' : 'ждут'}`;
}
