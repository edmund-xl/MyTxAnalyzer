-- On-chain RCA Workbench PostgreSQL schema v1.0

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TYPE seed_type AS ENUM ('transaction', 'address', 'contract', 'alert');
CREATE TYPE analysis_depth AS ENUM ('quick', 'full', 'full_replay');
CREATE TYPE case_status AS ENUM (
  'CREATED', 'ENV_CHECKING', 'ENV_CHECKED',
  'DISCOVERING_TRANSACTIONS', 'TRANSACTIONS_DISCOVERED',
  'PULLING_ARTIFACTS', 'ARTIFACTS_PULLED',
  'DECODING', 'DECODED',
  'BUILDING_EVIDENCE', 'EVIDENCE_BUILT',
  'RUNNING_FORENSICS', 'FORENSICS_DONE',
  'RUNNING_RCA_AGENT', 'RCA_DONE',
  'DRAFTING_REPORT', 'REPORT_DRAFTED',
  'UNDER_REVIEW', 'PUBLISHED',
  'PARTIAL', 'FAILED', 'CANCELLED'
);
CREATE TYPE severity AS ENUM ('critical', 'high', 'medium', 'low', 'info', 'unknown');
CREATE TYPE confidence AS ENUM ('high', 'medium', 'low', 'partial');
CREATE TYPE job_status AS ENUM ('pending', 'running', 'success', 'failed', 'partial');
CREATE TYPE review_status AS ENUM ('pending', 'approved', 'rejected', 'more_evidence_needed');
CREATE TYPE artifact_status AS ENUM ('pending', 'running', 'done', 'failed', 'partial');
CREATE TYPE report_status AS ENUM ('draft', 'under_review', 'published', 'archived');

CREATE TABLE networks (
  key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  chain_id BIGINT NOT NULL,
  explorer_type TEXT,
  explorer_base_url TEXT,
  rpc_url_secret_ref TEXT NOT NULL,
  explorer_api_key_secret_ref TEXT,
  supports_trace_transaction BOOLEAN DEFAULT FALSE,
  supports_debug_trace_transaction BOOLEAN DEFAULT FALSE,
  supports_historical_eth_call BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cases (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title TEXT,
  network_key TEXT NOT NULL REFERENCES networks(key),
  seed_type seed_type NOT NULL,
  seed_value TEXT NOT NULL,
  time_window_hours INTEGER NOT NULL DEFAULT 6,
  depth analysis_depth NOT NULL DEFAULT 'quick',
  status case_status NOT NULL DEFAULT 'CREATED',
  severity severity NOT NULL DEFAULT 'unknown',
  attack_type TEXT,
  root_cause_one_liner TEXT,
  loss_usd NUMERIC,
  confidence confidence NOT NULL DEFAULT 'low',
  language TEXT NOT NULL DEFAULT 'zh-CN',
  created_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  tx_hash TEXT NOT NULL,
  block_number BIGINT,
  block_timestamp TIMESTAMPTZ,
  tx_index INTEGER,
  from_address TEXT,
  to_address TEXT,
  nonce BIGINT,
  value_wei NUMERIC,
  status INTEGER,
  method_selector TEXT,
  method_name TEXT,
  phase TEXT DEFAULT 'unknown',
  phase_confidence confidence DEFAULT 'low',
  artifact_status artifact_status NOT NULL DEFAULT 'pending',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, tx_hash)
);

CREATE INDEX idx_transactions_case ON transactions(case_id);
CREATE INDEX idx_transactions_hash ON transactions(tx_hash);
CREATE INDEX idx_transactions_phase ON transactions(case_id, phase);

CREATE TABLE addresses (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  address TEXT NOT NULL,
  label TEXT,
  address_type TEXT,
  role TEXT,
  code_hash TEXT,
  first_seen_tx_id UUID REFERENCES transactions(id),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, address)
);

CREATE TABLE contracts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  address TEXT NOT NULL,
  proxy_type TEXT,
  implementation_address TEXT,
  contract_name TEXT,
  verified_source BOOLEAN DEFAULT FALSE,
  abi_available BOOLEAN DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, address)
);

CREATE TABLE artifacts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  tx_id UUID REFERENCES transactions(id) ON DELETE SET NULL,
  producer TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  object_path TEXT NOT NULL,
  content_hash TEXT,
  size_bytes BIGINT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, object_path)
);

CREATE INDEX idx_artifacts_case ON artifacts(case_id);
CREATE INDEX idx_artifacts_tx ON artifacts(tx_id);

CREATE TABLE evidence (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  tx_id UUID REFERENCES transactions(id) ON DELETE SET NULL,
  source_type TEXT NOT NULL,
  producer TEXT NOT NULL,
  claim_key TEXT NOT NULL,
  raw_path TEXT,
  decoded JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence confidence NOT NULL DEFAULT 'low',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, source_type, producer, claim_key, raw_path)
);

CREATE INDEX idx_evidence_case ON evidence(case_id);
CREATE INDEX idx_evidence_claim ON evidence(case_id, claim_key);
CREATE INDEX idx_evidence_source_type ON evidence(case_id, source_type);

CREATE TABLE findings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  finding_type TEXT NOT NULL,
  severity severity NOT NULL DEFAULT 'unknown',
  confidence confidence NOT NULL DEFAULT 'low',
  claim TEXT NOT NULL,
  rationale TEXT,
  falsification TEXT,
  evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  reviewer_status review_status NOT NULL DEFAULT 'pending',
  reviewer_comment TEXT,
  requires_reviewer BOOLEAN NOT NULL DEFAULT TRUE,
  created_by TEXT NOT NULL DEFAULT 'system',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_findings_case ON findings(case_id);
CREATE INDEX idx_findings_review ON findings(case_id, reviewer_status);

CREATE TABLE finding_evidence (
  finding_id UUID NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  evidence_id UUID NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
  PRIMARY KEY (finding_id, evidence_id)
);

CREATE TABLE reports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  language TEXT NOT NULL DEFAULT 'zh-CN',
  format TEXT NOT NULL DEFAULT 'markdown',
  status report_status NOT NULL DEFAULT 'draft',
  object_path TEXT,
  content_hash TEXT,
  evidence_coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT,
  reviewed_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(case_id, version, format)
);

CREATE TABLE report_sections (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  report_id UUID NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  section_order INTEGER NOT NULL,
  title TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  evidence_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  coverage NUMERIC NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE job_runs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
  job_name TEXT NOT NULL,
  status job_status NOT NULL DEFAULT 'pending',
  input JSONB NOT NULL DEFAULT '{}'::jsonb,
  output JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT,
  started_at TIMESTAMPTZ,
  ended_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_job_runs_case ON job_runs(case_id);
CREATE INDEX idx_job_runs_status ON job_runs(case_id, status);

CREATE TABLE audit_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
  actor TEXT,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
