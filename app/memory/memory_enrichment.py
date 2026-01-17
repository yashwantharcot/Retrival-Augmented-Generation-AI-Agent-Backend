# app/memory/memory_enrichment.py
from app.db.memory import get_last_memory



def get_enriched_memory_context(session_id: str, n: int = 5, weight_recent: int = 2, preferences=None, user_id=None):
    """
    Retrieve last n memories for a session and user, prioritize last `weight_recent` queries, and format for prompt injection.
    Personalize output using preferences.
    """
    # Fetch all memories for the session
    memories = get_last_memory(session_id, limit=n)
    # Filter by user_id if provided
    if user_id:
        memories = [mem for mem in memories if mem.get('user_id') == user_id]
    if not memories:
        return ""

    # Personalization: use preferences for tone/detail/domain/tags if provided
    user_tone = preferences.get('tone', 'default') if preferences else 'default'
    detail_level = preferences.get('detail_level', 'standard') if preferences else 'standard'
    domain_expertise = preferences.get('domain_expertise', None) if preferences else None
    custom_tags = preferences.get('custom_tags', []) if preferences else []

    recent = memories[:weight_recent]
    older = memories[weight_recent:]

    context_blocks = []
    for mem in recent:
        tone = mem.get('metadata', {}).get('tone', user_tone)
        detail = mem.get('metadata', {}).get('detail_level', detail_level)
        domain = mem.get('metadata', {}).get('domain_expertise', domain_expertise)
        tags = mem.get('metadata', {}).get('custom_tags', custom_tags)
        block = f"[RECENT][Tone: {tone}][Detail: {detail}][Domain: {domain}][Tags: {tags}] Query: {mem.get('query_text')}\nResponse: {mem.get('llm_response')}\nMetadata: {mem.get('metadata', {})}\n"
        context_blocks.append(block)
    for mem in older:
        tone = mem.get('metadata', {}).get('tone', user_tone)
        detail = mem.get('metadata', {}).get('detail_level', detail_level)
        domain = mem.get('metadata', {}).get('domain_expertise', domain_expertise)
        tags = mem.get('metadata', {}).get('custom_tags', custom_tags)
        block = f"[Tone: {tone}][Detail: {detail}][Domain: {domain}][Tags: {tags}] Query: {mem.get('query_text')}\nResponse: {mem.get('llm_response')}\nMetadata: {mem.get('metadata', {})}\n"
        context_blocks.append(block)

    # Contextual enrichment: add session-level info if available
    session_metadata = memories[0].get('session_metadata', {}) if memories else {}
    if session_metadata:
        context_blocks.insert(0, f"[SESSION] Metadata: {session_metadata}\n")
    # Add domain expertise and custom tags summary if available
    if domain_expertise:
        context_blocks.insert(0, f"[USER] Domain Expertise: {domain_expertise}\n")
    if custom_tags:
        context_blocks.insert(0, f"[USER] Custom Tags: {custom_tags}\n")

    return "\n".join(context_blocks)
    def get_enriched_memory_context(session_id: str, n: int = 5, weight_recent: int = 2, preferences=None, user_id=None):
        """
        Retrieve last n memories for a session and user, prioritize last `weight_recent` queries, and format for prompt injection.
        Personalize output using preferences.
        """
        # Fetch all memories for the session
        memories = get_last_memory(session_id, limit=n)
        # Filter by user_id if provided
        if user_id:
            memories = [mem for mem in memories if mem.get('user_id') == user_id]
        if not memories:
            return ""

        # Personalization: use preferences for tone/detail if provided
        user_tone = preferences.get('tone', 'default') if preferences else 'default'
        detail_level = preferences.get('detail_level', 'standard') if preferences else 'standard'

        recent = memories[:weight_recent]
        older = memories[weight_recent:]

        context_blocks = []
        for mem in recent:
            tone = mem.get('metadata', {}).get('tone', user_tone)
            detail = mem.get('metadata', {}).get('detail_level', detail_level)
            block = f"[RECENT][Tone: {tone}][Detail: {detail}] Query: {mem.get('query_text')}\nResponse: {mem.get('llm_response')}\nMetadata: {mem.get('metadata', {})}\n"
            context_blocks.append(block)
        for mem in older:
            tone = mem.get('metadata', {}).get('tone', user_tone)
            detail = mem.get('metadata', {}).get('detail_level', detail_level)
            block = f"[Tone: {tone}][Detail: {detail}] Query: {mem.get('query_text')}\nResponse: {mem.get('llm_response')}\nMetadata: {mem.get('metadata', {})}\n"
            context_blocks.append(block)

        # Contextual enrichment: add session-level info if available
        session_metadata = memories[0].get('session_metadata', {}) if memories else {}
        if session_metadata:
            context_blocks.insert(0, f"[SESSION] Metadata: {session_metadata}\n")

        return "\n".join(context_blocks)
