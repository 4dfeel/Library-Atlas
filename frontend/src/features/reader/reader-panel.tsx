import { useState } from 'react';
import { BookOpen, CircleAlert, FileArchive, FileText, Images } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useBooks, type GameDetail, type ReaderBook } from '@/lib/data';
import { ReaderView } from './reader-view';

const KIND_ICONS = { images: Images, archive: FileArchive, pdf: FileText };

function progress(book: ReaderBook) {
  if (book.readState === 'read') return '已读';
  if (book.pageIndex === null || book.readState === 'unread')
    return book.pageCount ? `${book.pageCount} 页` : '';
  return `读到 ${book.pageIndex + 1}${book.pageCount ? ` / ${book.pageCount}` : ''}`;
}

/** What can be read in a work's folder, grouped as it is on disk. */
export function ReaderPanel({ game }: { game: GameDetail }) {
  const { books, loading, refresh } = useBooks(game.id);
  const [open, setOpen] = useState<ReaderBook | null>(null);
  if (loading) return null;
  const heading = <h2>阅读</h2>;
  if (!books || books.state === 'no_copy')
    return (
      <section className="audio-panel" data-testid="reader-panel">
        {heading}
        <p className="settings-note">还没有在本机找到这部作品。下载并解压后，就可以在这里阅读。</p>
      </section>
    );
  if (books.state === 'offline' || books.state === 'empty' || !books.copyId)
    return (
      <section className="audio-panel" data-testid="reader-panel">
        {heading}
        <p className="settings-note">
          {books.state === 'offline'
            ? '这个文件夹现在不可用，可能是硬盘没有连接。'
            : '这个文件夹里没有找到图片、ZIP/CBZ 或 PDF。'}
        </p>
      </section>
    );
  const copyId = books.copyId;
  const last = books.books.find((book) => book.id === books.lastBookId);
  const first = books.books[0];
  const groups = new Map<string, ReaderBook[]>();
  for (const book of books.books) groups.set(book.group, [...(groups.get(book.group) ?? []), book]);
  return (
    <section className="audio-panel" data-testid="reader-panel">
      {heading}
      <div className="audio-main">
        {last ? (
          <Button data-testid="reader-continue" onClick={() => setOpen(last)}>
            <BookOpen size={15} />
            继续阅读 · {last.name}
            {last.pageIndex !== null ? ` · 第 ${last.pageIndex + 1} 页` : ''}
          </Button>
        ) : (
          first && (
            <Button data-testid="reader-start" onClick={() => setOpen(first)}>
              <BookOpen size={15} />
              开始阅读
            </Button>
          )
        )}
      </div>
      {!books.complete && <p className="settings-note">文件太多，这里只列出了一部分。</p>}
      {[...groups].map(([group, items]) => (
        <div className="audio-group" key={group}>
          {group && <h3 title={group}>{group}</h3>}
          <ol className="audio-tracks" data-testid="reader-books">
            {items.map((book) => {
              const Icon = KIND_ICONS[book.kind];
              return (
                <li key={book.id}>
                  <button type="button" title={book.name} onClick={() => setOpen(book)}>
                    <Icon size={14} />
                    <span>{book.name}</span>
                  </button>
                  <span className="audio-track-meta">{progress(book)}</span>
                </li>
              );
            })}
          </ol>
        </div>
      ))}
      {books.unsupported.length > 0 && (
        <div className="audio-group" data-testid="reader-unsupported">
          <h3>暂时不能在这里打开</h3>
          <ul className="audio-tracks">
            {books.unsupported.map((item) => (
              <li key={item.name}>
                <span className="reader-unsupported-name" title={item.name}>
                  <CircleAlert size={14} />
                  {item.name}
                </span>
                <span className="audio-track-meta">{item.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {open && (
        <ReaderView
          copyId={copyId}
          book={open}
          onClose={() => {
            setOpen(null);
            void refresh();
          }}
        />
      )}
    </section>
  );
}
