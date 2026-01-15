
// this file is generated — do not edit it


declare module "svelte/elements" {
	export interface HTMLAttributes<T> {
		'data-sveltekit-keepfocus'?: true | '' | 'off' | undefined | null;
		'data-sveltekit-noscroll'?: true | '' | 'off' | undefined | null;
		'data-sveltekit-preload-code'?:
			| true
			| ''
			| 'eager'
			| 'viewport'
			| 'hover'
			| 'tap'
			| 'off'
			| undefined
			| null;
		'data-sveltekit-preload-data'?: true | '' | 'hover' | 'tap' | 'off' | undefined | null;
		'data-sveltekit-reload'?: true | '' | 'off' | undefined | null;
		'data-sveltekit-replacestate'?: true | '' | 'off' | undefined | null;
	}
}

export {};


declare module "$app/types" {
	export interface AppTypes {
		RouteId(): "/" | "/_shared" | "/collections" | "/collections/[id]" | "/collections/[id]/documents" | "/collections/[id]/graph" | "/collections/[id]/reports" | "/collections/[id]/search" | "/collections/[id]/settings" | "/configs" | "/configs/create" | "/configs/list" | "/configs/upload" | "/configs/view" | "/docs" | "/export" | "/index" | "/index/config" | "/index/upload" | "/system" | "/upload";
		RouteParams(): {
			"/collections/[id]": { id: string };
			"/collections/[id]/documents": { id: string };
			"/collections/[id]/graph": { id: string };
			"/collections/[id]/reports": { id: string };
			"/collections/[id]/search": { id: string };
			"/collections/[id]/settings": { id: string }
		};
		LayoutParams(): {
			"/": { id?: string };
			"/_shared": Record<string, never>;
			"/collections": { id?: string };
			"/collections/[id]": { id: string };
			"/collections/[id]/documents": { id: string };
			"/collections/[id]/graph": { id: string };
			"/collections/[id]/reports": { id: string };
			"/collections/[id]/search": { id: string };
			"/collections/[id]/settings": { id: string };
			"/configs": Record<string, never>;
			"/configs/create": Record<string, never>;
			"/configs/list": Record<string, never>;
			"/configs/upload": Record<string, never>;
			"/configs/view": Record<string, never>;
			"/docs": Record<string, never>;
			"/export": Record<string, never>;
			"/index": Record<string, never>;
			"/index/config": Record<string, never>;
			"/index/upload": Record<string, never>;
			"/system": Record<string, never>;
			"/upload": Record<string, never>
		};
		Pathname(): "/" | "/_shared" | "/_shared/" | "/collections" | "/collections/" | `/collections/${string}` & {} | `/collections/${string}/` & {} | `/collections/${string}/documents` & {} | `/collections/${string}/documents/` & {} | `/collections/${string}/graph` & {} | `/collections/${string}/graph/` & {} | `/collections/${string}/reports` & {} | `/collections/${string}/reports/` & {} | `/collections/${string}/search` & {} | `/collections/${string}/search/` & {} | `/collections/${string}/settings` & {} | `/collections/${string}/settings/` & {} | "/configs" | "/configs/" | "/configs/create" | "/configs/create/" | "/configs/list" | "/configs/list/" | "/configs/upload" | "/configs/upload/" | "/configs/view" | "/configs/view/" | "/docs" | "/docs/" | "/export" | "/export/" | "/index" | "/index/" | "/index/config" | "/index/config/" | "/index/upload" | "/index/upload/" | "/system" | "/system/" | "/upload" | "/upload/";
		ResolvedPathname(): `${"" | `/${string}`}${ReturnType<AppTypes['Pathname']>}`;
		Asset(): "/robots.txt" | string & {};
	}
}