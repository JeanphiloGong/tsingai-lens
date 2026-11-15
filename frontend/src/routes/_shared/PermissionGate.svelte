<script lang="ts">
	import { resolve } from '$app/paths';
	import { authState } from './authState';
	import { t } from './i18n';
	import { permissionState, refreshPermissions } from './permissions';
	export let code: string;
</script>

{#if $authState.status !== 'authenticated' || $permissionState.userId !== $authState.user?.user_id || $permissionState.status === 'loading'}
	<p class="status" role="status">{$t('admin.loadingPermissions')}</p>
{:else if $permissionState.status === 'unavailable'}
	<div class="status status--error" role="alert">
		<p>{$t('admin.unavailable')}</p>
		<button class="btn btn--ghost" type="button" on:click={refreshPermissions}
			>{$t('admin.retry')}</button
		>
	</div>
{:else if !$permissionState.codes.includes(code)}
	<div class="status status--error" role="alert">
		<p>403 · {$t('admin.denied')}</p>
		<a class="btn btn--ghost" href={resolve('/')}>{$t('admin.back')}</a>
		<button class="btn btn--ghost" type="button" on:click={refreshPermissions}
			>{$t('admin.retry')}</button
		>
	</div>
{:else}
	<slot />
{/if}
