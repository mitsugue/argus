import React, { useEffect, useRef, useState } from 'react';
import { Rnd } from 'react-rnd';
import type { StickyNote } from '../types';
import { uid } from '../mock/data';
import './StickyNotes.css';

const STORAGE_KEY = 'argus:sticky:v1';

const seed = (): StickyNote[] => [
  {
    id: uid('note'),
    x: 80,
    y: 90,
    width: 220,
    height: 140,
    text: '7203 — VWAP奪還を10:00で再確認\n短期: 2,950 抜けで追撃',
    z: 1,
    color: 'cyan',
  },
  {
    id: uid('note'),
    x: 320,
    y: 220,
    width: 220,
    height: 140,
    text: 'NVDA 決算ストラドル候補\n出来高 > 3x なら入る',
    z: 2,
    color: 'amber',
  },
];

const load = (): StickyNote[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return seed();
    const parsed = JSON.parse(raw) as StickyNote[];
    return Array.isArray(parsed) && parsed.length ? parsed : seed();
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

  const update = (id: string, patch: Partial<StickyNote>) =>
    setNotes((prev) => prev.map((n) => (n.id === id ? { ...n, ...patch } : n)));

  const bringToFront = (id: string) => {
    topZ.current += 1;
    update(id, { z: topZ.current });
  };

  const remove = (id: string) => setNotes((prev) => prev.filter((n) => n.id !== id));

  const addNote = () => {
    topZ.current += 1;
    const n: StickyNote = {
      id: uid('note'),
      x: 120 + Math.random() * 120,
      y: 120 + Math.random() * 120,
      width: 220,
      height: 140,
      text: '',
      z: topZ.current,
      color: Math.random() > 0.5 ? 'cyan' : 'amber',
    };
    setNotes((prev) => [...prev, n]);
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
