import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import type { Game, Platform, WorkKind } from '@/lib/data';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPlaytime(minutes: number | null) {
  if (minutes === null) return '暂无游玩数据';
  if (minutes === 0) return '尚未开始';
  if (minutes < 60) return `${minutes} 分钟`;
  return `${(minutes / 60).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 小时`;
}

const dateFormat = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'long' });

/** Local calendar date; `null` stays absent rather than becoming a fake date. */
export function formatDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : dateFormat.format(date);
}

const pad = (value: number) => String(value).padStart(2, '0');

/** Fixed-width date for table columns: 2026/10/31. */
export function formatCompactDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())}`;
}

export const statusLabels = {
  unplayed: '未开始',
  playing: '进行中',
  completed: '已完成',
  paused: '搁置',
};

export const kindLabels: Record<WorkKind, string> = {
  game: '游戏',
  image: '漫画/图像',
  video: '视频',
  audio: '音声',
  other: '其他',
};

export const platformLabels: Record<Platform, string> = { steam: 'Steam', dlsite: 'DLsite' };

/**
 * Steam games are installed; DLsite works (games included) are downloaded. A demo
 * download never makes a DLsite game "installed" or launchable.
 */
export function availabilityLabel(game: Pick<Game, 'platform' | 'installed'>): string {
  if (game.installed === null) return '本机状态未知';
  if (game.platform === 'steam') return game.installed ? '已安装' : '未安装';
  return game.installed ? '已下载' : '未下载';
}

/** Primary local action per kind. None is wired up yet in the demo. */
export const openActionLabels: Record<WorkKind, string> = {
  game: '启动游戏',
  image: '浏览作品',
  video: '播放作品',
  audio: '播放作品',
  other: '打开文件夹',
};

/** Card/list secondary line: play time for Steam games, otherwise kind and platform. */
export function workMeta(game: Pick<Game, 'kind' | 'platform' | 'playtimeMinutes'>): string {
  if (game.platform === 'steam' && game.kind === 'game')
    return formatPlaytime(game.playtimeMinutes);
  return `${kindLabels[game.kind]} · ${platformLabels[game.platform]}`;
}

/** Binary units; callers render `null` as 大小未知, never 0 B. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(0)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

/** Verb for the last-use record; games are played, other works read/watched/heard. */
export const usageVerbs: Record<WorkKind, string> = {
  game: '游玩',
  image: '阅读',
  video: '观看',
  audio: '收听',
  other: '打开',
};

const shortDate = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric' });
export function formatShortDate(iso: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : shortDate.format(date);
}
