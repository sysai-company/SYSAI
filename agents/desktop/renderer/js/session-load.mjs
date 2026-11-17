// Share an in-flight restore between the selector and the composer. A failed restore is not cached:
// the next explicit attempt may retry it.
export function ensureLoaded(conv, load) {
  if (conv.loaded || conv.draft) return Promise.resolve(true);
  if (conv.loadPromise) return conv.loadPromise;

  let pending;
  pending = Promise.resolve()
    .then(load)
    .then((loaded) => Boolean(loaded), () => false)
    .finally(() => {
      if (conv.loadPromise === pending) conv.loadPromise = null;
    });
  conv.loadPromise = pending;
  return pending;
}
