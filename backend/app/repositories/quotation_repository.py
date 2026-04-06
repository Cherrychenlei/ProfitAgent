"""SQLite quotation repository."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.schemas.quotation_schema import QuotationResponse


@dataclass
class NegotiationRecord:
    negotiation_id: int
    action_type: str
    payload: dict
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


class QuotationRepository:
    def __init__(self, db_path: Optional[str] = None):
        base = Path(__file__).resolve().parents[2]
        default_path = base / "data" / "quotations.db"
        self.db_path = Path(db_path) if db_path else default_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quotations (
                    quote_id INTEGER PRIMARY KEY,
                    quote_number TEXT NOT NULL,
                    approval_status TEXT NOT NULL,
                    routing_channel TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            # Backward compatibility for older local DB files
            self._ensure_column(conn, "quotations", "created_at", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quotations_status_channel_created
                ON quotations (approval_status, routing_channel, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_quotations_created_at
                ON quotations (created_at DESC)
                """
            )
            try:
                conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_quotations_quote_number
                    ON quotations (quote_number)
                    """
                )
            except sqlite3.IntegrityError:
                # In case legacy data already contains duplicates.
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS negotiations (
                    negotiation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    quote_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_negotiations_quote_created
                ON negotiations (quote_id, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_negotiations_quote_action_created
                ON negotiations (quote_id, action_type, created_at DESC)
                """
            )
            conn.commit()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_def: str) -> None:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {c["name"] for c in cols}
        if column not in names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")

    def next_quote_id(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(quote_id), 0) + 1 AS next_id FROM quotations").fetchone()
            return int(row["next_id"])

    def next_quote_number(self, now: Optional[datetime] = None) -> str:
        ts = now or datetime.utcnow()
        day = ts.strftime("%Y%m%d")
        like_pattern = f"ZW-{day}-%-V1"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(CAST(substr(quote_number, 13, 3) AS INTEGER)), 0) + 1 AS next_seq
                FROM quotations
                WHERE quote_number LIKE ?
                """,
                (like_pattern,),
            ).fetchone()
        seq = int(row["next_seq"])
        return f"ZW-{day}-{seq:03d}-V1"

    def save(self, quote: QuotationResponse) -> None:
        payload = json.dumps(quote.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO quotations
                (quote_id, quote_number, approval_status, routing_channel, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    quote.quote_id,
                    quote.quote_number,
                    quote.approval_status,
                    quote.routing_channel,
                    quote.created_at.isoformat(),
                    payload,
                ),
            )
            conn.commit()

    def save_new_quote(self, quote: QuotationResponse, max_retries: int = 5) -> QuotationResponse:
        for _ in range(max_retries):
            created_at = datetime.utcnow()
            quote_number = self.next_quote_number(created_at)
            candidate = quote.model_copy(update={"quote_number": quote_number, "created_at": created_at})
            if not candidate.status_timeline:
                candidate = candidate.model_copy(update={"status_timeline": [{"status": "draft", "time": created_at.isoformat()}]})
            try:
                quote_id = self._insert_new_quote_row(candidate)
                return candidate.model_copy(update={"quote_id": quote_id})
            except sqlite3.IntegrityError:
                continue
        raise RuntimeError("Failed to generate unique quote number")

    def _insert_new_quote_row(self, candidate: QuotationResponse) -> int:
        payload = json.dumps(candidate.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO quotations
                (quote_number, approval_status, routing_channel, created_at, payload_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    candidate.quote_number,
                    candidate.approval_status,
                    candidate.routing_channel,
                    candidate.created_at.isoformat(),
                    payload,
                ),
            )
            quote_id = int(cur.lastrowid)
            conn.execute(
                """
                UPDATE quotations
                SET payload_json = ?
                WHERE quote_id = ?
                """,
                (json.dumps(candidate.model_copy(update={"quote_id": quote_id}).model_dump(mode="json"), ensure_ascii=False), quote_id),
            )
            conn.commit()
        return quote_id

    def get(self, quote_id: int) -> Optional[QuotationResponse]:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM quotations WHERE quote_id = ?", (quote_id,)).fetchone()
        if not row:
            return None
        return QuotationResponse.model_validate(json.loads(row["payload_json"]))

    def list(
        self,
        approval_status: Optional[str] = None,
        routing_channel: Optional[str] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[QuotationResponse]:
        conditions = []
        params: list = []
        if approval_status:
            conditions.append("approval_status = ?")
            params.append(approval_status)
        if routing_channel:
            conditions.append("routing_channel = ?")
            params.append(routing_channel)
        if created_from is not None:
            conditions.append("created_at >= ?")
            params.append(created_from.isoformat())
        if created_to is not None:
            conditions.append("created_at <= ?")
            params.append(created_to.isoformat())

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = max(0, (page - 1) * page_size)
        sql = (
            "SELECT payload_json FROM quotations "
            f"{where_clause} ORDER BY quote_id DESC LIMIT ? OFFSET ?"
        )
        params.extend([page_size, offset])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [QuotationResponse.model_validate(json.loads(r["payload_json"])) for r in rows]

    def log_negotiation(self, quote_id: int, action_type: str, payload: dict, created_at: str) -> int:
        payload_json = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO negotiations (quote_id, action_type, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (quote_id, action_type, payload_json, created_at),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_negotiations(
        self,
        quote_id: int,
        action_type: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> List[NegotiationRecord]:
        conditions = ["quote_id = ?"]
        params: list = [quote_id]
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)
        if start_at:
            conditions.append("created_at >= ?")
            params.append(start_at.isoformat())
        if end_at:
            conditions.append("created_at <= ?")
            params.append(end_at.isoformat())

        where_clause = " AND ".join(conditions)
        offset = max(0, (page - 1) * page_size)
        sql = f"""
            SELECT negotiation_id, action_type, payload_json, created_at
            FROM negotiations
            WHERE {where_clause}
            ORDER BY negotiation_id ASC
            LIMIT ? OFFSET ?
        """
        params.extend([page_size, offset])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            NegotiationRecord(
                negotiation_id=int(r["negotiation_id"]),
                action_type=r["action_type"],
                payload=json.loads(r["payload_json"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]
