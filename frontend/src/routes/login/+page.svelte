<script lang="ts">
	import { goto } from '$app/navigation';
	import { authState, login } from '../_shared/auth';
	import { errorMessage } from '../_shared/api';
	import { language, t } from '../_shared/i18n';
	import { ChevronDown, Globe2 } from '@lucide/svelte';

	let email = '';
	let password = '';
	let loading = false;
	let error = '';

	function changeLanguage(event: Event) {
		const value = (event.currentTarget as HTMLSelectElement).value;
		if (value === 'en' || value === 'zh') language.set(value);
	}

	$: if ($authState.status === 'authenticated') {
		void goto('/', { replaceState: true });
	}

	async function submitLogin(event: SubmitEvent) {
		event.preventDefault();
		error = '';

		if (!email.trim() || !password) {
			error = $t('auth.missingCredentials');
			return;
		}

		loading = true;
		try {
			await login(email.trim(), password);
			await goto('/', { replaceState: true });
		} catch (err) {
			error = errorMessage(err);
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{$t('auth.pageTitle')}</title>
</svelte:head>

<section class="login-shell" aria-labelledby="login-title">
	<div class="login-panel">
		<img class="login-mark" src="/lens-mark-a2.svg" alt="" />
		<h1 id="login-title">{$t('auth.title')}</h1>

		<form class="login-form" on:submit={submitLogin}>
			<label class="field" for="auth-email">
				<span>{$t('auth.email')}</span>
				<input
					id="auth-email"
					class="input"
					type="email"
					autocomplete="username"
					bind:value={email}
					disabled={loading}
				/>
			</label>

			<label class="field" for="auth-password">
				<span>{$t('auth.password')}</span>
				<input
					id="auth-password"
					class="input"
					type="password"
					autocomplete="current-password"
					bind:value={password}
					disabled={loading}
				/>
			</label>

			{#if error}
				<div class="status status--error" role="alert">{error}</div>
			{/if}

			<button class="btn btn--primary" type="submit" disabled={loading}>
				{loading ? $t('auth.signingIn') : $t('auth.signIn')}
			</button>
		</form>
	</div>

	<div class="login-language">
		<Globe2 size={16} strokeWidth={1.8} aria-hidden="true" />
		<label class="sr-only" for="login-language">{$t('header.languageLabel')}</label>
		<select id="login-language" value={$language} on:change={changeLanguage}>
			<option value="en">English</option>
			<option value="zh">简体中文</option>
		</select>
		<ChevronDown size={14} strokeWidth={1.8} aria-hidden="true" />
	</div>
</section>
