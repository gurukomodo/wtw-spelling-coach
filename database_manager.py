import sqlite3
from datetime import datetime
import os

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
    """
    Ensures the database schema is up-to-date with the current code.
    """
    cursor.execute("PRAGMA table_info(assessments)")
    columns = [col[1] for col in cursor.fetchall()]
    
    # A. Fix student_id / student_name migration
    if "student_name" in columns and "student_id" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN student_id TEXT")
        cursor.execute("UPDATE assessments SET student_id = student_name")
        print("Schema Repair: Migrated student_name to student_id.")

    # B. Ensure struggling_words exists
    if "struggling_words" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN struggling_words TEXT")
        print("Schema Repair: Added struggling_words column.")

    # C. Ensure created_at exists
    if "created_at" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN created_at DATETIME")
        print("Schema Repair: Added created_at column.")

    # D. Ensure teacher_id exists in assessments
    if "teacher_id" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN teacher_id TEXT")
        print("Schema Repair: Added teacher_id column to assessments.")

# ============================================================
# DATABASE SANITIZATION & MAINTENANCE
# ============================================================

def sync_identity_from_assessments():
    """
    CRITICAL: Syncs student_identity table from assessments table.
    Any student in assessments WITHOUT an identity record gets one created.
    Uses student_id as the anchor, with student_id as the display name.
    Returns count of new identity records created.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Find students in assessments that don't exist in student_identity
    cursor.execute('''
        SELECT DISTINCT a.student_id
        FROM assessments a
        LEFT JOIN student_identity si ON a.student_id = si.student_id
        WHERE si.student_id IS NULL AND a.student_id IS NOT NULL AND a.student_id != ''
    ''')
    missing_students = [row[0] for row in cursor.fetchall()]
    
    # Insert missing students as ORPHANS (teacher_id = NULL)
    created_count = 0
    for student_id in missing_students:
        try:
            cursor.execute('''
                INSERT INTO student_identity (teacher_id, student_id, real_name)
                VALUES (NULL, ?, ?)
            ''', (student_id, student_id))  # Use student_id as real_name too
            created_count += 1
        except Exception as e:
            print(f"Error creating identity for {student_id}: {e}")
    
    conn.commit()
    conn.close()
    return {"created": created_count, "total_missing": len(missing_students)}

def clear_all_data():
    """
    DELETES ALL DATA from both tables.
    Use with extreme caution - this is for clean re-import only.
    Returns confirmation dict.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Count before deletion
    cursor.execute("SELECT COUNT(*) FROM assessments")
    assessments_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM student_identity")
    identity_count = cursor.fetchone()[0]
    
    # Delete all data
    cursor.execute("DELETE FROM assessments")
    cursor.execute("DELETE FROM student_identity")
    
    conn.commit()
    conn.close()
    
    return {
        "assessments_deleted": assessments_count,
        "identity_deleted": identity_count,
        "status": "complete"
    }

