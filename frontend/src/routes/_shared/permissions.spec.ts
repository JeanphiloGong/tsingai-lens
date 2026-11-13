import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { authState, clearAuthState } from './authState';
import { permissionState, refreshPermissions, startPermissionSynchronization } from './permissions';

const fetchMock = vi.fn();
let stop: () => void;
const user = { user_id: 'admin', email: 'admin@example.test' };
const response = (codes: string[] = [], status = 200) =>
	new Response(
		JSON.stringify(status === 200 ? { permission_codes: codes } : { code: 'identity_unavailable' }),
		{ status }
	);

beforeEach(() => {
	clearAuthState();
	fetchMock.mockReset();
	vi.stubGlobal('fetch', fetchMock);
	stop = startPermissionSynchronization();
});
afterEach(() => {
	stop();
	clearAuthState();
	vi.unstubAllGlobals();
});

it('does not request permissions before a subject is authenticated', async () => {
	await refreshPermissions();
	expect(fetchMock).not.toHaveBeenCalled();
	expect(get(permissionState).codes).toEqual([]);
});

it('loads effective permissions through the same-origin account API', async () => {
	fetchMock.mockResolvedValue(response(['users.manage']));
	authState.set({ status: 'authenticated', user });
	await vi.waitFor(() =>
		expect(get(permissionState)).toMatchObject({
			status: 'ready',
			userId: 'admin',
			codes: ['users.manage']
		})
	);
	expect(fetchMock).toHaveBeenCalledWith(
		'/user-api/v1/me/permissions',
		expect.objectContaining({ credentials: 'same-origin' })
	);
});

it('cannot restore an old subject grant after logout or switching accounts', async () => {
	let finish!: (value: Response) => void;
	fetchMock.mockImplementationOnce(
		() =>
			new Promise<Response>((resolve) => {
				finish = resolve;
			})
	);
	authState.set({ status: 'authenticated', user });
	clearAuthState();
	fetchMock.mockResolvedValueOnce(response([]));
	authState.set({
		status: 'authenticated',
		user: { user_id: 'ordinary', email: 'ordinary@example.test' }
	});
	await vi.waitFor(() => expect(get(permissionState).status).toBe('ready'));
	finish(response(['users.manage']));
	await Promise.resolve();
	await Promise.resolve();
	expect(get(permissionState)).toMatchObject({ userId: 'ordinary', codes: [] });
});

it('keeps the latest permission refresh when responses arrive out of order', async () => {
	let finish!: (value: Response) => void;
	fetchMock.mockResolvedValueOnce(response(['users.manage']));
	authState.set({ status: 'authenticated', user });
	await vi.waitFor(() => expect(get(permissionState).status).toBe('ready'));
	fetchMock.mockImplementationOnce(
		() =>
			new Promise<Response>((resolve) => {
				finish = resolve;
			})
	);
	const older = refreshPermissions();
	fetchMock.mockResolvedValueOnce(response([]));
	await refreshPermissions();
	finish(response(['users.manage']));
	await older;
	expect(get(permissionState).codes).toEqual([]);
});

it('distinguishes service failure from denial and can retry', async () => {
	fetchMock.mockResolvedValueOnce(response([], 503));
	authState.set({ status: 'authenticated', user });
	await vi.waitFor(() => expect(get(permissionState).status).toBe('unavailable'));
	expect(get(authState).status).toBe('authenticated');
	fetchMock.mockResolvedValueOnce(response([]));
	await refreshPermissions();
	expect(get(permissionState)).toMatchObject({ status: 'ready', codes: [] });
});

it('clears the authenticated subject when its permission request reports an expired session', async () => {
	fetchMock.mockResolvedValueOnce(response([], 401));
	authState.set({ status: 'authenticated', user });
	await vi.waitFor(() => expect(get(authState).status).toBe('anonymous'));
	expect(get(permissionState).codes).toEqual([]);
});
