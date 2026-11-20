'use strict';
// The conversations of the window, kept on this computer: one JSON per conversation in <SYSAI>\chats. Why our own
// copy and not only Hermes' store: a restart, an update that installs a new build next to the old one, a profile made
// anew — and the conversation is gone from the list while the person remembers talking. Here the window keeps what
// was said (people's messages, the agent's answers, the tools it ran, the notices it showed) and opens the
// conversation from that copy when Hermes no longer knows it; the work itself continues in a new Hermes session.
//
// The file is written atomically (a temporary file and a rename): a machine switched off mid-write leaves the old
// copy, not half of the new one. A conversation that no longer belongs anywhere is not deleted at once — it is
// removed from the list by a tombstone (chats/.deleted.json): Hermes may still list its session, and a person who
// deleted the conversation does not want it back on the next start.
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');

const SCHEMA = 1;
const MAX_MESSAGES = 400; // a long conversation is worth keeping, a thousand tool rows are not
const MAX_BYTES = 2 * 1024 * 1024;
const DELETED = '.deleted.json';
const BAD_ID = /[^A-Za-z0-9._-]/g;

class ChatsError extends Error {}

function dir(home) {
  return path.join(home, 'chats');
}

// The id is a file name: only what a file name may hold, no leading dot (a hidden file is not listed) and no
// sequences of dots — «../..» must not climb out of the folder of conversations.
function safeId(id) {
  const s = String(id || '').replace(BAD_ID, '').replace(/\.{2,}/g, '.').replace(/^\.+/, '').slice(0, 120);
  if (!s || s === '.') throw new ChatsError('нет номера разговора');
  return s;
}

function fileOf(home, id) {
  return path.join(dir(home), `${safeId(id)}.json`);
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
  } catch {
    return null;
  }
}

async function ensure(home) {
  await fsp.mkdir(dir(home), { recursive: true });
}

// Conversations the person deleted: their ids stay here, so Hermes' own session list cannot bring them back.
async function tombstones(home) {
  const data = readJson(path.join(dir(home), DELETED));
  return Array.isArray(data && data.ids) ? data.ids.filter((x) => typeof x === 'string') : [];
}

async function bury(home, id) {
  const ids = new Set(await tombstones(home));
  ids.add(safeId(id));
  await writeAtomic(path.join(dir(home), DELETED), JSON.stringify({ schema: SCHEMA, ids: [...ids].slice(-2000) }));
}

async function writeAtomic(file, text) {
  await fsp.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  await fsp.writeFile(tmp, text, 'utf8');
  await fsp.rename(tmp, file);
}

function summary(doc) {
  return {
    id: doc.id,
    hermes: doc.hermes || '',
    title: doc.title || '',
    project: doc.project || '',
    cwd: doc.cwd || '',
    created: doc.created || '',
    updated: doc.updated || '',
    messages: Array.isArray(doc.messages) ? doc.messages.length : 0,
  };
}

// What the window shows at start: the conversations it keeps, newest first, and the ones already deleted.
async function list(home) {
  await ensure(home);
  let names = [];
  try {
    names = await fsp.readdir(dir(home));
  } catch {
    return { dialogs: [], deleted: [] };
  }
  const docs = [];
  for (const name of names) {
    if (!name.endsWith('.json') || name === DELETED) continue;
    const doc = readJson(path.join(dir(home), name));
    if (!doc || typeof doc.id !== 'string' || !Array.isArray(doc.messages)) continue;
    docs.push(summary(doc));
  }
  docs.sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')));
  return { dialogs: docs, deleted: await tombstones(home) };
}

async function read(home, id) {
  const doc = readJson(fileOf(home, id));
  if (!doc || typeof doc.id !== 'string' || !Array.isArray(doc.messages)) return null;
  return doc;
}

// Saved after every reply, debounced by the window: the person closes the window mid-answer and the conversation
// is still there next time.
async function write(home, doc) {
  const d = doc && typeof doc === 'object' ? doc : {};
  const id = safeId(d.id);
  const old = readJson(fileOf(home, id)) || {};
  const messages = (Array.isArray(d.messages) ? d.messages : [])
    .filter((m) => m && typeof m === 'object' && typeof m.t === 'string')
    .slice(-MAX_MESSAGES);
  const out = {
    schema: SCHEMA,
    id,
    hermes: String(d.hermes || old.hermes || ''),
    title: String(d.title || old.title || '').slice(0, 300),
    project: String(d.project || old.project || '').slice(0, 200),
    cwd: String(d.cwd || old.cwd || '').slice(0, 1000),
    created: old.created || new Date().toISOString(),
    updated: new Date().toISOString(),
    messages,
  };
  let text = `${JSON.stringify(out, null, 1)}\n`;
  while (Buffer.byteLength(text, 'utf8') > MAX_BYTES && out.messages.length > 1) {
    out.messages = out.messages.slice(Math.ceil(out.messages.length / 4));
    text = `${JSON.stringify(out, null, 1)}\n`;
  }
  await writeAtomic(fileOf(home, id), text);
  return summary(out);
}

async function remove(home, id) {
  const key = safeId(id);
  try {
    await fsp.unlink(fileOf(home, key));
  } catch (err) {
    if (err.code !== 'ENOENT') throw new ChatsError(`разговор не удалился: ${err.message}`);
  }
  await bury(home, key);
  return { id: key };
}

// A project goes — the conversations about it go with it: they have nowhere to be opened from.
async function removeProject(home, project) {
  const name = String(project || '');
  if (!name) return { removed: 0 };
  const gone = [];
  for (const d of (await list(home)).dialogs) {
    if (d.project === name) gone.push(await remove(home, d.id));
  }
  return { removed: gone.length };
}

module.exports = { ChatsError, dir, list, read, write, remove, removeProject, tombstones, summary };