def fix_all_teacher_ids():
    """
    Ensures teacher_id consistency:
    - Copies teacher_id from student_identity to ALL assessment rows for each student
    - Returns stats about what was updated
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get all students with their teacher_ids from identity
    cursor.execute('''
        SELECT student_id, teacher_id FROM student_identity
        WHERE teacher_id IS NOT NULL AND teacher_id != ''
    ''')
    student_teachers = cursor.fetchall()  # [(student_id, teacher_id), ...]
    
    updated_count = 0
    for student_id, teacher_id in student_teachers:
        # Update ALL assessment rows for this student
        cursor.execute('''
            UPDATE assessments
            SET teacher_id = ?
            WHERE student_id = ?
        ''', (teacher_id, student_id))
        updated_count += cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return {
        "students_synced": len(student_teachers),
        "total_assessment_rows_updated": updated_count
    }

# ============================================================
# TEACHER SETTINGS
# ============================================================

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
# STUDENT IDENTITY
# ============================================================

def save_student_identity(teacher_id, student_id, real_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO student_identity (teacher_id, student_id, real_name) 
        VALUES (?, ?, ?)
    ''', (teacher_id, student_id, real_name))
    conn.commit()
    conn.close()

def get_student_name(teacher_id, student_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT real_name FROM student_identity 
        WHERE teacher_id = ? AND student_id = ?
    ''', (teacher_id, student_id))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else student_id

def get_student_id_by_name(teacher_id, real_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT student_id FROM student_identity 
        WHERE teacher_id = ? AND real_name = ?
    ''', (teacher_id, real_name))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_teacher_students(teacher_id):
    """Returns a map of {student_id: real_name} for a specific teacher."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT student_id, real_name FROM student_identity 
        WHERE teacher_id = ?
    ''', (teacher_id,))
    results = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}

def count_unowned_students():
    """Returns count of students in identity table with no teacher."""
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
    """
    Finds students in student_identity who have no teacher_id (NULL or empty)
    and assigns them to the provided teacher_id.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Update identity map
    cursor.execute('''
        UPDATE student_identity 
        SET teacher_id = ? 
        WHERE teacher_id IS NULL OR teacher_id = ''
    ''', (teacher_id,))
    
    # 2. Update ALL assessments records for these students
    cursor.execute('''
        UPDATE assessments 
        SET teacher_id = ? 
        WHERE student_id IN (SELECT student_id FROM student_identity WHERE teacher_id = ?)
    ''', (teacher_id, teacher_id))
    
    updated_count = cursor.rowcount
    conn.commit()
    conn.close()
    return updated_count

# ============================================================
# TEACHER LOOKUPS
# ============================================================

def get_all_teachers():
    """Returns a list of all registered teacher IDs from the identity map and settings."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Combine unique teacher IDs from both identity map and settings table
    cursor.execute('''
        SELECT DISTINCT teacher_id FROM (
            SELECT teacher_id FROM student_identity
            UNION
            SELECT teacher_id FROM teacher_settings
        ) WHERE teacher_id IS NOT NULL AND teacher_id != '' AND teacher_id != 'orphaned'
    ''')
    results = cursor.fetchall()
    conn.close()
    return [row[0] for row in results]

# ============================================================
# ORPHANED STUDENTS
# ============================================================

def get_orphaned_students():
    """
    Returns orphaned students - those in student_identity with NULL/empty teacher_id.
    FIRST runs sync to ensure all assessment students have identity records.
    Returns list of tuples: (student_id, real_name)
    """
    # First, sync any missing students from assessments
    sync_identity_from_assessments()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get orphaned from student_identity ONLY (the source of truth for assignment)
    cursor.execute('''
        SELECT DISTINCT student_id, real_name, 'identity' as source
        FROM student_identity 
        WHERE teacher_id IS NULL OR teacher_id = '' OR teacher_id = 'orphaned' OR teacher_id = 'admin@example.com'
        ORDER BY real_name
    ''')
    orphans = cursor.fetchall()
    
    conn.close()
    return orphans

def get_orphaned_assessments_count():
    """Returns count of orphaned assessment records."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM assessments 
        WHERE teacher_id IS NULL OR teacher_id = '' OR teacher_id = 'orphaned' OR teacher_id = 'admin@example.com'
    ''')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ============================================================
# ASSIGNMENT FUNCTIONS
# ============================================================

def bulk_assign_students(student_ids, target_teacher_email):
    """
    Assigns a list of specific students to a target teacher.
    Updates BOTH student_identity AND ALL matching assessment rows.
    
    Args:
        student_ids: List of student_id strings to assign
        target_teacher_email: The teacher_id (email) to assign them to
    
    Returns:
        Dict with counts of updated rows
    """
    if not student_ids:
        return {"identity_updated": 0, "assessments_updated": 0}
    
    placeholders = ','.join(['?' for _ in student_ids])
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Update student_identity - INSERT OR REPLACE to ensure record exists
    for sid in student_ids:
        cursor.execute('''
            INSERT OR REPLACE INTO student_identity (teacher_id, student_id, real_name)
            VALUES (?, ?, COALESCE((SELECT real_name FROM student_identity WHERE student_id = ?), ?))
        ''', (target_teacher_email, sid, sid, sid))
    identity_updated = len(student_ids)
    
    # 2. Update ALL assessment rows for these students (no WHERE on teacher_id)
    cursor.execute(f'''
        UPDATE assessments 
        SET teacher_id = ? 
        WHERE student_id IN ({placeholders})
    ''', [target_teacher_email] + student_ids)
    assessments_updated = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    return {
        "identity_updated": identity_updated,
        "assessments_updated": assessments_updated
    }

