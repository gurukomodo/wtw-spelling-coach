"""
One-time migration + cleanup script for the UnBoxEd spelling coach app.

Run ONCE from the same directory as app.py:
    python cleanup_and_migrate.py

What it does (in order):
  1. Adds struggles / mastered / target_group columns to student_identity (safe if they exist).
  2. Migrates any data from students.csv into SQLite so nothing is lost.
  3. Deletes ghost students STU_4942 and STU_7775 from the database.
  4. Merges STU_3995 (duplicate Alice) into STU_6264 (real Alice).
  5. Renames students.csv to students.csv.retired so the app stops reading it.
  6. Prints a full before/after summary.

After this script completes:
  - SQLite is the single source of truth.
  - students.csv is retired (not deleted — you can remove it manually once happy).
  - Restart Streamlit and Glen's class should show exactly the correct students.
"""

import csv
import os
import sqlite3
import shutil
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH       = "data/spelling_coach.db"
CSV_PATH      = "students.csv"
TEACHER_EMAIL = "glenp@gm.yhsh.tn.edu.tw"

GHOST_IDS     = ["STU_4942", "STU_7775"]
MERGE_FROM    = "STU_3995"
MERGE_INTO    = "STU_6264"   # Alice


# ── Helpers ────────────────────────────────────────────────────────────────────
def backup(path):
    if os.path.exists(path):
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = f"{path}.backup_{ts}"
        shutil.copy2(path, dst)
        print(f"  Backed up  {path}  →  {dst}")
    else:
        print(f"  (skipped backup – {path} not found)")


