import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getDemoSource } from './demo-source';
import type { DemoScenario, DemoSize, GameDetail, GameUpdate, LibraryFilters } from './types';

export interface LibraryOptions {
  size: DemoSize;
  scenario?: DemoScenario;
}

const demoRoot = ['library', 'demo'] as const;

export function useLibrary(filters: LibraryFilters, { size, scenario = 'normal' }: LibraryOptions) {
  return useQuery({
    queryKey: [...demoRoot, size, 'ordinary', scenario, filters],
    queryFn: ({ signal }) => getDemoSource(size).list({ filters, scenario, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
}

function detailKey(size: DemoSize, id: string, scenario: DemoScenario = 'normal') {
  return [...demoRoot, size, 'ordinary-detail', id, scenario] as const;
}

/** One record by stable ID; private and absent IDs fail identically. */
export function useGameDetail(id: string, { size, scenario = 'normal' }: LibraryOptions) {
  return useQuery({
    queryKey: detailKey(size, id, scenario),
    queryFn: ({ signal }) => getDemoSource(size).getGame({ id, scenario, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
}

/**
 * Writes one game's personal fields. Each caller owns its pending/error state, so a
 * failed note save does not mask a successful rating change.
 */
export function useUpdateGame(size: DemoSize, id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationKey: [...demoRoot, 'update', id],
    mutationFn: (update: GameUpdate) => getDemoSource(size).updateGame(id, update),
    onSuccess: (detail: GameDetail) => {
      queryClient.setQueryData(detailKey(size, id), detail);
      // Both scales share one store; list facets and other cached details may change.
      return queryClient.invalidateQueries({ queryKey: demoRoot });
    },
  });
}

/** Favorites persist with the other demo edits in this browser's demo storage. */
export function useToggleFavorite(size: DemoSize) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => getDemoSource(size).toggleFavorite(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: demoRoot }),
  });
}

export function useResetDemoEdits(size: DemoSize) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => getDemoSource(size).resetEdits(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: demoRoot }),
  });
}

export function getDemoEditCount(size: DemoSize): number {
  return getDemoSource(size).editedCount();
}
