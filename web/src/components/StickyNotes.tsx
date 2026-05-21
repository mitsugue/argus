import React, { useEffect, useRef, useState } from 'react';
import { Rnd } from 'react-rnd';
import type { StickyNote } from '../types';
import { uid } from '../mock/data';
import './StickyNotes.css';

const STORAGE_KEY = 'argus:sticky:v1';

// Bump when the seed catalog or default positions change so users on
// older mobile-broken positions get the freshly-clamped layout.
const SEED_VERSION = 2;
const SEED_VERSION_KEY = 'argus:sticky:seed-version';

// Approximate iOS safe-area + HUD header height; positions notes below it.
const TOP_OFFSET = 130;
const SIDE_MARGIN = 12;

interface Viewport { w: number; h: number; mobile: boolean }

const viewport = (): Viewport => {
  if (typeof window === 'undefined') return { w: 1280, h: 800, mobile: false };
  const w = window.innerWidth;
  return { w, h: window.innerHeight, mobile: w < 700 };
};

// Constrain a note's geometry so the whole card (especially the drag handle)
// sits inside the visible viewport, irrespective of where it was created.
const clamp = (n: StickyNote, vp: Viewport): StickyNote => {
  const maxW = Math.min(n.width, vp.w - SIDE_MARGIN * 2);
  const maxH = Math.min(n.height, Math.max(110, vp.h - TOP_OFFSET - 40));
  const width = Math.max(140, maxW);
  const height = Math.max(100, maxH);
  const x = Math.max(SIDE_MARGIN, Math.min(n.x, vp.w - width - SIDE_MARGIN));
  const y = Math.max(TOP_OFFSET, Math.min(n.y, vp.h - height - 40));
  return { ...n, x, y, width, height };
};

const seed = (): StickyNote[] => {
  const vp = viewport();
  // On mobile, start with no demo notes — the news stream is the dominant
  // surface. The user can add memos via the + MEMO FAB when needed.
  if (vp.mobile) return [];
  const noteW = 220;
  const cyan: StickyNote = {
    id: uid('note'),
    x: SIDE_MARGIN,
    y: TOP_OFFSET,
    width: noteW,
    height: 120,
    text: '7203 — VWAP奪還を10:00で再確認\n短期: 2,950 抜けで追撃',
    z: 1,
    color: 'cyan',
  };
  const amber: StickyNote = {
    id: uid('note'),
    x: vp.mobile ? SIDE_MARGIN : 320,
    y: vp.mobile ? TOP_OFFSET + 140 : TOP_OFFSET + 130,
    width: noteW,
    height: 120,
    text: 'NVDA 決算ストラドル候補\n出来高 > 3x なら入る',
    z: 2,
    color: 'amber',
  };
  return [clamp(cyan, vp), clamp(amber, vp)];
};

const load = (): StickyNote[] => {
  try {
    const storedVersion = Number(localStorage.getItem(SEED_VERSION_KEY) || 0);
    if (storedVersion < SEED_VERSION) {
      // Older layout — start fresh so users with off-screen notes get fixed positions.
      localStorage.setItem(SEED_VERSION_KEY, String(SEED_VERSION));
      return seed();
    }
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return seed();
    const parsed = JSON.parse(raw) as StickyNote[];
    if (!Array.isArray(parsed) || !parsed.length) return seed();
    const vp = viewport();
    return parsed.map((n) => clamp(n, vp));
  } catch {
    return seed();
  }
};

const save = (notes: StickyNote[]) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notes));
  } catch {
    /* ignore */
  }
};

export const StickyNotes: React.FC = () => {
  const [notes, setNotes] = useState<StickyNote[]>(() => load());
  const topZ = useRef(1);

  useEffect(() => {
    topZ.current = Math.max(1, ...notes.map((n) => n.z));
  }, [notes]);

  useEffect(() => {
    save(notes);
  }, [notes]);

  // Re-clamp notes when the viewport changes (rotation, browser resize)
  useEffect(() => {
    const onResize = () => {
      const vp = viewport();
      setNotes((prev) => prev.map((n) => clamp(n, vp)));
    };
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, []);

  const update = (id: string, patch: Partial<StickyNote>) =>
    setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));

  const bringToFront = (id: string) => {
    topZ.current += 1;
    update(id, { z: topZ.current });
  };

  const remove = (id: string) => setNotes((prev) => prev.filter((n) => n.id !== id));

  const addNote = () => {
    topZ.current += 1;
    const vp = viewport();
    const noteW = vp.mobile ? Math.min(280, vp.w - SIDE_MARGIN * 2) : 220;
    const draft: StickyNote = {
      id: uid('note'),
      // Cluster around the FAB on mobile so notes always appear visibly;
      // some randomness on desktop so stacks don't sit perfectly aligned.
      x: vp.mobile ? SIDE_MARGIN : 120 + Math.random() * 120,
      y: vp.mobile ? TOP_OFFSET + 160 : 120 + Math.random() * 120,
      width: noteW,
      height: 120,
      text: '',
      z: topZ.current,
      color: Math.random() > 0.5 ? 'cyan' : 'amber',
    };
    setNotes((prev) => [...prev, clamp(draft, vp)]);
  };

  return (
    <>
      <button className="sticky-fab" onClick={addNote} aria-label="add note">
        <span>＋ MEMO</span>
      </button>

      <div className="sticky-layer">
        {notes.map((n) => (
          <Rnd
            key={n.id}
            size={{ width: n.width, height: n.height }}
            position={{ x: n.x, y: n.y }}
            minWidth={140}
            minHeight={90}
            bounds="window"
            dragHandleClassName="sticky__head"
            onDragStart={() => bringToFront(n.id)}
            onResizeStart={() => bringToFront(n.id)}
            onDragStop={(_, d) => update(n.id, { x: d.x, y: d.y })}
            onResizeStop={(_, __, ref, ___, pos) =>
              update(n.id, {
                width: ref.offsetWidth,
                height: ref.offsetHeight,
                x: pos.x,
                y: pos.y,
              })
            }
            style={{ zIndex: 30 + n.z }}
            className={`sticky sticky--${n.color}`}
          >
            <div className="sticky__head">
              <span className="sticky__tag">MEMO · {n.color.toUpperCase()}</span>
              <button
                className="sticky__btn"
                onClick={() => bringToFront(n.id)}
                title="bring to front"
              >
                ↑
              </button>
              <button
                className="sticky__btn sticky__btn--close"
                onClick={() => remove(n.id)}
                title="delete"
              >
                ×
              </button>
            </div>
            <textarea
              className="sticky__text"
              value={n.text}
              onChange={(e) => update(n.id, { text: e.target.value })}
              onFocus={() => bringToFront(n.id)}
              placeholder="メモを入力…"
              spellCheck={false}
            />
            <div className="sticky__corner" />
          </Rnd>
        ))}
      </div>
    </>
  );
};
