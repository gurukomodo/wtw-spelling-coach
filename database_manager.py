import sqlite3
from datetime import datetime
import os
import csv
import hashlib

DB_PATH = "data/spelling_coach.db"

def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Initial Table Creation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            teacher_id TEXT,
            test_date DATE,
            created_at DATETIME,
            raw_transcription TEXT,
            g0_phonemic REAL,
            g1_cvc REAL,
            g2_digraphs REAL,
            g3_silent_e REAL,
            g4_vowel_teams REAL,
            g5_r_controlled REAL,
            g6_clusters REAL,
            g7_multisyllabic REAL,
            g8_reduction REAL,
            suggested_next TEXT,
            teacher_notes TEXT,
            teacher_refined_notes TEXT,
            struggling_words TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_identity (
            teacher_id TEXT,
            student_id TEXT,
            real_name TEXT,
            pseudonym TEXT,
            PRIMARY KEY (teacher_id, student_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_settings (
            teacher_id TEXT PRIMARY KEY,
            unit_description TEXT
        )
    ''')

    # 2. Schema Repair / Migration
    repair_schema(cursor)

    conn.commit()
    conn.close()

def repair_schema(cursor):
    """Ensures the database schema is up-to-date."""
    cursor.execute("PRAGMA table_info(assessments)")
    columns = [col[1] for col in cursor.fetchall()]

    if "student_name" in columns and "student_id" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN student_id TEXT")
        cursor.execute("UPDATE assessments SET student_id = student_name")
        print("Schema Repair: Migrated student_name to student_id.")

    if "struggling_words" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN struggling_words TEXT")
        print("Schema Repair: Added struggling_words column.")

    if "created_at" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN created_at DATETIME")
        print("Schema Repair: Added created_at column.")

    if "teacher_id" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN teacher_id TEXT")
        print("Schema Repair: Added teacher_id column to assessments.")

    # Add pseudonym column if missing
    cursor.execute("PRAGMA table_info(student_identity)")
    identity_cols = [col[1] for col in cursor.fetchall()]
    if "pseudonym" not in identity_cols:
        cursor.execute("ALTER TABLE student_identity ADD COLUMN pseudonym TEXT")
        print("Schema Repair: Added pseudonym column.")

# ============================================================
# PRIVACY: PSEUDONYM SYSTEM
# ============================================================

def generate_pseudonym(teacher_id, student_id):
    """Generates a consistent pseudonym like 'Student_01' based on teacher."""
    # Count existing students for this teacher to get the number
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM student_identity WHERE teacher_id = ?', (teacher_id,))
    count = cursor.fetchone()[0] + 1
    conn.close()
    return f"Student_{count:02d}"

def get_pseudonym(teacher_id, student_id):
    """Returns the pseudonym for a student, generating one if needed."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT pseudonym FROM student_identity WHERE teacher_id = ? AND student_id = ?', (teacher_id, student_id))
    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        return result[0]

    # Generate new pseudonym
    pseudonym = generate_pseudonym(teacher_id, student_id)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE student_identity SET pseudonym = ? WHERE teacher_id = ? AND student_id = ?',
                   (pseudonym, teacher_id, student_id))
    conn.commit()
    conn.close()
    return pseudonym

def get_student_id_from_pseudonym(teacher_id, pseudonym):
    """Looks up the real student_id from a pseudonym."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT student_id FROM student_identity WHERE teacher_id = ? AND pseudonym = ?',
                   (teacher_id, pseudonym))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# ============================================================
# DATA SYNC & RECOVERY
# ============================================================

def sync_identity_from_assessments():
    """
    Syncs student_identity from assessments.
    Handles student_id AND student_name columns.
    Creates pseudonyms automatically.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get ALL unique students from assessments
    cursor.execute('''
        SELECT DISTINCT
            COALESCE(NULLIF(student_id, ''), student_name) as identifier,
            MAX(student_name) as raw_name
        FROM assessments
        WHERE COALESCE(NULLIF(student_id, ''), student_name) IS NOT NULL
        AND COALESCE(NULLIF(student_id, ''), student_name) != ''
        GROUP BY identifier
    ''')
    assessment_students = cursor.fetchall()

    created_count = 0
    for identifier, raw_name in assessment_students:
        cursor.execute('SELECT 1 FROM student_identity WHERE student_id = ?', (identifier,))
        if not cursor.fetchone():
            display_name = raw_name if raw_name and raw_name != identifier else identifier
            try:
                # Insert as orphan - no teacher assigned yet
                cursor.execute('''
                    INSERT INTO student_identity (teacher_id, student_id, real_name, pseudonym)
                    VALUES (NULL, ?, ?, NULL)
                ''', (identifier, display_name))
                created_count += 1
            except Exception as e:
                print(f"Error creating identity for {identifier}: {e}")

    conn.commit()
    conn.close()
    return {"created": created_count, "total_in_assessments": len(assessment_students)}

def clear_all_data():
    """
    Factory Reset: DELETES ALL DATA from assessments and student_identity.
    PRESERVES teacher_settings (registered teachers stay registered).
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM assessments")
    assessments_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM student_identity")
    identity_count = cursor.fetchone()[0]

    # Delete all data except teacher_settings
    cursor.execute("DELETE FROM assessments")
    cursor.execute("DELETE FROM student_identity")
    # teacher_settings is PRESERVED

    conn.commit()
    conn.close()

    return {
        "assessments_deleted": assessments_count,
        "identity_deleted": identity_count,
        "teachers_preserved": True
    }

def factory_reset():
    """
    Factory Reset: Deletes assessments and student_identity, keeps teacher_settings.
    Returns counts for confirmation.
    """
    return clear_all_data()

def fix_all_teacher_ids():
    """Ensures teacher_id consistency across all tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sync_identity_from_assessments()

    cursor.execute('''
        SELECT student_id, teacher_id FROM student_identity
        WHERE teacher_id IS NOT NULL AND teacher_id != ''
    ''')
    student_teachers = cursor.fetchall()

    updated_count = 0
    for student_id, teacher_id in student_teachers:
        cursor.execute('''
            UPDATE assessments SET teacher_id = ? WHERE student_id = ?
        ''', (teacher_id, student_id))
        updated_count += cursor.rowcount

    conn.commit()
    conn.close()

    return {"students_synced": len(student_teachers), "assessment_rows_updated": updated_count}

# ============================================================
# TEACHER SETTINGS
# ============================================================

def register_teacher(teacher_id, teacher_name):
    """Registers a new teacher."""
    save_teacher_settings(teacher_id, "")
    return True

def save_teacher_settings(teacher_id, description):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO teacher_settings (teacher_id, unit_description)
        VALUES (?, ?)
    ''', (teacher_id, description))
    conn.commit()
    conn.close()

def get_teacher_settings(teacher_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT unit_description FROM teacher_settings WHERE teacher_id = ?', (teacher_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] else ""

# ============================================================
# STUDENT IDENTITY (PRIVACY-FRIENDLY)
# ============================================================

def save_student_identity(teacher_id, student_id, real_name):
    """Saves student identity and generates pseudonym if needed."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if pseudonym exists
    cursor.execute('SELECT pseudonym FROM student_identity WHERE student_id = ?', (student_id,))
    result = cursor.fetchone()
    pseudonym = result[0] if result else generate_pseudonym(teacher_id, student_id)

    cursor.execute('''
        INSERT OR REPLACE INTO student_identity (teacher_id, student_id, real_name, pseudonym)
        VALUES (?, ?, ?, ?)
    ''', (teacher_id, student_id, real_name, pseudonym))

    conn.commit()
    conn.close()

def get_real_name(teacher_id, student_id):
    """Returns the real name for a student."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT real_name FROM student_identity WHERE student_id = ?', (student_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else student_id

def get_display_name(teacher_id, student_id):
    """
    Returns the name to display to the teacher.
    Teachers see real names for instructional clarity.
    """
    return get_real_name(teacher_id, student_id)

def get_student_id_by_name(teacher_id, real_name):
    """Looks up student_id by real_name."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT student_id FROM student_identity WHERE real_name = ?
    ''', (real_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_teacher_students(teacher_id):
    """
    Returns {student_id: real_name} for a specific teacher.
    Shows real names for instructional clarity.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT student_id, real_name FROM student_identity
        WHERE teacher_id = ?
    ''', (teacher_id,))
    results = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}

def get_teacher_student_pseudonyms(teacher_id):
    """
    Returns {pseudonym: real_name} for a specific teacher.
    Used for the app.py dropdown.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT pseudonym, real_name FROM student_identity
        WHERE teacher_id = ?
    ''', (teacher_id,))
    results = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}

