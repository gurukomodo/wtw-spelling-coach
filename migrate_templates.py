import sqlite3
import os
import sys
import json
from supabase import create_client, Client

def load_secrets():
    secrets = {}
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if not os.path.exists(secrets_path):
        print(f"Error: {secrets_path} not found.")
        sys.exit(1)
    with open(secrets_path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                secrets[key.strip()] = val.strip().strip('"').strip("'")
    return secrets

def migrate():
    secrets = load_secrets()
    url = secrets.get("SUPABASE_URL")
    key = secrets.get("SUPABASE_KEY") or secrets.get("SUPABASE_SERVICE_ROLE_KEY")

    if not url or not key:
        print("Error: Missing credentials in .streamlit/secrets.toml")
        sys.exit(1)

    supabase: Client = create_client(url, key)

    sqlite_db_path = os.path.join("data", "spelling_coach.db")
    conn = sqlite3.connect(sqlite_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Allowed columns per table in Supabase
    allowed_columns = {
        "test_templates": ["id", "teacher_id", "title", "word_list", "created_at"],
        "named_word_lists": ["id", "teacher_id", "list_name", "target_words", "created_at"]
    }

    for table, valid_cols in allowed_columns.items():
        print(f"\n--- Migrating {table} ---")
        try:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            
            if not rows:
                print(f"No rows found in local {table}. Skipping.")
                continue

            data = []
            for row in rows:
                raw_record = dict(row)
                
                # Filter record to keep ONLY columns that exist in Supabase
                clean_record = {k: v for k, v in raw_record.items() if k in valid_cols}

                # Decode stringified JSON arrays/objects for Supabase JSONB
                for k, v in clean_record.items():
                    if isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                        try:
                            clean_record[k] = json.loads(v)
                        except Exception:
                            pass

                data.append(clean_record)

            res = supabase.table(table).upsert(data).execute()
            print(f"Successfully uploaded {len(data)} record(s) to '{table}' in Supabase!")

        except Exception as e:
            print(f"Failed to migrate table '{table}': {e}")

    conn.close()
    print("\nTemplate & Word List migration completed successfully!")

if __name__ == "__main__":
    migrate()