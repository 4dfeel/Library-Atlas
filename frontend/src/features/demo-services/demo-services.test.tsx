import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SourcesDialog } from './sources-dialog';
import { TasksDialog } from './tasks-dialog';

function renderWithQuery(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe('demo services when demo mode is off', () => {
  it('never presents a demo session as a real connection', () => {
    renderWithQuery(<SourcesDialog open onOpenChange={vi.fn()} size={1500} demoEnabled={false} />);
    const dialog = screen.getByRole('dialog', { name: '来源连接' });
    expect(dialog).toHaveTextContent('真实来源连接尚未接入');
    expect(dialog).not.toHaveTextContent('已连接');
    expect(dialog).not.toHaveTextContent('演示');
    expect(screen.queryByRole('button', { name: /连接|断开/ })).toBeNull();
  });

  it('shows the demo connections only while demo mode is on', () => {
    renderWithQuery(<SourcesDialog open onOpenChange={vi.fn()} size={1500} demoEnabled />);
    expect(screen.getAllByText('已连接')).toHaveLength(2);
  });

  it('lists no demo tasks when demo mode is off', () => {
    renderWithQuery(<TasksDialog open onOpenChange={vi.fn()} size={1500} demoEnabled={false} />);
    const dialog = screen.getByRole('dialog', { name: '下载与解压' });
    expect(dialog).toHaveTextContent('真实下载与解压尚未接入');
    expect(screen.queryByRole('progressbar')).toBeNull();
  });
});
