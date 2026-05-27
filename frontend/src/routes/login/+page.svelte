<script lang="ts">
	import { goto } from '$app/navigation';
	import { authState, login } from '../_shared/auth';
	import { errorMessage } from '../_shared/api';
	import { t } from '../_shared/i18n';

	let email = '';
	let password = '';
	let loading = false;
	let error = '';

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

<section class="login-shell">
	<div class="login-panel">
		<p class="eyebrow">{$t('auth.eyebrow')}</p>
		<h1>{$t('auth.title')}</h1>
		<p class="lead">{$t('auth.lead')}</p>

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
</section>
