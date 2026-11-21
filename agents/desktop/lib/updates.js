// «Обновление» в окне агента: что предлагает SYSAI и что стоит на этом компьютере.
//
// The renderer cannot reach the network (CSP connect-src 'none'), so the check runs in the main process: agent.json
// gives the address, the Hermes profile's .env gives the agent's token, the signed document gives the offer
// (`synchronizer` — version, build, sha256, «обновлять сами»), and state.json tells what this computer runs and
// whether the last cycle failed. The install itself is not done here: the window only wakes the synchronizer, which
// owns the checked-install path (update.py), so there is one installer on the computer, not two.
const fs = require('node:fs');
const path = require('node:path');

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
}

function parts(version) {
  return (String(version || '').match(/\d+/g) || []).slice(0, 4).map(Number);
}

function cmp(a, b) {
  const x = parts(a);
  const y = parts(b);
  for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
    const d = (x[i] || 0) - (y[i] || 0);
    if (d) return d < 0 ? -1 : 1;
  }
  return 0;
}

// local/offered: {version, build}. A same-version other build is an update too — that is how a computer noticed
// nothing while SYSAI served new sources under an old version number.
function compare(local, offered) {
  const mine = (local && local.version) || '';
  const theirs = (offered && offered.version) || '';
  if (!theirs) return { update: false, why: 'SYSAI не назвал версию синхронизатора' };
  if (!mine) return { update: true, why: `SYSAI даёт ${theirs}, версия на компьютере неизвестна` };
  const c = cmp(theirs, mine);
  if (c > 0) return { update: true, why: `SYSAI даёт ${theirs}, на компьютере ${mine}` };
  if (c < 0) return { update: false, why: `на компьютере ${mine} — новее, чем даёт SYSAI (${theirs})` };
  if (offered.build && local.build && offered.build !== local.build) {
    return { update: true, why: `та же версия ${theirs}, но сборка другая` };
  }
  return { update: false, why: `последняя версия: ${mine}` };
}

function tail(file, lines = 12) {
  try {
    const text = fs.readFileSync(file, 'utf8').trimEnd();
    return text ? text.split('\n').slice(-lines) : [];
  } catch {
    return [];
  }
}

function offerOf(body) {
  const doc = body && (body.doc || body);
  const got = doc && doc.synchronizer;
  if (!got || !got.version) return {};
  return { version: String(got.version), build: String(got.build || ''), auto_update: got.auto_update !== false };
}

// The window SYSAI offers ({version, sha256}) from the signed document; {} when it names none.
function desktopOf(body) {
  const doc = body && (body.doc || body);
  const got = doc && doc.desktop;
  if (!got || !got.version) return {};
  return { version: String(got.version), sha256: String(got.sha256 || ''), auto_update: got.auto_update !== false };
}

// request(url, headers) -> {status, body} — the transport is passed in so this file stays testable without a server.
// `window` — the version of this window (package.json): a newer window on offer is an update too, and the same «Установить»
// (it wakes the synchronizer, which installs the window as well) puts it in place.
async function check({ home, server, token, state, request, window = '' }) {
  const got = state || readJson(path.join(home, 'state.json'), {}) || {};
  const versions = got.versions || {};
  const local = { version: String(versions['sysai-agent'] || ''), build: '' };
  const log = tail(path.join(home, 'logs', 'sync.log'));
  const out = { local, log, error: '', errorAt: got.error_at || '', syncAt: got.pulse_at || got.synced_at || '' };
  if (!server) return { ...out, ok: false, error: 'Компьютер не подключён к SYSAI' };
  if (!token) return { ...out, ok: false, error: 'Нет токена агента: подключите компьютер заново (новый код на странице агента)' };
  let answer;
  try {
    answer = await request(`${String(server).replace(/\/+$/, '')}/agents/api/config`, {
      Authorization: `Bearer ${token}`, Accept: 'application/json',
    });
  } catch (e) {
    return { ...out, ok: false, error: `Нет связи с SYSAI (${server}): ${e.message || e}` };
  }
  if (answer.status === 401) {
    return { ...out, ok: false, status: 401,
      error: 'SYSAI не принял токен агента: агента отключили или подключили на другом компьютере. '
        + 'Получите новый код на странице агента и запустите установщик снова' };
  }
  if (answer.status !== 200) {
    return { ...out, ok: false, status: answer.status, error: `SYSAI ответил HTTP ${answer.status}` };
  }
  const offered = offerOf(answer.body);
  const verdict = compare(local, offered);
  if (!verdict.update && window) {
    const win = desktopOf(answer.body);
    if (win.version && cmp(win.version, window) > 0) {
      return { ...out, ok: true, offered: win, desktop: true, update: true,
        why: `SYSAI даёт окно ${win.version}, открыто ${window}`, autoUpdate: win.auto_update !== false };
    }
  }
  return { ...out, ok: true, offered, update: verdict.update, why: verdict.why, autoUpdate: offered.auto_update !== false };
}

