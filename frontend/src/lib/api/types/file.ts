export interface UploadResponse {
  id: string;
  status?: string;
  status_message?: string;
}

export interface FileStatusResponse {
  id: string;
  status: string;
  status_message?: string;
  updated_at?: string;
}
