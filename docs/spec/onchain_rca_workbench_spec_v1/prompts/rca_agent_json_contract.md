Return JSON with exactly this structure:

{
  "root_cause_one_liner": "string",
  "attack_type": "string",
  "severity": "critical|high|medium|low|info|unknown",
  "confidence": "high|medium|low|partial",
  "findings": [
    {
      "title": "string",
      "finding_type": "access_control|multisig|fund_flow|contract_bug|loss|remediation|data_quality|root_cause|entity_profile",
      "severity": "critical|high|medium|low|info|unknown",
      "confidence": "high|medium|low|partial",
      "claim": "string",
      "rationale": "string",
      "falsification": "string",
      "evidence_ids": ["ev_..."],
      "requires_reviewer": true
    }
  ],
  "blockers": ["string"],
  "open_questions": ["string"]
}

Validation constraints:

- findings[*].evidence_ids must not be empty.
- confidence=high requires at least one non-agent evidence id.
- risky attribution findings require requires_reviewer=true.
