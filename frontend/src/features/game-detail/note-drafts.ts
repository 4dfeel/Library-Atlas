/**
 * Unsaved note drafts for this page session, keyed by game ID. Leaving a detail
 * (Back, Ctrl+K) keeps the draft and shows it as unsaved on return; a reload is
 * guarded by beforeunload. Drafts are never written to demo storage.
 */
const drafts = new Map<string, string>();

export const noteDrafts = {
  get: (id: string) => drafts.get(id),
  set: (id: string, value: string) => drafts.set(id, value),
  delete: (id: string) => drafts.delete(id),
  any: () => drafts.size > 0,
  clear: () => drafts.clear(),
};

let guarding = false;
function warnBeforeUnload(event: BeforeUnloadEvent) {
  if (!drafts.size) return;
  event.preventDefault();
}

export function guardUnsavedDrafts() {
  if (guarding || typeof window === 'undefined') return;
  guarding = true;
  window.addEventListener('beforeunload', warnBeforeUnload);
}
