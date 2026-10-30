import { describe, expect, it } from 'vitest';
import { onScreen, spreadAt, stepForSide, turn } from './spreads';

describe('spreads', () => {
  it('stands the cover alone and pairs the rest', () => {
    expect(spreadAt(0, 6, 'double')).toEqual([0]);
    expect(spreadAt(1, 6, 'double')).toEqual([1, 2]);
    expect(spreadAt(2, 6, 'double')).toEqual([1, 2]);
    expect(spreadAt(4, 6, 'double')).toEqual([3, 4]);
  });

  it('stands a last odd page alone', () => {
    expect(spreadAt(5, 6, 'double')).toEqual([5]);
    expect(spreadAt(3, 5, 'double')).toEqual([3, 4]);
  });

  it('shows one page in single mode and nothing for no pages', () => {
    expect(spreadAt(3, 6, 'single')).toEqual([3]);
    expect(spreadAt(0, 0, 'double')).toEqual([]);
  });

  it('keeps a page in range when the book got shorter', () => {
    expect(spreadAt(50, 3, 'single')).toEqual([2]);
  });
});

describe('turning', () => {
  it('walks every page exactly once, either way', () => {
    for (const mode of ['single', 'double'] as const)
      for (const count of [1, 2, 5, 6]) {
        const seen = new Set<number>();
        let index = 0;
        for (let i = 0; i < count; i += 1) {
          spreadAt(index, count, mode).forEach((page) => seen.add(page));
          index = turn(index, count, mode, 1);
        }
        expect(seen.size).toBe(count);
        for (let i = 0; i < count; i += 1) index = turn(index, count, mode, -1);
        expect(index).toBe(0);
      }
  });

  it('stays put at both ends', () => {
    expect(turn(0, 5, 'single', -1)).toBe(0);
    expect(turn(4, 5, 'single', 1)).toBe(4);
    expect(turn(5, 6, 'double', 1)).toBe(5);
  });
});

describe('direction', () => {
  it('moves forward towards the reading direction', () => {
    expect(stepForSide('right', 'ltr')).toBe(1);
    expect(stepForSide('left', 'ltr')).toBe(-1);
    expect(stepForSide('left', 'rtl')).toBe(1);
    expect(stepForSide('right', 'rtl')).toBe(-1);
  });

  it('puts the first page of a right-to-left spread on the right', () => {
    expect(onScreen([1, 2], 'rtl')).toEqual([2, 1]);
    expect(onScreen([1, 2], 'ltr')).toEqual([1, 2]);
  });
});
