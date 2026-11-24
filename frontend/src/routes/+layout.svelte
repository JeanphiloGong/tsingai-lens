<script lang="ts">
	import './layout.css';
	import { browser, version } from '$app/environment';
	import { afterNavigate, goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { onMount, tick } from 'svelte';
	import {
		ArrowLeft,
		Check,
		ChevronDown,
		ChevronRight,
		Languages,
		LogOut,
		Settings,
		ShieldCheck,
		SunMoon
	} from '@lucide/svelte';
	import { authState, startAuthSynchronization } from './_shared/authState';
	import { fetchCurrentSession, logout } from './_shared/auth';
	import { API_DOCS_PATH } from './_shared/base';
	import { workspaces } from '$lib/workspace/workspaces';
	import { errorMessage } from './_shared/api';
	import { language, t } from './_shared/i18n';
	import ResearchAgentLauncher from './_shared/ResearchAgentLauncher.svelte';
	import {
		permissionState,
		refreshPermissions,
		startPermissionSynchronization
	} from './_shared/permissions';
	import { themePreference } from './_shared/theme';
	import type { ThemePreference } from './_shared/theme';

	let sessionView: 'main' | 'theme' | 'language' | null = null;
	let sessionMenu: HTMLDivElement | null = null;
	let authError = '';
	const appVersion = `v${version}`;

	$: isAuthRoute = ['/login', '/register', '/forgot-password'].includes($page.url.pathname);
	$: authenticatedUser = $authState.user;
	$: adminPath =
		authenticatedUser &&
		$permissionState.status === 'ready' &&
		$permissionState.userId === authenticatedUser.user_id
			? $permissionState.codes.includes('users.manage')
				? ('/admin/users' as const)
				: $permissionState.codes.includes('models.manage')
					? ('/admin/models' as const)
					: null
			: null;
	$: if (!authenticatedUser) sessionView = null;
	$: userName = authenticatedUser?.display_name || authenticatedUser?.email || '';
	$: userInitial = (authenticatedUser?.display_name || authenticatedUser?.email || 'U')
		.slice(0, 1)
		.toUpperCase();
	$: if (browser && $authState.status === 'anonymous' && !isAuthRoute) {
		workspaces.set([]);
		void goto(resolve('/login'), { replaceState: true });
	}

	function decodeRoutePart(value: string) {
		try {
			return decodeURIComponent(value);
		} catch {
			return value;
		}
	}

	function setLanguage(value: 'en' | 'zh') {
		language.set(value);
		void showSessionView('main');
	}

	function toggleSessionMenu() {
		sessionView = sessionView ? null : 'main';
	}

	function setTheme(value: ThemePreference) {
		themePreference.set(value);
		void showSessionView('main');
	}

	async function showSessionView(view: 'main' | 'theme' | 'language') {
		const previousView = sessionView;
		sessionView = view;
		await tick();
		const selector =
			view === 'main' ? `[data-preference="${previousView}"]` : '[aria-pressed="true"]';
		sessionMenu?.querySelector<HTMLButtonElement>(selector)?.focus();
	}

	async function loadSession() {
		authError = '';
		try {
			const user = await fetchCurrentSession();
			if (!user && !isAuthRoute) {
				await goto(resolve('/login'), { replaceState: true });
			}
		} catch (error) {
			authError = errorMessage(error);
			if (!isAuthRoute) {
				await goto(resolve('/login'), { replaceState: true });
			}
		}
	}

	async function submitLogout() {
		authError = '';
		try {
			await logout();
		} catch (error) {
			authError = errorMessage(error);
		}
	}

	onMount(() => {
		const stopAuthSynchronization = startAuthSynchronization();
		const stopPermissionSynchronization = startPermissionSynchronization();
		void loadSession();

		const recheckPermissions = () => {
			if ($authState.status === 'authenticated') void refreshPermissions();
		};
		window.addEventListener('focus', recheckPermissions);

		const closeSessionOutside = (event: Event) => {
			if (sessionView && sessionMenu && !event.composedPath().includes(sessionMenu)) {
				sessionView = null;
			}
		};
		const handleKeydown = (event: KeyboardEvent) => {
			if (event.key === 'Escape' && sessionView) {
				event.preventDefault();
				sessionView = null;
				sessionMenu?.querySelector<HTMLButtonElement>('.session-trigger')?.focus();
			}
		};
		window.addEventListener('click', closeSessionOutside);
		window.addEventListener('focusin', closeSessionOutside);
		window.addEventListener('keydown', handleKeydown);
		return () => {
			stopAuthSynchronization();
			stopPermissionSynchronization();
			window.removeEventListener('focus', recheckPermissions);
			window.removeEventListener('click', closeSessionOutside);
			window.removeEventListener('focusin', closeSessionOutside);
			window.removeEventListener('keydown', handleKeydown);
		};
	});

	afterNavigate(({ from, to }) => {
		sessionView = null;
		if (from && to?.url.pathname.startsWith('/admin') && $authState.status === 'authenticated') {
			void refreshPermissions();
		}
	});

	$: workspaceRouteMatch = /^\/workspaces\/([^/]+)/.exec($page.url.pathname);
	$: isWorkspaceRoute = Boolean(workspaceRouteMatch);
	$: isFeedbackRoute = /^\/workspaces\/[^/]+\/feedback(?:\/|$)/.test($page.url.pathname);
	$: headerWorkspaceId = workspaceRouteMatch?.[1] ? decodeRoutePart(workspaceRouteMatch[1]) : '';
	$: headerWorkspace = $workspaces.find((item) => item.workspace_id === headerWorkspaceId);
	$: headerWorkspaceName = headerWorkspace?.name || headerWorkspaceId;
</script>

<div
	class="app-shell"
	class:app-shell--feedback={isFeedbackRoute}
	class:app-shell--login={isAuthRoute}
>
	<header class="site-header" class:site-header--workspace={isWorkspaceRoute}>
		<div class="header-left">
			<a class="brand" href={resolve('/')}>
				<img class="brand-logo" src="/lens-mark-a2.svg" alt="" />
				<div class="brand-text">
					<div class="brand-heading">
						<div class="brand-title">{$t('brand.title')}</div>
						<span
							class="brand-version"
							aria-label={`${$t('brand.version')}: ${appVersion}`}
							title={`${$t('brand.version')}: ${appVersion}`}>{appVersion}</span
						>
					</div>
					{#if $t('brand.sub')}
						<div class="brand-sub">{$t('brand.sub')}</div>
					{/if}
				</div>
			</a>

			{#if isWorkspaceRoute}
				<nav class="header-breadcrumb" aria-label={$t('header.breadcrumbLabel')}>
					<a href={resolve('/')}>{$t('header.breadcrumbWorkspace')}</a>
					<span aria-hidden="true">/</span>
					<span class="header-breadcrumb__current">{headerWorkspaceName}</span>
				</nav>
			{/if}
		</div>

		<div class="header-actions">
			{#if authenticatedUser}
				<ResearchAgentLauncher workspaceId={headerWorkspaceId} />
				<div class="session-menu" bind:this={sessionMenu}>
					<button
						class="session-trigger"
						type="button"
						aria-label={`${$t('header.userMenuLabel')}: ${userName}`}
						aria-controls="session-options"
						aria-expanded={sessionView !== null}
						title={userName}
						on:click|stopPropagation={toggleSessionMenu}
					>
						<span class="session-avatar" aria-hidden="true">{userInitial}</span>
						<span class="session-name">{userName}</span>
						<ChevronDown size={14} aria-hidden="true" />
					</button>
					{#if sessionView}
						<div
							id="session-options"
							class="session-dropdown"
							role="group"
							aria-label={$t('header.userMenuLabel')}
						>
							{#if sessionView === 'main'}
								<div class="session-identity">
									<span class="session-avatar" aria-hidden="true">{userInitial}</span>
									<div>
										<strong>{userName}</strong>
										{#if authenticatedUser.display_name}<span>{authenticatedUser.email}</span>{/if}
									</div>
								</div>
								<div class="session-section">
									<a
										href={resolve('/account')}
										aria-current={$page.url.pathname === '/account' ? 'page' : undefined}
									>
										<Settings size={17} aria-hidden="true" />
										{$t('onboarding.account')}
									</a>
									<button
										type="button"
										data-preference="theme"
										on:click={() => showSessionView('theme')}
									>
										<SunMoon size={17} aria-hidden="true" />
										{$t('header.themeLabel')}
										<span class="session-preference"
											>{$t(
												$themePreference === 'system'
													? 'header.themeSystem'
													: $themePreference === 'light'
														? 'header.themeLight'
														: 'header.themeDark'
											)}</span
										>
										<ChevronRight size={14} aria-hidden="true" />
									</button>
									<button
										type="button"
										data-preference="language"
										on:click={() => showSessionView('language')}
									>
										<Languages size={17} aria-hidden="true" />
										{$t('header.languageLabel')}
										<span class="session-preference"
											>{$language === 'en' ? 'English' : '简体中文'}</span
										>
										<ChevronRight size={14} aria-hidden="true" />
									</button>
								</div>
								{#if adminPath}
									<div class="session-section">
										<a href={resolve(adminPath)}>
											<ShieldCheck size={17} aria-hidden="true" />
											{$t('admin.title')}
										</a>
									</div>
								{/if}
								<div class="session-section">
									<button type="button" on:click={submitLogout}>
										<LogOut size={17} aria-hidden="true" />
										{$t('auth.logout')}
									</button>
								</div>
							{:else}
								<div class="session-subheader">
									<button
										type="button"
										aria-label={$t('header.userMenuBack')}
										on:click={() => showSessionView('main')}
									>
										<ArrowLeft size={18} aria-hidden="true" />
									</button>
									<h2>
										{sessionView === 'theme' ? $t('header.themeLabel') : $t('header.languageLabel')}
									</h2>
								</div>
								{#if sessionView === 'theme'}
									<div class="session-section" role="group" aria-label={$t('header.themeLabel')}>
										<button
											type="button"
											aria-pressed={$themePreference === 'system'}
											on:click={() => setTheme('system')}
										>
											{$t('header.themeSystem')}{#if $themePreference === 'system'}<Check
													size={16}
													aria-hidden="true"
												/>{/if}
										</button>
										<button
											type="button"
											aria-pressed={$themePreference === 'light'}
											on:click={() => setTheme('light')}
										>
											{$t('header.themeLight')}{#if $themePreference === 'light'}<Check
													size={16}
													aria-hidden="true"
												/>{/if}
										</button>
										<button
											type="button"
											aria-pressed={$themePreference === 'dark'}
											on:click={() => setTheme('dark')}
										>
											{$t('header.themeDark')}{#if $themePreference === 'dark'}<Check
													size={16}
													aria-hidden="true"
												/>{/if}
										</button>
									</div>
								{:else}
									<div class="session-section" role="group" aria-label={$t('header.languageLabel')}>
										<button
											type="button"
											aria-pressed={$language === 'en'}
											on:click={() => setLanguage('en')}
										>
											English{#if $language === 'en'}<Check size={16} aria-hidden="true" />{/if}
										</button>
										<button
											type="button"
											aria-pressed={$language === 'zh'}
											on:click={() => setLanguage('zh')}
										>
											简体中文{#if $language === 'zh'}<Check size={16} aria-hidden="true" />{/if}
										</button>
									</div>
								{/if}
							{/if}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	</header>

	<main class="page">
		{#if authError}
			<div class="status status--error" role="status">{authError}</div>
		{/if}
		<slot />
	</main>

	<footer class="site-footer">
		<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- This is a backend API URL, outside the Svelte page router. -->
		<a href={API_DOCS_PATH}>{$t('nav.docs')}</a>
		<span>·</span>
		<span>{$t('footer.pdfNote')}</span>
	</footer>
</div>
