import { describe, expect, it } from 'vitest';
import { formatPlayTime } from './play-time';

describe('formatPlayTime', () => {
  it('says short times plainly', () => {
    expect(formatPlayTime(0)).toBe('不足 1 分钟');
    expect(formatPlayTime(59)).toBe('不足 1 分钟');
    expect(formatPlayTime(60)).toBe('1 分钟');
    expect(formatPlayTime(3599)).toBe('59 分钟');
  });

  it('moves to hours with one decimal', () => {
    expect(formatPlayTime(3600)).toBe('1 小时');
    expect(formatPlayTime(5400)).toBe('1.5 小时');
    expect(formatPlayTime(36000)).toBe('10 小时');
  });
});
