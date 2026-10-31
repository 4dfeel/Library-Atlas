import { describe, expect, it } from 'vitest';
import { libraryUrl, parseLibraryUrl } from '@/features/library/library-url';
import { defaultLibraryFilters } from '@/lib/data';
import { gameHref, matchRoute } from './router';

describe('routes', () => {
  it('maps Library and stable game IDs, and rejects other paths', () => {
    expect(matchRoute('/')).toEqual({ name: 'dashboard' });
    expect(matchRoute('/library')).toEqual({ name: 'library' });
    expect(matchRoute('/library/')).toEqual({ name: 'library' });
    expect(matchRoute('/library/syn-00001')).toEqual({ name: 'game', id: 'syn-00001' });
    expect(matchRoute('/library/%E0%A4%A')).toEqual({ name: 'not-found' });
    expect(matchRoute('/library/a/b')).toEqual({ name: 'not-found' });
    expect(matchRoute('/dashboard')).toEqual({ name: 'not-found' });
    expect(gameHref('syn-00001')).toBe('/library/syn-00001');
  });
});

describe('Library URL state', () => {
  it('round-trips search, filters, sort and view while keeping other parameters', () => {
    const state = {
      filters: {
        ...defaultLibraryFilters,
        search: '星海',
        genre: '探索',
        status: 'playing' as const,
        installed: 'installed' as const,
        kind: 'audio' as const,
        platform: 'dlsite' as const,
        favoritesOnly: true,
        sort: 'playtime-desc' as const,
      },
      view: 'list' as const,
    };
    const url = libraryUrl('http://127.0.0.1/library?size=5000', state);
    expect(url).toContain('size=5000');
    expect(parseLibraryUrl(url.slice(url.indexOf('?')))).toEqual(state);
    expect(
      libraryUrl('http://127.0.0.1/library?q=old', {
        filters: defaultLibraryFilters,
        view: 'grid',
      }),
    ).toBe('/library');
  });

  it('falls back to defaults for unknown values', () => {
    expect(
      parseLibraryUrl(
        '?status=deleted&installed=maybe&kind=book&platform=gog&sort=random&view=table',
      ),
    ).toEqual({
      filters: defaultLibraryFilters,
      view: 'grid',
    });
  });
});
