# Dealdox CPQ Data Normalization & Enrichment Specification (Template)

Status: DRAFT  
Owner: <name / team>  
Version: 0.1  
Last Updated: <yyyy-mm-dd>

---
## 1. Scope & Goals
Purpose: Define a canonical, analytics + retrieval friendly layer over raw `dev_db` collections (MERN CPQ).  
Goals:
- Consistent schemas (stable field names + types)
- High‑quality denormalized “search documents” for hybrid RAG (lexical + vector + structured)
- Deterministic enrichment & derived metrics (discount %, cycle time, probability buckets)
- Support fast intent types: lookup, aggregation, comparison, insight
- Provide traceable lineage & validation rules

Out of Scope (for now): historical SCD type-2 tracking, real‑time streaming CDC, multi‑tenant isolation logic (unless noted).

---
## 2. Source Inventory
List each raw collection / API feed.
| Source Name | Type | Collection / Endpoint | Primary Key | Incremental Field | Notes |
|-------------|------|-----------------------|-------------|-------------------|-------|
| Accounts    | Mongo | `accounts` (if exists) / fallback inside quotes | `account_id` | `updated_at` | May not exist separately – derive from quotes/opportunities |
| Opportunities | Mongo | `opportunities` | `opportunity_id` | `updated_at` | Stage progression timeline |
| Quotes      | Mongo | `dd_quotes` | `quote_id` (or _id) | `updated_at` | Core pricing + discount data |
| Line Items  | Mongo | `quote_line_items` | composite (quote_id + line_seq) | `updated_at` | Might be embedded; confirm structure |
| Pricing Rules | Mongo | `pricing_rules` | `rule_id` | `updated_at` | For explanation features |
| Discount Policies | Mongo | `discount_policies` | `policy_id` | `updated_at` | Approval thresholds |
| Approvals   | Mongo | `approvals` | `approval_id` | `updated_at` | Status, latency |
| Activities / Notes | Mongo | `activities` | `activity_id` | `timestamp` | Sales notes / emails |
| Users / Owners | Mongo | `users` | `user_id` | `updated_at` | Owner normalization |

Add / adjust as discovered.

---
## 3. Canonical Entity Model
Minimal core entities and relationships:
```
Account 1---* Opportunity 1---* Quote 1---* LineItem
Quote *---* Approval (via quote_id)
Quote *---* Activity (conversation / note tagging)
Quote *---* PricingRule (applied_rules array of rule_id)
User 1---* (Account|Opportunity|Quote) (ownership / created_by)
```

---
## 4. Standard Field Dictionary
Define canonical names → raw variants.
| Canonical Field | Type | Raw Aliases | Example | Notes |
| account_id | string | `accountId`,`acct_id` | AC123 | Stable join key |
| account_name | string | `accountName`,`acct` | Acme Corp | Lowercase + trimmed stored in `account_name_norm` |
| opportunity_id | string | `opp_id` | OP7788 | |
| opportunity_name | string | `oppName` | Phoenix Q4 Expansion | |
| quote_id | string | `_id`, `quoteId` | QT001245 | |
| owner_id | string | `ownerId`,`rep_id` | U459 | Maps to user |
| owner_name | string | `ownerName`,`rep` | Jane Smith | Derive normalized version |
| stage | string | `stage`,`status` | Negotiation | Controlled vocab mapping |
| amount | number | `amount`,`total`,`value` | 15250.75 | Base currency (store normalized) |
| currency | string | `currencyCode` | USD | Uppercase, default from org |
| discount_amount | number | `discountAmount` | 1250 | |
| discount_pct | number | (derived) | 0.0768 | discount_amount / (amount + discount_amount) or (list - net)/list |
| list_price_total | number | `listTotal` | 16500 | |
| net_price_total | number | `netTotal` | 15250 | |
| created_at | datetime | `created_at`,`createdAt` | 2025-09-10T11:22:33Z | All stored UTC ISO8601 |
| updated_at | datetime | `updated_at` | 2025-09-11T03:10:00Z | |
| close_date | date | `closeDate`,`expectedClose` | 2025-12-01 | |
| approval_status | string | `approvalStatus` | Approved | Enum |
| approval_latency_hours | number | (derived) | 14.5 | First submitted -> approved |
| cycle_time_days | number | (derived) | 37 | created_at -> close_date (or now) |
| win_probability | number | `winProb` | 0.42 | Bucket after normalization |
| win_prob_bucket | string | (derived) | 40-49% | For faceting |
| line_items_count | integer | (derived) | 7 | |
| line_items_summary | string | (derived) | "7 items: routers(3), switches(2), licenses(2)" | Token-limited summary |
| key_terms | array<string> | (derived) | ["renewal","hardware","multi-year"] | Phrase extraction |
| anomalies | array<string> | (derived) | ["High discount", "Long cycle"] | Rule-based flags |

