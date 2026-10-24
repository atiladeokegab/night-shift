// E toggles the cover from anywhere but a text field, so typing in Ask never does (#277).
export const eyesKey = (e: Pick<KeyboardEvent, 'key' | 'repeat' | 'ctrlKey' | 'metaKey' | 'altKey' | 'target'>) =>
  e.key.toLowerCase() === 'e' && !e.repeat && !e.ctrlKey && !e.metaKey && !e.altKey
  && !(e.target as Element | null)?.closest?.('input, textarea, select, [contenteditable]')
