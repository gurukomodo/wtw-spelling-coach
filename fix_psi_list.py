import sqlite3
import os
import sys
import json
from supabase import create_client, Client

# Correct 26-word Primary Spelling Inventory (PSI)
CORRECT_PSI_WORDS = [
    "fan", "pet", "dig", "rob", "hope", "wait", "gum", "sled", 
    "stick", "shine", "dream", "blade", "coach", "fright", 
    "chewing", "crawl", "wishes", "thorn", "shouted", "spoil", 
    "growl", "third", "camped", "tries", "clapping", "riding"
]

def load_secrets():
    secrets = {}
    secrets_path = os.path.join(".streamlit", "secrets.toml")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    secrets[k.strip()] = v.strip().strip('"').strip("'")
    return secrets

def fix_all():
    # 1. Update local SQLite
    sqlite_path = os.path.join("data", "spelling_coach.db")
    if os.path.exists(sqlite_path):
        conn = sqlite3.connect(sqlite_path)
        cursor = conn.cursor()
        words_json = json.dumps(CORRECT_PSI_WORDS)
        
        cursor.execute(
            "UPDATE named_word_lists SET target_words = ? WHERE list_name LIKE '%PSI%' OR list_name LIKE '%Primary%'",
            (words_json,)
        )
        conn.commit()
        conn.close()
        print("Updated local SQLite database (spelling_coach.db).")

    # 2. Update Supabase
    secrets = load_secrets()
    url = secrets.get("SUPABASE_URL")
    key = secrets.get("SUPABASE_KEY") or secrets.get("SUPABASE_SERVICE_ROLE_KEY")

    if url and key:
        supabase: Client = create_client(url, key)
        # Fetch matching rows
        res = supabase.table("named_word_lists").select("*").ilike("list_name", "%PSI%").execute()
        for row in res.data:
            supabase.table("named_word_lists").update({"target_words": CORRECT_PSI_WORDS}).eq("id", row["id"]).execute()
            print(f"Updated Supabase named_word_lists (ID: {row['id']}).")
    else:
        print("Warning: Supabase credentials not found. Skipping Supabase update.")

    # 3. Check for hardcoded python files
    print("\nScanning .py source files for hardcoded 'trapped' references...")
    found_files = []
    for root, _, files in os.walk("."):
        if ".git" in root or "venv" in root or "__pycache__" in root:
            continue
        for file in files:
            if file.endswith(".py") and file != "fix_psi_list.py":
                path = os.path.join(root, file)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        if "trapped" in f.read():
                            found_files.append(path)
                except Exception:
                    pass

    if found_files:
        print("\nHardcoded references to 'trapped' found in these code files:")
        for p in found_files:
            print(f"  - {p}")
        print("Please review those files to update any static python data structures.")
    else:
        print("No hardcoded 'trapped' lists found in python source files.")

if __name__ == "__main__":
    fix_all()
    