def count_unowned_students():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM student_identity
        WHERE teacher_id IS NULL OR teacher_id = ''
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def assign_unowned_students(teacher_id):
    """Assigns ALL unowned students to the provided teacher."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE student_identity
        SET teacher_id = ?, pseudonym = ?
        WHERE teacher_id IS NULL OR teacher_id = ''
    ''', (teacher_id, None))

    # Generate new pseudonyms for assigned students
    cursor.execute('SELECT student_id FROM student_identity WHERE teacher_id = ?', (teacher_id,))
    for (sid,) in cursor.fetchall():
        pseudonym = generate_pseudonym(teacher_id, sid)
        cursor.execute('UPDATE student_identity SET pseudonym = ? WHERE student_id = ?', (pseudonym, sid))

    cursor.execute('''
        UPDATE assessments SET teacher_id = ?
        WHERE student_id IN (SELECT student_id FROM student_identity WHERE teacher_id = ?)
    ''', (teacher_id, teacher_id))

    conn.commit()
    conn.close()
    return cursor.rowcount

# ============================================================
# TEACHER LOOKUPS
# ============================================================

def get_all_teachers():
    """Returns all registered teacher emails."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT teacher_id FROM (
            SELECT teacher_id FROM student_identity
            UNION
            SELECT teacher_id FROM teacher_settings
        ) WHERE teacher_id IS NOT NULL AND teacher_id != '' AND teacher_id != 'orphaned'
    ''')
    results = [row[0] for row in cursor.fetchall()]
    conn.close()
    return results

# ============================================================
# ORPHANED STUDENTS
# ============================================================

def get_orphaned_students():
    """Returns students without a teacher assignment."""
    sync_identity_from_assessments()

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT student_id, real_name, pseudonym
        FROM student_identity
        WHERE teacher_id IS NULL OR teacher_id = '' OR teacher_id = 'orphaned'
        ORDER BY real_name
    ''')
    orphans = cursor.fetchall()
    conn.close()
    return orphans

