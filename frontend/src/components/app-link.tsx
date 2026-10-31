import type { AnchorHTMLAttributes, MouseEvent } from 'react';
import { navigate, type AtlasHistoryState } from '@/lib/router';

function isPlainClick(event: MouseEvent<HTMLAnchorElement>) {
  return (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey &&
    !event.currentTarget.target
  );
}

/** A real link (new tab, copy link and direct URLs all work) with in-app navigation. */
export function AppLink({
  to,
  state,
  replace,
  onNavigate,
  onClick,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  to: string;
  state?: AtlasHistoryState;
  replace?: boolean;
  /** Runs before the history entry changes, e.g. to remember a scroll anchor. */
  onNavigate?: () => void;
}) {
  return (
    <a
      {...props}
      href={to}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented || !isPlainClick(event)) return;
        event.preventDefault();
        onNavigate?.();
        navigate(to, { state, replace });
      }}
    />
  );
}
