from typing import Dict, List, Optional
from pydantic import BaseModel, Field

class FileStatusResponse(BaseModel):
    id: str
    status: str
    status_message: str = ""
    updated_at: str


class FileUploadResponse(BaseModel):
    id: str
    status: Optional[str] = None
