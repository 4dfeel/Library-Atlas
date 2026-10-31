import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { Dialog } from './dialog';

it('returns keyboard focus to the initiating control after Escape closes a controlled dialog', async () => {
  function Example() {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>关于演示</button>
        <Dialog open={open} onOpenChange={setOpen} title="演示空间" description="独立合成数据">
          <p>本地演示</p>
        </Dialog>
      </>
    );
  }
  const user = userEvent.setup();
  render(<Example />);
  const trigger = screen.getByRole('button', { name: '关于演示' });
  await user.click(trigger);
  expect(screen.getByRole('dialog', { name: '演示空间' })).toBeVisible();
  await user.keyboard('{Escape}');
  await waitFor(() => expect(trigger).toHaveFocus());
});
