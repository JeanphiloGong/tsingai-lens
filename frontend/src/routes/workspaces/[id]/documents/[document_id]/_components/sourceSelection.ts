import type { DocumentSourceSelection } from '../../../../../_shared/documents';

type SourceSelectionOptions = {
	selection: DocumentSourceSelection | null;
	disabled: boolean;
	onToggle: (selection: DocumentSourceSelection) => void;
};

export function selectableSource(node: HTMLElement, options: SourceSelectionOptions) {
	let start: { x: number; y: number } | null = null;
	function update(next: SourceSelectionOptions) {
		options = next;
		node.classList.toggle('source-selectable', Boolean(next.selection));
		if (next.selection) node.dataset.sourceRef = next.selection.source_ref;
		else delete node.dataset.sourceRef;
		node.classList.toggle('source-selection-disabled', next.disabled);
	}
	function pointerdown(event: PointerEvent) {
		start = { x: event.clientX, y: event.clientY };
	}
	function click(event: MouseEvent) {
		if (!options.selection || options.disabled || event.defaultPrevented || event.detail > 1)
			return;
		if (
			event.target instanceof Element &&
			event.target.closest('a, button, input, textarea, select, summary, [contenteditable="true"]')
		)
			return;
		if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 5) return;
		if (window.getSelection()?.isCollapsed === false) return;
		options.onToggle(options.selection);
	}
	update(options);
	node.addEventListener('pointerdown', pointerdown);
	node.addEventListener('click', click);
	return {
		update,
		destroy() {
			node.removeEventListener('pointerdown', pointerdown);
			node.removeEventListener('click', click);
		}
	};
}
