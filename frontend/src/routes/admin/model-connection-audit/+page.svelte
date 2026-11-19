<script lang="ts">
	import { onDestroy } from 'svelte';
	import { errorMessage, getApiErrorReason, requestJson } from '../../_shared/api';
	import { authState } from '../../_shared/authState';
	import { language, t } from '../../_shared/i18n';
	import PermissionGate from '../../_shared/PermissionGate.svelte';
	import { permissionState, refreshPermissions } from '../../_shared/permissions';
	import type { ConnectionPage } from '../models/modelConnections';

	type AuditValue = string | number | boolean | null;
	type AuditChange = {
		before: AuditValue;
		after: AuditValue;
		operation?: 'set' | 'replace' | 'clear';
	};
	type AuditRecord = {
		connection_id: string;
		actor_id: string;
		actor_display_name: string | null;
		action: 'create' | 'update';
		version: number;
		changes: Record<string, AuditChange>;
		created_at: string;
	};
	type AuditPage = { items: AuditRecord[]; total: number };

	const pageSize = 50;
	const labels: Record<string, string> = {
		display_name: 'admin.name',
		base_url: 'modelAdmin.baseURL',
		model: 'modelAdmin.model',
		kind: 'modelAdmin.kind',
		enabled: 'modelAdmin.enabled',
		priority: 'modelAdmin.priority',
		context_window_tokens: 'modelAdmin.context',
		max_output_tokens: 'modelAdmin.output',
		request_timeout_seconds: 'modelAdmin.timeout',
		api_key: 'modelAdmin.keyStatus'
	};

	let account = '';
	let connectionID = '';
	let offset = 0;
	let expanded = '';
	let connections: ConnectionPage['items'] = [];
	let page: AuditPage = { items: [], total: 0 };
	let loading = false;
	let error = '';
	let connectionError = '';
	let readController: AbortController | undefined;
	let connectionController: AbortController | undefined;

	$: allowedAccount =
		$authState.status === 'authenticated' &&
		$permissionState.status === 'ready' &&
		$permissionState.userId === $authState.user?.user_id &&
		$permissionState.codes.includes('models.manage')
			? $authState.user?.user_id || ''
			: '';
	$: if (account !== allowedAccount) {
		account = allowedAccount;
		readController?.abort();
		connectionController?.abort();
		connectionID = '';
		offset = 0;
		expanded = '';
		connections = [];
		page = { items: [], total: 0 };
		loading = false;
		error = '';
		connectionError = '';
		if (account) void loadConnections();
	}
	$: if (account) void loadAudit(connectionID, offset);
	$: connectionNames = new Map(
		connections.map((connection) => [connection.connection_id, connection.display_name])
	);
	$: dateFormat = new Intl.DateTimeFormat($language, { dateStyle: 'short', timeStyle: 'short' });

	onDestroy(() => {
		readController?.abort();
		connectionController?.abort();
	});

	async function loadConnections() {
		connectionController?.abort();
		const controller = new AbortController();
		connectionController = controller;
		connectionError = '';
		const options: ConnectionPage['items'] = [];
		try {
			while (!controller.signal.aborted) {
				const params = new URLSearchParams({ limit: '100', offset: String(options.length) });
				const result: ConnectionPage = await requestJson(
					'/api/v1/admin/model-connections?' + params,
					{ signal: controller.signal }
				);
				options.push(...result.items);
				if (!result.items.length || options.length >= result.total) break;
			}
			if (!controller.signal.aborted) connections = options;
		} catch (caught) {
			if (!controller.signal.aborted) {
				connectionError = errorMessage(caught);
				if (getApiErrorReason(caught) === 'permission_denied') void refreshPermissions();
			}
		}
	}

	async function loadAudit(filter: string, pageOffset: number) {
		readController?.abort();
		const controller = new AbortController();
		readController = controller;
		const params = new URLSearchParams({ limit: String(pageSize), offset: String(pageOffset) });
		if (filter) params.set('connection_id', filter);
		loading = true;
		error = '';
		expanded = '';
		try {
			const result: AuditPage = await requestJson(
				'/api/v1/admin/model-connection-audit?' + params,
				{ signal: controller.signal }
			);
			if (!controller.signal.aborted) page = result;
		} catch (caught) {
			if (!controller.signal.aborted) {
				error = errorMessage(caught);
				if (getApiErrorReason(caught) === 'permission_denied') void refreshPermissions();
			}
		} finally {
			if (!controller.signal.aborted) loading = false;
		}
	}

	function selectConnection(event: Event) {
		connectionID = (event.currentTarget as HTMLSelectElement).value;
		offset = 0;
	}

	function formatChange(
		field: string,
		entry: AuditChange,
		side: 'before' | 'after',
		action: AuditRecord['action']
	) {
		const value = entry[side];
		if (field === 'api_key') {
			if (side === 'after' && entry.operation) return $t('modelAudit.' + entry.operation);
			return $t(value === 'configured' ? 'modelAdmin.configured' : 'modelAdmin.notConfigured');
		}
		if (side === 'before' && action === 'create') return $t('modelAudit.initial');
		if (field === 'kind')
			return $t(value === 'embedding' ? 'modelAdmin.embeddingKind' : 'modelAdmin.chatKind');
		if (value === null) return $t('modelAudit.inherit');
		if (typeof value === 'boolean') return $t(value ? 'modelAdmin.enabled' : 'modelAdmin.disabled');
		return String(value);
	}