def add_column_if_missing(cursor, table, column, col_type):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cursor.fetchall()]
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"  Added column  {table}.{column}")
    else:
        print(f"  Column already exists: {table}.{column}")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("\n" + "=" * 62)
    print("  UnBoxEd – CSV → SQLite Migration + Ghost Student Cleanup")
    print("=" * 62)

    if not os.path.exists(DB_PATH):
        print(f"\nERROR: Database not found at '{DB_PATH}'.")
        print("Make sure you run this script from the same directory as app.py,")
        print("and that the app has been started at least once (to create the DB).")
        return

    # ── 0. Backups ──────────────────────────────────────────────────────────
    print("\n[0] Creating backups …")
    backup(DB_PATH)
    backup(CSV_PATH)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── 1. Schema: add profile columns to student_identity ──────────────────
    print("\n[1] Ensuring profile columns exist in student_identity …")
    add_column_if_missing(cursor, "student_identity", "struggles",    "TEXT DEFAULT ''")
    add_column_if_missing(cursor, "student_identity", "mastered",     "TEXT DEFAULT ''")
    add_column_if_missing(cursor, "student_identity", "target_group", "TEXT DEFAULT 'g1'")
    conn.commit()

    # ── 2. Migrate students.csv → student_identity ──────────────────────────
    print("\n[2] Migrating students.csv into SQLite …")
    migrated = 0
    skipped  = 0

    if not os.path.exists(CSV_PATH):
        print(f"  students.csv not found at '{CSV_PATH}' – skipping migration step.")
    else:
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows   = list(reader)

        print(f"  Found {len(rows)} rows in students.csv")

        for row in rows:
            sid          = (row.get("Student ID") or "").strip()
            struggles    = (row.get("Struggles") or "").strip()
            mastered     = (row.get("Mastered Words") or "").strip()
            target_group = (row.get("Target_Group") or "g1").strip()
            teacher_id   = (row.get("teacher_id") or TEACHER_EMAIL).strip()

            if not sid:
                skipped += 1
                continue

            # Does this student exist in the DB?
            cursor.execute("SELECT struggles, mastered, target_group FROM student_identity WHERE student_id = ?", (sid,))
            existing = cursor.fetchone()

            if existing:
                # Merge: only fill in empty DB fields with CSV values
                db_struggles, db_mastered, db_group = existing
                new_struggles    = db_struggles    or struggles
                new_mastered     = db_mastered     or mastered
                new_target_group = db_group        or target_group

                cursor.execute("""
                    UPDATE student_identity
                    SET struggles = ?, mastered = ?, target_group = ?
                    WHERE student_id = ?
                """, (new_struggles, new_mastered, new_target_group, sid))
                print(f"  Updated  {sid}: struggles='{new_struggles}' mastered='{new_mastered}' group='{new_target_group}'")
            else:
                # Insert a new identity row (will be orphaned if teacher unknown)
                cursor.execute("""
                    INSERT INTO student_identity (teacher_id, student_id, struggles, mastered, target_group)
                    VALUES (?, ?, ?, ?, ?)
                """, (teacher_id, sid, struggles, mastered, target_group))
                print(f"  Inserted {sid} (teacher={teacher_id})")

            migrated += 1

        conn.commit()
        print(f"  Migration complete: {migrated} rows processed, {skipped} skipped (blank IDs).")

    # ── 3. Show state before ghost cleanup ──────────────────────────────────
    all_problem_ids = GHOST_IDS + [MERGE_FROM, MERGE_INTO]
    print(f"\n[3] Database state for problem IDs before cleanup:")
    for sid in all_problem_ids:
        cursor.execute("SELECT student_id, real_name, teacher_id FROM student_identity WHERE student_id = ?", (sid,))
        identity = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM assessments WHERE student_id = ?", (sid,))
        count = cursor.fetchone()[0]
        tag = ""
        if sid in GHOST_IDS:  tag = "  ← GHOST – will delete"
        if sid == MERGE_FROM: tag = "  ← DUPLICATE – will merge → STU_6264"
        if sid == MERGE_INTO: tag = "  ← Alice (merge target)"
        print(f"  {sid}  identity={identity}  assessments={count}{tag}")

    # ── 4. Delete ghost students ─────────────────────────────────────────────
    print("\n[4] Deleting ghost students …")
    cursor.execute("PRAGMA foreign_keys = OFF")

    for sid in GHOST_IDS:
        cursor.execute("DELETE FROM student_identity WHERE student_id = ?", (sid,))
        id_del = cursor.rowcount
        cursor.execute("DELETE FROM assessments WHERE student_id = ?", (sid,))
        as_del = cursor.rowcount
        print(f"  Deleted {sid}: {id_del} identity row(s), {as_del} assessment row(s)")

    # ── 5. Merge STU_3995 → STU_6264 (Alice) ────────────────────────────────
    print(f"\n[5] Merging {MERGE_FROM} into {MERGE_INTO} (Alice) …")

    cursor.execute("SELECT COUNT(*) FROM assessments WHERE student_id = ?", (MERGE_FROM,))
    before_count = cursor.fetchone()[0]
    print(f"  Assessments to move: {before_count}")

    cursor.execute("UPDATE assessments SET student_id = ? WHERE student_id = ?", (MERGE_INTO, MERGE_FROM))
    moved = cursor.rowcount
    print(f"  Moved {moved} assessment row(s) from {MERGE_FROM} → {MERGE_INTO}")

    # Carry over struggles/mastered from duplicate into Alice if Alice's fields are empty
    cursor.execute("SELECT struggles, mastered, target_group FROM student_identity WHERE student_id = ?", (MERGE_FROM,))
    dup_row = cursor.fetchone()
    if dup_row:
        dup_struggles, dup_mastered, dup_group = dup_row
        cursor.execute("SELECT struggles, mastered, target_group FROM student_identity WHERE student_id = ?", (MERGE_INTO,))
        alice_row = cursor.fetchone()
        if alice_row:
            al_struggles, al_mastered, al_group = alice_row
            new_s = al_struggles or dup_struggles or ""
            new_m = al_mastered  or dup_mastered  or ""
            new_g = al_group     or dup_group     or "g1"
            cursor.execute("""
                UPDATE student_identity SET struggles = ?, mastered = ?, target_group = ?
                WHERE student_id = ?
            """, (new_s, new_m, new_g, MERGE_INTO))
            print(f"  Merged profile data into {MERGE_INTO}: struggles='{new_s}' mastered='{new_m}' group='{new_g}'")

    # Delete the duplicate identity row
    cursor.execute("DELETE FROM student_identity WHERE student_id = ?", (MERGE_FROM,))
    print(f"  Deleted identity row for {MERGE_FROM}: {cursor.rowcount} row(s)")

    # Ensure Alice has Glen as teacher
    cursor.execute("SELECT student_id FROM student_identity WHERE student_id = ?", (MERGE_INTO,))
    if cursor.fetchone():
        cursor.execute("UPDATE student_identity SET teacher_id = ? WHERE student_id = ?",
                       (TEACHER_EMAIL, MERGE_INTO))
        print(f"  Set teacher_id for {MERGE_INTO} → {TEACHER_EMAIL}")
    else:
        cursor.execute("""
            INSERT INTO student_identity (teacher_id, student_id, real_name)
            VALUES (?, ?, 'Alice')
        """, (TEACHER_EMAIL, MERGE_INTO))
        print(f"  Inserted missing identity row for Alice ({MERGE_INTO})")

    cursor.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()

    # ── 6. Retire the CSV ────────────────────────────────────────────────────
    print("\n[6] Retiring students.csv …")
    if os.path.exists(CSV_PATH):
        retired = CSV_PATH + ".retired"
        os.rename(CSV_PATH, retired)
        print(f"  Renamed  {CSV_PATH}  →  {retired}")
        print("  (The app will no longer read it. Delete it manually when you're confident.)")
    else:
        print(f"  {CSV_PATH} not found – nothing to retire.")

    # ── 7. Final summary ─────────────────────────────────────────────────────
    print("\n[7] Final state in SQLite:")
    conn2  = sqlite3.connect(DB_PATH)
    cur2   = conn2.cursor()
    cur2.execute("""
        SELECT student_id, real_name, struggles, mastered, target_group
        FROM student_identity
        WHERE teacher_id = ?
        ORDER BY real_name
    """, (TEACHER_EMAIL,))
    glen_students = cur2.fetchall()
    print(f"  Students assigned to {TEACHER_EMAIL}: {len(glen_students)}")
    for sid, name, struggles, mastered, group in glen_students:
        cur2.execute("SELECT COUNT(*) FROM assessments WHERE student_id = ?", (sid,))
        ac = cur2.fetchone()[0]
        print(f"    {sid}  name={name!r:10}  group={group}  assessments={ac}  struggles='{struggles}'  mastered='{mastered}'")
    conn2.close()

    print("\n✓  Migration and cleanup complete.")
    print("   Restart your Streamlit app — Glen's class should now show the correct students.\n")


if __name__ == "__main__":
    main()
