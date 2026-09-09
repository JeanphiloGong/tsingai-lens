export type PaperUploadStatus =
	| 'selected'
	| 'uploading'
	| 'preparing'
	| 'queued'
	| 'already_uploaded'
	| 'upload_failed'
	| 'preparation_failed';

export type PaperUploadItem = {
	key: string;
	file: File;
	status: PaperUploadStatus;
	documentId: string | null;
	error: string;
};
