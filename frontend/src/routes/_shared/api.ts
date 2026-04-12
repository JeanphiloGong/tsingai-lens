import { get } from 'svelte/store';
import { API_PREFIX } from './base';
import { language, translateKey } from './i18n';

const ERROR_CODE_TRANSLATIONS = {
	collection_not_found: 'error.collectionNotFound',
	graph_not_ready: 'error.graphNotReady',
	community_not_found: 'error.communityNotFound'
} as const;

export class ApiError extends Error {
	status: number;
	statusText: string;
	detail: unknown;

	constructor(status: number, statusText: string, detail: unknown) {
		const detailText = stringifyDetail(detail);
		super(`${status} ${statusText}${detailText ? ` - ${detailText}` : ''}`);
		this.name = 'ApiError';
		this.status = status;
		this.statusText = statusText;
		this.detail = detail;
	}
}

function stringifyDetail(detail: unknown) {
	if (typeof detail === 'string') return detail;
	if (detail === null || detail === undefined) return '';
	return JSON.stringify(detail);
}

function normalizeDetail(detail: unknown) {
	return detail && typeof detail === 'object' && 'detail' in detail ? detail.detail : detail;
}

function readDetailCode(detail: unknown) {
	return detail && typeof detail === 'object' && 'code' in detail && typeof detail.code === 'string'
		? detail.code
		: null;
}

export function errorMessage(error: unknown) {
	const detailCode = getApiErrorCode(error);
	if (detailCode) {
		const key = ERROR_CODE_TRANSLATIONS[detailCode as keyof typeof ERROR_CODE_TRANSLATIONS];
		if (key) {
			return translateKey(get(language), key);
		}
	}

	const message = error instanceof Error ? error.message : 'error.unexpected';
	if (message.startsWith('error.')) {
		return translateKey(get(language), message);
	}
	return message;
}

export function isHttpStatusError(error: unknown, status: number) {
	if (error instanceof ApiError) {
		return error.status === status;
	}
	const message = error instanceof Error ? error.message : String(error ?? '');
	return message.startsWith(`${status} `);
}

export function getApiErrorDetail(error: unknown) {
	if (error instanceof ApiError) {
		return normalizeDetail(error.detail);
	}

	if (error instanceof Error) {
		const marker = ' - ';
		const index = error.message.indexOf(marker);
		if (index >= 0) {
			return normalizeDetail(parseMaybeJson(error.message.slice(index + marker.length)));
		}
	}

	return null;
}

export function getApiErrorCode(error: unknown) {
	return readDetailCode(getApiErrorDetail(error));
}

export function formatResult(data: unknown) {
	if (data === null || data === undefined) return '';
	return typeof data === 'string' ? data : JSON.stringify(data, null, 2);
}

function parseMaybeJson(value: string) {
	try {
		return JSON.parse(value);
	} catch {
		return value;
	}
}

function normalizePath(path: string) {
	return path.startsWith('/') ? path : `/${path}`;
}

function buildUrl(path: string) {
	const normalized = normalizePath(path);
	if (normalized.startsWith('/api/')) {
		return normalized;
	}
	return `${API_PREFIX}${normalized}`;
}

export function buildApiUrl(path: string) {
	return buildUrl(path);
}

function buildApiError(response: Response, detail: unknown) {
	return new ApiError(response.status, response.statusText, normalizeDetail(detail));
}

async function readResponseData(response: Response) {
	const text = await response.text();
	return text ? parseMaybeJson(text) : null;
}

export async function throwApiError(response: Response): Promise<never> {
	const detail = await readResponseData(response);
	throw buildApiError(response, detail);
}

export async function requestJson(path: string, init: RequestInit = {}) {
	const url = buildUrl(path);
	const headers = new Headers(init.headers ?? {});
	if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
		headers.set('Content-Type', 'application/json');
	}

	const response = await fetch(url, { ...init, headers });
	const data = await readResponseData(response);

	if (!response.ok) {
		throw buildApiError(response, data);
	}

	return data;
}

export async function requestText(path: string, init: RequestInit = {}) {
	const url = buildUrl(path);
	const response = await fetch(url, init);
	const text = await response.text();

	if (!response.ok) {
		throw buildApiError(response, text ? parseMaybeJson(text) : null);
	}

	return text;
}

export async function requestBlob(path: string, init: RequestInit = {}) {
	const url = buildUrl(path);
	const response = await fetch(url, init);

	if (!response.ok) {
		await throwApiError(response);
	}

	return response.blob();
}
