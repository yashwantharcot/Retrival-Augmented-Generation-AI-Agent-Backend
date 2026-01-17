"""Evaluation Harness Outline (Phase D)

Purpose:
- Provide a structured, extensible framework to measure retrieval + answer quality, latency, grounding.
- Start lightweight (YAML/JSON scenario files) and grow into automated regression.

Components:
  1. TestCase model (query, intent, expected_docs, expected_answer_fields, tolerances)
  2. Runner orchestrating: intent → retrieval → answer → metrics
  3. Metrics aggregator (precision@k, recall@k, MRR, factual numeric accuracy, latency)
  4. Report generator (JSON + markdown summary)
  5. CLI entrypoint (python -m app.eval.evaluation_harness run ./tests/specs)

Extensibility Hooks:
  - Plug custom scorers (e.g. semantic similarity for paraphrased answers)
  - Add per-intent metric weighting
  - Integrate feedback logs as pseudo-labeled cases

Environment Variables (optional):
  EVAL_MAX_CASES=50            limit number of cases per run
  EVAL_PARALLEL=4              parallel worker processes
  EVAL_DEFAULT_K=20            retrieval depth for metrics
  EVAL_ENABLE_LATENCY=true     capture stage timings

File Format (YAML example):
```
- id: agg_001
  query: "total discount last quarter"
  intent: AGGREGATION
  expected_docs: ["QT001245","QT001300"]
  required_fields: ["discount_total","timeframe"]
  numeric_expectations:
    discount_total:
      op: ">="
      value: 0
  k: 15
- id: lookup_002
  query: "status of quote QT001245"
  intent: ENTITY_LOOKUP
  expected_answer_contains: ["Approved", "Negotiation"]
  expected_docs: ["QT001245"]
```

Minimal Implementation Steps:
  Step 1: Data classes
  Step 2: Load spec files (YAML/JSON)
  Step 3: Execute pipeline using existing /query or direct internal functions
  Step 4: Compute metrics & build summary
  Step 5: Output artifacts (results.json, summary.md)

This skeleton focuses on Steps 1–3 scaffolding.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple
import time, json, os, glob, math, statistics, datetime

try:
    import yaml  # optional dependency (add to requirements if used)
except Exception:  # graceful fallback
    yaml = None

from .evaluator import Evaluator  # existing simple exact-match (can extend)

# ------------------ Data Models ------------------ #

@dataclass
class NumericExpectation:
    field: str
    op: str
    value: float

    def check(self, actual: float) -> bool:
        ops = {
            "==": lambda a, b: a == b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            "approx": lambda a, b: abs(a - b) / max(1e-9, abs(b)) <= 0.05,
        }
        f = ops.get(self.op)
        if not f:
            return False
        try:
            return f(actual, self.value)
        except Exception:
            return False

@dataclass
class TestCase:
    id: str
    query: str
    intent: Optional[str] = None
    expected_docs: List[str] = field(default_factory=list)
    expected_answer_contains: List[str] = field(default_factory=list)
    required_fields: List[str] = field(default_factory=list)
    numeric_expectations: List[NumericExpectation] = field(default_factory=list)
    k: int = 20

@dataclass
class TestResult:
    id: str
    retrieved_docs: List[str]
    answer: str
    metrics: Dict[str, Any]
    pass_flags: Dict[str, bool]
    timings: Dict[str, float]
    confidence: Dict[str, Any] | None = None

# ------------------ Loader ------------------ #

def load_test_cases(path_pattern: str) -> List[TestCase]:
    cases = []
    for path in glob.glob(path_pattern):
        if path.endswith(('.yaml', '.yml')) and yaml:
            with open(path, 'r', encoding='utf-8') as f:
                raw = yaml.safe_load(f) or []
        elif path.endswith('.json'):
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f) or []
        else:
            continue
        if isinstance(raw, dict):
            raw = [raw]
        for item in raw:
            num_exp = []
            for field_name, spec in (item.get('numeric_expectations') or {}).items():
                num_exp.append(NumericExpectation(field=field_name, op=spec.get('op','=='), value=float(spec.get('value',0))))
            cases.append(TestCase(
                id=item.get('id') or f"case_{len(cases)+1}",
                query=item.get('query',''),
                intent=item.get('intent'),
                expected_docs=item.get('expected_docs') or [],
                expected_answer_contains=item.get('expected_answer_contains') or [],
                required_fields=item.get('required_fields') or [],
                numeric_expectations=num_exp,
                k=int(item.get('k',20))
            ))
    return cases

# ------------------ Core Harness ------------------ #

class EvaluationHarness:
    def __init__(self, query_callable):
        """query_callable: function(query: str) -> {answer:str, docs:[{id:..}]}
        Accepts internal function or wrapper hitting /query endpoint.
        """
        self.query_callable = query_callable
        self.evaluator = Evaluator()

    def run_case(self, case: TestCase) -> TestResult:
        t0 = time.perf_counter()
        resp = self.query_callable(case.query)
        t1 = time.perf_counter()
        answer = resp.get('answer','')
        docs = resp.get('docs', [])
        doc_ids = [d.get('id') or d.get('_id') for d in docs]
    # Basic retrieval metrics at case.k plus global cutoffs (P@5, R@20)
    intersection = set(doc_ids[:case.k]) & set(case.expected_docs)
    precision = (len(intersection) / max(1,len(doc_ids[:case.k]))) if doc_ids else 0.0
    recall = (len(intersection) / max(1,len(case.expected_docs))) if case.expected_docs else 0.0
    # Fixed cutoff metrics
    cutoff_p = 5
    cutoff_r = 20
    top_p = doc_ids[:cutoff_p]
    top_r = doc_ids[:cutoff_r]
    inter_p = set(top_p) & set(case.expected_docs)
    inter_r = set(top_r) & set(case.expected_docs)
    precision_at_5 = (len(inter_p)/max(1,len(top_p))) if top_p else 0.0
    recall_at_20 = (len(inter_r)/max(1,len(case.expected_docs))) if case.expected_docs else 0.0
        # MRR component (first relevant)
        rr = 0.0
        if case.expected_docs:
            for rank, did in enumerate(doc_ids, start=1):
                if did in case.expected_docs:
                    rr = 1.0 / rank
                    break
        # Simple answer containment checks
        contains_flags = {frag: (frag.lower() in answer.lower()) for frag in case.expected_answer_contains}
        # Numeric expectations (placeholder: expects numeric fields in resp['metrics'])
        numeric_flags = {}
        metrics_block = resp.get('metrics', {})
        for ne in case.numeric_expectations:
            actual = metrics_block.get(ne.field)
            ok = False
            if actual is not None:
                try:
                    ok = ne.check(float(actual))
                except Exception:
                    ok = False
            numeric_flags[f"num:{ne.field}"] = ok
        pass_flags = {**contains_flags, **numeric_flags}
        # Aggregate metric object
        result_metrics = {
            "precision@k": precision,
            "recall@k": recall,
            "precision@5": precision_at_5,
            "recall@20": recall_at_20,
            "rr": rr,
            "retrieved_k": len(doc_ids),
            "expected_hit_count": len(intersection),
        }
        timings = {"latency_ms": round((t1 - t0)*1000,2)}
        confidence = resp.get('confidence')
        if confidence:
            # numeric verification ratio if available
            numv = confidence.get('numeric_verification') or {}
            grounded = numv.get('grounded_count') or 0
            total_nums = (numv.get('grounded_count') or 0) + (numv.get('ungrounded_count') or 0)
            if total_nums:
                result_metrics['numeric_grounded_ratio'] = grounded / total_nums
            ec = confidence.get('entity_claim_verification') or {}
            etot = ec.get('entity_total'); eg = ec.get('entity_grounded')
            if etot:
                result_metrics['entity_grounded_ratio'] = (eg or 0)/etot
        return TestResult(
            id=case.id,
            retrieved_docs=doc_ids,
            answer=answer,
            metrics=result_metrics,
            pass_flags=pass_flags,
            timings=timings,
            confidence=confidence
        )

    def run(self, cases: List[TestCase]) -> Dict[str, Any]:
        max_cases = int(os.getenv('EVAL_MAX_CASES','0'))
        if max_cases:
            cases = cases[:max_cases]
        results = [self.run_case(c) for c in cases]
        # Aggregate summary
        if results:
            avg_precision = sum(r.metrics['precision@k'] for r in results)/len(results)
            avg_recall = sum(r.metrics['recall@k'] for r in results)/len(results)
            avg_p5 = sum(r.metrics.get('precision@5',0) for r in results)/len(results)
            avg_r20 = sum(r.metrics.get('recall@20',0) for r in results)/len(results)
            mrr = sum(r.metrics.get('rr',0) for r in results)/len(results)
            latencies = [r.timings['latency_ms'] for r in results]
            lat_p95 = percentile(latencies, 95)
            lat_p99 = percentile(latencies, 99)
            grounded_ratios = [r.metrics.get('numeric_grounded_ratio') for r in results if 'numeric_grounded_ratio' in r.metrics]
            avg_grounded = sum(grounded_ratios)/len(grounded_ratios) if grounded_ratios else None
        else:
            avg_precision = avg_recall = avg_p5 = avg_r20 = mrr = 0.0
            lat_p95 = lat_p99 = 0.0
            avg_grounded = None
        summary = {
            "cases": len(results),
            "avg_precision@k": round(avg_precision,3),
            "avg_recall@k": round(avg_recall,3),
            "avg_precision@5": round(avg_p5,3) if results else 0.0,
            "avg_recall@20": round(avg_r20,3) if results else 0.0,
            "mrr": round(mrr,3),
            "latency_p95_ms": lat_p95,
            "latency_p99_ms": lat_p99,
            "avg_numeric_grounded_ratio": round(avg_grounded,3) if avg_grounded is not None else None,
            "failures": [r.id for r in results if not all(r.pass_flags.values())]
        }
        report = {"summary": summary, "results": [r.__dict__ for r in results]}
        # Optional markdown output
        if os.getenv('EVAL_WRITE_MARKDOWN','true').lower() == 'true':
            try:
                md_path = os.getenv('EVAL_MD_PATH','evaluation_summary.md')
                with open(md_path,'w',encoding='utf-8') as f:
                    f.write(build_markdown_summary(report))
            except Exception:
                pass
        return report

# ------------------ Helper Functions ------------------ #

def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if p <=0: return min(values)
    if p >=100: return max(values)
    vs = sorted(values)
    k = (len(vs)-1) * (p/100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return round(vs[int(k)],2)
    d0 = vs[f]*(c-k); d1 = vs[c]*(k-f)
    return round(d0+d1,2)

def build_markdown_summary(report: Dict[str, Any]) -> str:
    s = report['summary']
    lines = [f"# Evaluation Summary ({datetime.datetime.utcnow().isoformat()}Z)",
             '',
             f"Cases: {s['cases']}",
             f"Avg Precision@k: {s['avg_precision@k']}",
             f"Avg Recall@k: {s['avg_recall@k']}",
             f"Avg Precision@5: {s.get('avg_precision@5')}",
             f"Avg Recall@20: {s.get('avg_recall@20')}",
             f"MRR: {s['mrr']}",
             f"Latency P95 (ms): {s['latency_p95_ms']}",
             f"Latency P99 (ms): {s['latency_p99_ms']}",
             f"Avg Numeric Grounded Ratio: {s.get('avg_numeric_grounded_ratio')}",
             f"Failures: {', '.join(s['failures']) if s['failures'] else 'None'}",
             '', '## Detailed Results', '']
    for r in report['results']:
        lines.append(f"### {r['id']}")
        lines.append(f"Precision@k: {r['metrics']['precision@k']} Recall@k: {r['metrics']['recall@k']} RR: {r['metrics'].get('rr')}")
        lines.append(f"Retrieved: {len(r['retrieved_docs'])} Latency: {r['timings']['latency_ms']} ms")
        if 'numeric_grounded_ratio' in r['metrics']:
            lines.append(f"Numeric Grounded Ratio: {round(r['metrics']['numeric_grounded_ratio'],3)}")
        lines.append('')
    return '\n'.join(lines)

# --------------- Example Local Usage --------------- #
if __name__ == "__main__":
    # Dummy query function for demonstration
    def fake_query(q: str):
        return {
            "answer": f"Answer about {q} Approved amount",  # naive
            "docs": [
                {"id": "QT001245"}, {"id": "QT001300"}
            ],
            "metrics": {"discount_total": 1000}
        }
    harness = EvaluationHarness(fake_query)
    spec_cases = [TestCase(id="agg_001", query="total discount last quarter", expected_docs=["QT001245","QT001300"], expected_answer_contains=["Approved"], k=5)]
    out = harness.run(spec_cases)
    print(json.dumps(out, indent=2))