Extend as needed.

---
## 5. Denormalized Search Documents
Produce 3 primary document granularities:
1. `search_quote_core` (one per quote) – high-cardinality, used for most lookups.  
2. `search_opportunity_agg` – aggregates from quotes, opportunity level metrics.  
3. `search_activity_chunk` – semantic text chunks (notes, approvals rationale, pricing explanations, PDF extracts).  

### 5.1 `search_quote_core` Schema (Proposed)
```
{
  _id: <quote_id>,
  entity_type: "quote",
  account_id, account_name, account_name_norm,
  opportunity_id, opportunity_name,
  owner_id, owner_name, owner_name_norm,
  stage, stage_history: [{stage, entered_at}],
  amount, currency,
  list_price_total, net_price_total, discount_amount, discount_pct,
  created_at, updated_at, close_date,
  cycle_time_days, approval_status, approval_latency_hours,
  win_probability, win_prob_bucket,
  line_items_count, line_items_summary,
  key_terms, anomalies,
  applied_rules: [rule_id],
  approvals: [{approval_id, status, decided_at}],
  recency_rank: <computed>,
  embeddings: { short_desc_vec: <vector>, summary_vec: <vector> }
}
```

### 5.2 `search_opportunity_agg` Key Derived Metrics
- quotes_count, open_quotes_count
- total_pipeline_amount
- weighted_amount (Σ amount * win_probability)
- avg_discount_pct (weighted)
- avg_cycle_time_days
- last_activity_at
- stage_age_days (time since stage entered)

### 5.3 `search_activity_chunk`
- chunk_id, parent_type (quote|opportunity), parent_id
- account_id, opportunity_id, quote_id
- chunk_text (<= ~1200 chars)
- chunk_type (note|approval|pricing_explanation|pdf_excerpt)
- source_ref (activity_id / approval_id / file id)
- created_at
- tokens (approx)
- embedding_vec
- key_terms

---
## 6. Enrichment / Derivation Logic
| Derived Field | Formula / Logic | Edge Cases |
| discount_pct | If list_price_total>0: 1 - (net_price_total / list_price_total) else null | Guard divide by zero |
| approval_latency_hours | (approved_at - first_submitted_at)/3600 | Missing approved_at -> null |
| cycle_time_days | (close_date or now) - created_at (days) | If missing close_date & > N days → flag stale |
| win_prob_bucket | floor(win_probability*100/10)*10 + '-' + next bucket | Clamp 0..1 |
| anomalies | Rule set (see Section 11) | Emits zero or more |
| line_items_summary | Group line items by product family; show top 5 + count | Fallback "n items" |
| key_terms | Keyword + noun phrase extraction (RAKE / regex) | Deduplicate lowercased |

---
## 7. Processing Pipeline Stages
1. Extract (raw Mongo queries; batch by updated_at > last_watermark)
2. Normalize (field rename, type coercion, trimming, lowercasing norms)
3. Enrich (calculations, summaries, anomaly rules)
4. Chunk (activities / long text split by semantic boundaries)
5. Embed (parallel pool; respect provider fallback order)
6. Index (write to `search_*` collections + refresh secondary indexes)
7. Validate (schema + quality checks)
8. Publish watermark & metrics

---
## 8. Scheduling & SLAs
| Layer | Frequency | Target Latency | Notes |
| Incremental ETL | Every 5 min | <90s per batch | Only changed docs |
| Full Rebuild | Weekly | <2h | Off-peak |
| Vector Refresh (changed docs) | Same as ETL | <120s | Queue embeddings |
| Aggregations (opportunity) | Hourly | <60s | Precompute for speed |

---
## 9. Indexing Strategy
Mongo (operational): ensure compound indexes:  
- `search_quote_core`: (account_id), (opportunity_id), (owner_id), (stage, updated_at), (win_prob_bucket)  
- TTL (optional) for soft-deleted staging docs.
Vector Indexes:  
- `quote_summary_vec` (short summary)  
- `activity_chunk_vec`  
Lexical Engine (OpenSearch/Elastic suggested):  
- Index A: quotes (boost: account_name^2, opportunity_name^2, line_items_summary^1.5, anomalies^0.8)  
- Index B: activity chunks (chunk_text)  
Fielddata for faceting: stage, owner_name_norm, win_prob_bucket, approval_status.

---
## 10. Data Quality Rules
| Rule | Severity | Action |
| created_at missing | ERROR | Reject document & log
| amount < 0 | ERROR | Reject / alert
| discount_pct > 0.95 | WARN | Flag anomaly
| win_probability not 0..1 | ERROR | Clamp + log
| stage not in controlled set | WARN | Map to OTHER
| duplicate quote_id | ERROR | Upsert with version increment

