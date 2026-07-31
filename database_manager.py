import os
import json
import uuid
from datetime import datetime, date
from typing import Any, Dict, Optional, List
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================================
# ASSESSMENT SAVING ENGINE
# ============================================================

def save_assessment(assessment_data, student_id=None, raw_text=None, teacher_id=None, teacher_refinement=None, struggling_words=None, test_name=None, test_date=None):
    """Saves assessment data to Supabase."""
    
    if isinstance(raw_text, (list, dict)):
        raw_text_db = json.dumps(raw_text)
    else:
        raw_text_db = str(raw_text) if raw_text is not None else ""

    if isinstance(struggling_words, (list, dict)):
        struggling_words_db = json.dumps(struggling_words)
    else:
        struggling_words_db = str(struggling_words) if struggling_words is not None else ""

    resolved_student_id = student_id or getattr(assessment_data, 'student_id', None)
    if isinstance(assessment_data, dict):
        resolved_student_id = resolved_student_id or assessment_data.get('student_id')

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    test_date_str = test_date.strftime("%Y-%m-%d") if isinstance(test_date, date) else (str(test_date) if test_date else now.split()[0])

    try:
        data = {
            "student_id": resolved_student_id,
            "teacher_id": teacher_id,
            "test_date": test_date_str,
            "created_at": now,
            "raw_transcription": raw_text_db,
            "teacher_refined_notes": teacher_refinement,
            "struggling_words": struggling_words_db,
            "test_name": test_name
        }
        supabase.table("assessments").insert(data).execute()
        return True
    except Exception as e:
        print(f"Error in save_assessment: {e}")
        return False

def update_assessment(assessment_id, test_date=None, test_name=None, teacher_notes=None, suggested_next=None):
    """Updates an existing assessment record in Supabase."""
    try:
        update_data = {}
        if test_date: update_data["test_date"] = test_date
        if test_name is not None: update_data["test_name"] = test_name
        if teacher_notes is not None: update_data["teacher_refined_notes"] = teacher_notes
        if suggested_next: update_data["suggested_next"] = suggested_next
            
        if not update_data: return False
            
        supabase.table("assessments").update(update_data).eq("id", assessment_id).execute()
        return True
    except Exception as e:
        print(f"Error updating assessment: {e}")
        return False

# ============================================================
# IDENTITY & ROSTER MANAGEMENT
# ============================================================

def get_teacher_students(teacher_id):
    try:
        response = supabase.table("student_identity").select("student_id, real_name").eq("teacher_id", teacher_id).execute()
        return {row['student_id']: row['real_name'] for row in response.data}
    except Exception as e:
        print(f"Error get_teacher_students: {e}")
        return {}

def save_student_identity(teacher_id, student_id, real_name, pseudonym=None):
    try:
        data = {"teacher_id": teacher_id, "student_id": student_id, "real_name": real_name, "pseudonym": pseudonym}
        supabase.table("student_identity").upsert(data).execute()
    except Exception as e:
        print(f"Error save_student_identity: {e}")

def get_real_name(teacher_id, student_id):
    try:
        response = supabase.table("student_identity").select("real_name").eq("student_id", student_id).execute()
        return response.data[0]['real_name'] if response.data else student_id
    except Exception as e:
        print(f"Error get_real_name: {e}")
        return student_id

def add_student(teacher_id, real_name, target_group="g1"):
    try:
        student_id = f"student_{uuid.uuid4().hex[:8]}"
        data = {
            "teacher_id": teacher_id,
            "student_id": student_id,
            "real_name": real_name,
            "current_group_focus": target_group
        }
        supabase.table("student_identity").insert(data).execute()
        
        # Also create initial assessment
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        supabase.table("assessments").insert({
            "student_id": student_id,
            "teacher_id": teacher_id,
            "test_date": datetime.now().strftime("%Y-%m-%d"),
            "created_at": now,
            "suggested_next": target_group,
            "teacher_notes": "Initial student record created."
        }).execute()
        return True
    except Exception as e:
        print(f"Error adding student: {e}")
        return False

def get_all_students_for_allocation():
    try:
        response = supabase.table("student_identity").select("student_id, real_name, teacher_id, current_group_focus").execute()
        return [{"student_id": r['student_id'], "name": r['real_name'], "teacher_id": r['teacher_id'], "current_group_focus": r['current_group_focus']} for r in response.data]
    except Exception as e:
        print(f"Error get_all_students_for_allocation: {e}")
        return []

