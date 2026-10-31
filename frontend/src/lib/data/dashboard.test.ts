import { describe, expect, it } from 'vitest';
import { dashboardScopes, scopeLibraryFilters } from './dashboard';

describe('dashboard ranges', () => {
  it('maps every range onto the Library filters that list the same works', () => {
    expect(dashboardScopes.map(scopeLibraryFilters)).toEqual([
      {},
      { kind: 'game' },
      { platform: 'steam' },
      { platform: 'dlsite', kind: 'game' },
      { platform: 'dlsite', kind: 'non-game' },
    ]);
  });
});
