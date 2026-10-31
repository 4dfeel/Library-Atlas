import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, CircleAlert, LoaderCircle } from 'lucide-react';
import { useWorkGallery } from '@/lib/data';

/**
 * The work's store images: one large, the rest as thumbnails below. All of them start loading
 * with the page, so moving between them is usually instant. The picture on screen stays until
 * the next one is ready: a click never leaves an empty frame, and a slow one says it is reading.
 * Images come in every shape, so both views show the whole picture and never crop it. A work
 * with no images shows nothing here, rather than an empty frame.
 */
export function WorkGallery({ workId }: { workId: string }) {
  const { gallery, loading } = useWorkGallery(workId);
  const [index, setIndex] = useState(0);
  const [ready, setReady] = useState<{ url: string; failed: boolean } | null>(null);
  const strip = useRef<HTMLDivElement>(null);
  const images = gallery?.images ?? [];
  const count = images.length;
  const current = Math.min(index, Math.max(count - 1, 0));
  const wanted = images[current]?.url;

  useEffect(() => {
    if (!wanted) return;
    let stale = false;
    const next = new Image();
    next.onload = () => {
      if (!stale) setReady({ url: wanted, failed: false });
    };
    next.onerror = () => {
      if (!stale) setReady({ url: wanted, failed: true });
    };
    next.src = wanted;
    return () => {
      stale = true;
    };
  }, [wanted]);

  useEffect(() => {
    // Only the strip scrolls. `scrollIntoView` would also scroll the page to reach a strip below
    // the fold, pulling the picture and the arrow out from under the pointer.
    const container = strip.current;
    const thumb = container?.children[current];
    if (!container || !thumb) return;
    const box = container.getBoundingClientRect();
    const place = thumb.getBoundingClientRect();
    if (place.left < box.left) container.scrollLeft -= box.left - place.left;
    else if (place.right > box.right) container.scrollLeft += place.right - box.right;
  }, [current]);

  if (loading)
    return (
      <section className="work-gallery is-loading" aria-busy="true" aria-label="作品介绍图">
        <div className="work-gallery-stage" />
      </section>
    );
  if (!count) return null;
  const step = (by: number) => setIndex((current + by + count) % count);
  const arrived = ready?.url === wanted;
  const failed = arrived && ready?.failed;
  const shown = ready && !ready.failed ? ready.url : null;

  return (
    <section
      className="work-gallery"
      aria-label="作品介绍图"
      data-testid="work-gallery"
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') step(-1);
        else if (event.key === 'ArrowRight') step(1);
      }}
    >
      <div className="work-gallery-stage" aria-busy={!arrived}>
        {shown && !failed && (
          <img src={shown} alt={`介绍图 ${current + 1}`} data-testid="gallery-image" />
        )}
        {!arrived && (
          <span className="work-gallery-note" role="status" data-testid="gallery-loading">
            <LoaderCircle size={14} className="spin" />
            正在读取…
          </span>
        )}
        {failed && (
          <span className="work-gallery-note" role="alert">
            <CircleAlert size={14} />
            这张图暂时无法读取。
          </span>
        )}
        {count > 1 && (
          <>
            <button
              type="button"
              className="work-gallery-arrow is-prev"
              aria-label="上一张"
              onClick={() => step(-1)}
            >
              <ChevronLeft size={22} />
            </button>
            <button
              type="button"
              className="work-gallery-arrow is-next"
              aria-label="下一张"
              onClick={() => step(1)}
            >
              <ChevronRight size={22} />
            </button>
          </>
        )}
      </div>
      {count > 1 && (
        <div className="work-gallery-strip" ref={strip} role="group" aria-label="选择介绍图">
          {images.map((thumb, position) => (
            <button
              type="button"
              key={thumb.url}
              className={position === current ? 'is-current' : ''}
              aria-label={`第 ${position + 1} 张`}
              aria-current={position === current ? 'true' : undefined}
              onClick={() => setIndex(position)}
            >
              <img src={thumb.url} alt="" decoding="async" />
            </button>
          ))}
        </div>
      )}
      <p className="work-gallery-count">共 {count} 张</p>
    </section>
  );
}
