import type { ReactNode, Ref } from 'react';
import { ChevronRight, LibraryBig, type LucideIcon } from 'lucide-react';
import { Button } from './ui/button';

export function FeedbackState({
  kind,
  title,
  description,
  action,
  onAction,
  icon: Icon = LibraryBig,
  eyebrow,
  headingRef,
  children,
}: {
  kind: 'error' | 'empty';
  title: string;
  description: string;
  action?: string;
  onAction?: () => void;
  icon?: LucideIcon;
  eyebrow?: string;
  headingRef?: Ref<HTMLHeadingElement>;
  children?: ReactNode;
}) {
  return (
    <div className={`feedback-state feedback-${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      <div className="feedback-illustration">
        <span />
        <Icon size={38} strokeWidth={1} />
      </div>
      <span className="eyebrow">
        {eyebrow ?? (kind === 'error' ? 'A SMALL DETOUR' : 'UNCHARTED TERRITORY')}
      </span>
      <h2 ref={headingRef} tabIndex={headingRef ? -1 : undefined}>
        {title}
      </h2>
      <p>{description}</p>
      {action && (
        <Button variant="secondary" onClick={onAction}>
          {action}
          <ChevronRight size={16} />
        </Button>
      )}
      {children}
    </div>
  );
}
