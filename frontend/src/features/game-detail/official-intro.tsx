import { useState } from 'react';
import {
  CircleAlert,
  ExternalLink,
  ImageOff,
  LoaderCircle,
  PlayCircle,
  RefreshCw,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { useWorkIntroduction, type IntroBlock, type IntroImageBlock } from '@/lib/data';
import { formatDate } from '@/lib/utils';

/** Keeps its place in the text if it fails; nothing else on the page depends on it. */
function IntroImage({
  block,
  onOpen,
}: {
  block: IntroImageBlock;
  onOpen: (block: IntroImageBlock) => void;
}) {
  const [failed, setFailed] = useState(false);
  if (failed)
    return (
      <p className="intro-image-missing">
        <ImageOff size={16} />
        这张图片暂时无法显示。
      </p>
    );
  return (
    <button
      type="button"
      className="intro-image"
      aria-label={block.alt ? `放大图片：${block.alt}` : '放大图片'}
      onClick={() => onOpen(block)}
    >
      <img
        src={block.url}
        alt={block.alt ?? ''}
        width={block.width ?? undefined}
        height={block.height ?? undefined}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
    </button>
  );
}

type VideoBlock = Extract<IntroBlock, { type: 'video' }>;

/**
 * The store's own preview player. Nothing is asked of its host until the user presses play: until
 * then the picture comes from Atlas. It runs in a sandbox and cannot touch this page.
 */
function IntroPlayer({ block }: { block: VideoBlock }) {
  const [playing, setPlaying] = useState(false);
  const label = block.media === 'audio' ? '播放预览音频' : '播放预览视频';
  const shape = block.width && block.height ? `${block.width} / ${block.height}` : '16 / 10';
  return (
    <div className="intro-player" data-testid="intro-player" style={{ aspectRatio: shape }}>
      {playing ? (
        <iframe
          src={block.embed}
          title={label}
          sandbox="allow-scripts allow-same-origin allow-presentation"
          allow="autoplay; fullscreen"
          allowFullScreen
          referrerPolicy="no-referrer"
        />
      ) : (
        <button type="button" aria-label={label} onClick={() => setPlaying(true)}>
          {block.poster && <img src={block.poster} alt="" loading="lazy" decoding="async" />}
          <PlayCircle size={56} strokeWidth={1.25} />
        </button>
      )}
    </div>
  );
}

function Block({
  block,
  sourceUrl,
  onOpen,
}: {
  block: IntroBlock;
  sourceUrl: string | null | undefined;
  onOpen: (block: IntroImageBlock) => void;
}) {
  switch (block.type) {
    case 'heading':
      return <h3 className="intro-heading">{block.text}</h3>;
    case 'paragraph':
      return (
        <p className="intro-paragraph">
          {block.spans.map((span, index) =>
            span.href ? (
              <a key={index} href={span.href} target="_blank" rel="noopener noreferrer">
                {span.text}
              </a>
            ) : (
              <span key={index}>{span.text}</span>
            ),
          )}
        </p>
      );
    case 'list':
      return (
        <ul className="intro-list">
          {block.items.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      );
    case 'table':
      return (
        <div className="intro-table">
          <table>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'image':
      return <IntroImage block={block} onOpen={onOpen} />;
    case 'video':
      if (block.embed) return <IntroPlayer block={block} />;
      return (
        <p className="intro-video" data-testid="intro-video">
          <PlayCircle size={18} />
          <span>这里有一段预览视频，目前需要到官方页面观看。</span>
          {sourceUrl && (
            <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
              前往官方页面
              <ExternalLink size={13} />
            </a>
          )}
        </p>
      );
  }
}

/**
 * The store's own introduction, in its order. Built only from checked blocks: no HTML from the
 * page ever reaches the document. It stands alone: a failure here leaves the rest of the page,
 * and any note being written, exactly as they were.
 */
export function OfficialIntro({
  workId,
  sourceUrl,
}: {
  workId: string;
  sourceUrl: string | null | undefined;
}) {
  const { intro, loading, refresh, refreshing } = useWorkIntroduction(workId);
  const [enlarged, setEnlarged] = useState<IntroImageBlock | null>(null);
  const heading = <h2 id="official-intro-title">官方作品介绍</h2>;
  if (loading)
    return (
      <section className="official-intro is-loading" aria-busy="true" data-testid="official-intro">
        {heading}
        <span className="official-intro-skeleton" />
        <span className="official-intro-skeleton" />
        <span className="official-intro-skeleton is-short" />
      </section>
    );
  if (!intro) return null;
  const fetched = formatDate(intro.fetchedAt ?? null);
  const empty = intro.blocks.length === 0;
  return (
    <section
      className="official-intro"
      aria-labelledby="official-intro-title"
      data-testid="official-intro"
    >
      <header>
        {heading}
        <span className="official-intro-meta">
          {fetched && `读取于 ${fetched}`}
          <Button variant="ghost" size="sm" disabled={refreshing} onClick={refresh}>
            {refreshing ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}
            刷新
          </Button>
        </span>
      </header>
      {intro.message && (
        <p className="dlsite-message" role={empty ? 'alert' : 'status'}>
          <CircleAlert size={14} />
          {intro.message}
          {!empty && ' 下面是上次读取的内容。'}
        </p>
      )}
      {empty && !intro.message && <p className="section-empty">DLsite 没有提供详细介绍。</p>}
      <div className="official-intro-body">
        {intro.blocks.map((block, index) => (
          <Block key={index} block={block} sourceUrl={sourceUrl} onOpen={setEnlarged} />
        ))}
      </div>
      {enlarged && (
        <Dialog
          open
          onOpenChange={(open) => !open && setEnlarged(null)}
          title="查看图片"
          description={enlarged.alt ?? '作品介绍中的图片'}
        >
          <div className="image-lightbox" data-testid="intro-lightbox">
            <img src={enlarged.url} alt={enlarged.alt ?? ''} />
          </div>
        </Dialog>
      )}
    </section>
  );
}
