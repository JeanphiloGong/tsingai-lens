import { get } from 'svelte/store';
import { API_PREFIX } from './base';
import { clearAuthState } from './auth';
import { language, translateKey } from './i18n';

const ERROR_CODE_TRANSLATIONS = {
	invalid_credentials: 'auth.invalidCredentials',
	collection_not_found: 'error.collectionNotFound',
	graph_not_ready: 'error.graphNotReady',
	community_not_found: 'error.communityNotFound',
	chat_session_busy: 'error.chatSessionBusy',
	chat_session_has_branches: 'error.chatSessionHasBranches',
	upload_too_large: 'error.uploadTooLarge'
} as const;

type ApiResponse = {
	code: number;
	message: string;
	data: unknown;
	meta: Record<string, unknown> | null;
};

export class ApiError extends Error {
	constructor(
		public code: number,
		message: string,
		public data: unknown
	) {
		super(message);
		this.name = 'ApiError';
	}
}

export function errorMessage(error: unknown) {
	const reason = getApiErrorReason(error);
	if (reason) {
		const key = ERROR_CODE_TRANSLATIONS[reason as keyof typeof ERROR_CODE_TRANSLATIONS];
		if (key) return translateKey(get(language), key);
	}
	if (isApiErrorCode(error, 200000)) {
		return translateKey(get(language), 'error.requestFailed');
	}
	const message = error instanceof Error ? error.message : 'error.unexpected';
	return message.startsWith('error.') ? translateKey(get(language), message) : message;
}

export function isApiErrorCode(error: unknown, code: number) {
	return error instanceof ApiError && error.code === code;
}

export function getApiErrorData(error: unknown) {
	return error instanceof ApiError ? error.data : null;
}

export function getApiErrorReason(error: unknown) {
	const data = getApiErrorData(error);
	return data && typeof data === 'object' && 'code' in data && typeof data.code === 'string'
		? data.code
		: null;
}

export function formatResult(data: unknown) {
	if (data === null || data === undefined) return '';
	return typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}

export function buildApiUrl(path: string) {
	const normalized = path.startsWith('/') ? path : `/${path}`;
	return normalized.startsWith('/api/') ? normalized : `${API_PREFIX}${normalized}`;
}

function buildApiError(payload: ApiResponse) {
	const error = new ApiError(payload.code, payload.message, payload.data);
	if (error.code === 200301 && getApiErrorReason(error) === 'authentication_required') {
		clearAuthState();
		if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
			window.location.replace('/login');
		}
	}
	return error;
}

async function readApiResponse(response: Response): Promise<ApiResponse> {
	if (!response.ok) throw new Error('error.requestFailed');
	const payload: unknown = await response.json();
	if (
		!payload ||
		typeof payload !== 'object' ||
		!('code' in payload) ||
		typeof payload.code !== 'number' ||
		!('message' in payload) ||
		typeof payload.message !== 'string' ||
		!('data' in payload) ||
		!('meta' in payload)
	)
		throw new Error('error.requestFailed');
	return payload as ApiResponse;
}

async function readApiData(response: Response) {
	const payload = await readApiResponse(response);
	if (payload.code !== 200) throw buildApiError(payload);
	return payload.data;
}

export async function throwApiError(response: Response): Promise<never> {
	const payload = await readApiResponse(response);
	if (payload.code === 200) throw new Error('error.requestFailed');
	throw buildApiError(payload);
}

export async function requestJson(path: string, init: RequestInit = {}) {
	const headers = new Headers(init.headers ?? {});
	if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}
	const response = await fetch(buildApiUrl(path), { ...init, credentials: 'same-origin', headers });
	return readApiData(response);
}

export async function requestText(path: string, init: RequestInit = {}) {
	const response = await fetch(buildApiUrl(path), { ...init, credentials: 'same-origin' });
	if (!response.ok) throw new Error('error.requestFailed');
	if (response.headers.get('Content-Type')?.includes('application/json')) {
		const data = await readApiData(response);
		return typeof data === 'string' ? data : JSON.stringify(data);
	}
	return response.text();
}

export async function requestBlob(path: string, init: RequestInit = {}) {
	const headers = new Headers(init.headers ?? {});
	if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}
	const response = await fetch(buildApiUrl(path), { ...init, credentials: 'same-origin', headers });
	if (!response.ok) throw new Error('error.requestFailed');
	if (
		response.headers.get('Content-Type')?.includes('application/json') &&
		!response.headers.has('Content-Disposition')
	) {
		const data = await readApiData(response);
		return new Blob([JSON.stringify(data)], { type: 'application/json' });
	}
	return response.blob();
}

/** Download a same-origin response through the browser's file-save flow. */
export async function downloadBlob(path: string, filename: string, init: RequestInit = {}) {
	const blob = await requestBlob(path, init);
	const objectUrl = URL.createObjectURL(blob);
	try {
		const link = document.createElement('a');
		link.href = objectUrl;
		link.download = filename;
		link.rel = 'noopener';
		link.click();
	} finally {
		URL.revokeObjectURL(objectUrl);
	}
}
