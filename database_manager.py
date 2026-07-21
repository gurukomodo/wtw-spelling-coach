import sqlite3
from datetime import datetime
import os
import csv
import hashlib
import json
import uuid
from typing import Any, Dict, Optional, List
from venv import logger
import pandas as pd


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
            teacher_name TEXT,
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
            struggling_words TEXT,
            teacher_observations TEXT,
            coaching_report TEXT,
            test_template TEXT,
            evaluation_json TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS student_identity (
            teacher_id TEXT,
            student_id TEXT,
            real_name TEXT,
            pseudonym TEXT,
            current_group_focus TEXT DEFAULT 'g1',
            PRIMARY KEY (teacher_id, student_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS teacher_settings (
            teacher_id TEXT PRIMARY KEY,
            teacher_name TEXT,
            unit_description TEXT,
            google_sheet_url TEXT
        )
    ''')
    
    # Test Templates table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT,
            test_name TEXT NOT NULL,
            intended_words TEXT NOT NULL
        )
    """)
    
    # Draft Assessments table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS draft_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            student_name TEXT NOT NULL,
            intended_words TEXT NOT NULL,
            edited_text TEXT,
            teacher_observations TEXT,
            struggling_words TEXT,
            shadow_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # New table for named word lists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS named_word_lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id TEXT NOT NULL,
            list_name TEXT NOT NULL UNIQUE,
            target_words TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # New table for AI Discrepancies
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ai_discrepancies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            assessment_id INTEGER,
            ai_suggested_group TEXT,
            teacher_assigned_group TEXT NOT NULL,
            teacher_direct_feedback TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES student_identity(student_id),
            FOREIGN KEY (assessment_id) REFERENCES assessments(id)
        )
    ''')

    conn.commit()

    # 2. Schema Repair / Migration
    repair_schema(cursor)

    conn.commit()
    conn.close()


def repair_schema(cursor):
    """Ensures the database schema is up-to-date with all required columns."""
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

    if "teacher_observations" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN teacher_observations TEXT")
        print("Schema Repair: Added teacher_observations column to assessments.")

    if "coaching_report" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN coaching_report TEXT")
        print("Schema Repair: Added coaching_report column to assessments.")

    if "test_template" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN test_template TEXT")
        print("Schema Repair: Added test_template column to assessments.")

    # Added lossless JSON payload column
    if "evaluation_json" not in columns:
        cursor.execute("ALTER TABLE assessments ADD COLUMN evaluation_json TEXT")
        print("Schema Repair: Added evaluation_json column to assessments.")

    # Check student_identity
    cursor.execute("PRAGMA table_info(student_identity)")
    identity_cols = [col[1] for col in cursor.fetchall()]
    if "pseudonym" not in identity_cols:
        cursor.execute("ALTER TABLE student_identity ADD COLUMN pseudonym TEXT")
        print("Schema Repair: Added pseudonym column.")
    
    if "current_group_focus" not in identity_cols:
        cursor.execute("ALTER TABLE student_identity ADD COLUMN current_group_focus TEXT DEFAULT 'g1'")
        print("Schema Repair: Added current_group_focus column to student_identity.")

    # Check teacher_settings
    cursor.execute("PRAGMA table_info(teacher_settings)")
    settings_cols = [col[1] for col in cursor.fetchall()]
    if "teacher_name" not in settings_cols:
        cursor.execute("ALTER TABLE teacher_settings ADD COLUMN teacher_name TEXT")
        print("Schema Repair: Added teacher_name column to teacher_settings.")
    if "google_sheet_url" not in settings_cols:
        cursor.execute("ALTER TABLE teacher_settings ADD COLUMN google_sheet_url TEXT")
        print("Schema Repair: Added google_sheet_url column to teacher_settings.")

    # Ensure test_templates table has default data
    try:
        cursor.execute("SELECT COUNT(*) FROM test_templates")
        count = cursor.fetchone()[0]
        if count == 0:
            default_words = "cat,bed,sit,run,fish,ship,sled,stick,shine,flash,grape,slide,plane,bone,game,cube,tube,brake,plant,string,cream,street,float,toast,boot,talk,car,far,star,start,spark,bird,burn,turn,fern,paint,wait,train,day,play,rain,tail,sail,boat,coat,goal"
            cursor.execute('''
                INSERT INTO test_templates (test_id, test_name, intended_words)
                VALUES (?, ?, ?)
            ''', ('default_standard', 'Standard Diagnostic', default_words))
            print("Schema Repair: Added default test template.")
    except Exception:
        pass

    # Ensure ai_discrepancies schema
    cursor.execute("PRAGMA table_info(ai_discrepancies)")
    discrepancy_cols = [col[1] for col in cursor.fetchall()]
    if discrepancy_cols and "teacher_direct_feedback" not in discrepancy_cols:
        cursor.execute("ALTER TABLE ai_discrepancies ADD COLUMN teacher_direct_feedback TEXT")
        print("Schema Repair: Added teacher_direct_feedback column to ai_discrepancies.")


# ============================================================
# ASSESSMENT SAVING ENGINE
# ============================================================

def save_assessment(
    data: Any,
    raw_text: str = "",
    teacher_refinement: Optional[str] = None,
    struggling_words: Optional[str] = None,
    teacher_id: Optional[str] = None,
    teacher_observations: Optional[str] = None,
    test_template: Optional[str] = None,
    coaching_report: Optional[str] = None
) -> bool:
    """
    Saves assessment data to SQLite database. Supports dictionary payloads from
    feature_evaluator.py, Pydantic objects, or legacy assessment classes.
    """
    if not teacher_id:
        raise ValueError("teacher_id is required to save assessment")

    # Handle Pydantic schema dict convert
    if hasattr(data, "dict") and callable(getattr(data, "dict")):
        data = data.dict()

    evaluation_json_str = None
    
    if isinstance(data, dict):
        student_id = data.get("student_id")
        real_name = data.get("real_name", student_id)
        
        feature_summary = data.get("feature_summary", {})
        
        def extract_score(g_key: str) -> float:
            val = feature_summary.get(g_key, 0.0)
            if isinstance(val, dict):
                return float(val.get("percentage", 0.0))
            return float(val)

        g0 = extract_score("g0")
        g1 = extract_score("g1")
        g2 = extract_score("g2")
        g3 = extract_score("g3")
        g4 = extract_score("g4")
        g5 = extract_score("g5")
        g6 = extract_score("g6")
        g7 = extract_score("g7")
        g8 = extract_score("g8")

        suggested = data.get("suggested_next_groups", [])
        suggested_str = ", ".join(suggested) if isinstance(suggested, list) else str(suggested or "")
        teacher_notes = data.get("teacher_notes", "")
        evaluation_json_str = json.dumps(data)

        # Auto-extract struggling words if missing
        if not struggling_words and "word_evaluations" in data:
            missed = []
            for w in data["word_evaluations"]:
                if not w.get("is_correct"):
                    attempt = w.get("student_attempt", "")
                    intended = w.get("intended_word", "")
                    missed.append(f"{intended}:{attempt}")
            if missed:
                struggling_words = ", ".join(missed)

    else:
        # Legacy Object Fallback
        student_id = getattr(data, 'student_id', None)
        real_name = getattr(data, 'real_name', None) or student_id
        g0 = getattr(data, 'g0_phonemic_awareness', 0.0)
        g1 = getattr(data, 'g1_cvc_mapping', 0.0)
        g2 = getattr(data, 'g2_digraphs', 0.0)
        g3 = getattr(data, 'g3_silent_e', 0.0)
        g4 = getattr(data, 'g4_vowel_teams', 0.0)
        g5 = getattr(data, 'g5_r_controlled', 0.0)
        g6 = getattr(data, 'g6_clusters', 0.0)
        g7 = getattr(data, 'g7_multisyllabic', 0.0)
        g8 = getattr(data, 'g8_reduction_morphology', 0.0)
        
        suggested = getattr(data, 'suggested_next_groups', [])
        suggested_str = ", ".join(suggested) if isinstance(suggested, list) else str(suggested or "")
        teacher_notes = getattr(data, 'teacher_notes', "")

    if not student_id:
        raise ValueError("student_id missing from assessment payload")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Link / update student identity
    cursor.execute('SELECT teacher_id, real_name FROM student_identity WHERE student_id = ?', (student_id,))
    result = cursor.fetchone()

    if result:
        existing_teacher, existing_name = result
        if not existing_teacher or existing_teacher != teacher_id:
            cursor.execute('UPDATE student_identity SET teacher_id = ? WHERE student_id = ?', (teacher_id, student_id))
        if existing_name != real_name and real_name != student_id:
            cursor.execute('UPDATE student_identity SET real_name = ? WHERE student_id = ?', (real_name, student_id))
    else:
        pseudonym = generate_pseudonym(teacher_id, student_id)
        cursor.execute('''
            INSERT INTO student_identity (teacher_id, student_id, real_name, pseudonym)
            VALUES (?, ?, ?, ?)
        ''', (teacher_id, student_id, real_name, pseudonym))

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute('''
        INSERT INTO assessments (
            student_id, teacher_id, test_date, created_at, raw_transcription,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e,
            g4_vowel_teams, g5_r_controlled, g6_clusters,
            g7_multisyllabic, g8_reduction, suggested_next,
            teacher_notes, teacher_refined_notes, struggling_words, teacher_observations,
            coaching_report, test_template, evaluation_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        student_id, teacher_id, datetime.now().strftime("%Y-%m-%d"), now, raw_text,
        g0, g1, g2, g3, g4, g5, g6, g7, g8,
        suggested_str, teacher_notes, teacher_refinement, struggling_words, teacher_observations,
        coaching_report, test_template, evaluation_json_str
    ))

    conn.commit()
    conn.close()
    return True


# ============================================================
# HELPER & UTILITY FUNCTIONS
# ============================================================



def sync_identity_from_assessments():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT student_id, student_id as raw_name
        FROM assessments
        WHERE student_id IS NOT NULL AND student_id != ''
    ''')
    assessment_students = cursor.fetchall()

    created_count = 0
    for identifier, raw_name in assessment_students:
        cursor.execute('SELECT 1 FROM student_identity WHERE student_id = ?', (identifier,))
        if not cursor.fetchone():
            try:
                cursor.execute('''
                    INSERT INTO student_identity (teacher_id, student_id, real_name, pseudonym)
                    VALUES (NULL, ?, ?, NULL)
                ''', (identifier, identifier))
                created_count += 1
            except Exception as e:
                print(f"Error creating identity for {identifier}: {e}")

    conn.commit()
    conn.close()
    return {"created": created_count, "total_in_assessments": len(assessment_students)}

def clear_all_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM assessments")
    assessments_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM student_identity")
    identity_count = cursor.fetchone()[0]

    cursor.execute("DELETE FROM assessments")
    cursor.execute("DELETE FROM student_identity")

    conn.commit()
    conn.close()

    return {
        "assessments_deleted": assessments_count,
        "identity_deleted": identity_count,
        "teachers_preserved": True
    }

def factory_reset():
    return clear_all_data()

def fix_all_teacher_ids():
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
        cursor.execute('UPDATE assessments SET teacher_id = ? WHERE student_id = ?', (teacher_id, student_id))
        updated_count += cursor.rowcount

    conn.commit()
    conn.close()

    return {"students_synced": len(student_teachers), "assessment_rows_updated": updated_count}

def register_teacher(teacher_id, teacher_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO teacher_settings (teacher_id, teacher_name, unit_description)
        VALUES (?, ?, '')
    ''', (teacher_id, teacher_name))
    conn.commit()
    conn.close()
    return True

def get_teacher_name(teacher_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT teacher_name FROM teacher_settings WHERE teacher_id = ?', (teacher_id,))
    result = cursor.fetchone()
    conn.close()
    if result and result[0]:
        return result[0]
    return teacher_id.split('@')[0]


def get_teacher_settings(teacher_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT unit_description, google_sheet_url FROM teacher_settings WHERE teacher_id = ?', (teacher_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        return {
            'unit_description': result[0] or "",
            'google_sheet_url': result[1] or ""
        }
    return {'unit_description': '', 'google_sheet_url': ''}

def save_student_identity(teacher_id, student_id, real_name, pseudonym=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if not pseudonym:
        cursor.execute('SELECT pseudonym FROM student_identity WHERE student_id = ?', (student_id,))
        res = cursor.fetchone()
        pseudonym = res[0] if res else generate_pseudonym(teacher_id, student_id)

    cursor.execute('''
        INSERT OR REPLACE INTO student_identity (teacher_id, student_id, real_name, pseudonym)
        VALUES (?, ?, ?, ?)
    ''', (teacher_id, student_id, real_name, pseudonym))

    conn.commit()
    conn.close()

def get_real_name(teacher_id, student_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT real_name FROM student_identity WHERE student_id = ?', (student_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else student_id

def get_display_name(teacher_id, student_id):
    return get_real_name(teacher_id, student_id)

def get_student_name(teacher_id, student_id):
    return get_real_name(teacher_id, student_id)

def get_name_for_id(teacher_id, student_id):
    return get_real_name(teacher_id, student_id)

def get_student_id_by_name(teacher_id, real_name):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT student_id FROM student_identity WHERE real_name = ?', (real_name,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def get_teacher_students(teacher_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT student_id, real_name FROM student_identity WHERE teacher_id = ?', (teacher_id,))
    results = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}

def get_teacher_student_pseudonyms(teacher_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT pseudonym, real_name FROM student_identity WHERE teacher_id = ?', (teacher_id,))
    results = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in results}

def get_all_teachers():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT teacher_id, teacher_name FROM teacher_settings
        WHERE teacher_id IS NOT NULL AND teacher_id != ''
        ORDER BY teacher_name
    ''')
    results = cursor.fetchall()
    conn.close()
    teachers = []
    for row in results:
        email = row[0]
        name = row[1]
        if not name or not name.strip():
            name = email.split('@')[0] if '@' in email else email
        teachers.append({"email": email, "name": name})
    return teachers


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


def get_student_history(student_id, teacher_id=None, admin=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            id, student_id, teacher_id, test_date, created_at,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e,
            g4_vowel_teams, g5_r_controlled, g6_clusters,
            g7_multisyllabic, g8_reduction, suggested_next,
            teacher_notes, teacher_refined_notes, struggling_words, teacher_observations,
            coaching_report, test_template, raw_transcription, evaluation_json
        FROM assessments
        WHERE student_id = ?
        ORDER BY created_at ASC
    ''', (student_id,))
    results = cursor.fetchall()
    conn.close()
    
    column_names = [
        'id', 'student_id', 'teacher_id', 'test_date', 'created_at',
        'g0_phonemic', 'g1_cvc', 'g2_digraphs', 'g3_silent_e',
        'g4_vowel_teams', 'g5_r_controlled', 'g6_clusters',
        'g7_multisyllabic', 'g8_reduction', 'suggested_next',
        'teacher_notes', 'teacher_refined_notes', 'struggling_words', 'teacher_observations',
        'coaching_report', 'test_template', 'raw_transcription', 'evaluation_json'
    ]
    return [dict(zip(column_names, row)) for row in results]


def get_all_students_by_teacher(teacher_email):
    if not teacher_email:
        return []
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    sync_identity_from_assessments()
    
    cursor.execute('''
        SELECT DISTINCT
            si.student_id,
            si.real_name,
            si.pseudonym,
            COALESCE(latest.total_attempts, 0) as total_attempts,
            latest.last_date,
            si.current_group_focus,
            latest.most_struggled_word
        FROM student_identity si
        LEFT JOIN (
            SELECT 
                a.student_id,
                COUNT(*) as total_attempts,
                MAX(a.created_at) as last_date,
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
        "name": s[1],
        "pseudonym": s[2] or f"Student_{i+1:02d}",
        "total_attempts": s[3] or 0,
        "last_date": s[4],
        "current_g_level": s[5],
        "most_struggled_word": s[6]
    } for i, s in enumerate(students)]

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

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def add_student(teacher_id, real_name, target_group="g1"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        student_id = f"student_{uuid.uuid4().hex[:8]}"
        pseudonym = generate_pseudonym(teacher_id, student_id)
        
        cursor.execute('''
            INSERT INTO student_identity (teacher_id, student_id, real_name, pseudonym, current_group_focus)
            VALUES (?, ?, ?, ?, ?)
        ''', (teacher_id, student_id, real_name, pseudonym, target_group))
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
            INSERT INTO assessments (student_id, teacher_id, test_date, created_at, suggested_next, teacher_notes)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (student_id, teacher_id, datetime.now().strftime("%Y-%m-%d"), now, target_group, "Initial student record created."))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding student: {e}")
        return False
    finally:
        conn.close()

def get_student_current_group_focus(student_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT current_group_focus FROM student_identity WHERE student_id = ?', (student_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 'g1'

def update_student_current_group_focus(student_id, new_group):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute('UPDATE student_identity SET current_group_focus = ? WHERE student_id = ?', (new_group, student_id))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error updating student group focus: {e}")
        return False
    finally:
        conn.close()


# ==========================================
# 1. INITIALIZATION & SETUP
# ==========================================

def init_correction_tables():
    """Ensure tables for manual corrections and custom named lists exist with proper schema and default lists."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historical_corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER,
                student_id INTEGER,
                word TEXT,
                original_status TEXT,
                corrected_status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id),
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS named_word_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                word_list TEXT,
                teacher_id INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Auto-patch missing columns from older schema versions
        cursor.execute("PRAGMA table_info(named_word_lists)")
        existing_columns = [col[1] for col in cursor.fetchall()]
        
        expected_columns = {
            "name": "TEXT",
            "word_list": "TEXT",
            "teacher_id": "INTEGER",
            "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP"
        }
        
        for col_name, col_type in expected_columns.items():
            if col_name not in existing_columns:
                cursor.execute(f"ALTER TABLE named_word_lists ADD COLUMN {col_name} {col_type}")

        # Refresh existing columns list
        cursor.execute("PRAGMA table_info(named_word_lists)")
        existing_columns = [col[1] for col in cursor.fetchall()]

        # Clean up legacy duplicate name if present
        if "list_name" in existing_columns:
            cursor.execute("""
                DELETE FROM named_word_lists 
                WHERE name = 'Primary Spelling Inventory (PSI)' 
                   OR list_name = 'Primary Spelling Inventory (PSI)'
            """)
        else:
            cursor.execute("""
                DELETE FROM named_word_lists 
                WHERE name = 'Primary Spelling Inventory (PSI)'
            """)

        # Check for PSI list using whichever name column exists
        check_col = "list_name" if "list_name" in existing_columns and "name" not in existing_columns else "name"
        cursor.execute(f"SELECT COUNT(*) FROM named_word_lists WHERE {check_col} LIKE '%PSI%'")
        
        if cursor.fetchone()[0] == 0:
            psi_words = [
                "fan", "pet", "dig", "rob", "hope", "wait", "gum", "sled", 
                "stick", "shine", "dream", "blade", "coach", "fright", "chewing", 
                "crawl", "wishes", "thorn", "shouted", "spoil", "growl", "third", 
                "trapped", "couples", "chase"
            ]
            psi_json = json.dumps(psi_words)
            
            # Dynamically map values to whatever columns exist in this database
            val_map = {}
            for col in existing_columns:
                if col in ('name', 'list_name'):
                    val_map[col] = "PSI - Primary Spelling Inventory"
                elif col in ('word_list', 'target_words'):
                    val_map[col] = psi_json
                elif col == 'teacher_id':
                    val_map[col] = 0

            if val_map:
                cols = list(val_map.keys())
                placeholders = ", ".join(["?"] * len(cols))
                col_names = ", ".join(cols)
                cursor.execute(
                    f"INSERT INTO named_word_lists ({col_names}) VALUES ({placeholders})",
                    [val_map[c] for c in cols]
                )
            
        conn.commit()

# ==========================================
# 2. ADMIN & ROSTER MANAGEMENT
# ==========================================

def get_database_stats():
    """Returns aggregate database counts for the admin overview page."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM students")
        total_students = cursor.fetchone()[0]
        
        # Fallback count from assessments if the students table isn't populated yet
        if total_students == 0:
            cursor.execute("SELECT COUNT(DISTINCT student_id) FROM assessments")
            total_students = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM teachers")
        total_teachers = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM assessments")
        total_assessments = cursor.fetchone()[0]
        
        return {
            "total_students": total_students,
            "total_teachers": total_teachers,
            "total_assessments": total_assessments
        }


def get_all_students_for_allocation():
    """Fetches all students alongside their assigned teacher details for allocation."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                s.id AS student_id,
                s.name AS student_name,
                s.grade,
                s.teacher_id,
                t.name AS teacher_name
            FROM students s
            LEFT JOIN teachers t ON s.teacher_id = t.id
            ORDER BY s.name ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def update_student_teacher(student_id, teacher_id):
    """Reassigns a student to a specific teacher ID (or None to unassign)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE students
            SET teacher_id = ?
            WHERE id = ?
        """, (teacher_id, student_id))
        conn.commit()
        return cursor.rowcount > 0


def import_from_csv(file_or_df, teacher_id=None):
    """
    Imports student roster data from a CSV file path, uploaded file buffer, or pandas DataFrame.
    """
    if isinstance(file_or_df, pd.DataFrame):
        df = file_or_df.copy()
    else:
        df = pd.read_csv(file_or_df)

    # Normalize column headers to lowercase without spaces
    df.columns = [str(col).strip().lower().replace(" ", "_") for col in df.columns]

    added_count = 0
    with get_db_connection() as conn:
        cursor = conn.cursor()
        for _, row in df.iterrows():
            student_name = row.get("student_name") or row.get("name") or row.get("student")
            if not student_name or pd.isna(student_name):
                continue
            
            grade = row.get("grade") if not pd.isna(row.get("grade")) else None
            t_id = row.get("teacher_id") if "teacher_id" in row and not pd.isna(row.get("teacher_id")) else teacher_id
            
            cursor.execute("""
                INSERT INTO students (name, grade, teacher_id)
                VALUES (?, ?, ?)
            """, (str(student_name).strip(), grade, t_id))
            added_count += 1
        conn.commit()
        
    return added_count


# ==========================================
# 3. CUSTOM WORD LIST CREATOR
# ==========================================

def save_named_list(name, word_list, teacher_id=None):
    """Saves a custom target word list for a teacher or globally."""
    words_json = json.dumps(word_list) if isinstance(word_list, list) else word_list
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO named_word_lists (name, word_list, teacher_id)
            VALUES (?, ?, ?)
        """, (name, words_json, teacher_id))
        conn.commit()
        return cursor.lastrowid


