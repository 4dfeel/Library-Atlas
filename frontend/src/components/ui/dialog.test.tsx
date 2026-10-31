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
        <button onClick={() => setOpen(true)}>资料库状态</button>
        <Dialog open={open} onOpenChange={setOpen} title="我的资料库" description="独立合成数据">
          <p>本地资料</p>
        </Dialog>
      </>
    );
  }
  const user = userEvent.setup();
  render(<Example />);
  const trigger = screen.getByRole('button', { name: '资料库状态' });
  await user.click(trigger);
  expect(screen.getByRole('dialog', { name: '我的资料库' })).toBeVisible();
  await user.keyboard('{Escape}');
  await waitFor(() => expect(trigger).toHaveFocus());
});
