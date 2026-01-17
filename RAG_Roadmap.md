# RAG Agent Roadmap & Progress Checklist

## ✅ Completed
- Core RAG pipeline (OpenAI embeddings, MongoDB Atlas Vector Search, LLM integration)
- Dynamic updates (MongoDB Change Streams for incremental re-embedding)
- Modular FastAPI backend (organized structure, ready for full stack)
- Initial memory/context handling (session-based storage, history injection)
- Prompt improvements (context enrichment, token limiter, weighted history)
- Number-sensitive QA design (hybrid retrieval plan, regex extraction, metadata filtering)
- Multilingual modules (translation, TTS in progress)

## 🟡 In Progress
- Memory management
  - NLP entity extraction & coreference resolution (standalone, not yet integrated)
  - Conversation history enrichment logic (partially implemented)
- Context-aware query handling
  - Metadata-aware vector search (filters: account, topic, timestamp)
  - Query enrichment from stored memory (partially planned)
- Evaluation & debugging
  - Debugging RAG pipeline steps
  - Need robust unit tests (embedding, retrieval, prompt injection, answer quality)

## 🔜 Next Steps
- Finish memory handling
  - Complete coreference resolution (AllenNLP SpanBERT)
  - Store/retrieve session history from MongoDB
  - Finalize memory enrichment logic (Steps 3-5)
- Advanced retrieval enhancements
  - Implement hybrid retrieval (semantic + BM25 keyword)
  - Add metadata filtering (date, account_id, topic)
  - Post-retrieval number extraction & validation
- Prompt optimization
  - Improve structured formatting of retrieved chunks
  - Weighted context blocks (last 2 queries prioritized)
  - Token-aware dynamic prompt builder
- Evaluation & benchmarking
  - Build evaluation harness for QA performance
  - Track accuracy on number-sensitive queries
  - Compare semantic-only vs hybrid vs metadata retrieval
- Frontend integration
  - Display top retrieved chunks for transparency
  - Show session-based history & memory usage
  - Enable feedback loop (thumbs up/down → memory learning)

## ⚡ Future Enhancements (Optional)
- Feedback-based learning (improve memory via user corrections)
- Multilingual retrieval (connect with translation pipeline)
- Agent orchestration (tools for DB queries, structured retrieval)

---

# Suggested Timeline

## Stage 1: Finalize Memory & Coreference (1-2 weeks)
- Integrate coreference resolution
- Complete session history storage/retrieval
- Finalize memory enrichment logic

## Stage 2: Advanced Retrieval & Prompting (2 weeks)
- Hybrid retrieval implementation
- Metadata filtering
- Structured/weighted prompt builder

## Stage 3: Evaluation & Frontend (2 weeks)
- Build evaluation harness
- Integrate frontend feedback loop
- Display retrieval/memory transparency

## Stage 4: Future Enhancements (ongoing)
- Feedback-based learning
- Multilingual retrieval
- Agent orchestration
