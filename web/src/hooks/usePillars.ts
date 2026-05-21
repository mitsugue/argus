import { useCallback, useEffect, useState } from 'react';
import type { GlobePillar } from '../types';
import { INITIAL_PILLARS, mutatePillars } from '../mock/data';

export interface PillarStore {
  pillars: GlobePillar[];
  selectedId: string | null;
  selected: GlobePillar | null;
  select: (id: string | null) => void;
}

export function usePillars(): PillarStore {
  const [pillars, setPillars] = useState<GlobePillar[]>(INITIAL_PILLARS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    const t = setInterval(() => setPillars((prev) => mutatePillars(prev)), 1800);
    return () => clearInterval(t);
  }, []);

  const select = useCallback((id: string | null) => setSelectedId(id), []);
  const selected = pillars.find((p) => p.id === selectedId) ?? null;

  return { pillars, selectedId, selected, select };
}