def get_named_lists(teacher_id=None):
    """Retrieves custom named word lists available to a specific teacher plus system lists (teacher_id = 0)."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if isinstance(teacher_id, str) and "@" in teacher_id:
            cursor.execute("SELECT id FROM teachers WHERE email = ?", (teacher_id,))
            row = cursor.fetchone()
            teacher_id = row['id'] if row else None

        if teacher_id is not None:
            cursor.execute("""
                SELECT * FROM named_word_lists 
                WHERE teacher_id = ? OR teacher_id = 0 OR teacher_id IS NULL 
                ORDER BY id DESC
            """, (teacher_id,))
        else:
            cursor.execute("""
                SELECT * FROM named_word_lists 
                ORDER BY id DESC
            """)
        
        results = []
        for row in cursor.fetchall():
            item = dict(row)
            # Harmonize legacy column names for the UI
            if 'name' not in item or not item['name']:
                item['name'] = item.get('list_name', 'Unnamed List')
            if 'word_list' not in item or not item['word_list']:
                item['word_list'] = item.get('target_words', '[]')
                
            try:
                if isinstance(item['word_list'], str):
                    item['word_list'] = json.loads(item['word_list'])
            except (json.JSONDecodeError, TypeError):
                pass
            results.append(item)
        return results


def get_named_list_by_id(list_id):
    """Fetches a single custom word list by its database ID."""
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, word_list, teacher_id, created_at 
            FROM named_word_lists 
            WHERE id = ?
        """, (list_id,))
        row = cursor.fetchone()
        if row:
            item = dict(row)
            try:
                item['word_list'] = json.loads(item['word_list'])
            except (json.JSONDecodeError, TypeError):
                pass
            return item
        return None


