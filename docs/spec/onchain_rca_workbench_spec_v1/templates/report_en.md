# {{ case.title }} Incident Analysis Report

## TL;DR

- Type: {{ case.attack_type }}
- Chain: {{ network.name }} (Chain ID: {{ network.chain_id }})
- Attack window: {{ attack_window }}
- Loss: {{ loss_summary }}
- Root cause: {{ root_cause_one_liner }}
- Confidence: {{ confidence }}

## 1. Overview

{{ overview }}

## 2. Parties

{{ entities_table }}

## 3. Timeline

{{ timeline_table }}

## 4. Key Transactions

{{ key_transactions }}

## 5. Root Cause

{{ root_cause_analysis }}

## 6. Permission / Multisig / Signature Forensics

{{ permission_and_multisig_forensics }}

## 7. Fund Flow

{{ fund_flow }}

## 8. Financial Impact

{{ financial_impact }}

## 9. Remediation

{{ remediation }}

## 10. Data Reliability

{{ data_reliability }}

## 11. Methodology and Query Checklist

{{ methodology }}

## 12. Appendix

{{ appendix }}
