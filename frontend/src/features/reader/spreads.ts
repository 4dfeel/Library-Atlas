export type ReaderMode = 'single' | 'double' | 'vertical';
export type ReaderDirection = 'ltr' | 'rtl';

/**
 * The pages shown together. In double mode the cover stands alone, the rest pair up (1-2, 3-4, …)
 * and a last odd page stands alone, so a book's real spreads line up. Always in reading order.
 */
export function spreadAt(index: number, count: number, mode: ReaderMode): number[] {
  if (count <= 0) return [];
  const page = Math.min(Math.max(index, 0), count - 1);
  if (mode !== 'double' || page === 0) return [page];
  const first = page % 2 === 1 ? page : page - 1;
  return first + 1 < count ? [first, first + 1] : [first];
}

/** The page a turn lands on. Staying put at either end is what "no further" looks like. */
export function turn(index: number, count: number, mode: ReaderMode, step: 1 | -1): number {
  const spread = spreadAt(index, count, mode);
  if (spread.length === 0) return 0;
  if (step === 1) {
    const next = spread[spread.length - 1]! + 1;
    return next < count ? next : spread[0]!;
  }
  return spread[0]! > 0 ? spreadAt(spread[0]! - 1, count, mode)[0]! : spread[0]!;
}

/** Which way a side of the screen goes. Going "left" in a right-to-left book moves forward. */
export function stepForSide(side: 'left' | 'right', direction: ReaderDirection): 1 | -1 {
  return (side === 'right') === (direction === 'ltr') ? 1 : -1;
}

/** The order on screen: a right-to-left spread shows its first page on the right. */
export function onScreen(spread: number[], direction: ReaderDirection): number[] {
  return direction === 'rtl' ? [...spread].reverse() : spread;
}
