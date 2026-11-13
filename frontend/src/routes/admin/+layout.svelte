<script lang="ts">
	import './admin.css';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { authState } from '../_shared/authState';
	import { t } from '../_shared/i18n';
	import { permissionState } from '../_shared/permissions';
</script>

<div class="admin-workspace">
	{#if $authState.status === 'authenticated' && $permissionState.userId === $authState.user?.user_id && $permissionState.codes.includes('users.manage')}
		<header class="admin-heading">
			<p>{$t('admin.description')}</p>
			<nav aria-label={$t('admin.title')}>
				<a
					href={resolve('/admin/users')}
					aria-current={$page.url.pathname === '/admin/users' ? 'page' : undefined}
					>{$t('admin.users')}</a
				>
				<a
					href={resolve('/admin/groups')}
					aria-current={$page.url.pathname === '/admin/groups' ? 'page' : undefined}
					>{$t('admin.groups')}</a
				>
				<a
					href={resolve('/admin/permissions')}
					aria-current={$page.url.pathname === '/admin/permissions' ? 'page' : undefined}
					>{$t('admin.permissions')}</a
				>
			</nav>
		</header>
	{/if}
	<slot />
</div>
