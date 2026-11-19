<script lang="ts">
	import { beforeNavigate, goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { onDestroy, tick } from 'svelte';
	import PermissionGate from '../../_shared/PermissionGate.svelte';
	import { authState } from '../../_shared/authState';
	import { permissionState, refreshPermissions } from '../../_shared/permissions';
	import { ApiError, errorMessage, getApiErrorReason, requestJson } from '../../_shared/api';
	import { t } from '../../_shared/i18n';
	import { fetchModelConnections } from '../../_shared/chatSessions';
	import {
		configurationChanges,
		type ConnectionPage,
		type ModelConnection,
		type ModelDraft,
		type ProbeResult
	} from './modelConnections';

	const endpoint = '/api/v1/admin/model-connections';
	let subject = '';
	let generation = 0;
	let loadedURL: string | null = null;
	let controller = new AbortController();
	let operation = new AbortController();
	let items: ModelConnection[] = [];
	let total = 0;
	let defaultID = '';
	let offset = 0;
	let selected = '';
	let saved: ModelConnection | null = null;
	let draft: ModelDraft = emptyDraft();
	let initialDraft = JSON.stringify(draft);
	let clearKey = false;
	let loading = false;
	let readFailed = false;
	let busy = false;
	let error = '';
	let notice = '';
	let probe: ProbeResult | null = null;
	let editorHeading: HTMLHeadingElement | undefined;

	function emptyDraft(): ModelDraft {
		return {
			display_name: '',
			base_url: '',
			model: '',
			kind: 'chat',
			enabled: false,
			priority: 0,
			context_window_tokens: null,
			max_output_tokens: null,
			request_timeout_seconds: null,
			api_key: ''
		};
	}
	$: allowed =
		$authState.status === 'authenticated' &&
		$permissionState.status === 'ready' &&
		$permissionState.userId === $authState.user?.user_id &&
		$permissionState.codes.includes('models.manage');
	$: account = allowed ? $authState.user?.user_id || '' : '';
	$: if (account !== subject) {
		subject = account;
		generation++;
		controller.abort();
		operation.abort();
		items = [];
		defaultID = '';
		total = 0;
		saved = null;
		selected = '';
		draft = emptyDraft();
		clearKey = false;
		probe = null;
		busy = false;
		error = '';
		notice = '';
		loadedURL = null;
	}
	$: if (subject && loadedURL !== $page.url.search) {
		loadedURL = $page.url.search;
		void load();
	}
	$: if (draft.api_key !== '') clearKey = false;
	$: dirty = Boolean(selected) && (JSON.stringify(draft) !== initialDraft || clearKey);

	beforeNavigate(({ to, cancel }) => {
		if (dirty && to?.url.href !== $page.url.href && !window.confirm($t('modelAdmin.unsaved')))
			cancel();
	});
	onDestroy(() => {
		generation++;
		controller.abort();
		operation.abort();
		draft.api_key = '';
		clearKey = false;
		probe = null;
	});

	function showError(caught: unknown) {
		error = caught instanceof ApiError ? errorMessage(caught) : $t('modelAdmin.unknownResult');
		if (getApiErrorReason(caught) === 'permission_denied') void refreshPermissions();
	}
	function editSaved(value: ModelConnection) {
		saved = value;
		draft = {
			display_name: value.display_name,
			base_url: value.base_url,
			model: value.model,
			kind: value.kind,
			enabled: value.enabled,
			priority: value.priority,
			context_window_tokens: value.context_window_tokens,
			max_output_tokens: value.max_output_tokens,
			request_timeout_seconds: value.request_timeout_seconds,
			api_key: ''
		};
		initialDraft = JSON.stringify(draft);
		clearKey = false;
		probe = null;
	}
	async function load() {
		if (!subject) return;
		const request = ++generation;
		controller.abort();
		controller = new AbortController();
		operation.abort();
		operation = new AbortController();
		loading = true;
		readFailed = false;
		busy = false;
		error = '';
		notice = '';
		probe = null;
		saved = null;
		draft = emptyDraft();
		initialDraft = JSON.stringify(draft);
		clearKey = false;
		const suppliedOffset = Number($page.url.searchParams.get('offset') || 0);
		offset = Number.isSafeInteger(suppliedOffset) && suppliedOffset >= 0 ? suppliedOffset : 0;
		selected = $page.url.searchParams.get('connection_id') || '';
		try {
			const [list, detail, directory] = await Promise.all([
				requestJson(`${endpoint}?limit=50&offset=${offset}`, {
					signal: controller.signal
				}) as Promise<ConnectionPage>,
				selected && selected !== 'new'
					? (requestJson(`${endpoint}/${encodeURIComponent(selected)}`, {
							signal: controller.signal
						}) as Promise<ModelConnection>)
					: Promise.resolve(null),
				fetchModelConnections(controller.signal)
			]);
			if (request !== generation) return;
			items = list.items;
			defaultID = directory.items[0]?.connection_id || '';
			total = list.total;
			if (detail) editSaved(detail);
		} catch (caught) {
			if (request === generation && !controller.signal.aborted) {
				readFailed = true;
				showError(caught);
			}
		} finally {
			if (request === generation) loading = false;
		}
	}
	async function navigate(id: string, nextOffset = offset) {
		const query = new URLSearchParams({ offset: String(nextOffset) });
		if (id) query.set('connection_id', id);
		await goto(`?${query}`, { keepFocus: true, noScroll: true });
		await tick();
		editorHeading?.focus();
	}
	async function save() {
		if (busy || loading || !subject) return;
		const request = generation;
		busy = true;
		error = '';
		notice = '';
		probe = null;
		const creating = !saved;
		const payload = saved
			? configurationChanges(saved, draft, clearKey)
			: {
					display_name: draft.display_name,
					base_url: draft.base_url,
					model: draft.model,
					kind: draft.kind,
					priority: draft.priority,
					context_window_tokens: draft.context_window_tokens ?? null,
					max_output_tokens: draft.max_output_tokens ?? null,
					request_timeout_seconds: draft.request_timeout_seconds ?? null,
					...(draft.api_key === '' ? {} : { api_key: draft.api_key })
				};
		if (!creating && Object.keys(payload).length === 1) {
			busy = false;
			return;
		}
		try {
			const result: ModelConnection = await requestJson(
				saved ? `${endpoint}/${encodeURIComponent(saved.connection_id)}` : endpoint,
				{
					method: creating ? 'POST' : 'PATCH',
					body: JSON.stringify(payload),
					signal: operation.signal
				}
			);
			if (request !== generation) return;
			editSaved(result);
			notice = $t('modelAdmin.saved');
			const [list, directory] = await Promise.all([
				requestJson(`${endpoint}?limit=50&offset=${offset}`, {
					signal: controller.signal
				}) as Promise<ConnectionPage>,
				fetchModelConnections(controller.signal)
			]);
			if (request !== generation) return;
			items = list.items;
			defaultID = directory.items[0]?.connection_id || '';
			total = list.total;
			if (creating) await navigate(result.connection_id);
		} catch (caught) {
			if (request === generation && !operation.signal.aborted) showError(caught);
		} finally {
			if (request === generation) {
				draft.api_key = '';
				clearKey = false;
				busy = false;
				await tick();
				editorHeading?.focus();
			}
		}
	}
	async function testConnection() {
		if (!saved || dirty || busy || loading || !subject) return;
		const request = generation,
			version = saved.version,
			identity = saved.connection_id;
		if (!window.confirm($t('modelAdmin.confirmProbe'))) return;
		busy = true;
		error = '';
		probe = null;
		try {
			const result: ProbeResult = await requestJson(
				`${endpoint}/${encodeURIComponent(identity)}/test`,
				{
					method: 'POST',
					body: JSON.stringify({ expected_version: version }),
					signal: operation.signal
				}
			);
			if (
				request === generation &&
				saved?.version === result.tested_version &&
				saved?.connection_id === result.connection_id
			)
				probe = result;
		} catch (caught) {
			if (request === generation && !operation.signal.aborted) showError(caught);
		} finally {
			if (request === generation) busy = false;
		}
	}
	function chooseClear() {
		if (!window.confirm($t('modelAdmin.confirmClear'))) return;
		draft.api_key = '';
		clearKey = true;
		probe = null;
	}
</script>

<svelte:head><title>{$t('modelAdmin.title')} · Lens</title></svelte:head>
<h1>{$t('modelAdmin.title')}</h1>
<PermissionGate code="models.manage">
	<div class="toolbar model-actions">
		<button type="button" class="btn btn--primary" on:click={() => navigate('new')} disabled={busy}
			>{$t('modelAdmin.create')}</button
		>
		<button type="button" class="btn btn--ghost" on:click={load} disabled={busy || dirty}
			>{$t('admin.refresh')}</button
		>
		<button
			type="button"
			class="btn btn--ghost"
			on:click={() => navigate('', Math.max(0, offset - 50))}
			disabled={busy || offset === 0}>{$t('admin.previousEntries')}</button
		>
		<button
			type="button"
			class="btn btn--ghost"
			on:click={() => navigate('', offset + 50)}
			disabled={busy || offset + 50 >= total}>{$t('admin.nextEntries')}</button
		>
		<span>{$t('admin.total')}: {total}</span>
	</div>
	{#if error}<div class="status status--error" role="alert">
			<p>{error}</p>
			<button type="button" class="btn btn--ghost" on:click={load} disabled={busy}
				>{$t('modelAdmin.reload')}</button
			>
		</div>{/if}
	{#if notice}<p class="status" role="status">{notice}</p>{/if}
	{#if loading}<p role="status">{$t('admin.loading')}</p>{/if}
	<!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll the named model table.) -->
	<div
		class="admin-table-wrap model-list"
		role="region"
		aria-label={$t('modelAdmin.title')}
		tabindex="0"
	>
		<table aria-busy={loading}>
			<thead
				><tr
					><th>{$t('admin.name')}</th><th>{$t('modelAdmin.model')}</th><th>{$t('admin.status')}</th
					><th>{$t('modelAdmin.keyStatus')}</th><th>{$t('modelAdmin.priority')}</th></tr
				></thead
			>
			<tbody
				>{#each items as item (item.connection_id)}<tr
						class:selected={selected === item.connection_id}
					>
						<td
							><button
								type="button"
								class="btn btn--ghost"
								on:click={() => navigate(item.connection_id)}
								disabled={busy || loading}>{item.display_name}</button
							></td
						>
						<td class="model-long-value">{item.model}</td><td
							>{item.enabled ? $t('modelAdmin.enabled') : $t('modelAdmin.disabled')}
							{#if item.connection_id === defaultID}<span class="model-default"
									>{$t('modelAdmin.default')}</span
								>{/if}</td
						>
						<td
							>{item.api_key_configured
								? $t('modelAdmin.configured')
								: $t('modelAdmin.notConfigured')}</td
						><td>{item.priority}</td>
					</tr>{/each}</tbody
			>
		</table>
	</div>
	{#if !loading && !error && !items.length}<p role="status">{$t('modelAdmin.empty')}</p>{/if}
	{#if selected && !loading && !readFailed}
		<section class="model-editor" aria-labelledby="model-editor-heading">
			<h2 id="model-editor-heading" bind:this={editorHeading} tabindex="-1">
				{saved ? saved.display_name : $t('modelAdmin.create')}
			</h2>
			<form class="admin-form model-form" on:submit|preventDefault={save}>
				<label>
					{$t('modelAdmin.kind')}
					<select class="input" bind:value={draft.kind} disabled={busy || Boolean(saved)}>
						<option value="chat">{$t('modelAdmin.chatKind')}</option>
						<option value="embedding">{$t('modelAdmin.embeddingKind')}</option>
					</select>
				</label>
				<label
					>{$t('admin.name')}<input
						class="input"
						bind:value={draft.display_name}
						maxlength="100"
						required
						disabled={busy}
					/></label
				>
				<label
					>{$t('modelAdmin.baseURL')}<input
						class="input"
						type="url"
						bind:value={draft.base_url}
						maxlength="2048"
						required
						disabled={busy || Boolean(saved)}
					/></label
				>
				<label
					>{$t('modelAdmin.model')}<input
						class="input"
						bind:value={draft.model}
						maxlength="200"
						required
						disabled={busy || Boolean(saved)}
					/></label
				>
				<label
					>{$t('modelAdmin.priority')}<input
						class="input"
						type="number"
						bind:value={draft.priority}
						min="-2147483648"
						max="2147483647"
						step="1"
						required
						disabled={busy}
					/></label
				>
				<label
					>{$t('modelAdmin.context')}<input
						class="input"
						type="number"
						bind:value={draft.context_window_tokens}
						min="1"
						max="2147483647"
						step="1"
						disabled={busy}
					/></label
				>
				<label
					>{$t('modelAdmin.output')}<input
						class="input"
						type="number"
						bind:value={draft.max_output_tokens}
						min="1"
						max="2147483647"
						step="1"
						disabled={busy}
					/></label
				>
				<label
					>{$t('modelAdmin.timeout')}<input
						class="input"
						type="number"
						bind:value={draft.request_timeout_seconds}
						min="0"
						step="any"
						disabled={busy}
					/></label
				>
				{#if saved}<label class="model-checkbox"
						><input type="checkbox" bind:checked={draft.enabled} disabled={busy} />{$t(
							'modelAdmin.enabled'
						)}</label
					>
					<p class="muted">{$t('modelAdmin.disableHint')}</p>{/if}
				<label class="model-key-field"
					>{$t('modelAdmin.newKey')}<input
						class="input"
						type="password"
						bind:value={draft.api_key}
						autocomplete="new-password"
						spellcheck="false"
						disabled={busy}
					/></label
				>
				<p class="muted">{$t('modelAdmin.keyHint')}</p>
				{#if saved?.api_key_configured}
					{#if clearKey}<p role="status">{$t('modelAdmin.clearPending')}</p>
						<button
							type="button"
							class="btn btn--ghost"
							on:click={() => (clearKey = false)}
							disabled={busy}>{$t('modelAdmin.cancelClear')}</button
						>
					{:else}<button type="button" class="btn btn--ghost" on:click={chooseClear} disabled={busy}
							>{$t('modelAdmin.clearKey')}</button
						>{/if}
				{/if}
				<div class="toolbar">
					<button class="btn btn--primary" disabled={busy || (Boolean(saved) && !dirty)}
						>{$t('modelAdmin.save')}</button
					>
					<button type="button" class="btn btn--ghost" on:click={() => navigate('')} disabled={busy}
						>{$t('modelAdmin.close')}</button
					>
					{#if saved}<button
							type="button"
							class="btn btn--ghost"
							on:click={testConnection}
							disabled={busy || dirty}>{$t('modelAdmin.test')}</button
						>{/if}
				</div>
				{#if dirty && saved}<p class="muted">{$t('modelAdmin.saveBeforeTest')}</p>{/if}
			</form>
			{#if probe}<p
					class:status--error={!probe.success}
					class="status"
					role="status"
					aria-live="polite"
				>
					{probe.success ? $t('modelAdmin.probeSuccess') : $t(`modelAdmin.${probe.reason}`)} · {probe.latency_ms}
					ms
				</p>{/if}
		</section>
	{/if}
</PermissionGate>
