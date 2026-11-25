/** Where each sound effect plays - the same rules as the server (backend/app/services/sfx.py, cues()),
 * so the timeline can show the user exactly when they will hear something. */

import type { EditPlan, SoundName } from './types';

export interface SoundCue {
  at: number;
  name: string;
  icon: string;
  why: string;
}

const MIN_CAPTION_GAP_S = 1.5;

const PACK: Record<SoundName, Pick<SoundCue, 'name' | 'icon'>> = {
  whoosh_fast: { name: 'whoosh', icon: '💨' }, whoosh_soft: { name: 'soft whoosh', icon: '🌬️' }, boom: { name: 'boom', icon: '💥' },
  slam: { name: 'hit', icon: '🥁' }, shutter: { name: 'shutter', icon: '📸' }, tick: { name: 'tick', icon: '⏱️' }, pop: { name: 'pop', icon: '🫧' },
  riser: { name: 'riser', icon: '📈' }, ding: { name: 'ding', icon: '🔔' }, click: { name: 'click', icon: '🖱️' },
  swipe: { name: 'swipe', icon: '👉' }, glitch: { name: 'glitch', icon: '📺' }, cash: { name: 'cash', icon: '💰' },
};
// motion graphics: same table as the server (sfx.py MOTION_SOUND)
const MOTION_SOUND: Record<string, [SoundName, number]> = {
  chat: ['pop', 0.15], counter: ['whoosh_soft', 0.1], graph: ['whoosh_soft', 0.2], widgets: ['pop', 0.1], checklist: ['click', 0.5],
  progress: ['whoosh_soft', 0.3], location: ['slam', 0.4], name_card: ['swipe', 0], follow: ['click', -0.5], emoji_burst: ['pop', 0.1],
  poll: ['click', 0.15], timer: ['tick', 0], notification: ['ding', 0.1], price_tag: ['cash', 0.35],
};
const TRANSITION_NAME = { whip: 'Whip transition', zoom: 'Zoom transition', flash: 'Flash transition' } as const;

export function soundCues(plan: EditPlan, total: number): SoundCue[] {
  const mode = plan.sound_effects ?? 'subtle';
  if (mode === 'off') return [];
  if (plan.sounds?.length) {
    return plan.sounds.filter((c) => c.at_s >= 0 && c.at_s < total)
      .map((c) => ({ at: c.at_s, ...PACK[c.sound], why: c.why || 'the edit' }));
  }
  const out: SoundCue[] = [];
  let t = 0;
  for (const sh of plan.shots) {
    const kind = sh.transition_in ?? 'cut';
    if (kind !== 'cut' && t > 0) out.push({ at: t, ...PACK[kind === 'flash' ? 'slam' : 'whoosh_fast'], why: TRANSITION_NAME[kind] });
    t += Math.max(0, (sh.out_s - sh.in_s) / (sh.speed || 1));
  }
  for (const e of plan.effects ?? []) {
    const d = e.end_s - e.start_s;
    if (e.type === 'punch_in') out.push({ at: e.start_s + 0.06, name: 'whoosh', icon: '💨', why: 'Punch in' });
    else if (e.type === 'slow_push') out.push({ at: e.start_s + 0.2, name: 'soft whoosh', icon: '🌬️', why: 'Slow push' });
    else if (e.type === 'spotlight') out.push({ at: e.start_s + 0.1, name: 'boom', icon: '💥', why: 'Spotlight' });
    else if (e.type === 'freeze_frame') out.push({ at: e.start_s, name: 'shutter', icon: '📸', why: 'Freeze frame' });
    else if (e.type === 'flash') out.push({ at: e.start_s + d / 2, name: 'hit', icon: '🥁', why: 'Flash' });
    else if (e.type === 'backdrop_word') out.push({ at: e.start_s + 0.25, name: 'hit', icon: '🥁', why: 'Word behind you' });
    else if (e.type === 'countdown') for (let k = 0; k < 3; k++) out.push({ at: e.start_s + (k * d) / 3, name: 'tick', icon: '⏱️', why: 'Countdown' });
    else if (e.type in MOTION_SOUND) {
      const [snd, at] = MOTION_SOUND[e.type];
      out.push({ at: e.start_s + (at < 0 ? -at * d : at), ...PACK[snd], why: e.type.replace(/_/g, ' ') });
    }
  }
  if (mode === 'punchy') {
    let last = -9;
    for (const c of plan.captions) {
      if (c.start_s - last >= MIN_CAPTION_GAP_S) {
        out.push({ at: c.start_s, name: 'pop', icon: '🫧', why: 'Caption appears' });
        last = c.start_s;
      }
    }
  }
  return out.filter((c) => c.at >= 0 && c.at < total).sort((a, b) => a.at - b.at);
}
