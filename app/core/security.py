"""Security & PII controls layer.

Features:
  - Role-based row-level filter construction for Mongo queries
  - PII redaction pass over context blocks before prompt assembly

Env:
  SECURITY_ENABLE=true|false
  SECURITY_ALLOWED_FIELDS (comma list) -> if set, only these metadata keys kept
  SECURITY_ROLE_FIELD=owner         (metadata/user field used for owner restriction)
  SECURITY_REGION_FIELD=region      (metadata/user field used for region restriction)
  SECURITY_PII_EMAIL_REDACT=true
  SECURITY_PII_ID_PATTERN=          (optional custom regex)

Row-level policy (simplified):
  - If role == 'admin' -> no extra filter
  - If role == 'manager' and region set -> restrict to docs with same region
  - Else (rep/user) restrict to owner == user_id OR shared flag (metadata.shared == True)

PII Redaction:
  - Emails
  - 16+ digit sequences (potential account IDs) -> masked
  - Custom pattern (if provided)
"""
from __future__ import annotations
import os, re
from typing import Dict, List

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,10}')
LONG_NUM_RE = re.compile(r'\b\d{16,}\b')

def build_row_level_filter(user_profile: Dict) -> Dict:
    if not os.getenv('SECURITY_ENABLE','true').lower() == 'true':
        return {}
    role = (user_profile or {}).get('role','user').lower()
    region = (user_profile or {}).get('region')
    user_id = (user_profile or {}).get('user_id')
    owner_field = os.getenv('SECURITY_ROLE_FIELD','owner')
    region_field = os.getenv('SECURITY_REGION_FIELD','region')
    if role == 'admin':
        return {}
    if role == 'manager' and region:
        return {f'metadata.{region_field}': region}
    # default rep
    if user_id:
        return { '$or': [ {f'metadata.{owner_field}': user_id}, {'metadata.shared': True} ] }
    return {}

def redact_pii(blocks: List[str]) -> List[str]:
    if not blocks:
        return []
    if os.getenv('SECURITY_ENABLE','true').lower() != 'true':
        return blocks
    email_redact = os.getenv('SECURITY_PII_EMAIL_REDACT','true').lower() == 'true'
    custom_pat = os.getenv('SECURITY_PII_ID_PATTERN')
    custom_re = re.compile(custom_pat) if custom_pat else None
    out = []
    for b in blocks:
        text = b
        if email_redact:
            text = EMAIL_RE.sub('[REDACTED_EMAIL]', text)
        text = LONG_NUM_RE.sub('[REDACTED_ID]', text)
        if custom_re:
            text = custom_re.sub('[REDACTED_TOKEN]', text)
        out.append(text)
    return out

def filter_allowed_metadata(meta: Dict) -> Dict:
    allow_raw = os.getenv('SECURITY_ALLOWED_FIELDS')
    if not allow_raw:
        return meta
    allowed = {k.strip() for k in allow_raw.split(',') if k.strip()}
    return {k:v for k,v in (meta or {}).items() if k in allowed}

__all__ = ['build_row_level_filter','redact_pii','filter_allowed_metadata']