import sqlite3
from datetime import datetime
import os

DB_PATH = "data/spelling_coach.db"

def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Updated Assessments Table for g0-g8 with struggling_words column
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
            teacher_refined_notes TEXT,
            struggling_words TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_assessment(data, raw_text, teacher_refinement=None, struggling_words=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        INSERT INTO assessments (
            student_name, test_date, raw_transcription,
            g0_phonemic, g1_cvc, g2_digraphs, g3_silent_e, 
            g4_vowel_teams, g5_r_controlled, g6_clusters, 
            g7_multisyllabic, g8_reduction, suggested_next, 
            teacher_notes, teacher_refined_notes, struggling_words
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    '''
    
    suggested_str = ", ".join(data.suggested_next_groups) if data.suggested_next_groups else ""
    
    values = (
        data.student_name, datetime.now().strftime("%Y-%m-%d %H:%M"), raw_text,
        data.g0_phonemic_awareness, data.g1_cvc_mapping, data.g2_digraphs,
        data.g3_silent_e, data.g4_vowel_teams, data.g5_r_controlled,
        data.g6_clusters, data.g7_multisyllabic, data.g8_reduction_morphology,
        suggested_str, data.teacher_notes, teacher_refinement, struggling_words
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

def get_struggling_words(student_name):
    """Retrieves the most recent struggling words for a student."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = '''
        SELECT struggling_words FROM assessments 
        WHERE student_name = ? AND struggling_words IS NOT NULL AND struggling_words != ''
        ORDER BY id DESC LIMIT 1
    '''
    cursor.execute(query, (student_name,))
    result = cursor.fetchone()
    conn.close()
    
    return result[0] if result else None

def generate_class_groups():
    """Reads all latest student results and organizes students by target groups.
    Each student is placed in exactly ONE group (the lowest numbered tag).
    Students with no tags are placed in 'Review Needed'.
    """
    results = get_all_latest_results()
    
    if not results:
        return {}
        
    # Mapping group names to clean display titles
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
    
    # Initialize our groups dictionary (including Review Needed fallback)
    groups = {title: [] for title in group_titles.values()}
    groups["Review Needed"] = []
    
    for row in results:
        student_name = row[1] # student_name is column 1
        suggested_string = row[13] # suggested_next is column 13
        
        if suggested_string:
            # Clean up the string (e.g. "g1, g2" -> ["g1", "g2"])
            target_areas = [area.strip() for area in suggested_string.split(",")]
            
            # Filter to only valid g0-g8 tags
            valid_tags = [area for area in target_areas if area in group_titles]
            
            if valid_tags:
                # Sort by group number and pick the lowest (e.g., g2 before g6)
                valid_tags.sort(key=lambda x: int(x[1:]))  # Sort by the number after 'g'
                lowest_group = valid_tags[0]
                display_title = group_titles[lowest_group]
                groups[display_title].append(student_name)
            else:
                # No valid g0-g8 tags found, put in Review Needed
                groups["Review Needed"].append(student_name)
        else:
            # No suggested groups at all, put in Review Needed
            groups["Review Needed"].append(student_name)
                    
    # Remove empty groups before returning so we only see active groups
    return {k: v for k, v in groups.items() if v}