def get_orphaned_assessments_count():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM assessments
        WHERE teacher_id IS NULL OR teacher_id = '' OR teacher_id = 'orphaned'
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ============================================================
# ASSIGNMENT FUNCTIONS
# ============================================================

def bulk_assign_students(student_ids, target_teacher_email):
    """Assigns students to a teacher. Updates both identity and assessments."""
    if not student_ids:
        return {"students_assigned": 0, "assessments_updated": 0}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for sid in student_ids:
        pseudonym = generate_pseudonym(target_teacher_email, sid)
        cursor.execute('''
            INSERT OR REPLACE INTO student_identity (teacher_id, student_id, real_name, pseudonym)
            VALUES (?, ?, COALESCE((SELECT real_name FROM student_identity WHERE student_id = ?), ?), ?)
        ''', (target_teacher_email, sid, sid, sid, pseudonym))

    placeholders = ','.join(['?' for _ in student_ids])
    cursor.execute(f'''
        UPDATE assessments SET teacher_id = ? WHERE student_id IN ({placeholders})
    ''', [target_teacher_email] + student_ids)
    assessments_updated = cursor.rowcount

    conn.commit()
    conn.close()

    return {"students_assigned": len(student_ids), "assessments_updated": assessments_updated}

def bulk_assign_orphans_to_teacher(target_teacher_id):
    """Assigns ALL orphaned students to the specified teacher."""
    orphans = get_orphaned_students()
    if not orphans:
        return {"students_assigned": 0, "assessments_updated": 0}

    student_ids = [o[0] for o in orphans]
    result = bulk_assign_students(student_ids, target_teacher_id)
    return {
        "students_assigned": result["students_assigned"],
        "assessments_updated": result["assessments_updated"]
    }

def assign_student_to_teacher(student_id, teacher_id):
    """Assigns a single student to a teacher."""
    return bulk_assign_students([student_id], teacher_id)

