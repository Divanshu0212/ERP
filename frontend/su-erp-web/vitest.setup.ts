import "@testing-library/jest-dom/vitest";

// Node 22+ ships an experimental localStorage that is disabled unless
// `--localstorage-file` is passed, so under jsdom `window.localStorage` can be
// undefined. Provide a simple in-memory implementation so client-side session
// helpers work in component tests.
if (typeof window !== "undefined") {
  const hasStorage = (() => {
    try {
      return typeof window.localStorage !== "undefined" && window.localStorage !== null;
    } catch {
      return false;
    }
  })();

  if (!hasStorage) {
    const store = new Map<string, string>();
    const memoryStorage: Storage = {
      get length() {
        return store.size;
      },
      clear: () => store.clear(),
      getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
      key: (index: number) => Array.from(store.keys())[index] ?? null,
      removeItem: (key: string) => void store.delete(key),
      setItem: (key: string, value: string) => void store.set(key, String(value)),
    };
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: memoryStorage,
    });
  }
}
