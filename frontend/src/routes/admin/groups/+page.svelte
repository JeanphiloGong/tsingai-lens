<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import {
		Layers,
		KeyRound,
		Plus,
		RefreshCw,
		ChevronLeft,
		ChevronRight,
		Info,
		X,
		Trash2
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
	let createDialog: HTMLDialogElement;
	let creating = false;
	let detailTab: 'permissions' | 'information' = 'permissions';
	let addingPermission = false;
	let permissionOptions: EntryPage = { items: [], total: 0, limit: 50, offset: 0 };
	let optionOffset = 0,
		optionGeneration = 0;
	let optionsLoading = false;
	let busy = false,
		loading = false,
		associationLoading = false,
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
		associationLoading = false;
		associationGeneration++;
		association = { items: [], total: 0, limit: 50, offset: 0 };
		associationOffset = 0;
		permissionCode = '';
		addingPermission = false;
		optionGeneration++;
		permissionOptions = { items: [], total: 0, limit: 50, offset: 0 };
		creating = false;
		optionsLoading = false;
		optionOffset = 0;
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
		associationGeneration++;
		optionGeneration++;
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
				`/user-api/v1/admin/groups?limit=${limit}&offset=${offset}`
			);
			if (request === generation && owner === subject) {
				page = result;
				if (!page.items.some((item) => item.code === selected)) {
					selected = '';
					if (page.items[0]) select(page.items[0]);
				}
			}
		} catch (caught) {
			if (request === generation && owner === subject) showError(caught);
		} finally {
			if (request === generation && owner === subject) loading = false;
		}
	}
	function select(item: Entry) {
		error = '';
		saved = false;
		detailTab = 'permissions';
		addingPermission = false;
		selected = item.code;
		editName = item.name;
		editDescription = item.description;
		associationOffset = 0;
		permissionCode = '';
		association = { items: [], total: 0, limit: 50, offset: 0 };
		void loadAssociation();
	}
	function pageEntries(next: number) {
		offset = next;
		selected = '';
		associationGeneration++;
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
			if (selected && page.items.some((item) => item.code === selected)) {
				associationOffset = 0;
				await loadAssociation();
			}
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
			await mutate('POST', '/user-api/v1/admin/groups', {
				code: newCode,
				name: newName,
				description: newDescription
			})
		) {
			newCode = '';
			newName = '';
			newDescription = '';
			createDialog?.close();
		}
	}
	async function saveMetadata() {
		await mutate('PATCH', `/user-api/v1/admin/groups/${encodeURIComponent(selected)}`, {
			name: editName,
			description: editDescription
		});
	}
	async function deleteItem() {
		if (!window.confirm($t('admin.confirmDelete'))) return;
		await mutate('DELETE', `/user-api/v1/admin/groups/${encodeURIComponent(selected)}`);
	}

	let association: EntryPage = { items: [], total: 0, limit: 50, offset: 0 };
	let permissionCode = '',
		associationOffset = 0,
		associationGeneration = 0;
	async function loadAssociation() {
		const request = ++associationGeneration,
			owner = subject,
			target = selected;
		if (!target) return;
		associationLoading = true;
		try {
			const result: EntryPage = await requestJson(
				`/user-api/v1/admin/groups/${encodeURIComponent(target)}/permissions?limit=50&offset=${associationOffset}`
			);
			if (request === associationGeneration && owner === subject && target === selected)
				association = result;
		} catch (caught) {
			if (request === associationGeneration && owner === subject && target === selected)
				showError(caught);
		} finally {
			if (request === associationGeneration && owner === subject && target === selected)
				associationLoading = false;
		}
	}
	async function changePermission(method: 'PUT' | 'DELETE', code: string) {
		if (
			await mutate(
				method,
				`/user-api/v1/admin/groups/${encodeURIComponent(selected)}/permissions/${encodeURIComponent(code)}`
			)
		) {
			permissionCode = '';
			addingPermission = false;
		}
	}

	async function loadPermissionOptions(next = 0) {
		optionOffset = next;
		permissionCode = '';
		const request = ++optionGeneration,
			owner = subject;
		optionsLoading = true;
		try {
			const result: EntryPage = await requestJson(
				`/user-api/v1/admin/permissions?limit=50&offset=${next}`
			);
			if (request === optionGeneration && owner === subject) permissionOptions = result;
		} catch (caught) {
			if (request === optionGeneration && owner === subject) showError(caught);
		} finally {
			if (request === optionGeneration && owner === subject) optionsLoading = false;
		}
	}
