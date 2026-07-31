import os
import json
from dotenv import load_dotenv
from supabase import create_client
import sqlite3

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Connect to local SQLite database
conn = sqlite3.connect('data/spelling_coach.db')
cursor = conn.cursor()

# Read all rows from local database
cursor.execute("SELECT * FROM student_identity")
student_identity_rows = cursor.fetchall()

cursor.execute("SELECT * FROM assessments")
assessments_rows = cursor.fetchall()

cursor.execute("SELECT * FROM teacher_settings")
teacher_settings_rows = cursor.fetchall()

# Upsert/insert records into Supabase tables
def upsert_student_identity(row):
    data = {
        "teacher_id": row[1],
        "student_id": row[2],
        "real_name": row[3],
        "pseudonym": row[4],
        "current_group_focus": row[5]
    }
    supabase.table("student_identity").upsert(data).execute()

def upsert_assessments(row):
    data = {
        "student_id": row[1],
        "teacher_id": row[2],
        "test_date": row[3],
        "created_at": row[4],
        "raw_transcription": row[5],
        "teacher_refined_notes": row[6],
        "struggling_words": row[7],
        "test_name": row[8]
    }
    supabase.table("assessments").upsert(data).execute()

def upsert_teacher_settings(row):
    data = {
        "teacher_id": row[1],
        "teacher_name": row[2]
    }
    supabase.table("teacher_settings").upsert(data).execute()

# Upsert/insert all local records into Supabase tables
for row in student_identity_rows:
    upsert_student_identity(row)

for row in assessments_rows:
    upsert_assessments(row)

for row in teacher_settings_rows:
    upsert_teacher_settings(row)

# Print out confirmation counts for each table migrated
print("Student Identity Records Migrated:", len(student_identity_rows))
print("Assessment Records Migrated:", len(assessments_rows))
print("Teacher Settings Records Migrated:", len(teacher_settings_rows))

# Close the local database connection
conn.close()
