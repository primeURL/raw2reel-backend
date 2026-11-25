/** Shapes returned by the Raw2Reel API (backend/app/schemas.py). Keep in sync. */

export type MediaStatus = 'pending' | 'downloading' | 'processing' | 'ready' | 'failed';
export type ProjectStatus = 'draft' | 'analyzing' | 'planned' | 'rendering' | 'done' | 'failed';
export type StyleStatus = 'draft' | 'analyzing' | 'needs_answers' | 'ready' | 'failed';

export interface Me {
  id: string;
  email: string | null;
  name: string | null;
  photo_url: string | null;
  created_at: string;
}

/** Creator memory: something the editor learnt from a change request (or the creator typed in). */
export interface Lesson {
  id: string;
  text: string;
  applies_to: string; // "all" or a kind of reel, e.g. "workout"
  rule: string | null; // a switch the app enforces itself, e.g. "no_sound:pop"
  active: boolean;
  project_id: string | null;
  request: string | null; // the creator's words it came from
  created_at: string;
}

export interface AIUsage {
  calls_last_24h: number;
  daily_limit: number;
  all_time: Record<string, { calls: number; estimated_usd: number }>;
  all_time_usd: number;
}

export interface ProjectSummary {
  id: string;
  title: string;
  style_id: string | null;
  status: ProjectStatus;
  language: string | null;
  created_at: string;
  updated_at: string;
  clip_count: number;
  total_duration_s: number;
  cover_url: string | null;
  analysis_ready: boolean;
}

export interface StyleQuestion {
  id: string;
  question: string;
  options: string[];
  why: string;
}

export interface Style {
  id: string;
  name: string;
  status: StyleStatus;
  profile: StyleProfile | null;
  questions: StyleQuestion[] | null;
  answers: { question_id: string; answer: string }[] | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  reference_notes: string[] | null;
  reference_count: number;
  references_ready: number;
  template?: string | null;
}

export interface Reference {
  id: string;
  style_id: string | null;
  source: 'upload' | 'instagram';
  source_url: string | null;
  shortcode: string | null;
  status: MediaStatus;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  error: string | null;
  created_at: string;
  download_url: string | null;
  analysis_status: MediaStatus | null;
  contact_sheet_url: string | null;
  pacing: { shot_count: number; avg_shot_s: number | null; cuts_per_10s: number | null } | null;
  transcript_text: string | null;
}

export interface UploadTicket {
  upload_url: string;
  key: string;
  reference_id: string;
  headers: Record<string, string>;
  expires_in: number;
}

/** The parts of the style profile the app shows (full shape: backend/app/services/style_schema.py). */
export interface StyleProfile {
  name: string;
  summary: string;
  pacing?: { reel_type?: string; target_length_s?: number[]; shot_length_s?: number[]; notes?: string };
  captions?: { mode?: string; size?: string; position?: string; animation?: string; language_script?: string };
  hook?: { style?: string; notes?: string };
  look?: { grade?: string; accent_color?: string; zooms?: string; transitions?: string; overlays?: string[] };
  sound?: { music?: string; music_mood?: string };
  ending?: { style?: string; cta_examples?: string[] };
  do?: string[];
  dont?: string[];
}

export type Language = 'en' | 'hi' | 'hinglish';

export interface Clip {
  id: string;
  position: number;
  original_filename: string | null;
  status: MediaStatus;
  duration_s: number | null;
  width: number | null;
  height: number | null;
  rotation: number | null;
  fps: number | null;
  has_audio: boolean | null;
  error: string | null;
  created_at: string;
  thumbnail_url: string | null;
  download_url: string | null;
  preview_url?: string | null; // upright H.264 copy the editor plays
  analysis_status: MediaStatus | null;
  contact_sheet_url: string | null;
  has_speech: boolean | null;
  transcript_text: string | null;
  spoken_language: string | null;
}

export interface Project extends ProjectSummary {
  script: string | null;
  stats: Record<string, string> | null;
  prefs?: Prefs | null;
  plan: EditPlan | null;
  plan_timeline: { total_s: number; footage_s: number; tail_hold_s: number; unused_clips?: string[] } | null;
  plan_warnings: string[];
  plan_request?: string | null; // what the creator asked for, when the edit is a revision
  plan_changes?: string[]; // what the AI changed for it
  plan_lesson?: { id: string; text: string; applies_to: string } | null; // what the editor learnt from it
  plan_kept_lessons?: string[]; // earlier lessons the app applied to this edit
  clip_aliases: Record<string, string>;
  error: string | null;
  clips: Clip[];
}

export interface ClipTicket {
  clip_id: string;
  upload_url: string;
  key: string;
  headers: Record<string, string>;
  expires_in: number;
}

/** The creator's own choices for one reel; null/missing = follow the style. */
export interface CaptionPrefs {
  enabled?: boolean | null;
  animation?: 'none' | 'fade' | 'pop' | 'slide_up' | 'typewriter' | 'karaoke' | null;
  look?: string | null;
  size?: 'small' | 'medium' | 'large' | null;
  position?: 'upper_third' | 'middle' | 'lower_middle' | null;
  highlight?: boolean | null;
  case?: 'sentence' | 'upper' | null;
}

export type MusicVolume = 'low_under_voice' | 'medium' | 'music_led';

