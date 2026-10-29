import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

afterEach(cleanup);
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

class ResizeObserverStub implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub;
HTMLElement.prototype.scrollIntoView = vi.fn();