# ============================================================
# DEBUG & STATS
# ============================================================

def get_raw_assessments(limit=10):
    """Returns raw assessment rows for admin debugging."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f'SELECT * FROM assessments ORDER BY id LIMIT {limit}')
    results = cursor.fetchall()
    cursor.execute("PRAGMA table_info(assessments)")
    columns = [col[1] for col in cursor.fetchall()]
    conn.close()
    return columns, results

def get_database_stats():
    """Returns database statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    stats = {}

    cursor.execute("SELECT COUNT(*) FROM assessments")
    stats["total_assessments"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT student_id) FROM assessments")
    stats["unique_students_in_assessments"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM student_identity")
    stats["total_students_in_identity"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM student_identity WHERE teacher_id IS NULL OR teacher_id = ''")
    stats["orphaned_students"] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT teacher_id) FROM student_identity WHERE teacher_id IS NOT NULL AND teacher_id != ''")
    stats["total_teachers"] = cursor.fetchone()[0]

    conn.close()
    return stats

# ============================================================
# CSV IMPORT
# ============================================================

def import_from_csv(teacher_email=None):
    """Imports legacy CSV data into the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    imported_students = 0
    imported_assessments = 0

    if os.path.exists("students.csv"):
        try:
            with open("students.csv", mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row.get("Student ID") or row.get("Student Name")
                    name = row.get("Student Name") or sid
                    if sid:
                        cursor.execute('SELECT 1 FROM student_identity WHERE student_id = ?', (sid,))
                        if not cursor.fetchone():
                            cursor.execute('''
                                INSERT INTO student_identity (teacher_id, student_id, real_name, pseudonym)
                                VALUES (NULL, ?, ?, NULL)
                            ''', (sid, name))
                            imported_students += 1
            conn.commit()
        except Exception as e:
            print(f"Error importing students.csv: {e}")

    if os.path.exists("assessments.csv"):
        try:
            with open("assessments.csv", mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row.get("student_id") or row.get("Student ID")
                    if not sid: continue

                    test_date = row.get("test_date") or datetime.now().strftime("%Y-%m-%d")

                    cursor.execute('''
                        INSERT INTO assessments (
                            student_id, teacher_id, test_date, created_at, raw_transcription,
                            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e,
                            g4_vowel_teams, g5_r_controlled, g6_clusters,
                            g7_multisyllabic, g8_reduction, suggested_next,
                            teacher_notes, teacher_refined_notes, struggling_words
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        sid, None, test_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        row.get("raw_transcription", ""),
                        row.get("g0", 0), row.get("g1", 0), row.get("g2", 0),
                        row.get("g3", 0), row.get("g4", 0), row.get("g5", 0),
                        row.get("g6", 0), row.get("g7", 0), row.get("g8", 0),
                        row.get("suggested_next", ""), row.get("teacher_notes", ""),
                        row.get("teacher_refined_notes", ""), row.get("struggling_words", "")
                    ))
                    imported_assessments += 1
            conn.commit()
        except Exception as e:
            print(f"Error importing assessments.csv: {e}")

    conn.close()
    sync_identity_from_assessments()

    return {"students": imported_students, "assessments": imported_assessments}

# ============================================================
# ASSESSMENT HISTORY (PRIVACY-FRIENDLY)
# ============================================================

def get_student_history(student_id, teacher_id=None, admin=False):
    """Fetches all historical assessments for a student."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            id, student_id, teacher_id, test_date, created_at,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e,
            g4_vowel_teams, g5_r_controlled, g6_clusters,
            g7_multisyllabic, g8_reduction, suggested_next,
            teacher_notes, teacher_refined_notes, struggling_words
        FROM assessments
        WHERE student_id = ?
        ORDER BY created_at DESC
    ''', (student_id,))
    results = cursor.fetchall()
    conn.close()
    return results

def get_anonymized_history(student_name):
    """
    CRITICAL: Returns student history with real name replaced by 'The Student'.
    This is the ONLY function that should be called when sending data to AI.
    Preserves all assessment data but removes identifying information.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Find the student by real_name or student_id
    cursor.execute('SELECT student_id FROM student_identity WHERE real_name = ?', (student_name,))
    result = cursor.fetchone()

    if not result:
        # Fallback: try student_id directly
        cursor.execute('SELECT student_id FROM student_identity WHERE student_id = ?', (student_name,))
        result = cursor.fetchone()

    if not result:
        conn.close()
        return []

    student_id = result[0]

    # Fetch all assessments with ALL relevant data
    cursor.execute('''
        SELECT
            test_date, created_at,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e,
            g4_vowel_teams, g5_r_controlled, g6_clusters,
            g7_multisyllabic, g8_reduction, suggested_next,
            teacher_notes, teacher_refined_notes, struggling_words
        FROM assessments
        WHERE student_id = ?
        ORDER BY created_at DESC
    ''', (student_id,))

    rows = cursor.fetchall()
    conn.close()

    # Build anonymized history - replace ALL identifiers with 'The Student'
    anonymized = []
    for row in rows:
        anon_record = {
            "student": "The Student",  # Alias instead of real name
            "student_id": "ANONYMIZED",  # No ID leakage
            "test_date": row[0],
            "created_at": row[1],
            "g0_phonemic": row[2],
            "g1_cvc": row[3],
            "g2_digraphs": row[4],
            "g3_silent_e": row[5],
            "g4_vowel_teams": row[6],
            "g5_r_controlled": row[7],
            "g6_clusters": row[8],
            "g7_multisyllabic": row[9],
            "g8_reduction": row[10],
            "suggested_next": row[11],
            "teacher_notes": row[12],
            "teacher_refined_notes": row[13],
            "struggling_words": row[14]
        }
        anonymized.append(anon_record)

    return anonymized


def get_all_students_by_teacher(teacher_email):
    """
    BUG FIX: Returns ALL students associated with a teacher's email.
    Searches both teacher_id and joins through student_identity.
    Ignores legacy CSV ID format issues.
    Uses student_name internally for join, strips before external display.
    Immediately reflects G-Level and Class Status cards once data is saved.
    """
    if not teacher_email:
        return []
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # First sync to ensure all students have identity records
    sync_identity_from_assessments()
    
    # Get ALL students for this teacher with their latest assessment data
    cursor.execute('''
        SELECT DISTINCT
            si.student_id,
            si.real_name,
            si.pseudonym,
            COALESCE(latest.total_attempts, 0) as total_attempts,
            latest.last_date,
            latest.current_g_level,
            latest.most_struggled_word
        FROM student_identity si
        LEFT JOIN (
            SELECT 
                a.student_id,
                COUNT(*) as total_attempts,
                MAX(a.created_at) as last_date,
                (
                    SELECT a2.suggested_next 
                    FROM assessments a2 
                    WHERE a2.student_id = a.student_id 
                    ORDER BY a2.created_at DESC LIMIT 1
                ) as current_g_level,
                (
                    SELECT a3.struggling_words 
                    FROM assessments a3 
                    WHERE a3.student_id = a.student_id 
                    ORDER BY a3.created_at DESC LIMIT 1
                ) as most_struggled_word
            FROM assessments a
            GROUP BY a.student_id
        ) latest ON si.student_id = latest.student_id
        WHERE si.teacher_id = ?
        ORDER BY si.real_name
    ''', (teacher_email,))
    
    students = cursor.fetchall()
    conn.close()
    
    return [{
        "student_id": s[0], 
        "name": s[1],  # Real name - for teacher eyes only
        "pseudonym": s[2] or f"Student_{i+1:02d}",
        "total_attempts": s[3] or 0,
        "last_date": s[4],
        "current_g_level": s[5],  # G-Level from most recent assessment
        "most_struggled_word": s[6]
    } for i, s in enumerate(students)]


def get_teacher_students_full(teacher_email):
    """
    Returns {student_id: {name, pseudonym}} for a teacher.
    Includes ALL students regardless of ID format (legacy or new).
    """
    if not teacher_email:
        return {}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure sync
    sync_identity_from_assessments()

    cursor.execute('''
        SELECT student_id, real_name, pseudonym
        FROM student_identity
        WHERE teacher_id = ?
    ''', (teacher_email,))

    results = cursor.fetchall()
    conn.close()

    student_map = {}
    for row in results:
        sid = row[0]
        student_map[sid] = {
            "name": row[1],
            "pseudonym": row[2] or f"Student_{list(student_map.keys()).index(sid) + 1:02d}"
        }

    return student_map


def get_all_students_for_allocation():
    """
    Returns ALL students from student_identity for the allocation table.
    Used by Admin to reassign students to teachers.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Ensure sync first
    sync_identity_from_assessments()

    cursor.execute('''
        SELECT student_id, real_name, teacher_id, pseudonym
        FROM student_identity
        ORDER BY real_name
    ''')

    students = cursor.fetchall()
    conn.close()

    return [{
        "student_id": s[0],
        "name": s[1],
        "current_teacher": s[2] or "Unassigned",
        "pseudonym": s[3] or f"Student_??"
    } for s in students]


def update_student_teacher(student_id, new_teacher_id):
    """
    Updates a student's teacher assignment across both tables.
    Updates student_identity AND assessments simultaneously.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Update student_identity
    cursor.execute('''
        UPDATE student_identity
        SET teacher_id = ?
        WHERE student_id = ?
    ''', (new_teacher_id, student_id))

    identity_updated = cursor.rowcount

    # Update all assessments for this student
    cursor.execute('''
        UPDATE assessments
        SET teacher_id = ?
        WHERE student_id = ?
    ''', (new_teacher_id, student_id))

    assessments_updated = cursor.rowcount

    conn.commit()
    conn.close()

    return {
        "student_id": student_id,
        "new_teacher": new_teacher_id,
        "identity_updated": identity_updated,
        "assessments_updated": assessments_updated
    }


def get_mastered_words_from_raw(raw_text, word_list=None):
    """Extracts correctly spelled words from raw transcription."""
    if not raw_text:
        return ""

    mastered = []
    for line in raw_text.strip().split('\n'):
        line = line.strip()
        if ':' in line:
            parts = line.split(':')
            if len(parts) >= 2 and parts[0].strip().lower() == parts[1].strip().lower():
                mastered.append(parts[0].strip())

    return ", ".join(mastered) if mastered else ""

def save_assessment(data, raw_text, teacher_refinement=None, struggling_words=None, teacher_id=None):
    """
    Saves a new assessment record.
    AUTO-CREATES student_identity entry if student is new.
    Uses student_name as the internal link to prevent None errors.

    Args:
        data: assessment data object with student_id, scores, etc.
        raw_text: raw transcription
        teacher_refinement: refined notes
        struggling_words: struggling words
        teacher_id: current teacher's email (auto-creates identity if needed)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    suggested_str = ", ".join(data.suggested_next_groups) if data.suggested_next_groups else ""

    # Check if student exists in identity table
    cursor.execute('SELECT teacher_id FROM student_identity WHERE student_id = ?', (data.student_id,))
    result = cursor.fetchone()

    if result:
        # Student exists - use their current teacher
        current_teacher_id = result[0] if result[0] else teacher_id
    else:
        # NEW STUDENT - auto-create identity entry
        current_teacher_id = teacher_id
        pseudonym = generate_pseudonym(teacher_id, data.student_id) if teacher_id else None

        # Extract real name from student_id if it looks like a real name
        real_name = data.student_id
        # If student_id is generated (STU_xxxx), use it as both id and name temporarily
        if data.student_id.startswith('STU_'):
            real_name = f"Student_{data.student_id.split('_')[1]}"

        cursor.execute('''
            INSERT INTO student_identity (teacher_id, student_id, real_name, pseudonym)
            VALUES (?, ?, ?, ?)
        ''', (teacher_id, data.student_id, real_name, pseudonym))
        print(f"Auto-created identity for {data.student_id}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
        INSERT INTO assessments (
            student_id, teacher_id, test_date, created_at, raw_transcription,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e,
            g4_vowel_teams, g5_r_controlled, g6_clusters,
            g7_multisyllabic, g8_reduction, suggested_next,
            teacher_notes, teacher_refined_notes, struggling_words
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.student_id, current_teacher_id, datetime.now().strftime("%Y-%m-%d"), now, raw_text,
        data.g0_phonemic_awareness, data.g1_cvc_mapping, data.g2_digraphs,
        data.g3_silent_e, data.g4_vowel_teams, data.g5_r_controlled,
        data.g6_clusters, data.g7_multisyllabic, data.g8_reduction_morphology,
        suggested_str, data.teacher_notes, teacher_refinement, struggling_words
    ))

    conn.commit()
    conn.close()
    return True

# ============================================================
# UNIFIED STUDENT STATUS (PRIVACY-FRIENDLY)
# ============================================================

def get_all_students_with_status():
    """
    Returns ALL students with status info.
    Real names are returned for admin view.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sync_identity_from_assessments()

    # Get all students
    cursor.execute('''
        SELECT DISTINCT
            si.student_id,
            si.real_name,
            si.teacher_id,
            si.pseudonym
        FROM student_identity si
        ORDER BY si.real_name
    ''')

    all_students = {}
    for row in cursor.fetchall():
        sid = row[0]
        all_students[sid] = {
            "student_id": sid,
            "name": row[1],  # Real name for admin
            "teacher": row[2] or "Unassigned",
            "pseudonym": row[3] or f"Student_??",
            "last_date": None,
            "total_attempts": 0,
            "current_g_level": None,
            "most_struggled_word": None
        }

    # Get assessment counts and last dates
    cursor.execute('''
        SELECT student_id, COUNT(*), MAX(created_at), MAX(test_date)
        FROM assessments
        WHERE student_id IS NOT NULL AND student_id != ''
        GROUP BY student_id
    ''')

    for row in cursor.fetchall():
        sid = row[0]
        if sid in all_students:
            all_students[sid]["total_attempts"] = row[1]
            all_students[sid]["last_date"] = row[2] or row[3]

    # Get current G-level from most recent assessment
    cursor.execute('''
        SELECT a.student_id, a.suggested_next
        FROM assessments a
        INNER JOIN (
            SELECT student_id, MAX(created_at) as max_date
            FROM assessments GROUP BY student_id
        ) latest ON a.student_id = latest.student_id AND a.created_at = latest.max_date
        WHERE a.suggested_next IS NOT NULL AND a.suggested_next != ''
    ''')

    G_LEVEL_MAP = {"g0": "G0", "g1": "G1", "g2": "G2", "g3": "G3", "g4": "G4",
                   "g5": "G5", "g6": "G6", "g7": "G7", "g8": "G8"}

    for row in cursor.fetchall():
        sid = row[0]
        if sid in all_students and row[1]:
            tags = [t.strip().lower() for t in row[1].split(",") if t.strip()]
            valid_tags = [t for t in tags if t in G_LEVEL_MAP]
            if valid_tags:
                valid_tags.sort(key=lambda x: int(x[1:]))
                all_students[sid]["current_g_level"] = G_LEVEL_MAP[valid_tags[0]]

    # Get most struggled word
    cursor.execute('''
        SELECT a.student_id, a.struggling_words
        FROM assessments a
        INNER JOIN (
            SELECT student_id, MAX(created_at) as max_date
            FROM assessments GROUP BY student_id
        ) latest ON a.student_id = latest.student_id AND a.created_at = latest.max_date
        WHERE a.struggling_words IS NOT NULL AND a.struggling_words != ''
    ''')

    for row in cursor.fetchall():
        sid = row[0]
        if sid in all_students and row[1]:
            words = row[1].split(",")
            if words:
                all_students[sid]["most_struggled_word"] = words[0].strip().split(":")[0]

    conn.close()

    result = list(all_students.values())
    result.sort(key=lambda x: x["name"].lower())
    return result

def get_teacher_student_status(teacher_id):
    """
    Returns student status for a specific teacher.
    Teachers see real names for instructional clarity.
    """
    all_students = get_all_students_with_status()
    return [s for s in all_students if s["teacher"] == teacher_id]

# ============================================================
# RESULTS & GROUPS
# ============================================================

def get_all_latest_results(teacher_id=None, admin=False):
    """
    Fetches the most recent assessment for students.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    sync_identity_from_assessments()

    query = '''
        SELECT a.*, si.teacher_id, si.real_name
        FROM assessments a
        INNER JOIN (
            SELECT student_id, MAX(created_at) as max_date
            FROM assessments
            WHERE student_id IS NOT NULL AND student_id != ''
            GROUP BY student_id
        ) latest ON a.student_id = latest.student_id AND a.created_at = latest.max_date
        INNER JOIN student_identity si ON a.student_id = si.student_id
    '''

    if not admin and teacher_id:
        query += f" WHERE si.teacher_id = '{teacher_id}'"

    try:
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        print(f"Database error: {e}")
        conn.close()
        return []

def get_latest_teacher_notes(student_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT teacher_refined_notes FROM assessments
        WHERE student_id = ? AND teacher_refined_notes IS NOT NULL
        ORDER BY id DESC LIMIT 1
    ''', (student_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_struggling_words(student_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT struggling_words FROM assessments
        WHERE student_id = ? AND struggling_words IS NOT NULL AND struggling_words != ''
        AND created_at >= datetime('now', '-60 days')
        ORDER BY created_at DESC LIMIT 1
    ''', (student_id,))
    result = cursor.fetchone()
    if result:
        conn.close()
        return result[0]

    cursor.execute('''
        SELECT struggling_words FROM assessments
        WHERE student_id = ? AND struggling_words IS NOT NULL AND struggling_words != ''
        ORDER BY created_at DESC LIMIT 1
    ''', (student_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def generate_class_groups():
    """Organizes students by their current G-level group."""
    results = get_all_latest_results(admin=True)

    if not results:
        return {}

    group_titles = {
        "g0": "Group 0: Phonemic Awareness",
        "g1": "Group 1: Basic CVC Mapping",
        "g2": "Group 2: Digraphs",
        "g3": "Group 3: Silent E",
        "g4": "Group 4: Vowel Teams",
        "g5": "Group 5: R-Controlled",
        "g6": "Group 6: Clusters/Blends",
        "g7": "Group 7: Multisyllabic",
        "g8": "Group 8: Reduction & Morphology"
    }

    groups = {title: [] for title in group_titles.values()}
    groups["Review Needed"] = []

    for row in results:
        student_id = row[1]
        suggested_string = row[14] if len(row) > 14 else None

        if suggested_string:
            target_areas = [area.strip().lower() for area in suggested_string.split(",")]
            valid_tags = [area for area in target_areas if area in group_titles]
            if valid_tags:
                valid_tags.sort(key=lambda x: int(x[1:]))
                lowest_group = valid_tags[0]
                display_title = group_titles[lowest_group]
                groups[display_title].append(student_id)
            else:
                groups["Review Needed"].append(student_id)
        else:
            groups["Review Needed"].append(student_id)

    return {k: v for k, v in groups.items() if v}

def get_db_connection():
    # Ensure this matches the filename in your app.py
    return sqlite3.connect(DB_PATH)

def factory_reset():
    """Wipes all student and assessment data but keeps teachers."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check for existing tables to avoid errors
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [t[0] for t in cursor.fetchall()]
        
        target_tables = ['assessments', 'student_identity', 'students']
        for table in target_tables:
            if table in tables:
                cursor.execute(f"DELETE FROM {table}")
        
        conn.commit()
        return True, "Database wiped successfully!"
    except Exception as e:
        return False, f"Reset failed: {str(e)}"
    finally:
        conn.close()

def get_all_teachers():
    """Returns a list of registered teacher emails, checking for column name variations."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Get column names for the table
        cursor.execute("PRAGMA table_info(teacher_settings)")
        columns = [col[1] for col in cursor.fetchall()]
        
        # Determine which column to use
        target_col = None
        for col in ['email', 'teacher_email', 'username']:
            if col in columns:
                target_col = col
                break
        
        if target_col:
            cursor.execute(f"SELECT {target_col} FROM teacher_settings")
            teachers = [row[0] for row in cursor.fetchall()]
            return teachers
        else:
            return []
    except Exception as e:
        print(f"Error fetching teachers: {e}")
        return []
    finally:
        conn.close()

def allocate_student_to_teacher(student_name, teacher_email):
    """Links a student name to a specific teacher across all tables."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Update identity table
        cursor.execute("UPDATE student_identity SET teacher_id = ? WHERE student_name = ?", (teacher_email, student_name))
        # Update assessments table
        cursor.execute("UPDATE assessments SET teacher_id = ? WHERE student_name = ?", (teacher_email, student_name))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()