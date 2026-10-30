import { useMemo, useState } from 'react';
import {
  Bookmark,
  CircleAlert,
  ListMusic,
  Moon,
  Pause,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Trash2,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  audioSession,
  useAudioBookmarks,
  useAudioSession,
  useAudioTracks,
  useBookmarkActions,
  usePlaylists,
  type AudioTrack,
  type GameDetail,
  type SessionTrack,
} from '@/lib/data';

function clock(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '--:--';
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  const hours = Math.floor(minutes / 60);
  const parts = hours
    ? [hours, String(minutes % 60).padStart(2, '0')]
    : [String(minutes).padStart(2, '0')];
  return `${parts.join(':')}:${String(whole % 60).padStart(2, '0')}`;
}

const RATES = [0.75, 1, 1.25, 1.5, 2];
const SLEEP_MINUTES = [15, 30, 60, 90];

function asSession(
  copyId: string,
  workId: string,
  track: AudioTrack,
  resume: boolean,
): SessionTrack {
  return {
    copyId,
    workId,
    trackId: track.id,
    name: track.name,
    startAt: resume && track.position > 0 ? track.position : undefined,
  };
}

/** A work's sound: what is there, where the user left off, and their marks. Plays only on a click. */
export function AudioPanel({ game }: { game: GameDetail }) {
  const { audio, loading } = useAudioTracks(game.id);
  const session = useAudioSession();
  const { bookmarks } = useAudioBookmarks(game.id);
  const bookmarkActions = useBookmarkActions(game.id);
  const { playlists, save: savePlaylist, remove: removePlaylist } = usePlaylists();
  const [playlistName, setPlaylistName] = useState('');
  const tracks = useMemo(() => audio?.tracks ?? [], [audio]);
  const playable = useMemo(() => tracks.filter((track) => track.playable), [tracks]);
  const copyId = audio?.copyId;
  if (loading) return null;
  if (!audio || audio.state === 'no_copy')
    return (
      <section className="audio-panel" data-testid="audio-panel">
        <h2>收听</h2>
        <p className="settings-note">下载并解压，或关联本地文件夹后，就可以在这里收听。</p>
      </section>
    );
  if (audio.state === 'offline' || audio.state === 'empty' || !copyId)
    return (
      <section className="audio-panel" data-testid="audio-panel">
        <h2>收听</h2>
        <p className="settings-note">
          {audio.state === 'offline'
            ? '这个文件夹现在不可用，可能是硬盘没有连接。'
            : '这个文件夹里没有找到音频文件。'}
        </p>
      </section>
    );

  const playFrom = (track: AudioTrack, resume: boolean) => {
    const index = playable.indexOf(track);
    audioSession.playQueue(
      playable.map((item) => asSession(copyId, game.id, item, resume && item === track)),
      index,
    );
  };
  const last = tracks.find((track) => track.id === audio.lastTrackId && track.playable);
  const first = playable[0];
  const groups = new Map<string, AudioTrack[]>();
  for (const track of tracks)
    groups.set(track.folder, [...(groups.get(track.folder) ?? []), track]);
  const nowPlaying = session.queue[session.index];
  const trackById = new Map(tracks.map((track) => [track.id, track]));
  const canMark = nowPlaying?.workId === game.id;

  return (
    <section className="audio-panel" data-testid="audio-panel">
      <h2>收听</h2>
      <div className="audio-main">
        {last ? (
          <Button data-testid="audio-continue" onClick={() => playFrom(last, true)}>
            <Play size={15} />
            继续收听 · {last.name} · {clock(last.position)}
          </Button>
        ) : (
          first && (
            <Button data-testid="audio-play" onClick={() => playFrom(first, false)}>
              <Play size={15} />
              播放
            </Button>
          )
        )}
        {canMark && (
          <Button
            variant="ghost"
            size="sm"
            data-testid="audio-bookmark"
            onClick={() =>
              void bookmarkActions.add(nowPlaying.copyId, nowPlaying.trackId, session.position)
            }
          >
            <Bookmark size={14} />在 {clock(session.position)} 加书签
          </Button>
        )}
        {playable.length > 0 && (
          <span className="audio-save-list">
            <input
              aria-label="播放列表名称"
              placeholder="播放列表名称"
              value={playlistName}
              onChange={(event) => setPlaylistName(event.target.value)}
            />
            <Button
              variant="ghost"
              size="sm"
              disabled={!playlistName.trim()}
              onClick={() => {
                void savePlaylist(
                  playlistName.trim(),
                  playable.map((track) => ({
                    copyId,
                    trackId: track.id,
                    workId: game.id,
                    name: track.name,
                  })),
                );
                setPlaylistName('');
              }}
            >
              <ListMusic size={14} />
              保存为播放列表
            </Button>
          </span>
        )}
      </div>
      {!audio.complete && <p className="settings-note">文件太多，这里只列出了一部分。</p>}
      {[...groups].map(([folder, items]) => (
        <div className="audio-group" key={folder}>
          {folder && <h3 title={folder}>{folder}</h3>}
          <ol className="audio-tracks" data-testid="audio-tracks">
            {items.map((track) => {
              const active = nowPlaying?.trackId === track.id;
              return (
                <li key={track.id} className={active ? 'is-current' : ''}>
                  <button
                    type="button"
                    disabled={!track.playable}
                    title={track.name}
                    aria-current={active ? 'true' : undefined}
                    onClick={() => playFrom(track, true)}
                  >
                    {active && session.playing ? <Volume2 size={14} /> : <Play size={14} />}
                    <span>{track.name}</span>
                  </button>
                  <span className="audio-track-meta">
                    {!track.playable
                      ? '无法在这里播放，可以打开目录用其他播放器'
                      : track.position > 0
                        ? `听到 ${clock(track.position)} / ${clock(track.duration)}`
                        : ''}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      ))}
      {bookmarks.length > 0 && (
        <div className="audio-group">
          <h3>书签</h3>
          <ul className="audio-tracks" data-testid="audio-bookmarks">
            {bookmarks.map((mark) => {
              const track = trackById.get(mark.resourceId);
              return (
                <li key={mark.id}>
                  <button
                    type="button"
                    disabled={!track?.playable}
                    onClick={() => {
                      if (!track) return;
                      const index = playable.indexOf(track);
                      audioSession.playQueue(
                        playable.map((item) => ({
                          ...asSession(copyId, game.id, item, false),
                          startAt: item === track ? mark.position : undefined,
                        })),
                        index,
                      );
                    }}
                  >
                    <Bookmark size={14} />
                    <span>
                      {track?.name ?? '文件已不在'} · {clock(mark.position)}
                    </span>
                  </button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label="删除书签"
                    onClick={() => void bookmarkActions.remove(mark.id)}
                  >
                    <Trash2 size={13} />
                  </Button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      {playlists.length > 0 && (
        <div className="audio-group">
          <h3>播放列表</h3>
          <ul className="audio-tracks" data-testid="audio-playlists">
            {playlists.map((list) => (
              <li key={list.id}>
                <button
                  type="button"
                  disabled={list.items.length === 0}
                  onClick={() =>
                    audioSession.playQueue(
                      list.items.map((item) => ({ ...item })),
                      0,
                    )
                  }
                >
                  <ListMusic size={14} />
                  <span>
                    {list.name} · {list.items.length} 首
                  </span>
                </button>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={`删除播放列表：${list.name}`}
                  onClick={() => void removePlaylist(list.id)}
                >
                  <Trash2 size={13} />
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** Stays along the bottom while something is loaded, whichever page is open. */
export function MiniPlayer() {
  const session = useAudioSession();
  const track = session.queue[session.index];
  if (!track) return null;
  const LoopIcon = session.loop === 'one' ? Repeat1 : Repeat;
  const nextLoop = { off: 'all', all: 'one', one: 'off' } as const;
  return (
    <div className="mini-player" role="region" aria-label="音频播放器" data-testid="mini-player">
      <div className="mini-player-buttons">
        <Button variant="ghost" size="icon" aria-label="上一首" onClick={audioSession.previous}>
          <SkipBack size={16} />
        </Button>
        <Button
          size="icon"
          aria-label={session.playing ? '暂停' : '播放'}
          data-testid="player-toggle"
          onClick={audioSession.toggle}
        >
          {session.playing ? <Pause size={16} /> : <Play size={16} />}
        </Button>
        <Button variant="ghost" size="icon" aria-label="下一首" onClick={audioSession.next}>
          <SkipForward size={16} />
        </Button>
      </div>
      <div className="mini-player-track">
        <span className="mini-player-name" title={track.name} data-testid="player-name">
          {track.name}
        </span>
        <input
          type="range"
          aria-label="播放进度"
          data-testid="player-seek"
          min={0}
          max={session.duration ?? 0}
          step={0.1}
          disabled={session.duration === null}
          value={Math.min(session.position, session.duration ?? 0)}
          onChange={(event) => audioSession.seek(Number(event.target.value))}
        />
        <span className="mini-player-time" data-testid="player-time">
          {clock(session.position)} / {clock(session.duration)}
        </span>
      </div>
      {session.error && (
        <span className="download-state is-error" role="alert" data-testid="player-error">
          <CircleAlert size={14} />
          {session.error}
        </span>
      )}
      <div className="mini-player-options">
        <Button
          variant="ghost"
          size="icon"
          aria-label={`循环：${{ off: '关', all: '列表', one: '单曲' }[session.loop]}`}
          aria-pressed={session.loop !== 'off'}
          data-testid="player-loop"
          onClick={() => audioSession.setLoop(nextLoop[session.loop])}
        >
          <LoopIcon size={15} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          aria-label="随机播放"
          aria-pressed={session.shuffle}
          onClick={audioSession.toggleShuffle}
        >
          <Shuffle size={15} />
        </Button>
        <select
          aria-label="倍速"
          data-testid="player-rate"
          value={session.rate}
          onChange={(event) => audioSession.setRate(Number(event.target.value))}
        >
          {RATES.map((rate) => (
            <option key={rate} value={rate}>
              {rate}×
            </option>
          ))}
        </select>
        <label className="mini-player-sleep">
          <Moon size={14} />
          <select
            aria-label="定时停止"
            data-testid="player-sleep"
            value={session.sleepMinutes}
            onChange={(event) => audioSession.sleep(Number(event.target.value))}
          >
            <option value={0}>不定时</option>
            {SLEEP_MINUTES.map((minutes) => (
              <option key={minutes} value={minutes}>
                {minutes} 分钟
              </option>
            ))}
          </select>
          {session.sleepAt !== null && (
            <span data-testid="player-sleep-at">
              {new Date(session.sleepAt).toLocaleTimeString('zh-CN', {
                hour: '2-digit',
                minute: '2-digit',
              })}{' '}
              停止
            </span>
          )}
        </label>
        <Button
          variant="ghost"
          size="icon"
          aria-label={session.muted ? '取消静音' : '静音'}
          onClick={audioSession.toggleMute}
        >
          {session.muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
        </Button>
        <input
          type="range"
          aria-label="音量"
          min={0}
          max={1}
          step={0.01}
          value={session.volume}
          onChange={(event) => audioSession.setVolume(Number(event.target.value))}
        />
        <Button variant="ghost" size="icon" aria-label="关闭播放器" onClick={audioSession.close}>
          <X size={15} />
        </Button>
      </div>
    </div>
  );
}