# ==========================================
# 4. ASSESSMENT & HISTORY DELETION
# ==========================================

def delete_assessment(assessment_id):
    """Permanently removes an assessment and all corresponding records."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM historical_corrections WHERE assessment_id = ?", (assessment_id,))
        cursor.execute("DELETE FROM assessment_results WHERE assessment_id = ?", (assessment_id,))
        cursor.execute("DELETE FROM assessments WHERE id = ?", (assessment_id,))
        conn.commit()
        return cursor.rowcount > 0
def init_db():
    """Creates core database tables if they do not exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Teachers table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                role TEXT DEFAULT 'teacher'
            )
        """)
        
        # Students table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                grade TEXT,
                teacher_id INTEGER,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id)
            )
        """)
        
        # Assessments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                date DATETIME DEFAULT CURRENT_TIMESTAMP,
                stage TEXT,
                score INTEGER,
                total INTEGER,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        """)
        
        # Assessment item details table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS assessment_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER,
                word TEXT,
                target_word TEXT,
                status TEXT,
                error_pattern TEXT,
                FOREIGN KEY (assessment_id) REFERENCES assessments(id)
            )
        """)
        conn.commit()

def get_sheet_data(*args, **kwargs):
    """Temporary stub until Google Sheets / Forms mobile integration is connected."""
    return []

