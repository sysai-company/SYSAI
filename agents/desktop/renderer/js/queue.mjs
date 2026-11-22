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
