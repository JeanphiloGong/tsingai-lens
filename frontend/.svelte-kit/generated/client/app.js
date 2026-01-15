export { matchers } from './matchers.js';

export const nodes = [
	() => import('./nodes/0'),
	() => import('./nodes/1'),
	() => import('./nodes/2'),
	() => import('./nodes/3'),
	() => import('./nodes/4'),
	() => import('./nodes/5'),
	() => import('./nodes/6'),
	() => import('./nodes/7'),
	() => import('./nodes/8'),
	() => import('./nodes/9'),
	() => import('./nodes/10'),
	() => import('./nodes/11'),
	() => import('./nodes/12'),
	() => import('./nodes/13'),
	() => import('./nodes/14'),
	() => import('./nodes/15'),
	() => import('./nodes/16'),
	() => import('./nodes/17'),
	() => import('./nodes/18'),
	() => import('./nodes/19'),
	() => import('./nodes/20'),
	() => import('./nodes/21')
];

export const server_loads = [];

export const dictionary = {
		"/": [3],
		"/collections/[id]": [4,[2]],
		"/collections/[id]/documents": [5,[2]],
		"/collections/[id]/graph": [6,[2]],
		"/collections/[id]/reports": [7,[2]],
		"/collections/[id]/search": [8,[2]],
		"/collections/[id]/settings": [9,[2]],
		"/configs": [10],
		"/configs/create": [11],
		"/configs/list": [12],
		"/configs/upload": [13],
		"/configs/view": [14],
		"/docs": [15],
		"/export": [16],
		"/index": [17],
		"/index/config": [18],
		"/index/upload": [19],
		"/system": [20],
		"/upload": [21]
	};

export const hooks = {
	handleError: (({ error }) => { console.error(error) }),
	
	reroute: (() => {}),
	transport: {}
};

export const decoders = Object.fromEntries(Object.entries(hooks.transport).map(([k, v]) => [k, v.decode]));
export const encoders = Object.fromEntries(Object.entries(hooks.transport).map(([k, v]) => [k, v.encode]));

export const hash = false;

export const decode = (type, value) => decoders[type](value);

export { default as root } from '../root.js';