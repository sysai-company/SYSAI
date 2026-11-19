// A conversation must be reserved synchronously before any asynchronous send preparation starts.
export function reserveSend(conv) {
  if (conv.running || conv.sending) return false;
  conv.sending = true;
  return true;
}

export function releaseSend(conv) {
  conv.sending = false;
}
