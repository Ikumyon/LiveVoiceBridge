from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import sqlite3
import threading
import uuid
import wave
from datetime import datetime, timedelta
from pathlib import Path

from core.app_config import EXE_DIR


CACHE_NONE = "none"
CACHE_TEMP = "temp"
CACHE_PERSISTENT = "persistent"

FIXED_PHRASES = {
    "コメントありがとうございます。",
    "初見さん、いらっしゃい。",
    "読み上げに失敗しました。",
}


class TtsWavCache:
    TEMP_TTL_DAYS = 7
    PERSISTENT_UNUSED_DAYS = 90
    MAX_CACHE_BYTES = 1024 * 1024 * 1024

    def __init__(self) -> None:
        self.cache_dir = EXE_DIR / "cache" / "tts"
        self.temp_dir = self.cache_dir / "temp"
        self.persistent_dir = self.cache_dir / "persistent"
        self.db_path = self.cache_dir / "cache.sqlite3"
        self.session_id = uuid.uuid4().hex
        self._lock = threading.RLock()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.persistent_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_database()
        self.cleanup()

    def classify_unit(self, text: str) -> str:
        return self._classify_unit(text)

    def record_and_lookup(
        self,
        unit_type: str,
        request: dict,
    ) -> tuple[str, int, bytes | None, str]:
        now = datetime.now()
        normalized = self._normalize_text(request["text"])
        canonical_request = dict(request)
        canonical_request["text"] = normalized
        canonical = json.dumps(
            canonical_request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        cache_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tts_units WHERE text_hash = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO tts_units (
                        unit_type, text_original, text_normalized, text_hash,
                        engine, voice, lang, speed, steps, dictionary_version,
                        hit_count, first_seen_at, last_seen_at, last_used_at,
                        cache_level, audio_path, fail_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL, 0)
                    """,
                    (
                        unit_type,
                        request["text"],
                        normalized,
                        cache_key,
                        request.get("engine", ""),
                        str(request.get("speaker_id", "")),
                        request.get("lang", "ja"),
                        request.get("speed"),
                        request.get("num_steps"),
                        request.get("dictionary_version", ""),
                        now.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                        CACHE_NONE,
                    ),
                )

            connection.execute(
                """
                UPDATE tts_units
                SET hit_count = hit_count + 1,
                    last_seen_at = ?,
                    last_used_at = ?,
                    unit_type = ?
                WHERE text_hash = ?
                """,
                (now.isoformat(), now.isoformat(), unit_type, cache_key),
            )
            connection.execute(
                "INSERT OR IGNORE INTO tts_unit_days (text_hash, active_day) VALUES (?, ?)",
                (cache_key, now.date().isoformat()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO tts_unit_sessions (text_hash, session_id) VALUES (?, ?)",
                (cache_key, self.session_id),
            )
            hour_key = now.strftime("%Y-%m-%dT%H")
            connection.execute(
                """
                INSERT INTO tts_unit_hours (text_hash, hour_key, hit_count)
                VALUES (?, ?, 1)
                ON CONFLICT(text_hash, hour_key)
                DO UPDATE SET hit_count = hit_count + 1
                """,
                (cache_key, hour_key),
            )

            stats = self._get_stats(connection, cache_key)
            connection.execute(
                """
                UPDATE tts_units
                SET active_days = ?, active_sessions = ?, burst_score = ?
                WHERE text_hash = ?
                """,
                (
                    stats["active_days"],
                    stats["active_sessions"],
                    stats["burst_ratio"],
                    cache_key,
                ),
            )
            audio_path = Path(stats["audio_path"]) if stats["audio_path"] else None
            if (
                audio_path
                and audio_path.is_file()
                and stats["cache_level"] == CACHE_TEMP
                and self._should_promote(
                    connection,
                    stats,
                    unit_type,
                    canonical_request,
                )
            ):
                persistent_path = self.persistent_dir / audio_path.name
                persistent_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(audio_path), str(persistent_path))
                connection.execute(
                    """
                    UPDATE tts_units
                    SET cache_level = ?, audio_path = ?
                    WHERE text_hash = ?
                    """,
                    (CACHE_PERSISTENT, str(persistent_path), cache_key),
                )
                audio_path = persistent_path
                stats = self._get_stats(connection, cache_key)
            cached = audio_path.read_bytes() if audio_path and audio_path.is_file() else None
            return cache_key, stats["hit_count"], cached, stats["cache_level"]

    def store_generated(
        self,
        cache_key: str,
        unit_type: str,
        request: dict,
        wav_data: bytes,
    ) -> tuple[Path | None, str]:
        with self._lock, self._connect() as connection:
            stats = self._get_stats(connection, cache_key)
            should_promote = self._should_promote(
                connection,
                stats,
                unit_type,
                request,
            )
            if stats["hit_count"] < 2 and not should_promote:
                return None, CACHE_NONE

            target_level = (
                CACHE_PERSISTENT
                if should_promote
                else CACHE_TEMP
            )
            target_dir = (
                self.persistent_dir
                if target_level == CACHE_PERSISTENT
                else self.temp_dir
            )
            target_path = target_dir / f"{cache_key}.wav"
            self._atomic_write(target_path, wav_data)

            previous_path = Path(stats["audio_path"]) if stats["audio_path"] else None
            if previous_path and previous_path != target_path:
                previous_path.unlink(missing_ok=True)

            connection.execute(
                """
                UPDATE tts_units
                SET cache_level = ?, audio_path = ?, duration_ms = ?, last_used_at = ?
                WHERE text_hash = ?
                """,
                (
                    target_level,
                    str(target_path),
                    self._wav_duration_ms(wav_data),
                    datetime.now().isoformat(),
                    cache_key,
                ),
            )
            return target_path, target_level

    def record_failure(self, cache_key: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE tts_units SET fail_count = fail_count + 1 WHERE text_hash = ?",
                (cache_key,),
            )

    def cleanup(self) -> None:
        now = datetime.now()
        temp_cutoff = (now - timedelta(days=self.TEMP_TTL_DAYS)).isoformat()
        persistent_cutoff = (
            now - timedelta(days=self.PERSISTENT_UNUSED_DAYS)
        ).isoformat()

        with self._lock, self._connect() as connection:
            stale_rows = connection.execute(
                """
                SELECT text_hash, audio_path FROM tts_units
                WHERE (cache_level = ? AND last_used_at < ?)
                   OR (cache_level = ? AND last_used_at < ?)
                ORDER BY last_used_at ASC
                """,
                (
                    CACHE_TEMP,
                    temp_cutoff,
                    CACHE_PERSISTENT,
                    persistent_cutoff,
                ),
            ).fetchall()
            for row in stale_rows:
                if row["audio_path"]:
                    Path(row["audio_path"]).unlink(missing_ok=True)
                connection.execute(
                    """
                    UPDATE tts_units
                    SET cache_level = ?, audio_path = NULL
                    WHERE text_hash = ?
                    """,
                    (CACHE_NONE, row["text_hash"]),
                )

            self._enforce_size_limit(connection)

    def _should_promote(
        self,
        connection: sqlite3.Connection,
        stats: sqlite3.Row,
        unit_type: str,
        request: dict,
    ) -> bool:
        text = request["text"]
        if not self._is_persistent_safe(text):
            return False
        if unit_type == "fixed_phrase":
            return True
        if unit_type == "name":
            return stats["active_days"] >= 2 or stats["active_sessions"] >= 2
        if unit_type == "short_reaction":
            return (
                stats["hit_count"] >= 5
                and (
                    stats["active_days"] >= 2
                    or stats["active_sessions"] >= 2
                )
                and stats["burst_ratio"] <= 0.8
            )
        return (
            stats["hit_count"] >= 4
            and stats["active_days"] >= 2
            and stats["burst_ratio"] <= 0.7
        )

    def _get_stats(
        self,
        connection: sqlite3.Connection,
        cache_key: str,
    ) -> dict:
        row = connection.execute(
            """
            SELECT u.*,
                (SELECT COUNT(*) FROM tts_unit_days d
                 WHERE d.text_hash = u.text_hash) AS calculated_active_days,
                (SELECT COUNT(*) FROM tts_unit_sessions s
                 WHERE s.text_hash = u.text_hash) AS calculated_active_sessions,
                COALESCE(
                    CAST((SELECT MAX(h.hit_count) FROM tts_unit_hours h
                          WHERE h.text_hash = u.text_hash) AS REAL)
                    / NULLIF(u.hit_count, 0),
                    0
                ) AS burst_ratio
            FROM tts_units u
            WHERE u.text_hash = ?
            """,
            (cache_key,),
        ).fetchone()
        stats = dict(row)
        stats["active_days"] = stats.pop("calculated_active_days")
        stats["active_sessions"] = stats.pop("calculated_active_sessions")
        return stats

    def _classify_unit(self, text: str) -> str:
        normalized = self._normalize_text(text)
        if normalized in FIXED_PHRASES:
            return "fixed_phrase"
        if re.search(r"(?:さん|ちゃん|くん|君|様)[。！？!?]?$", normalized):
            return "name"
        plain_length = len(re.sub(r"[。！？!?\s]", "", normalized))
        if 2 <= plain_length <= 20:
            return "short_reaction"
        return "sentence"

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _is_persistent_safe(text: str) -> bool:
        if len(text) > 120:
            return False
        if re.search(r"https?://|www\.", text, flags=re.IGNORECASE):
            return False
        digits = re.findall(r"\d", text)
        if len(digits) >= 6 or (text and len(digits) / len(text) > 0.3):
            return False
        if re.search(r"(.)\1{7,}", text):
            return False
        if re.search(r"\b\d{1,2}:\d{2}\b|\d{4}年\d{1,2}月\d{1,2}日", text):
            return False
        return True

    def _enforce_size_limit(self, connection: sqlite3.Connection) -> None:
        files = [
            path
            for directory in (self.temp_dir, self.persistent_dir)
            for path in directory.glob("*.wav")
        ]
        total_size = sum(path.stat().st_size for path in files if path.is_file())
        if total_size <= self.MAX_CACHE_BYTES:
            return

        rows = connection.execute(
            """
            SELECT text_hash, audio_path FROM tts_units
            WHERE audio_path IS NOT NULL
            ORDER BY
                CASE cache_level WHEN 'temp' THEN 0 ELSE 1 END,
                last_used_at ASC,
                hit_count ASC
            """
        ).fetchall()
        for row in rows:
            path = Path(row["audio_path"])
            size = path.stat().st_size if path.is_file() else 0
            path.unlink(missing_ok=True)
            total_size -= size
            connection.execute(
                """
                UPDATE tts_units
                SET cache_level = ?, audio_path = NULL
                WHERE text_hash = ?
                """,
                (CACHE_NONE, row["text_hash"]),
            )
            if total_size <= self.MAX_CACHE_BYTES:
                break

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tts_units (
                    id INTEGER PRIMARY KEY,
                    unit_type TEXT NOT NULL,
                    text_original TEXT NOT NULL,
                    text_normalized TEXT NOT NULL,
                    text_hash TEXT NOT NULL UNIQUE,
                    engine TEXT NOT NULL,
                    voice TEXT,
                    lang TEXT,
                    speed REAL,
                    steps INTEGER,
                    dictionary_version TEXT,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    active_days INTEGER NOT NULL DEFAULT 0,
                    active_sessions INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL,
                    burst_score REAL NOT NULL DEFAULT 0,
                    cache_level TEXT NOT NULL DEFAULT 'none',
                    audio_path TEXT,
                    duration_ms INTEGER,
                    fail_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tts_unit_days (
                    text_hash TEXT NOT NULL,
                    active_day TEXT NOT NULL,
                    PRIMARY KEY (text_hash, active_day)
                );
                CREATE TABLE IF NOT EXISTS tts_unit_sessions (
                    text_hash TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    PRIMARY KEY (text_hash, session_id)
                );
                CREATE TABLE IF NOT EXISTS tts_unit_hours (
                    text_hash TEXT NOT NULL,
                    hour_key TEXT NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (text_hash, hour_key)
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tts_units)")
            }
            for name, definition in (
                ("active_days", "INTEGER NOT NULL DEFAULT 0"),
                ("active_sessions", "INTEGER NOT NULL DEFAULT 0"),
                ("burst_score", "REAL NOT NULL DEFAULT 0"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE tts_units ADD COLUMN {name} {definition}"
                    )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _atomic_write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".wav.tmp")
        temp_path.write_bytes(data)
        temp_path.replace(path)

    @staticmethod
    def _wav_duration_ms(data: bytes) -> int | None:
        try:
            with wave.open(io.BytesIO(data), "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                if frame_rate <= 0:
                    return None
                return round(wav_file.getnframes() * 1000 / frame_rate)
        except (EOFError, wave.Error):
            return None
