import { get } from 'svelte/store';
import { getBaseUrlValue, validateBaseUrl } from './base';
import { language, translateKey } from './i18n';

export function errorMessage(error: unknown) {
  const message = error instanceof Error ? error.message : 'error.unexpected';
  if (message.startsWith('error.')) {
    return translateKey(get(language), message);
  }
  return message;
}

export function formatResult(data: unknown) {
  if (data === null || data === undefined) return '';
  return typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}

function parseMaybeJson(value: string) {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function buildUrl(path: string) {
  const base = validateBaseUrl(getBaseUrlValue());
  return `${base}${path}`;
}

export async function requestJson(path: string, init: RequestInit = {}) {
  const url = buildUrl(path);
  const headers = new Headers(init.headers ?? {});
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(url, { ...init, headers });
  const text = await response.text();
  const data = text ? parseMaybeJson(text) : null;

  if (!response.ok) {
    const detail = typeof data === 'string' ? data : JSON.stringify(data);
    throw new Error(`${response.status} ${response.statusText}${detail ? ` - ${detail}` : ''}`);
  }

  return data;
}

export async function requestText(path: string, init: RequestInit = {}) {
  const url = buildUrl(path);
  const response = await fetch(url, init);
  const text = await response.text();

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
  }

  return text;
}
