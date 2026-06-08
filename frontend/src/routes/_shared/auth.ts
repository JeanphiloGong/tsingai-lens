import { get, writable } from 'svelte/store';
import { isHttpStatusError, requestJson } from './api';

export type AuthUser = {
	user_id: string;
	email: string;
	display_name?: string | null;
};

type AuthSessionPayload = {
	user?: Partial<AuthUser> | null;
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

function normalizeUser(value: unknown): AuthUser | null {
	if (!value || typeof value !== 'object') return null;
	const record = value as Partial<AuthUser>;
	const userId = String(record.user_id ?? '').trim();
	const email = String(record.email ?? '').trim();
	if (!userId || !email) return null;
	return {
		user_id: userId,
		email,
		display_name: typeof record.display_name === 'string' ? record.display_name : null
	};
}

function setAuthenticated(payload: unknown) {
	const record = payload && typeof payload === 'object' ? (payload as AuthSessionPayload) : {};
	const user = normalizeUser(record.user);
	if (!user) {
		throw new Error('Auth response is missing user.');
	}
	authState.set({ status: 'authenticated', user });
	return user;
}

export async function fetchCurrentSession() {
	authState.set({ ...get(authState), status: 'loading' });
	try {
		const data = await requestJson('/auth/me', { method: 'GET' });
		return setAuthenticated(data);
	} catch (error) {
		if (isHttpStatusError(error, 401)) {
			authState.set(anonymousState);
			return null;
		}
		authState.set(anonymousState);
		throw error;
	}
}

export async function login(email: string, password: string) {
	const data = await requestJson('/auth/login', {
		method: 'POST',
		body: JSON.stringify({ email, password })
	});
	return setAuthenticated(data);
}

export async function logout() {
	await requestJson('/auth/logout', { method: 'POST' });
	authState.set(anonymousState);
}

export function clearAuthState() {
	authState.set(anonymousState);
}
