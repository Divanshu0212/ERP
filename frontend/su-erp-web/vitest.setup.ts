import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// In the real app, the root layout wraps every page in <ThemeProvider>, so any
// component under it can call useTheme(). Component tests render pages directly
// and would otherwise hit the provider-missing guard, so wrap render() at the
// root here rather than in each test.
vi.mock("@testing-library/react", async () => {
  const actual =
    await vi.importActual<typeof import("@testing-library/react")>("@testing-library/react");
  const { createElement } = await import("react");
  const { ThemeProvider } = await import("@/lib/theme");

  const render = (
    ui: Parameters<typeof actual.render>[0],
    options?: Parameters<typeof actual.render>[1],
  ) =>
    actual.render(ui, {
      wrapper: ({ children }) => createElement(ThemeProvider, null, children),
      ...options,
    });

  return { ...actual, render };
});

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