---
## 11. Anomaly Rule Set (Initial)
- High Discount: discount_pct > 0.35
- Long Cycle: cycle_time_days > P90 historical
- Fast Approval: approval_latency_hours < 1 AND amount > threshold (flag for audit)
- Stale Stage: stage_age_days > stage_max_days[stage]

Store anomalies array for retrieval explanations.

---
## 12. Security & Governance
- Row filter: user can only see quotes where (owner_id in team OR account assigned) unless admin.
- PII scrub for activity chunks: regex mask emails, phone numbers before embedding.
- Audit log: pipeline run id, counts (processed/errored/skipped), watermark.

---
## 13. Lineage & Versioning
Maintain `schema_version` in each search document. Increment on breaking change. Provide migration script template. Keep changelog in `SCHEMA_CHANGELOG.md`.

---
## 14. Validation & Metrics
Emit after each batch:
```
processed: <n>
inserted: <n>
updated: <n>
skipped: <n>
errors: <n>
error_samples: [quote_id,...]
embedding_queue: <n>
lag_seconds: <max(now - updated_at)>
```
Quality spot checks (sample 50): numeric sanity (amount>0), discount_pct distribution, stage coverage.

---
## 15. Testing Strategy
- Unit: field coercion, derived calc formulas
- Property: discount_pct within [0,1], win_probability buckets partition space
- Integration: end-to-end batch with synthetic fixtures
- Regression: snapshot of P50/P95 cycle_time_days vs baseline

---
## 16. Rollout Plan
Phase 1: Quotes + basic enrichment + embeddings  
Phase 2: Opportunity aggregations + anomalies  
Phase 3: Activity chunk embeddings + lexical hybrid  
Phase 4: Governance & lineage instrumentation  
Phase 5: Advanced analytics (trend baselines, anomaly auto-suppression)

---
## 17. Open Questions / TODO
- Exact raw collection names for accounts & line items?  
- Do discounts exist per line or only header?  
- Multi-currency handling (FX normalization strategy)?  
- Need historical stage snapshots?  
- Approval SLA thresholds configurable per region?

---
## 18. Acceptance Criteria (for Phase 1 Complete)
- >= 98% quotes represented in `search_quote_core`
- All mandatory canonical fields present
- Derived fields discount_pct & cycle_time_days populated for >= 95% eligible docs
- Embeddings available for >= 95% quotes without error
- Average incremental pipeline batch < 90s; P95 < 150s
- Validation dashboard shows zero ERROR severity unresolved

---
## 19. Appendix: Sample Normalized Quote (Redacted)
```
{
  "_id": "QT001245",
  "entity_type": "quote",
  "account_id": "AC123",
  "account_name": "Acme Corp",
  "account_name_norm": "acme corp",
  "opportunity_id": "OP7788",
  "opportunity_name": "Phoenix Q4 Expansion",
  "owner_id": "U459",
  "owner_name": "Jane Smith",
  "owner_name_norm": "jane smith",
  "stage": "Negotiation",
  "stage_history": [
    {"stage": "Qualification", "entered_at": "2025-07-10T09:00:00Z"},
    {"stage": "Proposal", "entered_at": "2025-08-01T12:00:00Z"},
    {"stage": "Negotiation", "entered_at": "2025-08-15T15:30:00Z"}
  ],
  "amount": 15250.75,
  "currency": "USD",
  "list_price_total": 16500,
  "net_price_total": 15250.75,
  "discount_amount": 1249.25,
  "discount_pct": 0.0757,
  "created_at": "2025-07-05T11:22:33Z",
  "updated_at": "2025-09-11T03:10:00Z",
  "close_date": "2025-10-01",
  "cycle_time_days": 58,
  "approval_status": "Approved",
  "approval_latency_hours": 14.5,
  "win_probability": 0.42,
  "win_prob_bucket": "40-49%",
  "line_items_count": 7,
  "line_items_summary": "7 items: routers(3), switches(2), licenses(2)",
  "key_terms": ["renewal","hardware","multi-year"],
  "anomalies": ["High Discount"],
  "applied_rules": ["PRC_RULE_17","DISC_POLICY_A"],
  "approvals": [{"approval_id":"APR998","status":"Approved","decided_at":"2025-08-20T01:00:00Z"}],
  "recency_rank": 0.18,
  "embeddings": {"short_desc_vec": "<vector>", "summary_vec": "<vector>"},
  "schema_version": 1
}
```

---
## 20. Change Log
| Version | Date | Author | Change |
|---------|------|--------|--------|
| 0.1 | <today> | <you> | Initial draft template |