def bulk_assign_orphans_to_teacher(target_teacher_id):
    """
    Assigns ALL orphaned students to the specified teacher.
    Updates BOTH student_identity AND ALL assessment rows.
    """
    # Get orphans first
    orphans = get_orphaned_students()
    if not orphans:
        return {"students_assigned": 0, "identity_rows_updated": 0, "assessment_rows_updated": 0}
    
    student_ids = [o[0] for o in orphans]
    return bulk_assign_students(student_ids, target_teacher_id)

def assign_student_to_teacher(student_id, teacher_id):
    """
    Assigns a single student to a teacher.
    Updates BOTH student_identity AND ALL assessment rows for that student.
    """
    return bulk_assign_students([student_id], teacher_id)

# ============================================================
# DEBUG & RAW DATA
# ============================================================

def get_raw_assessments(limit=5):
    """Returns the first N rows from assessments table, ignoring ownership. For admin debugging."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(f'''
        SELECT * FROM assessments ORDER BY id LIMIT {limit}
    ''')
    results = cursor.fetchall()
    
    # Get column names
    cursor.execute("PRAGMA table_info(assessments)")
    columns = [col[1] for col in cursor.fetchall()]
    conn.close()
    return columns, results

def get_database_stats():
    """Returns overall database statistics for admin dashboard."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    stats = {}
    
    # Total assessments
    cursor.execute("SELECT COUNT(*) FROM assessments")
    stats["total_assessments"] = cursor.fetchone()[0]
    
    # Total students in identity
    cursor.execute("SELECT COUNT(*) FROM student_identity")
    stats["total_students"] = cursor.fetchone()[0]
    
    # Orphaned students
    cursor.execute("SELECT COUNT(*) FROM student_identity WHERE teacher_id IS NULL OR teacher_id = ''")
    stats["orphaned_students"] = cursor.fetchone()[0]
    
    # Orphaned assessments
    cursor.execute("SELECT COUNT(*) FROM assessments WHERE teacher_id IS NULL OR teacher_id = ''")
    stats["orphaned_assessments"] = cursor.fetchone()[0]
    
    # Unique teachers
    cursor.execute("SELECT COUNT(DISTINCT teacher_id) FROM student_identity WHERE teacher_id IS NOT NULL AND teacher_id != ''")
    stats["total_teachers"] = cursor.fetchone()[0]
    
    conn.close()
    return stats

# ============================================================
# CSV IMPORT
# ============================================================

def import_from_csv(teacher_email=None):
    """
    Reads students.csv and assessments.csv and imports them into the SQL database.
    Sets teacher_id = NULL for ALL imported legacy data so they appear as 'orphaned'.
    Admin can then assign them to teachers.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    ORPHAN_TEACHER = None  # Explicitly NULL for orphan status
    
    # 1. Import Students from students.csv
    students_csv = "students.csv"
    imported_students = 0
    if os.path.exists(students_csv):
        try:
            with open(students_csv, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row.get("Student ID") or row.get("Student Name")
                    name = row.get("Student Name") or sid
                    if sid:
                        # Check if student already exists
                        cursor.execute('SELECT 1 FROM student_identity WHERE student_id = ?', (sid,))
                        if not cursor.fetchone():
                            cursor.execute('''
                                INSERT INTO student_identity (teacher_id, student_id, real_name) 
                                VALUES (?, ?, ?)
                            ''', (ORPHAN_TEACHER, sid, name))
                            imported_students += 1
            conn.commit()
        except Exception as e:
            print(f"Error importing students.csv: {e}")

    # 2. Import Assessments from assessments.csv (ALWAYS INSERT - never check for duplicates)
    assessments_csv = "assessments.csv"
    imported_assessments = 0
    if os.path.exists(assessments_csv):
        try:
            with open(assessments_csv, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row.get("student_id") or row.get("Student ID")
                    if not sid: continue
                    
                    # SAFE ENTRY: Always insert new row, never overwrite
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
                        sid, ORPHAN_TEACHER, test_date, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    
    # After import, sync identity from assessments
    sync_identity_from_assessments()
    
    return {"students": imported_students, "assessments": imported_assessments}

# ============================================================
# ASSESSMENT HISTORY
# ============================================================

def get_student_history(student_id, teacher_id=None, admin=False):
    """
    Fetches all historical assessments for a student.
    Teacher filtering: Teachers only see their own students' history.
    Admin can see all.
    Returns list of tuples ordered by created_at DESC.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Verify ownership if not admin
    if not admin and teacher_id:
        cursor.execute('''
            SELECT 1 FROM student_identity 
            WHERE student_id = ? AND teacher_id = ?
        ''', (student_id, teacher_id))
        if not cursor.fetchone():
            conn.close()
            return []  # Not authorized
    
    query = '''
        SELECT 
            id, student_id, teacher_id, test_date, created_at,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e, 
            g4_vowel_teams, g5_r_controlled, g6_clusters, 
            g7_multisyllabic, g8_reduction, suggested_next, 
            teacher_notes, teacher_refined_notes, struggling_words
        FROM assessments 
        WHERE student_id = ?
        ORDER BY created_at DESC
    '''
    
    cursor.execute(query, (student_id,))
    results = cursor.fetchall()
    conn.close()
    return results

