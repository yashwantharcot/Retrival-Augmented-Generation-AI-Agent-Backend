# app/memory/memory_entry.py

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class MemoryEntry(BaseModel):
    """
    Pydantic model for storing memory entries in MongoDB for a RAG system.
    """

    query: str = Field(..., description="Original user query")
    entities: List[str] = Field(default_factory=list, description="Named or resolved entities from query")
    embedding: List[float] = Field(..., description="Vector embedding of the query")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata like topic, session_id, etc.")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of memory entry creation")

    def __init__(self, **data):
        
        super().__init__(**data)

    def validate(self):
        
        return super().validate()

