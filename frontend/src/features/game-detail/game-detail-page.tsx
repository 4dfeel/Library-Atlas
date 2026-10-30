import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { Compass, FolderOpen, Tag, Trophy } from 'lucide-react';
import { FeedbackState } from '@/components/feedback-state';
import {
  GameUnavailableError,
  useGameDetail,
  type DemoScenario,
  type DemoSize,
  type GameDetail,
} from '@/lib/data';
import { libraryHref, navigate, readHistoryState } from '@/lib/router';
import { availabilityLabel, formatDate, kindLabels, platformLabels } from '@/lib/utils';
import { GameHero } from './game-hero';
import { PersonalRecord } from './personal-record';

type Notify = (message: string, tone?: 'success' | 'error') => void;

function scenarioFromUrl(): DemoScenario {
  const value = new URLSearchParams(window.location.search).get('state');
  return value === 'error' || value === 'loading' ? value : 'normal';
}

/** Back goes to the exact Library entry when we came from it; otherwise to /library. */
function useBackToLibrary(size: DemoSize) {
  const href = libraryHref(size);
  const onBack = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
    if (readHistoryState().fromLibrary) {
      event.preventDefault();
      window.history.back();
    }
  };
  return { href, onBack };
}

function DetailBody({ game }: { game: GameDetail }) {
  const achievements = game.achievements;
  const percent =
    achievements && achievements.total > 0
      ? Math.round((achievements.unlocked / achievements.total) * 100)
      : 0;
  return (
    <>
      <section className="detail-about" aria-labelledby="about-title">
        <span className="eyebrow">ABOUT THIS WORK</span>
        <h2 id="about-title">作品简介</h2>
        {game.description ? (
          <div className="about-text">
            {game.description.split('\n\n').map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
          </div>
        ) : (
          <p className="section-empty">这部作品暂未提供简介。</p>
        )}
        <p className="source-note">简介与标签为 Library Atlas 合成演示资料，不对应任何真实作品。</p>
      </section>

      <div className="detail-facets">
        <section className="detail-section" aria-labelledby="tags-title">
          <h2 id="tags-title">
            <Tag size={15} />
            类型与标签
          </h2>
          <ul className="tag-list">
            <li className="tag-genre">{game.genre}</li>
            {game.tags.map((tag) => (
              <li key={tag}>{tag}</li>
            ))}
          </ul>
        </section>

        {/* Only Steam exposes achievements; other platforms omit the section. */}
        {game.platform === 'steam' && (
          <section className="detail-section" aria-labelledby="achievements-title">
            <h2 id="achievements-title">
              <Trophy size={15} />
              成就进度<span className="field-rule">演示</span>
            </h2>
            {achievements ? (
              <div className="achievement-progress" data-testid="achievements">
                <div className="achievement-numbers">
                  <strong>{percent}%</strong>
                  <span>
                    已解锁 {achievements.unlocked} / {achievements.total}
                  </span>
                </div>
                <div
                  className="progress-track"
                  role="progressbar"
                  aria-label="成就解锁进度"
                  aria-valuemin={0}
                  aria-valuemax={achievements.total}
                  aria-valuenow={achievements.unlocked}
                  aria-valuetext={`${achievements.unlocked} / ${achievements.total}，${percent}%`}
                >
                  <span style={{ width: `${percent}%` }} />
                </div>
                {achievements.unlocked === 0 && <p className="section-empty">尚未解锁任何成就。</p>}
              </div>
            ) : (
              <p className="section-empty" data-testid="achievements">
                未提供成就信息。该条目没有成就数据，不以 0% 显示。
              </p>
            )}
          </section>
        )}

        <section className="detail-section" aria-labelledby="archive-title">
          <h2 id="archive-title">
            <FolderOpen size={15} />
            收藏档案
          </h2>
          <dl className="archive-list">
            <div>
              <dt>所属分类</dt>
              <dd>
                {game.categories.length ? (
                  <ul className="category-list">
                    {game.categories.map((category) => (
                      <li key={category}>{category}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="muted">尚未归类</span>
                )}
              </dd>
            </div>
            <div>
              <dt>平台</dt>
              <dd>
                {platformLabels[game.platform]} · {kindLabels[game.kind]}
              </dd>
            </div>
            <div>
              <dt>制作方</dt>
              <dd>{game.maker}</dd>
            </div>
            <div>
              <dt>发售日</dt>
              <dd>{formatDate(game.releaseDate) ?? <span className="muted">未提供</span>}</dd>
            </div>
            <div>
              <dt>本机状态</dt>
              <dd>
                {availabilityLabel(game)}
                {game.installed && '（演示）'}
              </dd>
            </div>
            <div>
              <dt>加入收藏</dt>
              <dd>{formatDate(game.addedAt) ?? '未记录'}</dd>
            </div>
            <div>
              <dt>资料来源</dt>
              <dd>合成演示数据 · 未连接 {platformLabels[game.platform]}</dd>
            </div>
          </dl>
        </section>
      </div>
    </>
  );
}

function DetailSkeleton() {
  return (
    <div className="detail-page detail-loading" role="status" aria-label="正在读取作品详情">
      <p className="sr-only">正在读取作品详情</p>
      <div className="detail-hero skeleton-hero">
        <div className="detail-frame hero-inner">
          <span className="skeleton-block back-skeleton" />
          <div className="hero-main">
            <div className="hero-cover">
              <div className="skeleton-cover" />
            </div>
            <div className="hero-copy">
              <span className="skeleton-block" style={{ width: 160, height: 12 }} />
              <span
                className="skeleton-block"
                style={{ width: '62%', height: 40, marginTop: 18 }}
              />
              <span className="skeleton-block" style={{ width: 220, height: 28, marginTop: 20 }} />
              <span className="skeleton-block" style={{ width: 280, height: 40, marginTop: 24 }} />
            </div>
          </div>
          <div className="hero-facts">
            {Array.from({ length: 4 }, (_, index) => (
              <span key={index} className="skeleton-block" style={{ height: 44 }} />
            ))}
          </div>
        </div>
      </div>
      <div className="detail-frame detail-body">
        <div className="detail-main">
          <span className="skeleton-block" style={{ width: 120, height: 18 }} />
          {[96, 92, 88, 60].map((width, index) => (
            <span
              key={index}
              className="skeleton-block"
              style={{ width: `${width}%`, height: 14, marginTop: 14 }}
            />
          ))}
        </div>
        <div className="personal-record skeleton-panel" />
      </div>
    </div>
  );
}

export function GameUnavailable({ size }: { size: DemoSize }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = '作品不可用 · Library Atlas';
    headingRef.current?.focus({ preventScroll: true });
  }, []);
  return (
    <main className="detail-page detail-feedback" data-testid="game-unavailable">
      <FeedbackState
        kind="empty"
        icon={Compass}
        eyebrow="OFF THE MAP"
        title="找不到这部作品"
        description="它不在当前演示收藏中，或暂时无法在普通页面查看。请返回作品库继续浏览。"
        action="返回作品库"
        headingRef={headingRef}
        onAction={() => navigate(libraryHref(size))}
      />
    </main>
  );
}

export function GameDetailPage({
  id,
  size,
  demoEnabled,
  notify,
}: {
  id: string;
  size: DemoSize;
  demoEnabled: boolean;
  notify: Notify;
}) {
  const [scenario, setScenario] = useState<DemoScenario>(scenarioFromUrl);
  const query = useGameDetail(id, { size, scenario });
  const headingRef = useRef<HTMLHeadingElement>(null);
  const back = useBackToLibrary(size);
  const game = query.data;

  useEffect(() => {
    if (!game) return;
    document.title = `${game.title} · Library Atlas`;
    headingRef.current?.focus({ preventScroll: true });
    // Focus once per opened game; later edits must not pull focus back to the title.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [game?.id]);
  useEffect(() => {
    if (!game) document.title = '作品详情 · Library Atlas';
  }, [game]);
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'k') return;
      event.preventDefault();
      // Never yank the user out of a note they are typing.
      if (document.activeElement instanceof HTMLTextAreaElement) {
        notify('正在编辑备注 · 保存或取消后再用 Ctrl+K 搜索', 'error');
        return;
      }
      navigate(libraryHref(size), { state: { focusSearch: true } });
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [notify, size]);

  if (!demoEnabled)
    return (
      <main className="detail-page detail-feedback">
        <FeedbackState
          kind="empty"
          title="真实资料尚未接入"
          description="此检查点仅提供独立演示空间，不会把演示资料当作真实记录展示。"
        />
      </main>
    );
  if (query.isPending) return <DetailSkeleton />;
  if (query.isError) {
    if (query.error instanceof GameUnavailableError) return <GameUnavailable size={size} />;
    return (
      <main className="detail-page detail-feedback">
        <FeedbackState
          kind="error"
          title="暂时未能读取作品详情"
          description="演示资料仍然安全，请重试；也可以先返回作品库。"
          action="重新加载"
          onAction={() => {
            if (scenario !== 'normal') setScenario('normal');
            else void query.refetch();
          }}
        >
          <a
            className="feedback-link"
            href={back.href}
            onClick={(event) => {
              event.preventDefault();
              navigate(back.href);
            }}
          >
            返回作品库
          </a>
        </FeedbackState>
      </main>
    );
  }
  const loaded = query.data;
  return (
    <main className="detail-page" data-testid="game-detail" data-game-id={loaded.id}>
      <GameHero
        game={loaded}
        size={size}
        notify={notify}
        backHref={back.href}
        onBack={back.onBack}
        headingRef={headingRef}
      />
      <div className="detail-frame detail-body">
        <div className="detail-main">
          <DetailBody game={loaded} />
        </div>
        <aside className="detail-side" aria-label="我的记录">
          <PersonalRecord game={loaded} size={size} notify={notify} />
        </aside>
      </div>
      <footer className="detail-footer detail-frame">
        <span>DEMO · 所有游玩时长、成就、评分与备注均为合成或本机演示数据</span>
        <span>LIBRARY ATLAS · PREVIEW 02</span>
      </footer>
    </main>
  );
}
