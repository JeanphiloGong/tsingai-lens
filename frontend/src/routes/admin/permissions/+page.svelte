<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		KeyRound,
		Plus,
		RefreshCw,
		ChevronLeft,
		ChevronRight,
		Info,
		Trash2,
		X
	} from '@lucide/svelte';
	import PermissionGate from '../../_shared/PermissionGate.svelte';
	import { permissionState, refreshPermissions } from '../../_shared/permissions';
	import { authState, clearAuthState } from '../../_shared/authState';
	import { t } from '../../_shared/i18n';
	import { requestJson, errorMessage, getApiErrorReason, isApiErrorCode } from '../../_shared/api';
	type Entry = { code: string; name: string; description: string; is_system: boolean };
	type EntryPage = { items: Entry[]; total: number; limit: number; offset: number };
	let page: EntryPage = { items: [], total: 0, limit: 50, offset: 0 };
	let limit = 50,
		offset = 0,
		selected = '',
		newCode = '',
		newName = '',
		newDescription = '',
		editName = '',
		editDescription = '',
		error = '';
	let saved = false;
	let editor: HTMLDialogElement;
	let editorMode: 'create' | 'edit' | null = null;
	let busy = false,
		loading = false,
		mounted = false,
		subject = '',
		loadedSubject = '',
		generation = 0;
	$: currentSubject = $authState.status === 'authenticated' ? ($authState.user?.user_id ?? '') : '';
	$: canManage =
		$permissionState.status === 'ready' &&
		$permissionState.userId === currentSubject &&
		$permissionState.codes.includes('users.manage');
	$: if (currentSubject !== subject) {
		subject = currentSubject;
		loadedSubject = '';
		saved = false;
		generation++;
		page = { items: [], total: 0, limit, offset: 0 };
		selected = '';
		offset = 0;
		newCode = '';
		newName = '';
		newDescription = '';
		editName = '';
		editDescription = '';
		error = '';
		busy = false;
		loading = false;
		editorMode = null;
	}
	$: if (mounted && canManage && subject && loadedSubject !== subject) {
		loadedSubject = subject;
		void load();
	}
	$: selectedItem = page.items.find((item) => item.code === selected);
	onMount(() => {
		mounted = true;
	});
	onDestroy(() => {
		mounted = false;
		subject = '';
		generation++;
	});
	function showError(caught: unknown) {
		saved = false;
		const reason = getApiErrorReason(caught);
		error =
			reason === 'already_exists'
				? $t('admin.duplicate')
				: reason === 'invalid_request'
					? $t('admin.invalid')
					: errorMessage(caught);
		if (isApiErrorCode(caught, 200301)) clearAuthState();
		else if (isApiErrorCode(caught, 200203)) void refreshPermissions();
	}

	async function load() {
		const request = ++generation,
			owner = subject;
		loading = true;
		error = '';
		try {
			const result: EntryPage = await requestJson(
				`/user-api/v1/admin/permissions?limit=${limit}&offset=${offset}`
			);
			if (request === generation && owner === subject) page = result;
		} catch (caught) {
			if (request === generation && owner === subject) showError(caught);
		} finally {
			if (request === generation && owner === subject) loading = false;
		}
	}
	function select(item: Entry) {
		error = '';
		editorMode = 'edit';
		selected = item.code;
		editName = item.name;
		editDescription = item.description;
		editor.showModal();
	}
	function pageEntries(next: number) {
		offset = next;
		selected = '';
		void load();
	}
	async function mutate(method: string, path: string, body?: unknown): Promise<boolean> {
		if (busy) return false;
		const owner = subject;
		busy = true;
		saved = false;
		error = '';
		try {
			await requestJson(path, {
				method,
				...(body === undefined ? {} : { body: JSON.stringify(body) })
			});
			if (owner !== subject) return false;
			await load();
			if (owner !== subject) return false;
			await refreshPermissions();
			saved = owner === subject;
			return owner === subject;
		} catch (caught) {
			if (owner === subject) showError(caught);
			return false;
		} finally {
			if (owner === subject) busy = false;
		}
	}
	async function createItem() {
		if (
			await mutate('POST', '/user-api/v1/admin/permissions', {
				code: newCode,
				name: newName,
				description: newDescription
			})
		) {
			newCode = '';
			newName = '';
			newDescription = '';
			editor?.close();
		}
	}
	async function saveMetadata() {
		if (
			await mutate('PATCH', `/user-api/v1/admin/permissions/${encodeURIComponent(selected)}`, {
				name: editName,
				description: editDescription
			})
		)
			editor?.close();
	}
	async function deleteItem() {
		if (!window.confirm($t('admin.confirmDelete'))) return;
		if (await mutate('DELETE', `/user-api/v1/admin/permissions/${encodeURIComponent(selected)}`)) {
			selected = '';
			editor?.close();
		}
	}
