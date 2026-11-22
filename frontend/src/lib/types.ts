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
  analysis_status: MediaStatus | null;
  contact_sheet_url: string | null;
  has_speech: boolean | null;
  transcript_text: string | null;
  spoken_language: string | null;
}

export interface Project extends ProjectSummary {
  script: string | null;
  stats: Record<string, string> | null;
  plan: EditPlan | null;
  plan_timeline: { total_s: number; footage_s: number; tail_hold_s: number; unused_clips?: string[] } | null;
  plan_warnings: string[];
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

export interface ProjectInput {
  title?: string;
  style_id?: string | null;
  script?: string | null;
  language?: Language | null;
  stats?: Record<string, string> | null;
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

export type EffectType = 'punch_in' | 'slow_push' | 'spotlight' | 'grade' | 'freeze_frame' | 'flash' | 'countdown';
export type Look = 'moody' | 'bw' | 'warm' | 'cool' | 'pop';

export interface Effect {
  type: EffectType;
  start_s: number; // on the final reel
  end_s: number;
  text?: string | null; // freeze_frame label
  look?: Look | null; // grade only
}

export interface EditPlan {
  title: string;
  summary: string;
  shots: Shot[];
  captions: Caption[];
  overlays: Overlay[];
  effects?: Effect[]; // missing on plans saved before effects existed
  music: { enabled: boolean; mood: string; volume: 'low_under_voice' | 'medium' | 'music_led' };
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
