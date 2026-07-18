import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? false : query.includes("prefers-color-scheme: light") ? false : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

class EventSourceMock {
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onerror: (() => void) | null = null;
  addEventListener = vi.fn();
  close = vi.fn();
}
Object.defineProperty(globalThis, "EventSource", { value: EventSourceMock, writable: true });
const stored = new Map<string, string>();
const localStorageMock = {
  get length() { return stored.size; },
  clear: () => stored.clear(),
  getItem: (key: string) => stored.get(key) ?? null,
  key: (index: number) => [...stored.keys()][index] ?? null,
  removeItem: (key: string) => stored.delete(key),
  setItem: (key: string, value: string) => stored.set(key, String(value)),
};
Object.defineProperty(window, "localStorage", { value: localStorageMock, configurable: true });
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, configurable: true });
Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
Object.defineProperty(URL, "createObjectURL", { value: vi.fn(() => "blob:test-export"), configurable: true });
Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true });
Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { value: vi.fn(), configurable: true });
Object.defineProperty(HTMLDialogElement.prototype, "showModal", { value: function showModal(this: HTMLDialogElement) { this.setAttribute("open", ""); }, configurable: true });
Object.defineProperty(HTMLDialogElement.prototype, "close", { value: function close(this: HTMLDialogElement) { this.removeAttribute("open"); }, configurable: true });

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useParams: () => ({ batchId: "batch-test", runId: "run-test", evaluationId: "talon-eval-test" }),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => ({ getAll: () => [], get: () => null }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => <a href={href} {...props}>{children}</a>,
}));

vi.mock("react-chartjs-2", () => ({
  Bar: ({ data }: { data: unknown }) => <div data-testid="bar-chart" data-chart={JSON.stringify(data)} />,
  Line: ({ data }: { data: unknown }) => <div data-testid="line-chart" data-chart={JSON.stringify(data)} />,
  Scatter: ({ data }: { data: unknown }) => <div data-testid="scatter-chart" data-chart={JSON.stringify(data)} />,
  Doughnut: ({ data }: { data: unknown }) => <div data-testid="doughnut-chart" data-chart={JSON.stringify(data)} />,
}));

beforeEach(() => {
  window.localStorage.clear();
  vi.clearAllMocks();
});
