import { describe, expect, it } from 'vitest';
import { getCoverSource } from './covers';
import type { Game } from './types';

const game = {
  title: '</text><script>alert(1)</script>',
  subtitle: '合成样本',
  visibility: 'normal',
  cover: { kind: 'procedural', index: 3 },
} as Game;

describe('covers', () => {
  it('lays out a drawn cover from escaped text, never markup', () => {
    const source = getCoverSource(game)!;
    expect(source.startsWith('data:image/svg+xml')).toBe(true);
    const svg = decodeURIComponent(source);
    expect(svg).not.toContain('<script>');
    expect(svg).toContain('&lt;script&gt;');
  });

  it('gives no image for a missing cover or a work outside ordinary views', () => {
    expect(getCoverSource({ ...game, cover: { kind: 'missing', index: 0 } })).toBeNull();
    expect(getCoverSource({ ...game, visibility: 'private' })).toBeNull();
  });

  it('uses a platform image only through the address the service gave', () => {
    const remote = { kind: 'remote', index: 0, url: '/api/v1/works/x/cover' } as const;
    expect(getCoverSource({ ...game, cover: remote })).toBe('/api/v1/works/x/cover');
  });
});
