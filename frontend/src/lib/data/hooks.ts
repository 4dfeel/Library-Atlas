import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getDemoSource } from './demo-source';
import type { DemoScenario, DemoSize, LibraryFilters } from './types';

export interface LibraryOptions {
  size: DemoSize;
  scenario?: DemoScenario;
}

export function useLibrary(filters: LibraryFilters, { size, scenario = 'normal' }: LibraryOptions) {
  return useQuery({
    queryKey: ['library', 'demo', size, 'ordinary', scenario, filters],
    queryFn: ({ signal }) => getDemoSource(size).list({ filters, scenario, signal }),
    staleTime: 60_000,
    gcTime: 120_000,
    retry: false,
  });
}

/** Favorites are deliberately session-only in this isolated demo source. */
export function useToggleFavorite(size: DemoSize) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => getDemoSource(size).toggleFavorite(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['library', 'demo', size, 'ordinary'] }),
  });
}
