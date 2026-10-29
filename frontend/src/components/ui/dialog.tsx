import * as Primitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useRef, type ReactNode } from 'react';
import { Button } from './button';

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  return (
    <Primitive.Root open={open} onOpenChange={onOpenChange}>
      <Primitive.Portal>
        <Primitive.Overlay className="dialog-overlay" />
        <Primitive.Content
          className="dialog-content"
          onOpenAutoFocus={() => {
            returnFocus.current =
              document.activeElement instanceof HTMLElement ? document.activeElement : null;
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (returnFocus.current?.isConnected) returnFocus.current.focus();
          }}
        >
          <div className="dialog-heading">
            <Primitive.Title>{title}</Primitive.Title>
            <Primitive.Close asChild>
              <Button variant="ghost" size="icon" aria-label="关闭">
                <X size={20} />
              </Button>
            </Primitive.Close>
          </div>
          <Primitive.Description>{description}</Primitive.Description>
          {children}
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  );
}