</script>

<svelte:head><title>{$t('modelAudit.title')} · Lens</title></svelte:head>

<h1>{$t('modelAudit.title')}</h1>
<PermissionGate code="models.manage">
	<div class="toolbar">
		<label>
			{$t('modelAdmin.title')}
			<select class="input model-filter" value={connectionID} on:change={selectConnection}>
				<option value="">{$t('modelAudit.all')}</option>
				{#each connections as connection (connection.connection_id)}
					<option value={connection.connection_id}>{connection.display_name}</option>
				{/each}
			</select>
		</label>
	</div>
	{#if connectionError}
		<div class="status status--error" role="alert">
			<p>{connectionError}</p>
			<button class="btn btn--ghost" type="button" on:click={loadConnections}
				>{$t('admin.retry')}</button
			>
		</div>
	{/if}
	{#if loading}
		<p role="status">{$t('admin.loading')}</p>
	{:else if error}
		<div class="status status--error" role="alert">
			<p>{error}</p>
			<button class="btn btn--ghost" type="button" on:click={() => loadAudit(connectionID, offset)}
				>{$t('admin.retry')}</button
			>
		</div>
	{:else}
		{#if !page.items.length}
			<p role="status">{$t('modelAudit.empty')}</p>
		{:else}
			<!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users can scroll the named table.) -->
			<div class="audit-table" role="region" aria-label={$t('modelAudit.title')} tabindex="0">
				<table>
					<thead>
						<tr>
							<th scope="col">{$t('modelAudit.time')}</th>
							<th scope="col">{$t('modelAdmin.title')}</th>
							<th scope="col">{$t('modelAudit.actor')}</th>
							<th scope="col">{$t('modelAudit.action')}</th>
							<th scope="col">{$t('modelAudit.changes')}</th>
						</tr>
					</thead>
					<tbody>
						{#each page.items as record (record.connection_id + ':' + record.version)}
							{@const key = record.connection_id + ':' + record.version}
							<tr>
								<td
									><time datetime={record.created_at}
										>{dateFormat.format(new Date(record.created_at))}</time
									></td
								>
								<td>{connectionNames.get(record.connection_id) ?? record.connection_id}</td>
								<td>{record.actor_display_name ?? record.actor_id}</td>
								<td>{$t('modelAudit.' + record.action)}</td>
								<td>
									{Object.keys(record.changes).length}
									<button
										class="btn btn--ghost"
										type="button"
										aria-expanded={expanded === key}
										on:click={() => (expanded = expanded === key ? '' : key)}
									>
										{$t(expanded === key ? 'modelAudit.hide' : 'modelAudit.show')}
									</button>
								</td>
							</tr>
							{#if expanded === key}
								<tr>
									<td colspan="5">
										<table aria-label={$t('modelAudit.changes')}>
											<thead
												><tr>
													<th scope="col">{$t('modelAudit.field')}</th>
													<th scope="col">{$t('modelAudit.before')}</th>
													<th scope="col">{$t('modelAudit.after')}</th>
												</tr></thead
											>
											<tbody>
												{#each Object.entries(record.changes) as [field, entry] (field)}
													<tr>
														<th scope="row">{labels[field] ? $t(labels[field]) : field}</th>
														<td>{formatChange(field, entry, 'before', record.action)}</td>
														<td>{formatChange(field, entry, 'after', record.action)}</td>
													</tr>
												{/each}
											</tbody>
										</table>
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
		<div class="toolbar">
			<button
				class="btn btn--ghost"
				type="button"
				disabled={offset === 0}
				on:click={() => (offset = Math.max(offset - pageSize, 0))}
				>{$t('admin.previousEntries')}</button
			>
			<button
				class="btn btn--ghost"
				type="button"
				disabled={offset + pageSize >= page.total}
				on:click={() => (offset += pageSize)}>{$t('admin.nextEntries')}</button
			>
			<span>{$t('admin.total')}: {page.total}</span>
		</div>
	{/if}
</PermissionGate>

<style>
	.toolbar .model-filter {
		width: auto;
		min-width: 12rem;
		max-width: min(100%, 24rem);
	}
	.audit-table {
		overflow-x: auto;
	}
	th,
	td {
		overflow-wrap: anywhere;
	}
	.audit-table > table {
		min-width: 38rem;
	}
</style>
