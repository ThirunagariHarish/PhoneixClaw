import '@testing-library/jest-dom'

// Vitest/jsdom: ensure localStorage has working getItem/setItem (some envs stub it incompletely).
const _lsStore: Record<string, string> = {}
const mockLocalStorage = {
  getItem: (k: string) => (_lsStore[k] ?? null) as string | null,
  setItem: (k: string, v: string) => {
    _lsStore[k] = v
  },
  removeItem: (k: string) => {
    delete _lsStore[k]
  },
  clear: () => {
    for (const k of Object.keys(_lsStore)) delete _lsStore[k]
  },
  key: (i: number) => Object.keys(_lsStore)[i] ?? null,
  get length() {
    return Object.keys(_lsStore).length
  },
}
Object.defineProperty(globalThis, 'localStorage', {
  value: mockLocalStorage,
  configurable: true,
  writable: true,
})

// Login page canvas animation: jsdom has no getContext without native canvas.
HTMLCanvasElement.prototype.getContext = function getContext() {
  return null
} as unknown as typeof HTMLCanvasElement.prototype.getContext
