import os
import json
import sqlite3
import tomllib  # Python 3.11+ built-in
from supabase import create_client

# 1. Load directly from secrets.toml
secrets_path = ".streamlit/secrets.toml"
if not os.path.exists(secrets_path):
    raise FileNotFoundError(f"Could not find {secrets_path}")

with open(secrets_path, "rb") as f:
    secrets = tomllib.load(f)

# Handle both flat structure and [supabase] header block
sb_config = secrets.get("supabase", secrets)

SUPABASE_URL = sb_config.get("SUPABASE_URL") or sb_config.get("supabase_url")
SUPABASE_KEY = (
    sb_config.get("SUPABASE_KEY") 
    or sb_config.get("supabase_key") 
    or sb_config.get("SUPABASE_ANON_KEY")
    or sb_config.get("SUPABASE_SERVICE_KEY")
)

# 2. Verify values before passing to Supabase
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        f"Missing credentials in secrets.toml.\n"
        f"Found URL: {SUPABASE_URL}\n"
        f"Available keys in secrets.toml: {list(sb_config.keys())}"
    )

# 3. Connect directly
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Connect to local SQLite database using Row factory for safe named access
conn = sqlite3.connect('data/spelling_coach.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

def migrate_table(table_name, json_fields=None):
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()
    
    if not rows:
        print(f"No records found in local table '{table_name}'. Skipping.")
        return 0

    batch = []
    for row in rows:
        record = dict(row)
        
        # Parse text string back into valid JSON/list objects if required by Supabase
        if json_fields:
            for field in json_fields:
                if field in record and isinstance(record[field], str):
                    try:
                        record[field] = json.loads(record[field])
                    except (json.JSONDecodeError, TypeError):
                        pass # Keep as raw string if parsing fails
                        
        batch.append(record)

    # Perform a single bulk upsert network request
    response = supabase.table(table_name).upsert(batch).execute()
    return len(batch)

try:
    print("Starting migration to Supabase...")
    
    teachers_count = migrate_table("teacher_settings")
    print(f"✓ Teacher Settings Records Migrated: {teachers_count}")

    students_count = migrate_table("student_identity")
    print(f"✓ Student Identity Records Migrated: {students_count}")

    assessments_count = migrate_table("assessments", json_fields=["struggling_words"])
    print(f"✓ Assessment Records Migrated: {assessments_count}")

    print("\nMigration completed successfully!")

except Exception as e:
    print(f"\n❌ Migration failed with error: {e}")

finally:
    conn.close()