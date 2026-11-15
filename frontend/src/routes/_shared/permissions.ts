import { get, writable } from 'svelte/store';
import { isApiErrorCode, requestJson } from './api';
import { authState, clearAuthState } from './authState';

type PermissionState = {
	status: 'loading' | 'ready' | 'unavailable';
	userId: string;
	codes: string[];
};

const empty: PermissionState = { status: 'loading', userId: '', codes: [] };
export const permissionState = writable<PermissionState>(empty);
let generation = 0;

export async function refreshPermissions() {
	const request = ++generation;
	const account = get(authState);
	const userId = account.status === 'authenticated' ? account.user?.user_id : '';
	permissionState.set({ ...empty, userId: userId || '' });
	if (!userId) return;
	try {
		const data: { permission_codes: string[] } = await requestJson('/user-api/v1/me/permissions');
		if (request === generation)
			permissionState.set({ status: 'ready', userId, codes: data.permission_codes });
	} catch (error) {
		if (request !== generation) return;
		if (isApiErrorCode(error, 200301)) clearAuthState();
		else permissionState.set({ status: 'unavailable', userId, codes: [] });
	}
}

// The application layout owns this subscription and stops it on teardown.
export function startPermissionSynchronization() {
	let subject = '';
	const unsubscribe = authState.subscribe((account) => {
		const next = account.status === 'authenticated' ? account.user?.user_id || '' : '';
		if (next === subject) return;
		subject = next;
		if (next) void refreshPermissions();
		else {
			generation++;
			permissionState.set(empty);
		}
	});
	return () => {
		unsubscribe();
		generation++;
		permissionState.set(empty);
	};
}