def get_mastered_words_from_raw(raw_text, word_list=None):
    """
    Extracts mastered words from the raw transcription.
    Words are considered mastered if spelled correctly.
    """
    if not raw_text:
        return ""
    
    mastered = []
    lines = raw_text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if ':' in line:
            parts = line.split(':')
            if len(parts) >= 2:
                correct = parts[0].strip()
                attempt = parts[1].strip()
                if correct.lower() == attempt.lower():
                    mastered.append(correct)
    
    return ", ".join(mastered) if mastered else ""

def save_assessment(data, raw_text, teacher_refinement=None, struggling_words=None):
    """
    Saves an assessment. Always creates a NEW row to preserve history.
    Never overwrites existing entries.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        INSERT INTO assessments (
            student_id, teacher_id, test_date, created_at, raw_transcription,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e, 
            g4_vowel_teams, g5_r_controlled, g6_clusters, 
            g7_multisyllabic, g8_reduction, suggested_next, 
            teacher_notes, teacher_refined_notes, struggling_words
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    suggested_str = ", ".join(data.suggested_next_groups) if data.suggested_next_groups else ""
    
    # Get the teacher's ID associated with the student
    cursor.execute('SELECT teacher_id FROM student_identity WHERE student_id = ?', (data.student_id,))
    owner_result = cursor.fetchone()
    current_teacher_id = owner_result[0] if owner_result else None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_date = datetime.now().strftime("%Y-%m-%d")
    
    values = (
        data.student_id, 
        current_teacher_id,
        today_date, 
        now, 
        raw_text,
        data.g0_phonemic_awareness, data.g1_cvc_mapping, data.g2_digraphs,
        data.g3_silent_e, data.g4_vowel_teams, data.g5_r_controlled,
        data.g6_clusters, data.g7_multisyllabic, data.g8_reduction_morphology,
        suggested_str, data.teacher_notes, teacher_refinement, struggling_words
    )
    
    cursor.execute(query, values)
    conn.commit()
    conn.close()
    return True

# ============================================================
# RESULTS & GROUPS
# ============================================================

def get_all_latest_results(teacher_id=None, admin=False):
    """
    Fetches the most recent assessment for students.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        SELECT a.*, si.teacher_id 
        FROM assessments a
        JOIN student_identity si ON a.student_id = si.student_id
        WHERE a.id IN (
            SELECT MAX(id) FROM assessments GROUP BY student_id
        )
    '''
    
    if not admin and teacher_id:
        query += f" AND si.teacher_id = '{teacher_id}'"
    
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
    query_60 = '''
        SELECT struggling_words FROM assessments 
        WHERE student_id = ? AND struggling_words IS NOT NULL AND struggling_words != ''
        AND created_at >= datetime('now', '-60 days')
        ORDER BY created_at DESC
    '''
    cursor.execute(query_60, (student_id,))
    results = cursor.fetchall()
    if results:
        all_words = " ".join([r[0] for r in results])
        conn.close()
        return all_words
    
    query_recent = '''
        SELECT struggling_words FROM assessments 
        WHERE student_id = ? AND struggling_words IS NOT NULL AND struggling_words != ''
        ORDER BY created_at DESC LIMIT 5
    '''
    cursor.execute(query_recent, (student_id,))
    results_recent = cursor.fetchall()
    conn.close()
    if results_recent:
        return " ".join([r[0] for r in results_recent])
    return None

def generate_class_groups():
    """Reads all latest student results and organizes students by target groups."""
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
        suggested_string = row[14] 
        
        if suggested_string:
            target_areas = [area.strip() for area in suggested_string.split(",")]
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
