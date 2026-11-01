import { writable } from 'svelte/store';

export type AuthUser = { user_id: string; email: string; display_name?: string | null };
type AuthState = { status: 'loading' | 'authenticated' | 'anonymous'; user: AuthUser | null };
const anonymousState: AuthState = { status: 'anonymous', user: null };
export const authState = writable<AuthState>({ status: 'loading', user: null });
const authInvalidationKey = 'lens.authInvalidation';
let authGeneration = 0;
export function startAuthSynchronization() {
	const handleStorage = (event: StorageEvent) => {
		if (event.key === authInvalidationKey && event.newValue) invalidateAuth();
	};
	window.addEventListener('storage', handleStorage);
	return () => window.removeEventListener('storage', handleStorage);
}
export function nextAuthGeneration() {
	return ++authGeneration;
}
export function isCurrentAuthGeneration(generation: number) {
	return generation === authGeneration;
}
export function clearAuthState() {
	invalidateAuth();
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(
			authInvalidationKey,
			crypto.getRandomValues(new Uint32Array(4)).join('-')
		);
	} catch {
		// Local sign-out still works when browser storage is unavailable.
	}
}
export function invalidateAuth() {
	authGeneration += 1;
	clearOtherUsersChatStorage();
	authState.set(anonymousState);
}
export function clearOtherUsersChatStorage(keepUserId = '') {
	if (typeof window === 'undefined') return;
	const prefixes = [
		'lens.chatSession.',
		'lens.chatSessionHistory.',
		'lens.chatSourceContext.',
		'lens.goalSession.',
		'lens.goalSessionHistory.'
	];
	for (const storageName of ['localStorage', 'sessionStorage'] as const) {
		try {
			const storage = window[storageName];
			for (const key of Object.keys(storage)) {
				const prefix = prefixes.find((value) => key.startsWith(value));
				if (
					prefix &&
					(!keepUserId || !key.startsWith(`${prefix}${encodeURIComponent(keepUserId)}:`))
				)
					storage.removeItem(key);
			}
		} catch {
			// Browser storage restrictions must not prevent signing out.
		}
	}
}
