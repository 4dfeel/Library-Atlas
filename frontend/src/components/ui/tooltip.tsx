import * as Primitive from '@radix-ui/react-tooltip';
import type { ReactNode } from 'react';

export function Tooltip({ children, content }: { children: ReactNode; content: ReactNode }) {
  return (
    <Primitive.Root delayDuration={350}>
      <Primitive.Trigger asChild>{children}</Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Content className="tooltip" sideOffset={8}>
          {content}
          <Primitive.Arrow className="tooltip-arrow" />
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
