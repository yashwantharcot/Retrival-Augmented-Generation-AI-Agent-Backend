"""CLI entrypoint to run evaluation harness over golden set specs.

Usage:
  python -m app.eval.run_eval --pattern tests/golden/*.yaml --out results_eval.json

Env (optional):
  EVAL_MAX_CASES, EVAL_WRITE_MARKDOWN, EVAL_MD_PATH (see evaluation_harness.py)
"""
from __future__ import annotations
import argparse, json
from app.eval.evaluation_harness import load_test_cases, EvaluationHarness

# Thin internal query callable placeholder; in production hook internal pipeline
from app.main import app
from fastapi.testclient import TestClient
client = TestClient(app)

def query_internal(q: str):
    # Assumes /query endpoint exists returning JSON with answer, docs, confidence
    r = client.get('/query', params={'q': q})
    if r.status_code != 200:
        return {'answer':'', 'docs':[], 'error': r.text}
    return r.json()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pattern', required=True, help='Glob pattern for spec files')
    ap.add_argument('--out', default='evaluation_results.json')
    args = ap.parse_args()
    cases = load_test_cases(args.pattern)
    if not cases:
        print('No test cases found.')
        return
    harness = EvaluationHarness(query_internal)
    report = harness.run(cases)
    with open(args.out,'w',encoding='utf-8') as f:
        json.dump(report,f,indent=2)
    print(f"Wrote {args.out}. Summary: {report['summary']}")

if __name__ == '__main__':
    main()
