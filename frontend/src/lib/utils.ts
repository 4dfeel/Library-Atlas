import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPlaytime(minutes: number | null) {
  if (minutes === null) return '暂无游玩数据';
  if (minutes === 0) return '尚未开始';
  if (minutes < 60) return `${minutes} 分钟`;
  return `${(minutes / 60).toLocaleString('zh-CN', { maximumFractionDigits: 1 })} 小时`;
}

export const statusLabels = {
  unplayed: '未开始',
  playing: '在玩',
  completed: '已完成',
  paused: '搁置',
};
