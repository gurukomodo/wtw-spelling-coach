import sqlite3
from datetime import datetime
import os

DB_PATH = "data/spelling_coach.db"

def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Updated Assessments Table for g0-g8
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT,
            test_date DATE,
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
            teacher_refined_notes TEXT 
        )
    ''')
    conn.commit()
    conn.close()

def save_assessment(data, raw_text, teacher_refinement=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        INSERT INTO assessments (
            student_name, test_date, raw_transcription,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e, 
            g4_vowel_teams, g5_r_controlled, g6_clusters, 
            g7_multisyllabic, g8_reduction, suggested_next, 
            teacher_notes, teacher_refined_notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    suggested_str = ", ".join(data.suggested_next_groups) if data.suggested_next_groups else ""
    
    values = (
        data.student_name, datetime.now().strftime("%Y-%m-%d %H:%M"), raw_text,
        data.g0_phonemic_awareness, data.g1_cvc_mapping, data.g2_digraphs,
        data.g3_silent_e, data.g4_vowel_teams, data.g5_r_controlled,
        data.g6_clusters, data.g7_multisyllabic, data.g8_reduction_morphology,
        suggested_str, data.teacher_notes, teacher_refinement
    )
    
    cursor.execute(query, values)
    conn.commit()
    conn.close()

def get_all_latest_results():
    """Fetches the most recent assessment for every student in the system."""
    conn = sqlite3.connect(DB_PATH) # <-- Fixed to use your shared DB path
    cursor = conn.cursor()
    
    query = '''
        SELECT * FROM assessments 
        WHERE id IN (
            SELECT MAX(id) FROM assessments GROUP BY student_name
        )
    '''
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        conn.close()
        return results
    except Exception as e:
        print(f"Database error: {e}")
        conn.close()
        return []

def get_latest_teacher_notes(student_name):
    """Retrieves the most recent teacher-corrected notes for a student."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        SELECT teacher_refined_notes FROM assessments 
        WHERE student_name = ? AND teacher_refined_notes IS NOT NULL 
        ORDER BY id DESC LIMIT 1
    '''
    cursor.execute(query, (student_name,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None