# app/pipeline/rag_engine.py
from app.prompt.token_limiter import format_structured_data
import logging

# Embeddings & Search
from app.core.embeddings import get_query_embedding
from app.db.vector_store import search_similar_documents

# Prompt Construction


# Memory Components
from app.memory.memory_manager import (
    add_query_to_memory,
    get_query_history,
    get_metadata_filter
)
from app.memory.memory_pipeline import enrich_query_with_memory

# Coreference Resolution
from app.core.coreference import resolve_coreference

# LLM Engine
from app.core.llm import OpenAIEngine

# Logger
log_info = logging.getLogger("rag_engine")

import logging
from typing import List, Dict, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

# Embeddings & Search
from app.core.embeddings import get_query_embedding
 

# Prompt Construction


# Memory Components
from app.memory.memory_manager import (
    add_query_to_memory,
    get_query_history,
    get_metadata_filter
)
from app.memory.memory_pipeline import enrich_query_with_memory

# Coreference Resolution
from app.core.coreference import resolve_coreference

# LLM Engine
from app.core.llm import OpenAIEngine


class RAGEngine:
    def __init__(self, retriever, llm=None):
        self.retriever = retriever
        self.llm = llm or OpenAIEngine()
        self.logger = logging.getLogger('rag_engine')
        

    def run(self, query: str, session_id: str) -> Dict:
        """Execute the full RAG pipeline for a given query."""
        try:
            
            history = get_query_history(session_id)
            
            resolved_query = resolve_coreference(query, history[0]['query'] if history else query, history)
            
            enriched_query = enrich_query_with_memory(session_id, resolved_query)
            

            # Step 4-6: Document retrieval
            query_embedding = [float(x) for x in get_query_embedding(enriched_query)]
            
            metadata_filter = get_metadata_filter(session_id)
            
            documents = search_similar_documents(
                query_vector=query_embedding,
                k=4,
                metadata_filter=metadata_filter
            )
            
            

            # Step 7: Try structured response first
            structured_response = self._format_structured_response(documents, enriched_query)
            if structured_response:
                
                self._store_in_memory(session_id, query, enriched_query, structured_response)
                return structured_response

            # Step 8: LLM fallback
            response = self._generate_llm_response(enriched_query, documents)
            
            self._store_in_memory(session_id, query, enriched_query, response)
            return response

        except Exception as e:
            self.logger.error(f"RAG pipeline failed: {str(e)}", exc_info=True)
            return {
                "error": "Failed to process query",
                "details": str(e)
            }

    def _format_structured_response(self, documents: List[Dict], query: str) -> Optional[Dict]:
        """Attempt to create structured response from documents."""
        
        if not documents:
            self.logger.debug("No documents found for structured response")
            return None
        try:
            response = format_structured_data(documents, query)
            
            if response:
                
                return {
                    **response,
                    "source": "structured_data",
                    "documents_used": [doc.get('doc_id') for doc in documents]
                }
            return None
        except Exception as e:
            self.logger.warning(f"Structured data formatting failed: {str(e)}")
            return None

    def _generate_llm_response(self, query: str, documents: List[Dict]) -> Dict:
        """Generate response using LLM fallback."""
        
        prompt, _ = build_enriched_prompt(query, documents or [])
        
        response = self.llm.complete(prompt)
        
        return {
            "answer": response,
            "source": "llm_generation",
            "documents_used": [doc.get('doc_id') for doc in documents] if documents else []
        }

    def _store_in_memory(self, session_id: str, query: str, resolved_query: str, response: Dict):
        """Store conversation in memory."""
        
        try:
            add_query_to_memory(
                session_id=session_id,
                query=query,
                resolved_query=resolved_query,
                response=response
            )
            
        except Exception as e:
            self.logger.error(f"Failed to store in memory: {str(e)}")


    def rag_pipeline(query: str, session_id: str, retriever=None) -> Dict:
        """Convenience wrapper for RAG pipeline."""
        return RAGEngine(retriever).run(query, session_id)
# Convenience wrapper

    def complete(self, prompt: str) -> str:
        return self.chat(prompt)
