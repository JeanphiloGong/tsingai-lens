import { get } from 'svelte/store';
import { isApiErrorCode, requestJson } from './api';
import {
	authState,
	clearAuthState,
	clearOtherUsersChatStorage,
	isCurrentAuthGeneration,
	nextAuthGeneration
} from './authState';
import type { AuthUser } from './authState';
type AuthSessionPayload = { user: AuthUser };
function setAuthenticated(payload: unknown) {
	const user = (payload as AuthSessionPayload)?.user;
	if (
		!user ||
		typeof user.user_id !== 'string' ||
		!user.user_id ||
		typeof user.email !== 'string' ||
		!user.email
	)
		throw new Error('Auth response is missing user.');
	clearOtherUsersChatStorage(user.user_id);
	authState.set({ status: 'authenticated', user });
	return user;
}
export async function fetchCurrentSession() {
	const generation = nextAuthGeneration();
	authState.set({ ...get(authState), status: 'loading' });
	try {
		const data = await requestJson('/auth/me', { method: 'GET' });
		if (!isCurrentAuthGeneration(generation)) return null;
		return setAuthenticated(data);
	} catch (error) {
		if (!isCurrentAuthGeneration(generation)) return null;
		if (isApiErrorCode(error, 200301)) {
			clearAuthState();
			return null;
		}
		authState.set({ status: 'anonymous', user: null });
		throw error;
	}
}
export async function login(email: string, password: string) {
	const generation = nextAuthGeneration();
	// The earlier logout must clear its cookie before login sets a new one.
	if (logoutRequest) await logoutRequest.catch(() => undefined);
	if (!isCurrentAuthGeneration(generation)) throw new Error('error.authSessionChanged');
	const data = await requestJson('/auth/login', {
		method: 'POST',
		body: JSON.stringify({ email, password })
	});
	if (!isCurrentAuthGeneration(generation)) throw new Error('error.authSessionChanged');
	return setAuthenticated(data);
}
let logoutRequest: Promise<void> | null = null;
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
