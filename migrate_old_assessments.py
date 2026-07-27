"""
One-time migration for UnBoxEd's assessments table.

Old rows have their notes stuck in the orphaned 'teacher_refinement' column
(never read by get_student_history) and no 'test_name' value at all (the
column didn't exist yet when they were saved).

This script:
  1. Copies teacher_refinement -> teacher_refined_notes wherever
     teacher_refined_notes is empty and teacher_refinement has data.
  2. Extracts a test_name from the "Word List: X" header embedded in the
     notes (the same convention app.py already writes), wherever test_name
     is empty.

Run it once, from the same folder as your app (so the relative DB_PATH
resolves the same way). It runs as a DRY RUN by default -- it prints what
it *would* change but does not commit. Re-run with --apply to actually
write the changes.

Usage:
    python migrate_old_assessments.py            # dry run, just prints
    python migrate_old_assessments.py --apply     # actually updates the DB
"""

import sqlite3
import sys

DB_PATH = "data/spelling_coach.db"  # must match DB_PATH in database_manager.py


def extract_test_name(notes_text):
    """Same convention app.py uses: a 'Word List: X' header on the first line."""
    if not notes_text:
        return None
    first_line = str(notes_text).strip().split("\n")[0]
    if first_line.startswith("Word List:"):
        name = first_line.replace("Word List:", "").strip()
        return name if name else None
    return None


def main():
    apply_changes = "--apply" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, teacher_refinement, teacher_refined_notes, test_name
        FROM assessments
    """)
    rows = cursor.fetchall()

    notes_updates = []
    name_updates = []

    for row_id, teacher_refinement, teacher_refined_notes, test_name in rows:
        new_notes = None
        new_name = None

        if (not teacher_refined_notes or not str(teacher_refined_notes).strip()) \
                and teacher_refinement and str(teacher_refinement).strip():
            new_notes = teacher_refinement

        if not test_name or not str(test_name).strip():
            source_text = teacher_refined_notes or teacher_refinement
            extracted = extract_test_name(source_text)
            if extracted:
                new_name = extracted

        if new_notes is not None:
            notes_updates.append((new_notes, row_id))
        if new_name is not None:
            name_updates.append((new_name, row_id))

    print(f"Scanned {len(rows)} assessment rows.")
    print(f"  {len(notes_updates)} rows will get teacher_refined_notes backfilled.")
    print(f"  {len(name_updates)} rows will get test_name backfilled.")

    if not apply_changes:
        print("\nDry run only -- no changes written.")
        print("Preview of the first 5 note backfills:")
        for new_notes, row_id in notes_updates[:5]:
            preview = new_notes[:80].replace("\n", " ")
            print(f"  id={row_id}: {preview}...")
        print("\nPreview of the first 5 test_name backfills:")
        for new_name, row_id in name_updates[:5]:
            print(f"  id={row_id}: test_name -> '{new_name}'")
        print("\nRun again with --apply to write these changes.")
        conn.close()
        return

    for new_notes, row_id in notes_updates:
        cursor.execute(
            "UPDATE assessments SET teacher_refined_notes = ? WHERE id = ?",
            (new_notes, row_id)
        )
    for new_name, row_id in name_updates:
        cursor.execute(
            "UPDATE assessments SET test_name = ? WHERE id = ?",
            (new_name, row_id)
        )

    conn.commit()
    conn.close()
    print("\nDone. Changes committed.")


if __name__ == "__main__":
    main()