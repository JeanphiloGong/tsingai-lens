import { browser } from '$app/environment';
import { get, writable } from 'svelte/store';

export type ThemePreference = 'system' | 'light' | 'dark';
export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'retrieval.theme';

function getSystemTheme() {
  if (!browser) return 'light';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolveTheme(preference: ThemePreference): Theme {
  if (preference === 'system') {
    return getSystemTheme();
  }
  return preference;
}

function loadInitialPreference(): ThemePreference {
  if (!browser) return 'system';
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  return 'system';
}

export const themePreference = writable<ThemePreference>(loadInitialPreference());

function applyTheme(preference: ThemePreference) {
  if (!browser) return;
  const resolved = resolveTheme(preference);
  document.documentElement.dataset.theme = resolved;
}

if (browser) {
  themePreference.subscribe((value) => {
    localStorage.setItem(STORAGE_KEY, value);
    applyTheme(value);
  });

  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const handleChange = () => {
    if (get(themePreference) === 'system') {
      applyTheme('system');
    }
  };
  if (media.addEventListener) {
    media.addEventListener('change', handleChange);
  } else {
    media.addListener(handleChange);
  }
}
