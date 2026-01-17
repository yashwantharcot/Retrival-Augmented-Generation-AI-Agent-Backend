"""Auto-calibration for hybrid retrieval source weights.

Approach:
  - Collect per-query contribution stats for each source:
      * reciprocal rank sum of that source's unique docs appearing in top K fused
      * coverage: fraction of fused top K containing at least one doc from source
  - Maintain sliding window (deque) of last N queries (env: FUSION_AUTOCALIBRATE_WINDOW, default 50)
  - Periodically (every M queries; env: FUSION_AUTOCALIBRATE_INTERVAL) recompute dynamic weights:
        weight_source = (avg_reciprocal_rank_sum + epsilon) / total_sum
        then scaled so mean weight == 1.0 (stability)
  - Exposed API get_dynamic_weights() returns dynamic merged with any static env override map.

Environment Flags:
  FUSION_AUTOCALIBRATE_ENABLE=true|false
  FUSION_AUTOCALIBRATE_WINDOW=50
  FUSION_AUTOCALIBRATE_INTERVAL=8
  FUSION_AUTOCALIBRATE_MIN_DOCS=3   # skip calibration if too few fused docs

Thread safety: simple; FastAPI default single-threaded per worker. For multi-worker, per-process calibration is acceptable.
"""
from __future__ import annotations
from collections import deque, defaultdict
from typing import Dict, List
import os, json, math

class FusionAutoCalibrator:
    def __init__(self):
        self.enabled = os.getenv("FUSION_AUTOCALIBRATE_ENABLE","false").lower() == "true"
        self.window = int(os.getenv("FUSION_AUTOCALIBRATE_WINDOW","50"))
        self.interval = int(os.getenv("FUSION_AUTOCALIBRATE_INTERVAL","8"))
        self.min_docs = int(os.getenv("FUSION_AUTOCALIBRATE_MIN_DOCS","3"))
        self.samples: deque = deque(maxlen=self.window)
        self.dynamic_weights: Dict[str,float] = {}
        self.query_counter = 0

    def record(self, fused_candidates: List[object]):  # candidate objects from fusion_rerank
        if not self.enabled:
            return
        if not fused_candidates or len(fused_candidates) < self.min_docs:
            return
        # Build per-source reciprocal rank sum in top K
        per_source_rr = defaultdict(float)
        seen_ids = set()
        for idx, c in enumerate(fused_candidates, start=1):
            # Avoid double counting same id if appears (shouldn't normally)
            if c.id in seen_ids:
                continue
            seen_ids.add(c.id)
            # Source may be original; we stored original source in candidate.source
            s = getattr(c, 'source', 'unknown') or 'unknown'
            per_source_rr[s] += 1.0/idx
        self.samples.append(per_source_rr)
        self.query_counter += 1
        if self.query_counter % self.interval == 0:
            self._recompute()

    def _recompute(self):
        # Aggregate sums
        total_per_source = defaultdict(float)
        for snap in self.samples:
            for s, val in snap.items():
                total_per_source[s] += val
        if not total_per_source:
            return
        # Average
        avg = {s: total_per_source[s] / len(self.samples) for s in total_per_source}
        # Normalize so mean = 1.0
        mean_val = sum(avg.values())/len(avg)
        if mean_val <= 0:
            return
        scaled = {s: (v/mean_val) for s,v in avg.items()}
        self.dynamic_weights = scaled

    def get_dynamic_weights(self) -> Dict[str,float]:
        if not self.enabled:
            return {}
        return dict(self.dynamic_weights)

_fusion_calibrator_singleton: FusionAutoCalibrator | None = None

def get_fusion_calibrator() -> FusionAutoCalibrator:
    global _fusion_calibrator_singleton
    if _fusion_calibrator_singleton is None:
        _fusion_calibrator_singleton = FusionAutoCalibrator()
    return _fusion_calibrator_singleton

__all__ = ["get_fusion_calibrator"]
