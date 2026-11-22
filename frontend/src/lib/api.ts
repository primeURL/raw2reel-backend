/**
 * Small typed client for the Raw2Reel API. Every call sends the session's bearer token;
 * a 401 signs the user out (expired / revoked token).
 */

import { API_URL } from './config';
import type { AIUsage, Clip, ClipTicket, EditPlan, Me, Project, ProjectInput, ProjectSummary, Reference, Render, Style, UploadTicket } from './types';

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

type TokenGetter = () => string | null;
let getToken: TokenGetter = () => null;
let onUnauthorized: () => void = () => {};

/** The signed-in user's bearer token (for the few calls that don't go through request()). */
export const currentToken = () => getToken();

/** Wired once by the SessionProvider. */
export function configureApi(tokenGetter: TokenGetter, unauthorized: () => void) {
  getToken = tokenGetter;
  onUnauthorized = unauthorized;
}

function detailOf(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg); // FastAPI validation error
  }
  return fallback;
}

export async function request<T>(method: string, path: string, body?: unknown, token = getToken()): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, `Can't reach the server at ${API_URL}`);
  }
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401) onUnauthorized();
    throw new ApiError(res.status, detailOf(data, `Request failed (${res.status})`));
  }
  return data as T;
}

export const api = {
  health: () => request<{ status: string }>('GET', '/health', undefined, null),
  me: (token?: string) => request<Me>('GET', '/v1/me', undefined, token ?? getToken()),
  aiUsage: () => request<AIUsage>('GET', '/v1/me/ai-usage'),
  projects: () => request<ProjectSummary[]>('GET', '/v1/projects'),
  project: (id: string) => request<Project>('GET', `/v1/projects/${id}`),
  createProject: (input: ProjectInput) => request<Project>('POST', '/v1/projects', input),
  updateProject: (id: string, input: ProjectInput) => request<Project>('PATCH', `/v1/projects/${id}`, input),
  deleteProject: (id: string) => request<void>('DELETE', `/v1/projects/${id}`),
  clipUploadUrl: (projectId: string, filename: string, contentType: string, sizeBytes?: number) =>
    request<ClipTicket>('POST', `/v1/projects/${projectId}/clips/upload-url`, {
      filename, content_type: contentType, size_bytes: sizeBytes || null,
    }),
  completeClip: (projectId: string, clipId: string) => request<Clip>('POST', `/v1/projects/${projectId}/clips/${clipId}/complete`),
  deleteClip: (projectId: string, clipId: string) => request<void>('DELETE', `/v1/projects/${projectId}/clips/${clipId}`),
  reorderClips: (projectId: string, clipIds: string[]) => request<Clip[]>('PUT', `/v1/projects/${projectId}/clips/order`, { clip_ids: clipIds }),
  generatePlan: (projectId: string) => request<Project>('POST', `/v1/projects/${projectId}/plan`),
  /** Save the user's edits: checked and auto-fixed on the server, no AI call. */
  savePlan: (projectId: string, plan: EditPlan) => request<Project>('PUT', `/v1/projects/${projectId}/plan`, plan),
  render: (projectId: string, quality: 'preview' | 'final') => request<Render>('POST', `/v1/projects/${projectId}/render`, { quality }),
  renders: (projectId: string) => request<Render[]>('GET', `/v1/projects/${projectId}/renders`),
  deleteRender: (projectId: string, renderId: string) => request<void>('DELETE', `/v1/projects/${projectId}/renders/${renderId}`),
  styles: () => request<Style[]>('GET', '/v1/styles'),
  style: (id: string) => request<Style>('GET', `/v1/styles/${id}`),
  createStyle: (name: string) => request<Style>('POST', '/v1/styles', { name }),
  renameStyle: (id: string, name: string) => request<Style>('PATCH', `/v1/styles/${id}`, { name }),
  deleteStyle: (id: string) => request<void>('DELETE', `/v1/styles/${id}`),
  analyzeStyle: (id: string) => request<Style>('POST', `/v1/styles/${id}/analyze`),
  answerStyle: (id: string, answers: { question_id: string; answer: string }[], notes?: string) =>
    request<Style>('POST', `/v1/styles/${id}/answers`, { answers, notes: notes || null }),
  skipQuestions: (id: string) => request<Style>('POST', `/v1/styles/${id}/skip-questions`),

  references: (styleId: string) => request<Reference[]>('GET', `/v1/references?style_id=${styleId}`),
  importInstagram: (url: string, styleId: string) =>
    request<Reference>('POST', '/v1/references/instagram', { url, style_id: styleId }),
  referenceUploadUrl: (filename: string, contentType: string) =>
    request<UploadTicket>('POST', '/v1/references/upload-url', { kind: 'reference', filename, content_type: contentType }),
  completeReference: (id: string, styleId: string) =>
    request<Reference>('POST', `/v1/references/${id}/complete`, { style_id: styleId }),
  retryReference: (id: string) => request<Reference>('POST', `/v1/references/${id}/retry`),
  deleteReference: (id: string) => request<void>('DELETE', `/v1/references/${id}`),
};
