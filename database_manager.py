import sqlite3
from datetime import datetime
import os

DB_PATH = "data/spelling_coach.db"

def init_db():
    """Creates the database and tables if they don't exist."""
    if not os.path.exists("data"):
        os.makedirs("data")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Students Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            first_language TEXT DEFAULT 'Mandarin',
            current_group TEXT
        )
    ''')
    
    # 2. Assessment Results Table
    # We store the 8 specific levels you defined
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            test_date DATE,
            raw_transcription TEXT,
            level_1_init_cons REAL,
            level_2_final_cons REAL,
            level_3_short_vowels REAL,
            level_4_vowel_families REAL,
            level_5_digraphs REAL,
            level_6_blends REAL,
            level_7_long_vowels REAL,
            level_8_inflected_endings REAL,
            FOREIGN KEY (student_id) REFERENCES students (id)
        )
    ''')
    conn.commit()
    conn.close()

def save_assessment(name, levels_dict, raw_text):
    """Saves a student's test results."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Ensure student exists or get their ID
    cursor.execute("INSERT OR IGNORE INTO students (name) VALUES (?)", (name,))
    cursor.execute("SELECT id FROM students WHERE name = ?", (name,))
    student_id = cursor.fetchone()[0]
    
    # Insert assessment data
    query = '''
        INSERT INTO assessments (
            student_id, test_date, raw_transcription,
            level_1_init_cons, level_2_final_cons, level_3_short_vowels,
            level_4_vowel_families, level_5_digraphs, level_6_blends,
            level_7_long_vowels, level_8_inflected_endings
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    values = (
        student_id, 
        datetime.now().strftime("%Y-%m-%d"),
        raw_text,
        levels_dict.get('l1', 0), levels_dict.get('l2', 0),
        levels_dict.get('l3', 0), levels_dict.get('l4', 0),
        levels_dict.get('l5', 0), levels_dict.get('l6', 0),
        levels_dict.get('l7', 0), levels_dict.get('l8', 0)
    )
    
    cursor.execute(query, values)
    conn.commit()
    conn.close()

def get_student_history(name):
    """Fetches all past tests for a specific student."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    query = '''
        SELECT a.* FROM assessments a 
        JOIN students s ON a.student_id = s.id 
        WHERE s.name = ? 
        ORDER BY a.test_date DESC
    '''
    cursor.execute(query, (name,))
    results = cursor.fetchall()
    conn.close()
    return results