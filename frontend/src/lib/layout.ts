import { useLayoutEffect, useState, type RefObject } from 'react';

/** One container-based contract for loaded cards and their loading placeholders. */
export function getGridLayout(width: number) {
  const columns = Math.max(
    1,
    Math.min(Math.floor((width + 20) / 196), Math.ceil((width + 20) / 260)),
  );
  const cardWidth = Math.min(240, Math.max(0, (width - (columns - 1) * 20) / columns));
  return { columns, cardWidth, rowHeight: cardWidth * 1.5 + 108 };
}

export function useMeasuredWidth(ref: RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
