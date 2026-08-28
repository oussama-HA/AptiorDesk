"""Persistence for the candidate profile and its items."""

from __future__ import annotations

import json
import sqlite3

from aptiordesk.database.models.profile import Profile, ProfileItem
from aptiordesk.database.repositories._util import now_iso


class ProfileRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    # -- profile -------------------------------------------------------------

    def get_default(self) -> Profile:
        """Return the single MVP profile, creating an empty one if needed."""
        row = self._conn.execute("SELECT * FROM profiles ORDER BY id LIMIT 1").fetchone()
        if row is None:
            ts = now_iso()
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO profiles(display_name, summary, contact_json, "
                    "preferences_json, work_auth_json, created_at, updated_at) "
                    "VALUES('', '', '{}', '{}', '{}', ?, ?)",
                    (ts, ts),
                )
            row = self._conn.execute(
                "SELECT * FROM profiles WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        return self._row_to_profile(row)

    def save(self, profile: Profile) -> Profile:
        if profile.id is None:
            raise ValueError("Profile must have an id (use get_default() first)")
        with self._conn:
            self._conn.execute(
                "UPDATE profiles SET display_name=?, summary=?, contact_json=?, "
                "preferences_json=?, work_auth_json=?, field_origin_json=?, "
                "updated_at=? WHERE id=?",
                (
                    profile.display_name,
                    profile.summary,
                    profile.contact.model_dump_json(),
                    profile.preferences.model_dump_json(),
                    profile.work_auth.model_dump_json(),
                    json.dumps(profile.field_origin),
                    now_iso(),
                    profile.id,
                ),
            )
        return profile

    @staticmethod
    def _row_to_profile(row: sqlite3.Row) -> Profile:
        return Profile(
            id=row["id"],
            display_name=row["display_name"],
            summary=row["summary"],
            contact=json.loads(row["contact_json"]),
            preferences=json.loads(row["preferences_json"]),
            work_auth=json.loads(row["work_auth_json"]),
            field_origin=json.loads(row["field_origin_json"] or "{}"),
        )

    # -- items ---------------------------------------------------------------

    def list_items(self, profile_id: int, kind: str | None = None) -> list[ProfileItem]:
        if kind is None:
            rows = self._conn.execute(
                "SELECT * FROM profile_items WHERE profile_id=? ORDER BY kind, sort_order, id",
                (profile_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM profile_items WHERE profile_id=? AND kind=? ORDER BY sort_order, id",
                (profile_id, kind),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def add_item(self, item: ProfileItem) -> ProfileItem:
        item.parsed()  # validate data against the kind's model before writing
        ts = now_iso()
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO profile_items(profile_id, kind, sort_order, data_json, "
                "provenance, source_resume_version_id, user_edited, needs_review, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    item.profile_id,
                    item.kind,
                    item.sort_order,
                    json.dumps(item.data),
                    item.provenance,
                    item.source_resume_version_id,
                    int(item.user_edited),
                    int(item.needs_review),
                    ts,
                    ts,
                ),
            )
        item.id = cur.lastrowid
        return item

    def update_item(self, item: ProfileItem) -> None:
        item.parsed()
        with self._conn:
            self._conn.execute(
                "UPDATE profile_items SET sort_order=?, data_json=?, provenance=?, "
                "source_resume_version_id=?, user_edited=?, needs_review=?, "
                "updated_at=? WHERE id=?",
                (
                    item.sort_order,
                    json.dumps(item.data),
                    item.provenance,
                    item.source_resume_version_id,
                    int(item.user_edited),
                    int(item.needs_review),
                    now_iso(),
                    item.id,
                ),
            )

    def mark_user_edited(self, item_id: int) -> None:
        """Record that the user changed this entry by hand, so a later resume
        import will treat replacing it as a conflict rather than an update."""
        with self._conn:
            self._conn.execute(
                "UPDATE profile_items SET user_edited=1, needs_review=0, updated_at=? WHERE id=?",
                (now_iso(), item_id),
            )

    def delete_item(self, item_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM profile_items WHERE id=?", (item_id,))

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ProfileItem:
        return ProfileItem(
            id=row["id"],
            profile_id=row["profile_id"],
            kind=row["kind"],
            sort_order=row["sort_order"],
            data=json.loads(row["data_json"]),
            provenance=row["provenance"],
            source_resume_version_id=row["source_resume_version_id"],
            user_edited=bool(row["user_edited"]),
            needs_review=bool(row["needs_review"]),
        )
