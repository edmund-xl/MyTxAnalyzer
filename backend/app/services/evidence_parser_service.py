from __future__ import annotations

from typing import Any


TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
APPROVAL_TOPIC = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class EvidenceParserService:
    """Normalize raw chain artifacts into small, evidence-friendly graph inputs."""

    def normalize_evm_receipt(self, receipt: dict[str, Any], tx_hash: str) -> dict[str, Any]:
        logs = receipt.get("logs") or []
        events: list[dict[str, Any]] = []
        token_transfers: list[dict[str, Any]] = []
        approvals: list[dict[str, Any]] = []
        for index, log in enumerate(logs):
            topics = [self._hex(topic).lower() for topic in (log.get("topics") or [])]
            if not topics:
                continue
            address = str(log.get("address") or "").lower()
            base_event = {
                "tx_hash": tx_hash,
                "log_index": self._int(log.get("logIndex"), index),
                "contract": address,
                "topic0": topics[0],
            }
            if topics[0] == TRANSFER_TOPIC and len(topics) >= 3:
                source = self._topic_address(topics[1])
                target = self._topic_address(topics[2])
                value = self._int_hex_data(log.get("data"))
                transfer = {
                    **base_event,
                    "event": "Transfer",
                    "asset": address,
                    "from": source,
                    "to": target,
                    "amount_raw": str(value),
                    "amount": str(value),
                    "token_standard": "erc721" if len(topics) >= 4 else "erc20_or_erc721",
                }
                if len(topics) >= 4:
                    token_id = self._int_hex_data(topics[3])
                    transfer["token_id"] = str(token_id)
                    transfer["amount"] = f"tokenId {token_id}"
                token_transfers.append(transfer)
                events.append(transfer)
            elif topics[0] == APPROVAL_TOPIC and len(topics) >= 3:
                approval = {
                    **base_event,
                    "event": "Approval",
                    "asset": address,
                    "owner": self._topic_address(topics[1]),
                    "spender": self._topic_address(topics[2]),
                    "amount_raw": str(self._int_hex_data(log.get("data"))),
                }
                approvals.append(approval)
                events.append(approval)
            else:
                events.append({**base_event, "event": "Unknown"})
        fund_flow_edges = [
            {
                "from": item["from"],
                "to": item["to"],
                "asset": item["asset"],
                "amount": item.get("amount"),
                "amount_raw": item.get("amount_raw"),
                "tx_hash": tx_hash,
                "log_index": item.get("log_index"),
                "confidence": "high",
            }
            for item in token_transfers
            if item.get("from") != ZERO_ADDRESS and item.get("to") != ZERO_ADDRESS
        ]
        return {
            "tx_hash": tx_hash,
            "status": self._int(receipt.get("status"), None),
            "block_number": self._int(receipt.get("blockNumber"), None),
            "log_count": len(logs),
            "event_count": len(events),
            "transfer_count": len(token_transfers),
            "approval_count": len(approvals),
            "events": events,
            "token_transfers": token_transfers,
            "approvals": approvals,
            "fund_flow_edges": fund_flow_edges,
            "attack_steps": self._attack_steps_from_receipt(receipt, tx_hash),
        }

    def _attack_steps_from_receipt(self, receipt: dict[str, Any], tx_hash: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "seed_receipt",
                "label": "Seed transaction receipt",
                "tx_hash": tx_hash,
                "confidence": "high" if self._int(receipt.get("status"), 0) == 1 else "partial",
                "evidence": "eth_getTransactionReceipt",
            }
        ]

    def _topic_address(self, topic: str) -> str:
        text = topic.lower()
        if text.startswith("0x") and len(text) >= 42:
            return "0x" + text[-40:]
        return text

    def _hex(self, value: Any) -> str:
        if hasattr(value, "hex"):
            return value.hex()
        return str(value or "0x")

    def _int_hex_data(self, value: Any) -> int:
        text = self._hex(value)
        if text in {"", "0x"}:
            return 0
        return int(text, 16)

    def _int(self, value: Any, default: int | None = 0) -> int | None:
        if value is None:
            return default
        if isinstance(value, str) and value.startswith("0x"):
            return int(value, 16)
        return int(value)