// «Установить»: the window asks the running loop to do it now (a «wake» file beside «stop», which core._wait watches).
// Nothing is installed from here — a second installer would fight the first one for the same files.
function wake(home) {
  if (!fs.existsSync(path.join(home, 'run.lock'))) {
    return { asking: false, note: 'Синхронизатор на этом компьютере не запущен: обновите установщиком со страницы агента' };
  }
  fs.writeFileSync(path.join(home, 'wake'), 'wake');
  return { asking: true };
}

// «Что происходит с обновлением прямо сейчас»: the window asks every couple of seconds after «Установить», because
// installing is done by the synchronizer in the background and the person must see that it moves — and where it
// stopped when it does not. Nothing here changes anything: only what is on disk is read.
function status({ home }) {
  const state = readJson(path.join(home, 'state.json'), {}) || {};
  const versions = (state && state.versions) || {};
  const logFile = path.join(home, 'logs', 'update.log');
  let logAt = '';
  try {
    logAt = fs.statSync(logFile).mtime.toISOString();
  } catch { /* ещё не обновлялся */ }
  return {
    running: fs.existsSync(path.join(home, 'run.lock')),
    asked: fs.existsSync(path.join(home, 'wake')),
    version: String(versions['sysai-agent'] || ''),
    updateTo: String(state.update_to || ''),
    updateAt: state.update_at || '',
    desktopTo: String(state.desktop_to || ''),
    error: String(state.error || ''),
    errorAt: state.error_at || '',
    syncedAt: state.pulse_at || state.synced_at || '',
    // The live channel (app/net/live.py): held or not, and why not — the synchronizer writes both to state.json, so
    // «почему не мгновенно» has an answer in the window, not only in the journal.
    liveUp: Boolean(state.live_up),
    liveError: String(state.live_error || ''),
    logAt,
    log: tail(logFile, 6),
  };
}

// What the synchronizer last heard SYSAI offer (state.json: `offer` — itself, `desktop_offer` — this window) as one key:
// it changes when a new build is offered, so the window can say «есть обновление» the moment the pulse (or a push on
// the live channel) brought it, instead of at its own half-hourly check.
function offerKey(state) {
  const s = state || {};
  const sync = (s.offer && typeof s.offer === 'object') ? s.offer : {};
  const win = (s.desktop_offer && typeof s.desktop_offer === 'object') ? s.desktop_offer : {};
  const key = [sync.version || '', sync.build || '', win.version || '', win.sha256 || ''].join('|');
  return key === '|||' ? '' : key;
}

// The verified access document this computer holds (state.json: `access_sha` — the hash the synchronizer checked
// against the signature) as one key. It changes when SYSAI brought new rules — the swarm of the person among them —
// so the window can ask for them again at once instead of only at its start.
function accessKey(state) {
  const sha = (state || {}).access_sha;
  return typeof sha === 'string' ? sha : '';
}

// Watches state.json every `every` ms; `changed(key)` once per new value of `key` (by default `offerKey`: the builds
// SYSAI offers). Not for the value there at the start: the window checks that itself on opening. Returns stop().
// `key` and `timer` are swappable for the tests.
function watch({ home, changed, key = offerKey, every = 3000, timer = { set: setInterval, clear: clearInterval } }) {
  const read = () => key(readJson(path.join(home, 'state.json'), {}));
  let seen = read();
  const id = timer.set(() => {
    const now = read();
    if (now && now !== seen) {
      seen = now;
      changed(now);
    }
  }, every);
  return () => timer.clear(id);
}

module.exports = { cmp, compare, offerOf, desktopOf, tail, check, wake, status, readJson, offerKey, accessKey, watch };