</script>

<svelte:head><title>{$t('admin.permissions')} · Lens</title></svelte:head>
<PermissionGate code="users.manage">
	<header class="admin-page-header">
		<div>
			<h1>{$t('admin.permissions')}</h1>
			<p>{$t('admin.permissionsDescription')}</p>
		</div>
		<div class="admin-header-actions">
			<button
				class="btn btn--ghost admin-icon-button"
				type="button"
				aria-label={$t('admin.refresh')}
				title={$t('admin.refresh')}
				disabled={busy || loading}
				on:click={load}><RefreshCw size={16} aria-hidden="true" /></button
			><button
				class="btn btn--primary"
				type="button"
				disabled={busy}
				on:click={() => {
					error = '';
					editorMode = 'create';
					editor.showModal();
				}}><Plus size={16} aria-hidden="true" />{$t('admin.createPermission')}</button
			>
		</div>
	</header>
	{#if saved}<p class="status admin-success" role="status">{$t('admin.saved')}</p>{/if}
	{#if error && !editorMode}<p class="status status--error" role="alert">{error}</p>{/if}
	{#if loading}<p class="status" role="status">{$t('admin.loading')}</p>{/if}
	<section class="admin-panel" aria-label={$t('admin.allPermissions')}>
		<div class="admin-panel-header">
			<h2>{$t('admin.allPermissions')}</h2>
			<span class="admin-count">{$t('admin.total')}: {page.total}</span>
		</div>
		<div class="admin-table-wrap">
			<table class="admin-permission-table" aria-busy={loading}>
				<thead
					><tr
						><th>{$t('admin.permissions')}</th><th>{$t('admin.descriptionLabel')}</th><th
							>{$t('admin.type')}</th
						><th>{$t('admin.actions')}</th></tr
					></thead
				><tbody>
					{#each page.items as item (item.code)}<tr
							><td
								><strong class="admin-cell-name">{item.name}</strong><span class="admin-code"
									>{item.code}</span
								></td
							><td>{item.description || $t('admin.noDescription')}</td><td
								><span class="admin-badge"
									>{item.is_system ? $t('admin.systemEntry') : $t('admin.customEntry')}</span
								></td
							><td
								><button
									class="admin-text-button"
									type="button"
									disabled={busy || loading}
									aria-label={$t('admin.editPermission', { name: item.name })}
									on:click={() => select(item)}>{$t('admin.edit')}</button
								></td
							></tr
						>{/each}
				</tbody>
			</table>
		</div>
		{#if !loading && !page.items.length}<div class="admin-empty">
				<KeyRound size={26} aria-hidden="true" />
				<p>{$t('admin.noEntries')}</p>
			</div>{/if}
		<footer class="admin-pagination">
			<span
				>{$t('admin.pageRange', {
					start: page.items.length ? offset + 1 : 0,
					end: offset + page.items.length,
					total: page.total
				})}</span
			>
			<div class="admin-pagination-controls">
				<label class="admin-page-label"
					>{$t('admin.pageSize')}<select
						class="input"
						aria-label={$t('admin.pageSize')}
						bind:value={limit}
						on:change={() => pageEntries(0)}
						disabled={busy || loading}
						><option value={2}>2</option><option value={10}>10</option><option value={50}>50</option
						><option value={200}>200</option></select
					></label
				><button
					class="btn btn--ghost"
					type="button"
					aria-label={$t('admin.previousEntries')}
					disabled={busy || loading || offset === 0}
					on:click={() => pageEntries(Math.max(0, offset - limit))}
					><ChevronLeft size={15} aria-hidden="true" /></button
				><button
					class="btn btn--ghost"
					type="button"
					aria-label={$t('admin.nextEntries')}
					disabled={busy || loading || offset + limit >= page.total}
					on:click={() => pageEntries(offset + limit)}
					><ChevronRight size={15} aria-hidden="true" /></button
				>
			</div>
		</footer>
	</section>
	<p class="admin-context-note"><Info size={14} aria-hidden="true" />{$t('admin.stableCode')}</p>
	<dialog
		class="admin-dialog"
		bind:this={editor}
		aria-labelledby="permission-editor-title"
		on:close={() => (editorMode = null)}
		on:cancel={(event) => {
			if (busy) event.preventDefault();
		}}
	>
		<div class="admin-dialog-heading">
			<h2 id="permission-editor-title">
				{editorMode === 'create' ? $t('admin.createPermission') : $t('admin.edit')}
			</h2>
			<button
				class="admin-text-button"
				type="button"
				disabled={busy}
				aria-label={$t('admin.close')}
				on:click={() => editor.close()}><X size={18} aria-hidden="true" /></button
			>
		</div>
		<p class="admin-help">
			{editorMode === 'create' ? $t('admin.createPermissionHint') : $t('admin.stableCode')}
		</p>
		{#if editorMode === 'create'}<form class="admin-form" on:submit|preventDefault={createItem}>
				<label
					>{$t('admin.newPermissionCode')}<input
						class="input"
						maxlength="128"
						pattern="[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+"
						bind:value={newCode}
						required
						disabled={busy}
					/></label
				><label
					>{$t('admin.newPermissionName')}<input
						class="input"
						maxlength="100"
						bind:value={newName}
						required
						disabled={busy}
					/></label
				><label
					>{$t('admin.newPermissionDescription')}<textarea
						class="input"
						maxlength="1000"
						bind:value={newDescription}
						disabled={busy}
					></textarea></label
				>{#if error}<p class="status status--error" role="alert">{error}</p>{/if}
				<div class="admin-form-actions">
					<button
						class="btn btn--ghost"
						type="button"
						disabled={busy}
						on:click={() => editor.close()}>{$t('admin.cancel')}</button
					><button class="btn btn--primary" disabled={busy}>{$t('admin.createPermission')}</button>
				</div>
			</form>
		{:else if selectedItem}<form class="admin-form" on:submit|preventDefault={saveMetadata}>
				<label
					>{$t('admin.code')}<input
						class="input admin-code"
						value={selectedItem.code}
						readonly
					/></label
				><label
					>{$t('admin.permissionName')}<input
						class="input"
						maxlength="100"
						bind:value={editName}
						required
						disabled={busy}
					/></label
				><label
					>{$t('admin.permissionDescription')}<textarea
						class="input"
						maxlength="1000"
						bind:value={editDescription}
						disabled={busy}
					></textarea></label
				>{#if error}<p class="status status--error" role="alert">{error}</p>{/if}
				<div class="admin-form-actions">
					<button
						class="btn btn--ghost"
						type="button"
						disabled={busy}
						on:click={() => editor.close()}>{$t('admin.cancel')}</button
					><button class="btn btn--primary" disabled={busy}>{$t('admin.saveMetadata')}</button>
				</div>
			</form>
			<div class="admin-danger-zone">
				<p>
					{selectedItem.is_system ? $t('admin.protectedEntry') : $t('admin.deletePermissionHint')}
				</p>
				<button
					class="btn admin-danger"
					type="button"
					disabled={busy || selectedItem.is_system}
					on:click={deleteItem}
					><Trash2 size={15} aria-hidden="true" />{$t('admin.deletePermission')}</button
				>
			</div>{/if}
	</dialog>
</PermissionGate>
