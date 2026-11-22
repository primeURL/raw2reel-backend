/** Client-side plan timing, so edits show their effect before saving.
 * The server's validator (backend/app/services/plan_validate.py) stays the source of truth. */

import type { EditPlan, Shot } from './types';

const MAX_TAIL_S = 6;

export const shotLength = (s: Shot) => Math.max(0, (s.out_s - s.in_s) / (s.speed || 1));

export function timeline(plan: EditPlan) {
  let t = 0;
  const shots = plan.shots.map((s) => {
    const start = t;
    t += shotLength(s);
    return { start, end: t };
  });
  const footage = t;
  const lastEnd = Math.max(0, ...plan.overlays.map((o) => o.end_s));
  const tail = Math.min(MAX_TAIL_S, Math.max(0, lastEnd - footage));
  return { shots, footage, tail, total: footage + tail };
}

/** 0.5 s + 0.3 s per word, at least 1 s - the same rule the server warns on. */
export const readableSeconds = (text: string) => Math.max(1, 0.5 + 0.3 * text.trim().split(/\s+/).filter(Boolean).length);

export const round = (v: number, step = 0.1) => Math.round(v / step) * step;

export function fmt(s: number) {
  const m = Math.floor(s / 60);
  const r = s - m * 60;
  return m ? `${m}:${r.toFixed(1).padStart(4, '0')}` : `${r.toFixed(1)}s`;
}
