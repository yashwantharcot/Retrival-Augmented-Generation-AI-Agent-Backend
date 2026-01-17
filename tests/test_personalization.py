import os
import re
from app.main import build_llm_prompt, finalize_answer, align_answer_with_context


def test_build_prompt_detail_scaling():
    ctx = [f"Block {i}: Revenue grew 10% year {i}." for i in range(1,30)]
    p_low = build_llm_prompt("Explain revenue", ctx, {"detailLevel":"low"})
    p_high = build_llm_prompt("Explain revenue", ctx, {"detailLevel":"deep"})
    # low should include fewer explicit 'Context ' lines than deep
    low_blocks = p_low.count('Context ')
    high_blocks = p_high.count('Context ')
    assert high_blocks >= low_blocks
    assert low_blocks <= 8  # enforced cap


def test_finalize_answer_trims():
    long_text = ' '.join(['Sentence %d about performance.'%i for i in range(1,200)])
    trimmed = finalize_answer(long_text,{"detailLevel":"low","responseStyle":"summary"})
    # Should include notice of shortening
    assert '[Answer shortened' in trimmed
    words = len(trimmed.split())
    assert words < 250  # ensure trimmed relative to original ~ 1000 words


def test_alignment_basic():
    ctx = ["Context 1: Alpha beta gamma delta.", "Context 2: Market share increased in Q2."]
    answer = "Market share increased sharply. Alpha beta improvements sustained."
    aligned, citations = align_answer_with_context(answer, ctx)
    assert 'C' in aligned  # at least one citation tag
    assert any(c.get('block') == 2 for c in citations)  # second block referenced

