"""
Patch script — run this ONCE to finish the cleanup that crashed.

The previous cleanup_and_migrate.py script errored before committing,
so the ghost deletes and Alice merge were not saved.

This script completes exactly those two steps and nothing else.

Run from the same directory as app.py:
    python patch_cleanup.py
"""

import sqlite3
import shutil
from datetime import datetime
import os

DB_PATH       = "data/spelling_coach.db"
TEACHER_EMAIL = "glenp@gm.yhsh.tn.edu.tw"
GHOST_IDS     = ["STU_4942", "STU_7775"]
MERGE_FROM    = "STU_3995"
MERGE_INTO    = "STU_6264"   # Alice


def backup(path):
    if os.path.exists(path):
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = f"{path}.backup_{ts}"
        shutil.copy2(path, dst)
        print(f"  Backed up {path} → {dst}")


def main():
    print("\n" + "=" * 55)
    print("  UnBoxEd – Ghost Delete + Alice Merge Patch")
    print("=" * 55)

    backup(DB_PATH)

    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")

    # ── Current state ──────────────────────────────────────────────────────
    print("\n[1] Current state for affected IDs:")
    for sid in GHOST_IDS + [MERGE_FROM, MERGE_INTO]:
        cursor.execute(
            "SELECT student_id, real_name, teacher_id FROM student_identity WHERE student_id = ?", (sid,))
        row = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM assessments WHERE student_id = ?", (sid,))
        ac = cursor.fetchone()[0]
        print(f"  {sid}  identity={row}  assessments={ac}")

    # ── Delete ghosts ──────────────────────────────────────────────────────
    print("\n[2] Deleting ghost students …")
    for sid in GHOST_IDS:
        cursor.execute("DELETE FROM student_identity WHERE student_id = ?", (sid,))
        id_del = cursor.rowcount
        cursor.execute("DELETE FROM assessments WHERE student_id = ?", (sid,))
        as_del = cursor.rowcount
        print(f"  {sid}: removed {id_del} identity row(s), {as_del} assessment row(s)")

    # ── Merge STU_3995 → STU_6264 ──────────────────────────────────────────
    print(f"\n[3] Merging {MERGE_FROM} → {MERGE_INTO} (Alice) …")

    # Move assessments
    cursor.execute(
        "UPDATE assessments SET student_id = ? WHERE student_id = ?", (MERGE_INTO, MERGE_FROM))
    print(f"  Moved {cursor.rowcount} assessment row(s) to {MERGE_INTO}")

    # Carry profile data from duplicate into Alice (only fills blank fields)
    cursor.execute(
        "SELECT struggles, mastered, target_group FROM student_identity WHERE student_id = ?",
        (MERGE_FROM,))
    dup = cursor.fetchone()

    cursor.execute(
        "SELECT teacher_id, struggles, mastered, target_group FROM student_identity WHERE student_id = ?",
        (MERGE_INTO,))
    alice = cursor.fetchone()

    if alice:
        al_teacher, al_s, al_m, al_g = alice
        new_s = al_s or (dup[0] if dup else "") or ""
        new_m = al_m or (dup[1] if dup else "") or ""
        new_g = al_g or (dup[2] if dup else "") or "g1"
        # Use UPDATE with WHERE — do NOT touch teacher_id (avoids the PK constraint error)
        cursor.execute("""
            UPDATE student_identity
            SET struggles = ?, mastered = ?, target_group = ?
            WHERE student_id = ?
        """, (new_s, new_m, new_g, MERGE_INTO))
        print(f"  Updated Alice's profile: struggles='{new_s}' mastered='{new_m}' group='{new_g}'")

        # Fix teacher only if it's wrong or missing
        if al_teacher != TEACHER_EMAIL:
            # DELETE + INSERT to safely update a composite primary key
            cursor.execute("DELETE FROM student_identity WHERE student_id = ?", (MERGE_INTO,))
            cursor.execute("""
                INSERT INTO student_identity (teacher_id, student_id, real_name, struggles, mastered, target_group)
                VALUES (?, ?, 'Alice', ?, ?, ?)
            """, (TEACHER_EMAIL, MERGE_INTO, new_s, new_m, new_g))
            print(f"  Re-assigned Alice ({MERGE_INTO}) to teacher {TEACHER_EMAIL}")
        else:
            print(f"  Alice already assigned to {TEACHER_EMAIL} — no change needed")
    else:
        # Alice row doesn't exist at all — create it
        dup_s = dup[0] if dup else ""
        dup_m = dup[1] if dup else ""
        dup_g = dup[2] if dup else "g1"
        cursor.execute("""
            INSERT INTO student_identity (teacher_id, student_id, real_name, struggles, mastered, target_group)
            VALUES (?, ?, 'Alice', ?, ?, ?)
        """, (TEACHER_EMAIL, MERGE_INTO, dup_s, dup_m, dup_g))
        print(f"  Created Alice identity row for {MERGE_INTO}")

    # Remove the duplicate identity row
    cursor.execute("DELETE FROM student_identity WHERE student_id = ?", (MERGE_FROM,))
    print(f"  Deleted duplicate identity row for {MERGE_FROM}: {cursor.rowcount} row(s)")

    cursor.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    print("\n  ✓ Changes committed.")

    # ── Final summary ──────────────────────────────────────────────────────
    print(f"\n[4] Students now assigned to {TEACHER_EMAIL}:")
    conn2  = sqlite3.connect(DB_PATH)
    cur2   = conn2.cursor()
    cur2.execute("""
        SELECT student_id, real_name, target_group
        FROM student_identity
        WHERE teacher_id = ?
        ORDER BY real_name
    """, (TEACHER_EMAIL,))
    students = cur2.fetchall()
    for sid, name, group in students:
        cur2.execute("SELECT COUNT(*) FROM assessments WHERE student_id = ?", (sid,))
        ac = cur2.fetchone()[0]
        print(f"  {sid}  name={name!r:10}  group={group}  assessments={ac}")
    conn2.close()

    print(f"\n  Total: {len(students)} student(s)")
    print("\n✓  Patch complete. Restart Streamlit to see the updated class list.\n")


if __name__ == "__main__":
    main()
