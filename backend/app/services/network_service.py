from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.db import Network


class NetworkService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_networks(self) -> list[Network]:
        return list(self.db.scalars(select(Network).order_by(Network.key)).all())

    def get_network(self, key: str) -> Network | None:
        return self.db.get(Network, key)

    def seed_from_config(self, path: str | Path | None = None) -> int:
        config_path = Path(path) if path else settings.resolve_path(settings.network_config_path)
        if not config_path.exists():
            return 0
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        count = 0
        for key, data in (payload.get("networks") or {}).items():
            self.upsert_network(key, data)
            count += 1
        self.db.commit()
        return count

    def upsert_network(self, key: str, data: dict[str, Any]) -> Network:
        network = self.db.get(Network, key)
        if network is None:
            network = Network(
                key=key,
                name=data["name"],
                network_type=data.get("network_type", "evm"),
                chain_id=int(data["chain_id"]),
                rpc_url_secret_ref=data["rpc_url_secret_ref"],
            )
        network.name = data["name"]
        network.network_type = data.get("network_type", "evm")
        network.chain_id = int(data["chain_id"])
        network.explorer_type = data.get("explorer_type")
        network.explorer_base_url = data.get("explorer_base_url")
        network.rpc_url_secret_ref = data["rpc_url_secret_ref"]
        network.explorer_api_key_secret_ref = data.get("explorer_api_key_secret_ref")
        network.supports_trace_transaction = bool(data.get("supports_trace_transaction", False))
        network.supports_debug_trace_transaction = bool(data.get("supports_debug_trace_transaction", False))
        network.supports_historical_eth_call = bool(data.get("supports_historical_eth_call", True))
        self.db.add(network)
        return network