def purge_student_and_feedback_data():
    """Completely wipes all students, assessments, assessment results, and LLM historical corrections.
    Leaves teacher accounts and named word lists intact.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Purge assessment results and corrections
        cursor.execute("DELETE FROM historical_corrections")
        cursor.execute("DELETE FROM assessment_results") if table_exists("assessment_results", cursor) else None
        
        # Purge main tables
        cursor.execute("DELETE FROM assessments")
        cursor.execute("DELETE FROM students")
        
        # Reset AUTOINCREMENT counters for clean IDs
        try:
            cursor.execute("""
                DELETE FROM sqlite_sequence 
                WHERE name IN ('students', 'assessments', 'assessment_results', 'historical_corrections')
            """)
        except sqlite3.OperationalError:
            pass # sqlite_sequence might not exist if tables were never populated via autoincrement
            
        conn.commit()
    print("✨ Student, assessment, and LLM feedback data successfully purged!")

def table_exists(table_name, cursor):
    cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone()[0] == 1

def log_model_event(model_name, status, error_msg=None, action=None):
    """Logs an AI model call event (success or error) into SQLite."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                model_name TEXT,
                status TEXT,
                error_msg TEXT,
                action TEXT
            )
        """)
        cursor.execute("""
            INSERT INTO model_logs (model_name, status, error_msg, action)
            VALUES (?, ?, ?, ?)
        """, (model_name, status, str(error_msg) if error_msg else None, action))
        conn.commit()


def get_model_logs():
    """Retrieves aggregated usage statistics and recent log entries."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if not table_exists("model_logs", cursor):
            return [], []

        # Fetch summary count grouped by model and status
        cursor.execute("""
            SELECT model_name, status, COUNT(*) 
            FROM model_logs 
            GROUP BY model_name, status
        """)
        summary = cursor.fetchall()

        # Fetch 30 most recent log entries
        cursor.execute("""
            SELECT timestamp, model_name, status, action, error_msg 
            FROM model_logs 
            ORDER BY id DESC LIMIT 30
        """)
        recent_logs = cursor.fetchall()

        return summary, recent_logs