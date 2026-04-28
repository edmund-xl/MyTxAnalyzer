# 12 Security, Privacy, and Operations

## 1. Secrets

Secrets must come from environment variables or secret manager:

- RPC URLs
- Explorer API keys
- LLM API keys
- Object store credentials
- Database password

Never store secrets in:

- Git repo
- frontend bundle
- raw logs
- job_run.input unless redacted

## 2. RBAC

| Role | Capabilities |
|---|---|
| admin | manage networks, users, all cases |
| analyst | create/run cases, draft reports |
| reviewer | approve/reject findings, publish reports |
| reader | read published reports |

## 3. Audit log

Record:

- case created
- workflow run started/failed/completed
- finding approved/rejected
- report published
- network config changed
- API key reference changed

## 4. Data retention

Default:

- raw artifacts: 180 days
- published reports: indefinite
- job logs: 90 days
- failed raw stdout/stderr: 30 days unless attached to case

## 5. External API rate limit

Implement per-network and per-provider rate limits.

Recommended:

- exponential backoff for RPC/Explorer errors
- local cache for contract source and ABI
- selector cache
- transaction metadata cache

## 6. Data integrity

Every raw artifact must have sha256 content hash.

Report should include:

- report version
- case id
- artifact bundle hash optional
- model/prompt version

## 7. Operational metrics

Track:

- case count
- average workflow time
- TxAnalyzer runtime per tx
- artifact pull failures
- RPC error rates
- Explorer error rates
- Agent token/cost
- review turnaround
- report coverage

## 8. Incident response for this system

If the system generates wrong high-risk finding:

1. Mark finding rejected.
2. Add reviewer comment.
3. Open quality issue.
4. Store artifacts and model output.
5. Add regression test.
6. Update QA rules/prompt if needed.

