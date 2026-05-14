import sqlite3

def wipe_and_reset():
    conn = sqlite3.connect('data/spelling_coach.db')
    cursor = conn.cursor()
    
    # List of tables to clear
    tables = ['student_identity', 'assessments']
    
    for table in tables:
        try:
            cursor.execute(f"DELETE FROM {table}")
            print(f"Cleared table: {table}")
        except Exception as e:
            print(f"Could not clear {table}: {e}")
            
    conn.commit()
    conn.close()
    print("Database is now empty and ready for real students.")

if __name__ == "__main__":
    wipe_and_reset()