import { browser } from '$app/environment';
import { get, writable } from 'svelte/store';

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

function loadInitialBaseUrl() {
  if (!browser) return DEFAULT_BASE_URL;
  const stored = localStorage.getItem('retrieval.baseUrl');
  if (!stored) return DEFAULT_BASE_URL;
  try {
    return normalizeBaseUrl(stored);
  } catch {
    return DEFAULT_BASE_URL;
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