</script>

<svelte:head><title>{$t('admin.groups')} · Lens</title></svelte:head>
<PermissionGate code="users.manage">
	<header class="admin-page-header">
		<div>
			<h1>{$t('admin.groups')}</h1>
			<p>{$t('admin.groupsDescription')}</p>
		</div>
		<div class="admin-header-actions">
			<button
				class="btn btn--ghost admin-icon-button"
				type="button"
				aria-label={$t('admin.refresh')}
				title={$t('admin.refresh')}
				disabled={busy || loading}
				on:click={load}><RefreshCw size={16} aria-hidden="true" /></button
			>
			<button
				class="btn btn--primary"
				type="button"
				disabled={busy}
				on:click={() => {
					error = '';
					creating = true;
					createDialog.showModal();
				}}><Plus size={16} aria-hidden="true" />{$t('admin.createGroup')}</button
			>
		</div>
	</header>
	{#if saved}<p class="status admin-success" role="status">{$t('admin.saved')}</p>{/if}
	{#if error && !creating}<p class="status status--error" role="alert">{error}</p>{/if}
	{#if loading}<p class="status" role="status">{$t('admin.loading')}</p>{/if}
	<div class="admin-group-layout">
		<section
			class="admin-panel admin-directory"
			aria-label={$t('admin.groups')}
			aria-busy={loading}
		>
			<div class="admin-panel-header">
				<h2>{$t('admin.allGroups')}</h2>
				<span class="admin-count">{$t('admin.total')}: {page.total}</span>
			</div>
			<div class="admin-entry-list">
				{#each page.items as item (item.code)}
					<button
						class="admin-entry"
						type="button"
						disabled={busy || loading}
						aria-label={$t('admin.selectGroup', { name: item.name })}
						aria-pressed={selected === item.code}
						on:click={() => select(item)}
					>
						<span class="admin-symbol"><Layers size={18} aria-hidden="true" /></span>
						<div class="admin-entry-content">
							<div class="admin-entry-title">
								<strong>{item.name}</strong><span class="admin-badge"
									>{item.is_system ? $t('admin.systemEntry') : $t('admin.customEntry')}</span
								>
							</div>
							<span class="admin-code">{item.code}</span>{#if item.description}<p>
									{item.description}
								</p>{/if}
						</div>
					</button>
				{/each}
				{#if !loading && !page.items.length}<div class="admin-empty">
						<Layers size={24} aria-hidden="true" />
						<p>{$t('admin.noEntries')}</p>
					</div>{/if}
			</div>
			<footer class="admin-pagination">
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
				>
				<div class="admin-pagination-controls">
					<button
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
		{#if selectedItem}
			<section class="admin-panel admin-detail" aria-labelledby="selected-group-heading">
				<header class="admin-detail-heading">
					<div class="admin-detail-title">
						<span class="admin-symbol"><Layers size={21} aria-hidden="true" /></span>
						<div>
							<h2 id="selected-group-heading">{selectedItem.name}</h2>
							<span class="admin-code">{selectedItem.code}</span>
						</div>
						<span class="admin-badge"
							>{selectedItem.is_system ? $t('admin.systemEntry') : $t('admin.customEntry')}</span
						>
					</div>
					{#if selectedItem.description}<p class="admin-detail-description">
							{selectedItem.description}
						</p>{/if}
				</header>
				<div class="admin-detail-tabs">
					<button
						type="button"
						aria-pressed={detailTab === 'permissions'}
						on:click={() => (detailTab = 'permissions')}>{$t('admin.groupPermissions')}</button
					><button
						type="button"
						aria-pressed={detailTab === 'information'}
						on:click={() => (detailTab = 'information')}>{$t('admin.basicInformation')}</button
					>
				</div>
				<div class="admin-detail-body">
					{#if detailTab === 'permissions'}
						<div class="admin-section-heading">
							<h3>
								{$t('admin.grantedPermissions')}
								<span class="admin-count">{associationLoading ? '…' : association.total}</span>
							</h3>
							<button
								class="admin-text-button"
								type="button"
								disabled={busy}
								aria-expanded={addingPermission}
								on:click={() => {
									addingPermission = !addingPermission;
									if (addingPermission) void loadPermissionOptions();
								}}><Plus size={15} aria-hidden="true" />{$t('admin.addPermission')}</button
							>
						</div>
						{#if addingPermission}
							<form
								class="admin-form admin-picker"
								on:submit|preventDefault={() => changePermission('PUT', permissionCode)}
							>
								<label
									>{$t('admin.existingPermissionCode')}<select
										class="input"
										aria-label={$t('admin.existingPermissionCode')}
										bind:value={permissionCode}
										disabled={busy || optionsLoading}
										required
										><option value="">{$t('admin.choosePermission')}</option
										>{#each permissionOptions.items as item (item.code)}<option value={item.code}
												>{item.name} ({item.code})</option
											>{/each}</select
									></label
								>
								{#if optionsLoading}<p class="admin-help" role="status">
										{$t('admin.loading')}
									</p>{/if}
								<div class="admin-pagination">
									<span>{$t('admin.total')}: {permissionOptions.total}</span>
									<div class="admin-pagination-controls">
										<button
											class="btn btn--ghost"
											type="button"
											aria-label={$t('admin.previousOptions')}
											disabled={busy || optionsLoading || optionOffset === 0}
											on:click={() => loadPermissionOptions(Math.max(0, optionOffset - 50))}
											><ChevronLeft size={15} aria-hidden="true" /></button
										><button
											class="btn btn--ghost"
											type="button"
											aria-label={$t('admin.nextOptions')}
											disabled={busy ||
												optionsLoading ||
												optionOffset + 50 >= permissionOptions.total}
											on:click={() => loadPermissionOptions(optionOffset + 50)}
											><ChevronRight size={15} aria-hidden="true" /></button
										>
									</div>
								</div>
								<div class="admin-form-actions">
									<button
										class="btn btn--ghost"
										type="button"
										disabled={busy}
										on:click={() => (addingPermission = false)}>{$t('admin.cancel')}</button
									><button
										class="btn btn--primary"
										disabled={busy || optionsLoading || !permissionCode}
										>{$t('admin.addPermission')}</button
									>
								</div>
							</form>
						{/if}
						{#if associationLoading}<p class="admin-help" role="status">
								{$t('admin.loadingAssociations')}
							</p>{/if}
						<ul class="admin-associations" aria-busy={associationLoading}>
							{#each association.items as item (item.code)}<li>
									<span class="admin-symbol"><KeyRound size={17} aria-hidden="true" /></span>
									<div class="admin-association-content">
										<strong>{item.name}</strong><span class="admin-code">{item.code}</span
										>{#if item.description}<p>{item.description}</p>{/if}
									</div>
									<button
										class="admin-text-button admin-remove"
										type="button"
										disabled={busy || associationLoading}
										aria-label={`${$t('admin.removePermission')} ${item.code}`}
										on:click={() => changePermission('DELETE', item.code)}
										>{$t('admin.remove')}</button
									>
								</li>{/each}
						</ul>
						{#if !associationLoading && !association.items.length}<div class="admin-empty">
								<KeyRound size={24} aria-hidden="true" />
								<p>{$t('admin.noGroupPermissions')}</p>
							</div>{/if}
						{#if association.total > 50}<div class="admin-pagination admin-association-pagination">
								<span>{$t('admin.total')}: {association.total}</span>
								<div class="admin-pagination-controls">
									<button
										class="btn btn--ghost"
										type="button"
										aria-label={$t('admin.previousGroupPermissions')}
										disabled={busy || associationLoading || associationOffset === 0}
										on:click={() => {
											associationOffset = Math.max(0, associationOffset - 50);
											void loadAssociation();
										}}><ChevronLeft size={15} aria-hidden="true" /></button
									><button
										class="btn btn--ghost"
										type="button"
										aria-label={$t('admin.nextGroupPermissions')}
										disabled={busy ||
											associationLoading ||
											associationOffset + 50 >= association.total}
										on:click={() => {
											associationOffset += 50;
											void loadAssociation();
										}}><ChevronRight size={15} aria-hidden="true" /></button
									>
								</div>
							</div>{/if}
						<p class="admin-context-note">
							<Info size={14} aria-hidden="true" />{$t('admin.groupEffect')}
						</p>
					{:else}
						<form class="admin-form" on:submit|preventDefault={saveMetadata}>
							<label
								>{$t('admin.groupName')}<input
									class="input"
									maxlength="100"
									bind:value={editName}
									required
									disabled={busy}
								/></label
							>
							<label
								>{$t('admin.groupDescription')}<textarea
									class="input"
									maxlength="1000"
									bind:value={editDescription}
									disabled={busy}
								></textarea></label
							>
							<p class="admin-help">{$t('admin.stableCode')}</p>
							<div class="admin-form-actions">
								<button class="btn btn--primary" disabled={busy}>{$t('admin.saveMetadata')}</button>
							</div>
						</form>
						<div class="admin-danger-zone">
							<p>
								{selectedItem.is_system ? $t('admin.protectedEntry') : $t('admin.deleteGroupHint')}
							</p>
							<button
								class="btn admin-danger"
								type="button"
								disabled={busy || selectedItem.is_system}
								on:click={deleteItem}
								><Trash2 size={15} aria-hidden="true" />{$t('admin.deleteGroup')}</button
							>
						</div>
					{/if}
				</div>
				{#if detailTab === 'permissions'}<footer class="admin-detail-footer">
						<Info size={14} aria-hidden="true" /><span
							>{selectedItem.is_system
								? $t('admin.systemGroupProtected')
								: $t('admin.customEntry')}</span
						><button
							class="admin-text-button"
							type="button"
							on:click={() => (detailTab = 'information')}>{$t('admin.editGroup')}</button
						>
					</footer>{/if}
			</section>
		{:else}<section class="admin-panel admin-empty">
				<Layers size={28} aria-hidden="true" />
				<h2>{$t('admin.groups')}</h2>
				<p>{$t('admin.selectEntry')}</p>
			</section>{/if}
	</div>
	<dialog
		class="admin-dialog"
		bind:this={createDialog}
		aria-labelledby="create-group-title"
		on:close={() => (creating = false)}
		on:cancel={(event) => {
			if (busy) event.preventDefault();
		}}
	>
		<div class="admin-dialog-heading">
			<h2 id="create-group-title">{$t('admin.createGroup')}</h2>
			<button
				class="admin-text-button"
				type="button"
				aria-label={$t('admin.close')}
				disabled={busy}
				on:click={() => createDialog.close()}><X size={18} aria-hidden="true" /></button
			>
		</div>
		<p class="admin-help">{$t('admin.createGroupHint')}</p>
		<form class="admin-form" on:submit|preventDefault={createItem}>
			<label
				>{$t('admin.newGroupCode')}<input
					class="input"
					maxlength="64"
					pattern="[a-z][a-z0-9_]*"
					bind:value={newCode}
					required
					disabled={busy}
				/></label
			>
			<label
				>{$t('admin.newGroupName')}<input
					class="input"
					maxlength="100"
					bind:value={newName}
					required
					disabled={busy}
				/></label
			>
			<label
				>{$t('admin.newGroupDescription')}<textarea
					class="input"
					maxlength="1000"
					bind:value={newDescription}
					disabled={busy}
				></textarea></label
			>
			{#if error && creating}<p class="status status--error" role="alert">{error}</p>{/if}
			<div class="admin-form-actions">
				<button
					class="btn btn--ghost"
					type="button"
					disabled={busy}
					on:click={() => createDialog.close()}>{$t('admin.cancel')}</button
				><button class="btn btn--primary" disabled={busy}>{$t('admin.createGroup')}</button>
			</div>
		</form>
	</dialog>
</PermissionGate>
