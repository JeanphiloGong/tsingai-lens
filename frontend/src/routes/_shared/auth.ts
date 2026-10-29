import { get, writable } from 'svelte/store';
import { isHttpStatusError, requestJson } from './api';

export type AuthUser = {
	user_id: string;
	email: string;
	display_name?: string | null;
};

type AuthSessionPayload = {
	user: AuthUser;
};

type AuthState = {
	status: 'loading' | 'authenticated' | 'anonymous';
	user: AuthUser | null;
};

const anonymousState: AuthState = {
	status: 'anonymous',
	user: null
};

export const authState = writable<AuthState>({
	status: 'loading',
	user: null
});

const authInvalidationKey = 'lens.authInvalidation';
let authGeneration = 0;
let logoutRequest: Promise<void> | null = null;

export function startAuthSynchronization() {
	const handleStorage = (event: StorageEvent) => {
		if (event.key === authInvalidationKey && event.newValue) invalidateAuth();
	};
	window.addEventListener('storage', handleStorage);
	return () => window.removeEventListener('storage', handleStorage);
}

function setAuthenticated(payload: unknown) {
	const record = payload as AuthSessionPayload;
	const user = record?.user;
	if (!user || typeof user.user_id !== 'string' || !user.user_id || typeof user.email !== 'string' || !user.email) {
		throw new Error('Auth response is missing user.');
	}
	clearOtherUsersChatStorage(user.user_id);
	authState.set({ status: 'authenticated', user });
	return user;
}

export async function fetchCurrentSession() {
	const generation = ++authGeneration;
	authState.set({ ...get(authState), status: 'loading' });
	try {
		const data = await requestJson('/auth/me', { method: 'GET' });
		if (generation !== authGeneration) return null;
		return setAuthenticated(data);
	} catch (error) {
		if (generation !== authGeneration) return null;
		if (isHttpStatusError(error, 401)) {
			clearAuthState();
			return null;
		}
		authState.set(anonymousState);
		throw error;
	}
}

export async function login(email: string, password: string) {
	const generation = ++authGeneration;
	// The earlier logout must finish clearing its cookie before login sets a new one.
	if (logoutRequest) await logoutRequest.catch(() => undefined);
	if (generation !== authGeneration) throw new Error('error.authSessionChanged');
	const data = await requestJson('/auth/login', {
		method: 'POST',
		body: JSON.stringify({ email, password })
	});
	if (generation !== authGeneration) throw new Error('error.authSessionChanged');
	return setAuthenticated(data);
}

export function logout() {
	if (logoutRequest) return logoutRequest;
	clearAuthState();
	logoutRequest = requestJson('/auth/logout', { method: 'POST' })
		.then(() => undefined)
		.finally(() => {
			logoutRequest = null;
		});
	return logoutRequest;
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

function invalidateAuth() {
	authGeneration += 1;
	clearOtherUsersChatStorage();
	authState.set(anonymousState);
}

function clearOtherUsersChatStorage(keepUserId = '') {
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
				) {
					storage.removeItem(key);
				}
			}
		} catch {
			// Browser storage restrictions must not prevent signing out.
		}
	}
}