export interface MusicPrefs {
  enabled?: boolean | null;
  track?: string | null;
  volume?: MusicVolume | null;
}

export interface Prefs {
  captions: CaptionPrefs;
  music?: MusicPrefs;
  sound_effects?: 'off' | 'subtle' | 'punchy' | null;
  transitions?: 'cuts' | 'smooth' | 'energetic' | null;
  effects?: 'none' | 'few' | 'lots' | null;
}

export interface ProjectInput {
  title?: string;
  style_id?: string | null;
  script?: string | null;
  language?: Language | null;
  stats?: Record<string, string> | null;
  prefs?: Prefs | null;
}

/** Edit plan - mirrors backend/app/services/plan_schema.py. Shot times are inside the clip;
 * caption/overlay times are on the final reel. */
export type CaptionPosition = 'upper_third' | 'middle' | 'lower_middle';

export interface Shot {
  clip: string; // alias C1, C2...
  in_s: number;
  out_s: number;
  speed: number;
  zoom_from: number;
  zoom_to: number;
  focus_x: number;
  focus_y: number;
  keep_audio: boolean;
  purpose: string;
  transition_in?: Transition; // how it comes in from the previous part; missing = cut
}

export type Transition = 'cut' | 'whip' | 'zoom' | 'flash';
export type SoundName = 'whoosh_fast' | 'whoosh_soft' | 'boom' | 'slam' | 'shutter' | 'tick' | 'pop'
  | 'riser' | 'ding' | 'click' | 'swipe' | 'glitch' | 'cash';

export interface SoundCue {
  at_s: number; // on the final reel
  sound: SoundName;
  level: 'soft' | 'normal' | 'loud';
  why: string;
}

export interface StoryBeat {
  beat: string;
  clips: string[];
}

export interface Caption {
  text: string;
  start_s: number;
  end_s: number;
  position: CaptionPosition;
  highlight: string | null;
}

export interface Overlay {
  type: 'stats_card' | 'title';
  start_s: number;
  end_s: number;
  title: string | null;
  items: { label: string; value: string }[];
}

export type MotionType = 'chat' | 'counter' | 'graph' | 'widgets' | 'checklist' | 'progress' | 'location' | 'name_card'
  | 'follow' | 'emoji_burst' | 'poll' | 'timer' | 'notification' | 'price_tag';
export type EffectType = 'punch_in' | 'slow_push' | 'spotlight' | 'grade' | 'freeze_frame' | 'flash' | 'countdown' | 'backdrop_word'
  | MotionType;
export type Look = 'moody' | 'bw' | 'warm' | 'cool' | 'pop';

export interface Effect {
  type: EffectType;
  start_s: number; // on the final reel
  end_s: number;
  text?: string | null; // freeze_frame label / backdrop_word word / a motion graphic's title
  look?: Look | null; // grade only
  // motion graphics only
  items?: string[];
  numbers?: number[];
  unit?: string | null;
  position?: 'top' | 'middle' | 'bottom' | null;
  behind?: boolean;
  ticks_s?: number[]; // set by the server: when each rep finishes (counter)
}

export interface MotionEffectInfo {
  type: MotionType;
  name: string;
  help: string;
  sample: { text?: string; items?: string[]; numbers?: number[]; unit?: string };
  position: 'top' | 'middle' | 'bottom';
  preview_url: string;
}

export interface EditPlan {
  title: string;
  summary: string;
  shots: Shot[];
  captions: Caption[];
  overlays: Overlay[];
  effects?: Effect[]; // missing on plans saved before effects existed
  sound_effects?: 'off' | 'subtle' | 'punchy'; // sounds under the effects; server default 'subtle'
  sounds?: SoundCue[]; // the editor's sound design; empty = sounds follow the effects (older plans)
  story?: StoryBeat[]; // the story in order and which clips show each step
  music: { enabled: boolean; mood: string; volume: MusicVolume; track?: string | null };
  end_fade_s: number;
}

export interface Render {
  id: string;
  version: number;
  quality: 'preview' | 'final';
  status: MediaStatus;
  duration_s: number | null;
  size_bytes: number | null;
  seconds_taken: number | null;
  progress: number | null; // 0..1 while rendering
  stage: string | null; // e.g. "Cutting shot 3 of 6"
  error: string | null;
  created_at: string;
  video_url: string | null;
  thumbnail_url: string | null;
  checks?: { name: string; ok: boolean; detail: string }[] | null; // quality checks of the finished reel
  notes?: string[] | null; // what the renderer fixed on its own
}

export interface MusicTrack {
  id: string;
  title: string;
  moods: string[];
  energy: 'calm' | 'medium' | 'high' | null;
  bpm: number | null;
  duration_s: number | null;
  preview_url: string | null;
}

export interface MusicLibrary {
  moods: { id: string; help: string }[];
  tracks: MusicTrack[];
}

export interface CaptionLook {
  id: string;
  name: string;
  group: string;
  animation: string | null;
  preview_url: string;
}

export interface CaptionLooks {
  groups: { id: string; name: string }[];
  looks: CaptionLook[];
}

export interface Template {
  id: string;
  name: string;
  emoji: string;
  tagline: string;
  summary: string;
  caption_look: string;
  music_mood: string;
  cover_url: string;
}
