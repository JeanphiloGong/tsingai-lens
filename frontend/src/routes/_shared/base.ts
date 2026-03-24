import { browser } from '$app/environment';
import { get, writable } from 'svelte/store';

const SAME_ORIGIN_BASE_URL = 'same-origin';
const configuredApiBaseUrl =
  (import.meta.env.PUBLIC_API_BASE_URL as string | undefined) ??
  (import.meta.env.PUBLIC_API_BASE as string | undefined);

export const DEFAULT_BASE_URL = 'http://localhost:8010';

function normalizeBaseUrl(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error('error.baseUrlRequired');
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error('error.baseUrlInvalid');
  }

  return parsed.toString().replace(/\/$/, '');
}

function resolveConfiguredBaseUrl(value: string | undefined) {
  const trimmed = value?.trim() ?? '';
  if (!trimmed) return null;
  if (trimmed === SAME_ORIGIN_BASE_URL) {
    if (!browser) return DEFAULT_BASE_URL;
    return window.location.origin.replace(/\/$/, '');
  }
  return normalizeBaseUrl(trimmed);
}

export function getDefaultBaseUrl() {
  return resolveConfiguredBaseUrl(configuredApiBaseUrl) ?? DEFAULT_BASE_URL;
}

function loadInitialBaseUrl() {
  const fallback = getDefaultBaseUrl();
  if (!browser) return fallback;
  const stored = localStorage.getItem('retrieval.baseUrl');
  if (!stored) return fallback;
  try {
    return normalizeBaseUrl(stored);
  } catch {
    return fallback;
  }
}

export const baseUrl = writable(loadInitialBaseUrl());

if (browser) {
  baseUrl.subscribe((value) => {
    localStorage.setItem('retrieval.baseUrl', value);
  });
}

export function getBaseUrlValue() {
  return get(baseUrl);
}

export function validateBaseUrl(value: string) {
  return normalizeBaseUrl(value);
}
