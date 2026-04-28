# 13 Implementation Notes

## 1. Idempotency

Use deterministic keys:

- transaction: `(case_id, tx_hash)`
- evidence: hash of `(case_id, source_type, producer, claim_key, raw_path, decoded_hash)`
- artifact: hash of `(case_id, tx_id, producer, object_path)`

## 2. Address normalization

- Store lowercase checksummed form separately if needed.
- `address_normalized = lower(address)`.
- UI can display checksum.

## 3. Decimal handling

- Store raw amounts as strings or numeric with sufficient precision.
- Keep `amount_raw`, `decimals`, `amount_human`.
- Do not use float for token amounts.

## 4. Time zones

- Store all times in UTC.
- UI can display local timezone.
- Reports should specify timezone.

## 5. Selector lookup

Priority:

1. Verified ABI from Explorer.
2. TxAnalyzer selector mapping.
3. Local selector cache.
4. 4byte/openchain fallback.
5. Unknown selector.

## 6. Source handling

- Verified source may be multi-file JSON or flattened source.
- Store raw source and parsed metadata.
- Source line numbers can be added P1.

## 7. Safe signature handling

Signature types:

- ECDSA normal: v 27/28.
- eth_sign: v 31/32.
- approvedHash: v 1.
- contract signature: v 0 / ERC-1271.

Do not assume all signatures are ECDSA.

## 8. Report publication

Only reports with status `UNDER_REVIEW` can become `PUBLISHED`.

Publish preconditions:

- no rejected critical finding included;
- all critical findings approved;
- report coverage gate passes;
- reviewer exists.