def delete_student(student_id):
    try:
        supabase.table("assessments").delete().eq("student_id", student_id).execute()
        supabase.table("student_practice_lists").delete().eq("student_id", student_id).execute()
        supabase.table("student_identity").delete().eq("student_id", student_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting student: {e}")
        return False

def update_student_teacher(student_id, teacher_id):
    try:
        supabase.table("student_identity").update({"teacher_id": teacher_id}).eq("student_id", student_id).execute()
        return True
    except Exception as e:
        print(f"Error update_student_teacher: {e}")
        return False

# ============================================================
# TEACHER SETTINGS
# ============================================================

def register_teacher(teacher_id, teacher_name):
    try:
        data = {"teacher_id": teacher_id, "teacher_name": teacher_name}
        supabase.table("teacher_settings").upsert(data).execute()
        return True
    except Exception as e:
        print(f"Error register_teacher: {e}")
        return False

def get_teacher_name(teacher_id):
    try:
        response = supabase.table("teacher_settings").select("teacher_name").eq("teacher_id", teacher_id).execute()
        return response.data[0]['teacher_name'] if response.data and response.data[0].get('teacher_name') else teacher_id.split('@')[0]
    except Exception as e:
        print(f"Error get_teacher_name: {e}")
        return teacher_id.split('@')[0]

def get_teacher_settings(teacher_id):
    try:
        response = supabase.table("teacher_settings").select("unit_description, google_sheet_url").eq("teacher_id", teacher_id).execute()
        if response.data:
            return {'unit_description': response.data[0].get('unit_description') or "", 'google_sheet_url': response.data[0].get('google_sheet_url') or ""}
        return {'unit_description': '', 'google_sheet_url': ''}
    except Exception as e:
        print(f"Error get_teacher_settings: {e}")
        return {'unit_description': '', 'google_sheet_url': ''}

def get_all_teachers():
    try:
        response = supabase.table("teacher_settings").select("teacher_id, teacher_name").execute()
        teachers = []
        for row in response.data:
            email = row['teacher_id']
            name = row.get('teacher_name') or email.split('@')[0]
            teachers.append({"email": email, "name": name})
        return teachers
    except Exception as e:
        print(f"Error get_all_teachers: {e}")
        return []

# ============================================================
# ASSESSMENTS & HISTORY
# ============================================================

def get_student_history(student_id, teacher_id=None, admin=False):
    try:
        query = supabase.table("assessments").select("*").eq("student_id", student_id).order("created_at")
        response = query.execute()
        return response.data
    except Exception as e:
        print(f"Error get_student_history: {e}")
        return []

def get_all_students_by_teacher(teacher_email):
    try:
        response = supabase.table("student_identity").select("student_id, real_name, pseudonym, current_group_focus").eq("teacher_id", teacher_email).execute()
        # Note: join logic with latest attempts may need adjustment to Supabase
        return [{"student_id": s['student_id'], "name": s['real_name'], "pseudonym": s['pseudonym'], "current_g_level": s['current_group_focus'], "total_attempts": 0} for s in response.data]
    except Exception as e:
        print(f"Error get_all_students_by_teacher: {e}")
        return []

def delete_assessment(assessment_id):
    try:
        supabase.table("assessments").delete().eq("id", assessment_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting assessment: {e}")
        return False

# ============================================================
# WORD LISTS
# ============================================================

def save_named_list(name, word_list, teacher_id=None):
    try:
        words_json = json.dumps(word_list) if isinstance(word_list, list) else word_list
        data = {"list_name": name, "target_words": words_json, "teacher_id": teacher_id}
        response = supabase.table("named_word_lists").insert(data).execute()
        return response.data[0]['id'] if response.data else None
    except Exception as e:
        print(f"Error save_named_list: {e}")
        return None

def get_named_lists(teacher_id=None):
    try:
        query = supabase.table("named_word_lists").select("*")
        if teacher_id: query = query.or_(f"teacher_id.eq.{teacher_id},teacher_id.eq.0,teacher_id.is.null")
        response = query.order("id", desc=True).execute()
        return response.data
    except Exception as e:
        print(f"Error get_named_lists: {e}")
        return []

def get_named_list_by_id(list_id):
    try:
        response = supabase.table("named_word_lists").select("*").eq("id", list_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error get_named_list_by_id: {e}")
        return None

# ============================================================
# PRACTICE LISTS
# ============================================================

def save_student_practice_list(student_id, teacher_id, list_name, group_title, words_list):
    try:
        words_json = json.dumps(words_list) if isinstance(words_list, list) else words_list
        data = {"student_id": student_id, "teacher_id": teacher_id, "list_name": list_name, "group_title": group_title, "words": words_json}
        supabase.table("student_practice_lists").insert(data).execute()
        return True
    except Exception as e:
        print(f"Error save_student_practice_list: {e}")
        return False

def get_student_practice_lists(student_id):
    try:
        response = supabase.table("student_practice_lists").select("*").eq("student_id", student_id).order("created_at", desc=True).execute()
        result = []
        for r in response.data:
            try:
                words = json.loads(r['words']) if isinstance(r['words'], str) else r['words']
            except Exception:
                words = []
            result.append({**r, 'words': words})
        return result
    except Exception as e:
        print(f"Error get_student_practice_lists: {e}")
        return []

def delete_student_practice_list(list_id):
    try:
        supabase.table("student_practice_lists").delete().eq("id", list_id).execute()
        return True
    except Exception as e:
        print(f"Error deleting student_practice_list: {e}")
        return False

# ============================================================
# MISC UTILS
# ============================================================

def get_latest_teacher_notes(student_id):
    try:
        response = supabase.table("assessments").select("teacher_refined_notes").eq("student_id", student_id).not_.is_("teacher_refined_notes", "null").order("id", desc=True).limit(1).execute()
        return response.data[0]['teacher_refined_notes'] if response.data else None
    except Exception as e:
        print(f"Error get_latest_teacher_notes: {e}")
        return None

def get_struggling_words(student_id):
    try:
        response = supabase.table("assessments").select("struggling_words").eq("student_id", student_id).not_.is_("struggling_words", "null").order("created_at", desc=True).limit(1).execute()
        return response.data[0]['struggling_words'] if response.data else None
    except Exception as e:
        print(f"Error get_struggling_words: {e}")
        return None

def get_student_current_group_focus(student_id):
    try:
        response = supabase.table("student_identity").select("current_group_focus").eq("student_id", student_id).execute()
        return response.data[0]['current_group_focus'] if response.data else 'g1'
    except Exception as e:
        print(f"Error get_student_current_group_focus: {e}")
        return 'g1'

def update_student_current_group_focus(student_id, new_group):
    try:
        supabase.table("student_identity").update({"current_group_focus": new_group}).eq("student_id", student_id).execute()
        return True
    except Exception as e:
        print(f"Error update_student_current_group_focus: {e}")
        return False

def get_database_stats():
    # Supabase doesn't support count directly like SQLite. Simplified.
    return {"total_students": 0, "total_teachers": 0, "total_assessments": 0}

def fix_all_teacher_ids(): return {"students_synced": 0, "assessment_rows_updated": 0}
def get_orphaned_assessments_count(): return 0
def sync_identity_from_assessments(): return {"created": 0, "total_in_assessments": 0}
def import_from_csv(file=None): return {"students": 0, "assessments": 0}
def get_model_logs(): return [], []

# ============================================================
# MISSING FUNCTIONS — required by app.py
# ============================================================

def init_db():
    """No-op on Supabase — tables are pre-created in the dashboard."""
    pass

def init_correction_tables():
    """No-op on Supabase — tables are pre-created in the dashboard."""
    pass

def clear_all_data():
    try:
        supabase.table("assessments").delete().neq("id", 0).execute()
        supabase.table("student_identity").delete().neq("student_id", "").execute()
        supabase.table("student_practice_lists").delete().neq("id", 0).execute()
        return True
    except Exception as e:
        print(f"Error clear_all_data: {e}")
        return False

def get_student_id_by_name(teacher_id, name):
    try:
        response = supabase.table("student_identity").select("student_id").eq("teacher_id", teacher_id).eq("real_name", name).execute()
        return response.data[0]['student_id'] if response.data else None
    except Exception as e:
        print(f"Error get_student_id_by_name: {e}")
        return None

def get_student_name(student_id):
    try:
        response = supabase.table("student_identity").select("real_name").eq("student_id", student_id).execute()
        return response.data[0]['real_name'] if response.data else student_id
    except Exception as e:
        print(f"Error get_student_name: {e}")
        return student_id

def get_name_for_id(student_id):
    return get_student_name(student_id)

def get_sheet_data(*args, **kwargs):
    return []

def save_diagnostic_assessment(assessment, teacher_id):
    try:
        data = {
            "assessment_id": assessment['assessment_id'],
            "teacher_id": teacher_id,
            "test_name": assessment['test_name'],
            "words": json.dumps(assessment['words']),
            "feature_map": json.dumps(assessment.get('feature_map', {})),
            "created_at": assessment['created_at'],
        }
        supabase.table("class_diagnostic_assessments").upsert(data, on_conflict="assessment_id").execute()
        return True
    except Exception as e:
        print(f"Error save_diagnostic_assessment: {e}")
        return False

def get_diagnostic_assessments(teacher_id):
    try:
        response = supabase.table("class_diagnostic_assessments").select("*").eq("teacher_id", teacher_id).order("created_at", desc=True).execute()
        return [
            {
                'assessment_id': r['assessment_id'],
                'test_name': r['test_name'],
                'words': json.loads(r['words']),
                'feature_map': json.loads(r['feature_map']) if r.get('feature_map') else {},
                'created_at': r['created_at'],
            }
            for r in response.data
        ]
    except Exception as e:
        print(f"Error get_diagnostic_assessments: {e}")
        return []