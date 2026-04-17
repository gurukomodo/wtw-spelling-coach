import pandas as pd
import streamlit as st
from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew, generate_personalized_practice_words
from database_manager import init_db, get_all_latest_results, assign_unowned_students, get_teacher_settings, save_teacher_settings, import_from_csv, get_student_history, get_mastered_words_from_raw, get_database_stats, fix_all_teacher_ids, clear_all_data, sync_identity_from_assessments
import random
import os
import csv
import json
from datetime import datetime


# --- PAGE CONFIG ---
st.set_page_config(page_title="Unboxed Spelling Coach", layout="wide", page_icon="logo.svg")

# --- PERSISTENCE HELPERS ---
PROFILES_CSV = "students.csv"
SETTINGS_FILE = "settings.json"

def load_settings():
    """Load class-wide settings from JSON."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading settings: {e}")
    return {"unit_description": ""}

def save_settings(settings):
    """Save class-wide settings to JSON."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        st.error(f"Error saving settings: {e}")

def get_or_create_student_id(teacher_id, name):
    """Returns the ID for a name, creating one if it doesn't exist in DB."""
    from database_manager import get_student_id_by_name, save_student_identity
    
    existing_id = get_student_id_by_name(teacher_id, name)
    if existing_id:
        return existing_id
            
    new_id = f"STU_{random.randint(1000, 9999)}"
    save_student_identity(teacher_id, new_id, name)
    return new_id

def migrate_legacy_profiles():
    """
    Scan students.csv for real names instead of IDs.
    Migrate them into the SQL student_identity table.
    """
    if not os.path.exists(PROFILES_CSV):
        return

    updated = False
    profiles_data = []
    teacher_id = st.session_state.get("user_email", "default_teacher")
    
    try:
        with open(PROFILES_CSV, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            id_col = "Student ID" if "Student ID" in fieldnames else "Student Name"
            
            for row in reader:
                val = row.get(id_col, "")
                if val and not val.startswith("STU_"):
                    new_id = get_or_create_student_id(teacher_id, val)
                    row[id_col] = new_id
                    updated = True
                profiles_data.append(row)
                
        if updated:
            new_fieldnames = ["Student ID", "Struggles", "Mastered Words", "Target_Group"]
            with open(PROFILES_CSV, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=new_fieldnames)
                writer.writeheader()
                for row in profiles_data:
                    updated_row = {
                        "Student ID": row.get("Student ID") or row.get("Student Name"),
                        "Struggles": row.get("Sruggles", ""),
                        "Mastered Words": row.get("Mastered Words", ""),
                        "Target_Group": row.get("Target_Group", "g1")
                    }
                    writer.writerow(updated_row)
            st.toast(" Legacy student profiles migrated to Cloud-hosted Map.")
            
    except Exception as e:
        st.error(f"Migration error: {e}")

def get_name_for_id(teacher_id, student_id):
    """Returns the real name for a given ID from the DB."""
    from database_manager import get_student_name
    return get_student_name(teacher_id, student_id)

def load_profiles():
    """Load student profiles from CSV into a dictionary."""
    profiles = {}
    if os.path.exists(PROFILES_CSV):
        try:
            with open(PROFILES_CSV, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = row.get("Student ID")
                    if sid:
                        profiles[sid] = {
                            "struggles": row.get("Struggles", ""),
                            "mastered": row.get("Mastered Words", ""),
                            "target_group": row.get("Target_Group", "g1")
                        }
        except Exception as e:
            st.error(f"Error loading profiles: {e}")
    return profiles

def save_profile(student_id, struggles, mastered, target_group):
    """Save/Update a student profile in the CSV."""
    profiles = load_profiles()
    profiles[student_id] = {"struggles": struggles, "mastered": mastered, "target_group": target_group}
    
    try:
        with open(PROFILES_CSV, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["Student ID", "Struggles", "Mastered Words", "Target_Group"])
            writer.writeheader()
            for sid, data in profiles.items():
                writer.writerow({
                    "Student ID": sid,
                    "Struggles": data["struggles"],
                    "Mastered Words": data["mastered"],
                    "Target_Group": data["target_group"]
                })
    except Exception as e:
        st.error(f"Error saving profile: {e}")

def generate_groups_from_csv():
    """Reads student profiles from students.csv and organizes them by Target Group."""
    profiles = load_profiles()
    
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
    
    groups = {title: [] for title in group_titles.values()}
    groups["Review Needed"] = []
    
    for name, data in profiles.items():
        target = data.get("target_group", "").lower().strip()
        if target in group_titles:
            groups[group_titles[target]].append(name)
        else:
            groups["Review Needed"].append(name)
            
    return {k: v for k, v in groups.items() if v}

# --- HELPER: Convert practice lists to transposed DataFrame for Google Sheets ---
def practice_lists_to_table(practice_lists):
    """Convert practice lists into a transposed DataFrame.
    Columns = student names, Rows = word positions (Word 1-10)
    """
    if not practice_lists:
        return None
    
    # Build dict: student_name -> list of 10 words
    data = {}
    for slip in practice_lists:
        student_name = slip["student_name"]
        words = slip["words"]
        data[student_name] = words
    
    # Create DataFrame with rows as word positions
    df = pd.DataFrame(data)
    # Rename index to show word positions
    df.index = [f"Word {i+1}" for i in range(len(df))]
    return df

# --- INITIALIZE DATABASE ---
init_db()  

st.title("Unboxed Spelling Coach")

# --- INITIALIZE ALL MEMORY ---
if "user_email" not in st.session_state:
    st.session_state.user_email = "admin@example.com"

from database_manager import assign_unowned_students, get_all_teachers
num_assigned = assign_unowned_students(st.session_state.user_email)
if num_assigned > 0:
    st.toast(f" Assigned {num_assigned} unowned students to your profile.")

migrate_legacy_profiles()

for key, default in [("raw_transcription", ""), ("analysis_result", None), ("practice_lists", None), 
                      ("diagnostic_test", None), ("struggling_words", ""), ("students", load_profiles())]:
    if key not in st.session_state:
        st.session_state[key] = default

if "unit_description" not in st.session_state:
    st.session_state.unit_description = load_settings().get("unit_description", "")

query_params = st.query_params
if "email" in query_params:
    st.session_state.user_email = query_params["email"]
if "user_email" not in st.session_state:
    st.session_state.user_email = "admin@example.com"

ADMIN_EMAIL = "komododundee@gmail.com"
all_teachers = get_all_teachers()
login_options = ["Select your email..."]
seen = set()
for e in [ADMIN_EMAIL] + all_teachers:
    if e and e not in seen and e != "orphaned" and e != "admin@example.com":
        seen.add(e)
        login_options.append(e)

with st.sidebar:
    st.sidebar.image("logo.svg", width=200)
    st.header(" User Account")
    
    # Current selection index for selectbox
    current_user = st.session_state.get("user_email", "")
    try:
        default_idx = login_options.index(current_user) if current_user in login_options else 0
    except ValueError:
        default_idx = 0
    
    selected = st.selectbox(" Login", options=login_options, index=default_idx)
    
    # Log in if a real email is selected
    if selected != "Select your email...":
        if selected != st.session_state.user_email:
            st.session_state.user_email = selected
            # Persist to URL query params for Remember Me
            st.query_params["email"] = selected
            st.rerun()
        st.success(f" Logged in as *{selected}*")
    else:
        st.info(" Please select your email above to login.")
    
    # --- NEW TEACHER REGISTRATION ---
    with st.expander(" New Teacher? Register here"):
        reg_name = st.text_input("Your Name", key="reg_name")
        reg_email = st.text_input("Your Email", key="reg_email", placeholder="you@school.edu")
        if st.button("Register", key="register_btn"):
            if reg_name and reg_email and "@" in reg_email:
                from database_manager import save_teacher_settings
                save_teacher_settings(reg_email, "")
                st.success(f" Registered! Please select your email from the dropdown above.")
                st.rerun()
            else:
                st.error("Please enter a valid name and email address.")
    
    # ADMIN CHECK
    is_admin = st.session_state.user_email == ADMIN_EMAIL
    if is_admin:
        st.success(" Admin Access Granted")
        
        # ==========================================
        # ADMIN ONLY: CSV STATUS & FORCE IMPORT
        # ==========================================
        with st.expander(" Admin: CSV Data Management"):
            st.subheader(" CSV File Status")
            
            students_csv_exists = os.path.exists("students.csv")
            assessments_csv_exists = os.path.exists("assessments.csv")
            
            col_status1, col_status2 = st.columns(2)
            with col_status1:
                if students_csv_exists:
                    st.success(" students.csv: FOUND")
                    try:
                        with open("students.csv", 'r') as f:
                            line_count = sum(1 for _ in f) - 1
                        st.caption(f"   → {line_count} student records")
                    except:
                        pass
                else:
                    st.error(" students.csv: MISSING")
            
            with col_status2:
                if assessments_csv_exists:
                    st.success(" assessments.csv: FOUND")
                    try:
                        with open("assessments.csv", 'r') as f:
                            line_count = sum(1 for _ in f) - 1
                        st.caption(f"   → {line_count} assessment records")
                    except:
                        pass
                else:
                    st.error(" assessments.csv: MISSING")
            
            st.markdown("---")
            st.subheader(" Force Import from CSV")
            st.warning(" This will import ALL data from CSV files as **orphaned** (teacher_id = NULL)")
            
            if st.button(" FORCE IMPORT FROM CSV", type="primary", use_container_width=True):
                with st.spinner("Importing data..."):
                    from database_manager import import_from_csv, sync_identity_from_assessments
                    result = import_from_csv()
                    sync_result = sync_identity_from_assessments()
                    st.success(f" Import Complete!")
                    st.write(f"   • Students imported: **{result['students']}**")
                    st.write(f"   • Assessments imported: **{result['assessments']}**")
                    st.write(f"   • Identity records synced: **{sync_result['created']}**")
                    if result['students'] > 0 or result['assessments'] > 0:
                        st.info(" Imported records are marked as ORPHANED. Use 'Admin Student Allocation' to assign them to teachers.")
                    else:
                        st.info("No new records were imported (files may be empty or already imported).")
                st.rerun()
        
        st.markdown("---")
        
        # DATABASE SANITIZATION
        with st.expander(" Database Sanitization"):
            st.subheader(" Maintenance Tools")
            
            # Show current stats
            stats = get_database_stats()
            st.write(f" **Current Database Stats:**")
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.metric("Total Assessments", stats.get('total_assessments', 0))
                st.metric("Total Students", stats.get('total_students', 0))
            with col_s2:
                st.metric("Orphaned Students", stats.get('orphaned_students', 0))
                st.metric("Orphaned Assessments", stats.get('orphaned_assessments', 0))
            
            st.markdown("---")
            
            # Fix Teacher IDs button
            col_fix1, col_fix2 = st.columns([2, 1])
            with col_fix1:
                st.write("** Fix Teacher ID Consistency**")
                st.caption("Updates ALL assessment rows to match student_identity table")
            with col_fix2:
                if st.button(" Fix All Teacher IDs", use_container_width=True):
                    result = fix_all_teacher_ids()
                    st.success(f" Fixed! Synced {result['students_synced']} students, updated {result['total_assessment_rows_updated']} assessment rows.")
                    st.rerun()
            
            st.markdown("---")
            
            # Clear All Data - with double confirmation
            st.write("** Danger Zone**")
            st.error(" This will DELETE ALL DATA from the database. Use only for clean re-import.")
            
            # First confirmation
            if "confirm_clear" not in st.session_state:
                st.session_state.confirm_clear = False
            
            if not st.session_state.confirm_clear:
                if st.button(" Clear All Local Data", type="secondary", use_container_width=True):
                    st.session_state.confirm_clear = True
                    st.rerun()
            else:
                st.warning(" Are you absolutely sure? Click again to confirm deletion.")
                col_confirm1, col_confirm2 = st.columns(2)
                with col_confirm1:
                    if st.button(" Yes, DELETE Everything", type="primary", use_container_width=True):
                        result = clear_all_data()
                        st.error(f" Deleted! {result['assessments_deleted']} assessments, {result['identity_deleted']} identity records removed.")
                        st.session_state.confirm_clear = False
                        st.rerun()
                with col_confirm2:
                    if st.button(" Cancel", use_container_width=True):
                        st.session_state.confirm_clear = False
                        st.rerun()
    
    # STATUS INDICATORS
    st.divider()
    try:
        from database_manager import init_db
        init_db()
        st.write("Database Connection: OK")
    except Exception as e:
        st.write(f" Database Connection: Error ({e})")
    
    role = "Admin" if is_admin else "Teacher"
    st.write(f" User Role: {role}")

    st.divider()
    st.header(" Class Settings")
    
    # GLOBAL UNIT DESCRIPTION
    from database_manager import get_teacher_settings, save_teacher_settings
    current_unit_desc = get_teacher_settings(st.session_state.user_email)
    
    if not current_unit_desc:
        st.warning(" Please enter your Unit Description")
    
    unit_desc = st.text_area(
        " Global Unit Description", 
        value=current_unit_desc,
        placeholder="e.g., This unit focuses on long-a vowel teams and silent-e in the context of nature and animals.",
        key="unit_description_input"
    )
    
    if unit_desc != current_unit_desc:
        save_teacher_settings(st.session_state.user_email, unit_desc)
        st.session_state.unit_description = unit_desc
        st.toast("Unit description saved!")

    st.divider()
    
    # STUDENT SELECTION (Privacy: Teachers see real names, session stores pseudonym)
    teacher_id = st.session_state.get("user_email", "default_teacher")
    from database_manager import get_teacher_students, get_student_id_by_name, generate_pseudonym
    
    student_map = get_teacher_students(teacher_id)  # {student_id: real_name}
    
    # Build dropdown options: show real names, store pseudonym
    existing_students = []
    for sid, rname in student_map.items():
        existing_students.append({"label": rname, "id": sid})
    
    existing_names = [s["label"] for s in existing_students]
    selection = st.selectbox(" Load Student Profile", options=["None / New Student"] + existing_names)
    
    if selection != "None / New Student":
        # Find the student_id for this name
        student_id = None
        for s in existing_students:
            if s["label"] == selection:
                student_id = s["id"]
                break
        student_name = selection  # Teacher sees real name
        pseudonym = f"Student_{list(student_map.keys()).index(student_id) + 1:02d}" if student_id else selection
    else:
        student_name = st.text_input("Student Name (required)", key="name_input")
        student_id = get_or_create_student_id(teacher_id, student_name) if student_name else None
        pseudonym = generate_pseudonym(teacher_id, student_id) if student_id else None
    
    # Store pseudonym in session state for privacy
    if student_id:
        st.session_state.current_pseudonym = pseudonym
    
    # Logic to Load Student Data when name is changed
    if "last_loaded_student" not in st.session_state:
        st.session_state.last_loaded_student = ""
    
    if student_name and student_name != st.session_state.last_loaded_student:
        profiles = st.session_state.students
        if student_id and student_id in profiles:
            data = profiles[student_id]
            st.session_state.struggling_words_input = data.get("struggles", "")
            st.session_state.mastered_words_input = data.get("mastered", "")
            st.session_state.target_group_input = data.get("target_group", "g1")
        else:
            st.session_state.struggling_words_input = ""
            st.session_state.mastered_words_input = ""
            st.session_state.target_group_input = "g1"
        st.session_state.last_loaded_student = student_name
    
    st.divider()
    st.caption(" Privacy: Student data is anonymized for AI processing.")
    
    st.write("** Target Group**")
    target_group_input = st.selectbox(
        "Select student's current G-level",
        options=[f"g{i}" for i in range(9)],
        key="target_group_input"
    )
    
    st.divider()
    
    # STUDENT STRUGGLING WORDS INPUT
    st.write("** Experienced Errors (Long-term Struggles)**")
    struggling_words_input = st.text_area(
        "Enter words student has struggled with across multiple tests ('Correct:Attempt')",
        height=120,
        placeholder="e.g., ship:sip, sled:sed, stick:stik (comma-separated or one per line)",
        key="struggling_words_input"
    )
    
    st.divider()
    # MASTERED WORDS INPUT
    st.write("** Mastered Words (Spelled Correctly)**")
    mastered_words_input = st.text_area(
        "Enter words the student consistently spells correctly",
        placeholder="e.g., cat, bed, sit, run (comma-separated)",
        key="mastered_words_input"
    )
    
    # SAVE STUDENT DATA
    if st.button(" Save Student Data"):
        if student_name:
            # Use ID instead of Name
            st.session_state.students[student_id] = {
                "struggles": struggling_words_input,
                "mastered": mastered_words_input,
                "target_group": target_group_input
            }
            # Persist to CSV using ID
            save_profile(student_id, struggling_words_input, mastered_words_input, target_group_input)
            st.success(f"Saved data for {student_name}!")
            st.rerun() # Refresh dropdown and state
        else:
            st.error("Please enter a student name first.")

    st.divider()
    
    # ==========================================
    # SPELLING JOURNEY - Historical Progress View
    # ==========================================
    if student_id:
        with st.expander(" Spelling Journey (History)"):
            teacher_id = st.session_state.get("user_email", "")
            is_admin = teacher_id == ADMIN_EMAIL
            
            history = get_student_history(student_id, teacher_id=teacher_id, admin=is_admin)
            
            if history:
                st.caption(f"Showing {len(history)} recorded sessions for {student_name}")
                
                # Build display data
                history_data = []
                for row in history:
                    # Row: id(0), student_id(1), teacher_id(2), test_date(3), created_at(4),
                    # g0(5), g1(6), g2(7), g3(8), g4(9), g5(10), g6(11), g7(12), g8(13),
                    # suggested_next(14), teacher_notes(15), teacher_refined_notes(16), struggling_words(17)
                    
                    test_date = row[3] if row[3] else row[4][:10]  # Prefer test_date, fallback to created_at
                    created_at = row[4] if row[4] else ""
                    
                    # Determine the dominant G-level (lowest non-zero group)
                    g_scores = [row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12], row[13]]
                    g_names = ["g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]
                    dominant_g = "-"
                    for i, score in enumerate(g_scores):
                        if score is not None and score > 0:
                            dominant_g = g_names[i]
                            break
                    
                    # Struggling words from the record
                    struggling = row[17] if row[17] else ""
                    
                    # Check for 100% scores to identify mastered words
                    mastered = ""
                    if all(s == 100 or s is None for s in g_scores):
                        mastered = " 100% All Groups"
                    else:
                        # Extract mastered words from raw transcription
                        raw_text = row[5] if False else ""  # We don't have raw in this query
                        # Check each group for 100% mastery
                        mastered_groups = []
                        for i, score in enumerate(g_scores):
                            if score == 100:
                                mastered_groups.append(g_names[i].upper())
                        if mastered_groups:
                            mastered = f" {', '.join(mastered_groups)}"
                    
                    history_data.append({
                        "Date": test_date[:10] if test_date else created_at[:10],
                        "G-Level": dominant_g.upper(),
                        "Struggling Words": struggling[:50] + "..." if len(struggling) > 50 else struggling,
                        "Mastered": mastered
                    })
                
                # Display as dataframe
                history_df = pd.DataFrame(history_data)
                st.dataframe(history_df, use_container_width=True, hide_index=True)
                
                # Show details on hover/expand
                with st.expander(" View Full Session Details"):
                    for i, row in enumerate(history):
                        st.markdown(f"**Session {i+1}** - {row[4][:16] if row[4] else 'Unknown date'}")
                        cols_detail = st.columns(3)
                        cols_detail[0].metric("g0 Phonemic", f"{row[5] if row[5] else 0}%")
                        cols_detail[1].metric("g1 CVC", f"{row[6] if row[6] else 0}%")
                        cols_detail[2].metric("g2 Digraphs", f"{row[7] if row[7] else 0}%")
                        cols_detail2 = st.columns(3)
                        cols_detail2[0].metric("g3 Silent E", f"{row[8] if row[8] else 0}%")
                        cols_detail2[1].metric("g4 Vowel Teams", f"{row[9] if row[9] else 0}%")
                        cols_detail2[2].metric("g5 R-Controlled", f"{row[10] if row[10] else 0}%")
                        cols_detail3 = st.columns(3)
                        cols_detail3[0].metric("g6 Clusters", f"{row[11] if row[11] else 0}%")
                        cols_detail3[1].metric("g7 Multisyllabic", f"{row[12] if row[12] else 0}%")
                        cols_detail3[2].metric("g8 Reduction", f"{row[13] if row[13] else 0}%")
                        
                        if row[16]:  # teacher_refined_notes
                            st.markdown(f" **Notes:** {row[16]}")
                        if row[17]:  # struggling_words
                            st.markdown(f" **Struggling:** {row[17]}")
                        st.divider()
            else:
                st.info(f"No history found for {student_name}. Save an assessment to start their journey!")

    st.divider()
    
    # WORD BANK TOOLS
    st.write("** Word Bank Tools**")

    # G-GROUP LEGEND (Moved to expander at bottom)
    with st.expander(" Diagnostic Group Description"):
        st.caption("G0 Phonemic Awareness")
        st.caption("G1 Basic CVC Mapping")
        st.caption("G2 Digraphs")
        st.caption("G3 Silent E")
        st.caption("G4 Vowel Teams")
        st.caption("G5 R-Controlled")
        st.caption("G6 Clusters (Blends)")
        st.caption("G7 Multisyllabic")
        st.caption("G8 Reduction & Morphology")


if st.button(" AI-Generate Personalized Practice Lists"):
    with st.spinner("Generating personalized practice lists with AI..."):
        from database_manager import generate_class_groups
        
        # Get active groups (only groups with students assigned)
        teaching_groups = generate_class_groups()
        
        word_banks_path = "word_banks"
        student_slips = []
        
        # Mapping from group titles back to g-keys
        title_to_key = {
            "Group 0: Phonemic Awareness": "g0",
            "Group 1: Basic CVC Mapping": "g1",
            "Group 2: Digraphs": "g2",
            "Group 3: Silent E": "g3",
            "Group 4: Vowel Teams": "g4",
            "Group 5: R-Controlled": "g5",
            "Group 6: Clusters/Blends": "g6",
            "Group 7: Multisyllabic": "g7",
            "Group 8: Reduction & Morphology": "g8"
        }
        
        # For each active group, get students and generate their personalized slips
        for group_title, students in teaching_groups.items():
            g_key = title_to_key.get(group_title)
            if not g_key:
                continue
            
            # Load base word bank for fallback
            file_path = os.path.join(word_banks_path, f"{g_key}.txt")
            base_words = []
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    base_words = [line.strip() for line in f.readlines() if line.strip()]
            
            # Create a personalized slip for each student in this group
            for student_id in students:
                # Resolve ID to Real Name for UI display and internal mapping
                display_name = get_name_for_id(student_id)
                
                # Fetch student's teacher notes and struggling words from database
                from database_manager import get_latest_teacher_notes, get_struggling_words
                teacher_notes = get_latest_teacher_notes(student_id)
                db_struggling_words = get_struggling_words(student_id)
                
                # Combine: custom input takes priority, then DB records
                custom_input = st.session_state.get("struggling_words_input", "")
                combined_struggling = custom_input if custom_input.strip() else db_struggling_words
                
                # Generate personalized words using AI (pass ID to maintain privacy)
                try:
                    personalized_words = generate_personalized_practice_words(
                        student_name=student_id,
                        target_group=g_key,
                        teacher_notes=teacher_notes,
                        struggling_words=combined_struggling,
                        mastered_words=st.session_state.get("mastered_words_input", ""),
                        unit_description=st.session_state.unit_description,
                        custom_words_input=custom_input if custom_input.strip() else None
                    )
                except Exception as e:
                    st.warning(f"AI generation failed for {display_name}, using fallback: {e}")
                    # Fallback to random selection from word bank
                    personalized_words = random.sample(base_words, min(10, len(base_words))) if base_words else ["word" + str(i) for i in range(1, 11)]
                
                student_slips.append({
                    "student_name": display_name,
                    "group_title": group_title,
                    "words": personalized_words
                })
        
        st.session_state.practice_lists = student_slips
        st.rerun()

if st.button(" Generate New 20-Word Diagnostic Test"):
    with st.spinner("Creating diagnostic test..."):
        word_banks_path = "word_banks"
        test_words = []
        
        # 5 words from g1/g2
        g1_path = os.path.join(word_banks_path, "g1.txt")
        g2_path = os.path.join(word_banks_path, "g2.txt")
        g1_words = []
        g2_words = []
        if os.path.exists(g1_path):
            with open(g1_path, "r") as f:
                g1_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g2_path):
            with open(g2_path, "r") as f:
                g2_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g1_words + g2_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # 5 words from g3/g4
        g3_path = os.path.join(word_banks_path, "g3.txt")
        g4_path = os.path.join(word_banks_path, "g4.txt")
        g3_words = []
        g4_words = []
        if os.path.exists(g3_path):
            with open(g3_path, "r") as f:
                g3_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g4_path):
            with open(g4_path, "r") as f:
                g4_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g3_words + g4_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # 5 words from g5/g6
        g5_path = os.path.join(word_banks_path, "g5.txt")
        g6_path = os.path.join(word_banks_path, "g6.txt")
        g5_words = []
        g6_words = []
        if os.path.exists(g5_path):
            with open(g5_path, "r") as f:
                g5_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g6_path):
            with open(g6_path, "r") as f:
                g6_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g5_words + g6_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # 5 words from g7/g8
        g7_path = os.path.join(word_banks_path, "g7.txt")
        g8_path = os.path.join(word_banks_path, "g8.txt")
        g7_words = []
        g8_words = []
        if os.path.exists(g7_path):
            with open(g7_path, "r") as f:
                g7_words = [line.strip() for line in f.readlines() if line.strip()]
        if os.path.exists(g8_path):
            with open(g8_path, "r") as f:
                g8_words = [line.strip() for line in f.readlines() if line.strip()]
        combined = g7_words + g8_words
        test_words.extend(random.sample(combined, min(5, len(combined))))
        
        # Save to assessments folder
        assessments_folder = "assessments"
        if not os.path.exists(assessments_folder):
            os.makedirs(assessments_folder)
        
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"dynamic_test_{date_str}.txt"
        file_path = os.path.join(assessments_folder, file_name)
        
        with open(file_path, "w") as f:
            for word in test_words:
                f.write(word + "\n")
        
        st.session_state.diagnostic_test = {
            "words": test_words,
            "file_name": file_name
        }
        st.rerun()

st.divider()

# THE RESET BUTTON
if st.button(" Start New Student"):
    st.session_state.raw_transcription = ""
    st.session_state.analysis_result = None
    st.session_state.practice_lists = None
    st.session_state.diagnostic_test = None
    st.session_state.struggling_words = ""
    st.rerun()

uploaded_file = st.file_uploader(" Step 1: Upload Test Photo", type=["jpg", "jpeg", "png"])

# --- 2. PRE-PROCESS & LAYOUT ---
if uploaded_file:
    clean_base64, clean_img = preprocess_image(uploaded_file)
    
    col_img, col_text = st.columns([1, 1])
    
    with col_img:
        st.subheader(" AI's View (Cleaned)")
        st.image(clean_img, use_container_width=True)
        if st.button(" Step 2: Read Handwriting"):
            with st.spinner("AI is reading..."):
                st.session_state.raw_transcription = transcribe_handwriting(clean_base64)
                st.rerun() 

    with col_text:
        st.subheader(" Step 3: Verify & Edit")
        edited_text = st.text_area(
            "Verify and edit student attempts here:", 
            value=st.session_state.raw_transcription,
            height=400 
        )

    # --- 3. THE ANALYSIS BUTTON ---
    if st.button(" Step 4: Run Analysis"):
        if not student_name:
            st.warning(" Please enter a Student Name in the sidebar!")
        elif not edited_text:
            st.warning(" No text to analyze. Please read handwriting or type manually.")
        else:
            with st.spinner(f"Analyzing {student_name}..."):
                # Save the edited text to session state so it persists after analysis
                st.session_state.edited_transcription = edited_text
                # Pass the student_id to the AI to keep it anonymous
                result = run_scoring_crew(student_id, edited_text)
                
                if result is None:
                    st.error("The AI returned nothing. Check your internet or API key.")
                else:
                    st.session_state.analysis_result = result
                    
    # --- 4. DISPLAY RESULTS ---
    if st.session_state.analysis_result:
        data = st.session_state.analysis_result 

        st.subheader(f" Diagnostic for {student_name}") # Keep the real name for the teacher's view
        
        # 1. ATTEMPT TO READ STRUCTURED DATA OR PARSE RAW JSON
        import json
        
        # Pre-fill defaults
        g_scores = {f"g{i}": 0 for i in range(9)}
        notes = "No notes generated."
        targets = []
        
        # Scenario A: Crew AI successfully mapped to Pydantic
        if hasattr(data, 'g0_phonemic_awareness'):
            g_scores = {
                "g0": data.g0_phonemic_awareness, "g1": data.g1_cvc_mapping, "g2": data.g2_digraphs,
                "g3": data.g3_silent_e, "g4": data.g4_vowel_teams, "g5": data.g5_r_controlled,
                "g6": data.g6_clusters, "g7": data.g7_multisyllabic, "g8": data.g8_reduction_morphology
            }
            notes = data.teacher_notes
            targets = data.suggested_next_groups
            
        # Scenario B: Crew AI returned a raw JSON string like it just did for Alice!
        elif hasattr(data, 'raw') and data.raw:
            import re
            try:
                raw_json = json.loads(data.raw)
                g_scores = {
                    "g0": raw_json.get("g0_phonemic_awareness", 0),
                    "g1": raw_json.get("g1_cvc_mapping", 0),
                    "g2": raw_json.get("g2_digraphs", 0),
                    "g3": raw_json.get("g3_silent_e", 0),
                    "g4": raw_json.get("g4_vowel_teams", 0),
                    "g5": raw_json.get("g5_r_controlled", 0),
                    "g6": raw_json.get("g6_clusters", 0),
                    "g7": raw_json.get("g7_multisyllabic", 0),
                    "g8": raw_json.get("g8_reduction_morphology", 0)
                }
                notes = raw_json.get("teacher_notes", "No notes generated.")
                targets = raw_json.get("suggested_next_groups", [])
            except:
                # Fallback: silently extract g0-g8 mentions from raw_analysis using regex
                notes = "AI returned text but couldn't parse scores automatically. See below."
                # Extract any mentions of g0 through g8 from the raw text
                raw_text = data.raw if hasattr(data, 'raw') else str(data)
                found_groups = re.findall(r'g[0-8]', raw_text)
                # Remove duplicates while preserving order
                targets = list(dict.fromkeys(found_groups))

        # Display the scores in the clean UI metrics
        cols = st.columns(3)
        cols[0].metric("g0: Phonemic", f"{g_scores['g0']}%")
        cols[1].metric("g1: CVC", f"{g_scores['g1']}%")
        cols[2].metric("g2: Digraphs", f"{g_scores['g2']}%")
        
        cols2 = st.columns(3)
        cols2[0].metric("g3: Silent E", f"{g_scores['g3']}%")
        cols2[1].metric("g4: Vowel Teams", f"{g_scores['g4']}%")
        cols2[2].metric("g5: R-Controlled", f"{g_scores['g5']}%")
        
        cols3 = st.columns(3)
        cols3[0].metric("g6: Clusters", f"{g_scores['g6']}%")
        cols3[1].metric("g7: Multisyllabic", f"{g_scores['g7']}%")
        cols3[2].metric("g8: Reduction", f"{g_scores['g8']}%")

        # Recommendations
        st.subheader(" Instructional Targets")
        
        # Mapping from ugly g-names to pretty human-readable titles
        GROUP_NAME_MAP = {
            "g0": "G0 Phonemic Awareness",
            "g1": "G1 Basic CVC Mapping",
            "g2": "G2 Digraphs",
            "g3": "G3 Silent E",
            "g4": "G4 Vowel Teams",
            "g5": "G5 R-Controlled",
            "g6": "G6 Clusters (Blends)",
            "g7": "G7 Multisyllabic",
            "g8": "G8 Reduction & Morphology"
        }
        
        # Create checkboxes for each group, pre-checked if AI suggested them
        selected_targets = []
        for g_key, pretty_name in GROUP_NAME_MAP.items():
            is_checked = g_key in targets
            if st.checkbox(pretty_name, value=is_checked, key=f"target_{g_key}"):
                selected_targets.append(g_key)
        
        # Use the checkbox selections as the targets
        targets = selected_targets
            
        # 2. THE FEEDBACK LOOP: The "Gold Standard" Editor (Side-by-Side Layout)
        st.write("### ‍ Teacher Refinement")
        st.caption("Review the AI's notes above. Verify the student's attempts and record your final diagnostic decision.")
        
        # Create two columns for side-by-side text areas
        col1, col2 = st.columns(2)
        
        with col1:
            # Use the teacher's edited transcription (saved before analysis)
            edited_text = st.text_area(
                "Student's Spelling Attempts", 
                value=st.session_state.get('edited_transcription', st.session_state.raw_transcription),
                height=400,
                key="edited_text_final"
            )
        
        with col2:
            # We give them placeholder text if the AI didn't return a perfect string!
            default_text_area_val = notes if notes != "No notes generated." else "Type your own diagnostic notes here for this student..."
            
            final_notes = st.text_area(
                "Final Diagnostic Notes (The 'Gold Standard')", 
                value=default_text_area_val, 
                height=400
            )

        # 3. THE SAVE BUTTON
        if st.button(" Confirm & Save to Student History"):
            from database_manager import save_assessment
            
            # targets is already clean (g0, g1, etc.) from the checkboxes
            cleaned_targets = targets

            # Since the database expects a structured object, we can build a fake one 
            # with our extracted data to pass to save_assessment safely!
            class SaveObject:
                pass
            save_obj = SaveObject()
            save_obj.student_id = student_id
            save_obj.suggested_next_groups = cleaned_targets # Uses our newly cleaned list!
            save_obj.teacher_notes = notes
            save_obj.g0_phonemic_awareness = g_scores["g0"]
            save_obj.g1_cvc_mapping = g_scores["g1"]
            save_obj.g2_digraphs = g_scores["g2"]
            save_obj.g3_silent_e = g_scores["g3"]
            save_obj.g4_vowel_teams = g_scores["g4"]
            save_obj.g5_r_controlled = g_scores["g5"]
            save_obj.g6_clusters = g_scores["g6"]
            save_obj.g7_multisyllabic = g_scores["g7"]
            save_obj.g8_reduction_morphology = g_scores["g8"]

            # Get struggling words from session state
            struggling_words = st.session_state.get("struggling_words_input", "")
            
            save_assessment(save_obj, edited_text, teacher_refinement=final_notes, struggling_words=struggling_words)
            
            st.success(f" Final assessment for {student_name} has been saved with clean tags!")
            st.balloons()
            
# --- STEP 2: CLASS ANALYSIS ---
st.header("Class Overview & Grouping")

from database_manager import (
    get_all_latest_results, generate_class_groups, get_orphaned_students, 
    assign_student_to_teacher, get_all_teachers, get_raw_assessments, 
    bulk_assign_orphans_to_teacher, bulk_assign_students, get_database_stats, 
    clear_all_data, fix_all_teacher_ids, sync_identity_from_assessments,
    get_all_students_with_status, get_teacher_student_status
)

# Permissions check
teacher_id = st.session_state.get("user_email", "default_teacher")
is_admin = teacher_id == ADMIN_EMAIL

# ============================================================
# ADMIN DASHBOARD
# ============================================================
if is_admin:
    st.subheader("School-Wide Research Dashboard")
    
    # First, sync all data
    sync_result = sync_identity_from_assessments()
    
    # Show database stats
    stats = get_database_stats()
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Total Assessments", stats.get('total_assessments', 0))
    col_s2.metric("Unique Students", stats.get('unique_students_in_assessments', 0))
    col_s3.metric("Teachers", stats.get('total_teachers', 0))
    
    st.markdown("---")
    
    # --- ADMIN DATABASE REPAIR SECTION ---
    with st.expander("Database Repair"):
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            st.write("**Button A: Link Ghost Records**")
            st.caption("Syncs all assessment students to identity table.")
            if st.button("Link Ghost Records", use_container_width=True):
                with st.spinner("Linking ghost records..."):
                    result = fix_all_teacher_ids()
                    sync_result = sync_identity_from_assessments()
                    st.success(f"Synced {sync_result.get('created', 0)} new identity records.")
                    st.success(f"Updated {result['assessment_rows_updated']} assessment rows.")
                    st.rerun()
        
        with col_btn2:
            st.write("**Button B: Global Claim**")
            st.caption("Assigns ALL unassigned students to glenp@gm.yhsh.tn.edu.tw.")
            if st.button("Global Claim", use_container_width=True):
                with st.spinner("Assigning all orphans..."):
                    result = bulk_assign_orphans_to_teacher("glenp@gm.yhsh.tn.edu.tw")
                    st.success(f"Assigned {result['students_assigned']} students to glenp@gm.yhsh.tn.edu.tw")
                    st.rerun()
    
    st.markdown("---")
    
    # --- ADMIN: COMPLETE STUDENT TABLE ---
    st.subheader("All Students in Database")
    
    all_students = get_all_students_with_status()
    
    if not all_students:
        st.info("No students found. Import legacy CSV data or save new assessments.")
    else:
        # Build table data
        table_data = []
        for s in all_students:
            table_data.append({
                "Name": s["name"],
                "Last Assessment": s["last_date"][:10] if s["last_date"] else "Never",
                "Total Attempts": s["total_attempts"],
                "Teacher": s["teacher"],
                "student_id": s["student_id"]  # Hidden for button action
            })
        
        table_df = pd.DataFrame(table_data)
        
        # Display with formatted columns (exclude hidden student_id)
        display_cols = ["Name", "Last Assessment", "Total Attempts", "Teacher"]
        st.dataframe(table_df[display_cols], use_container_width=True, hide_index=True)
        
        st.caption(f"Showing {len(all_students)} students")
        
        # --- FORCE-ASSIGN SECTION ---
        st.markdown("### Quick Assign Students")
        orphans = [s for s in all_students if s["teacher"] == "Unassigned"]
        
        if orphans:
            st.warning(f"{len(orphans)} students need assignment")
            
            # Bulk assign
            all_teachers = get_all_teachers()
            if all_teachers:
                col_bulk, col_btn = st.columns([3, 1])
                with col_bulk:
                    bulk_teacher = st.selectbox("Assign unassigned students to:", options=all_teachers, key="bulk_admin_assign")
                with col_btn:
                    st.write("")
                    if st.button("Assign All", type="primary", use_container_width=True):
                        orphan_ids = [s["student_id"] for s in orphans]
                        result = bulk_assign_students(orphan_ids, bulk_teacher)
                        st.success(f"Assigned {result['students_assigned']} students to {bulk_teacher}")
                        st.rerun()
            
            # Individual assign with display_name
            st.markdown("**Individual Assignment:**")
            col_names, col_teachers, col_btns = st.columns([2, 2, 1])
            
            orphan_options = [(s["student_id"], s["name"]) for s in orphans]
            all_teachers_list = get_all_teachers()
            
            if all_teachers_list:
                selected = st.selectbox("Select student:", options=orphan_options, format_func=lambda x: x[1])
                selected_teacher = st.selectbox("Assign to:", options=all_teachers_list)
                if st.button("Force-Assign to Me", use_container_width=True):
                    assign_student_to_teacher(selected[0], selected_teacher)
                    st.success(f"{selected[1]} assigned to {selected_teacher}")
                    st.rerun()
        else:
            st.success("All students are assigned to a teacher.")

# ============================================================
# TEACHER DASHBOARD
# ============================================================
else:
    st.subheader(f"My Class ({teacher_id})")
    
    # Get students for this teacher
    teacher_students = get_teacher_student_status(teacher_id)
    
    if not teacher_students:
        st.info("No students assigned to you yet. Ask admin to assign students.")
    else:
        st.write(f"**{len(teacher_students)} students in your class**")
        
        # Show student cards
        for student in teacher_students:
            with st.container():
                col1, col2, col3 = st.columns([2, 1, 1])
                
                with col1:
                    st.markdown(f"**{student['name']}**")
                    st.caption(f"Attempts: {student['total_attempts']} | Last: {student['last_date'][:10] if student['last_date'] else 'Never'}")
                
                with col2:
                    if student['current_g_level']:
                        st.metric("Current G-Level", student['current_g_level'])
                    else:
                        st.metric("Current G-Level", "N/A")
                
                with col3:
                    if student['most_struggled_word']:
                        st.metric("Most Struggled", student['most_struggled_word'][:20])
                    else:
                        st.metric("Most Struggled", "N/A")
                
                st.divider()

# ============================================================
# SHARED: CLASS OVERVIEW & GROUPING (for both admin and teachers)
# ============================================================
st.markdown("---")
st.subheader("Assessment Results")

data = get_all_latest_results(teacher_id=teacher_id, admin=is_admin)

if not data:
    st.info("No assessment data found. Save an assessment to see results here.")
else:
    # Draw the Results Table
    df = pd.DataFrame(data)
    cols_to_show = [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 17]
    available_cols = [c for c in cols_to_show if c < len(df.columns)]
    display_df = df.iloc[:, available_cols].copy()
    display_df.columns = ["Student ID", "Date", "Created At", "g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", "Suggested", "Notes", "Struggling"]
    st.dataframe(display_df, use_container_width=True)
    
    st.markdown("---")
    
    # Teaching Groups
    st.subheader("Auto-Generated Teaching Groups")
    
    if st.button("Refresh Groups"):
        st.rerun()

    teaching_groups = generate_class_groups()
    
    if not teaching_groups:
        st.warning("No groups can be formed. Save assessments with diagnostic results.")
    else:
        cols = st.columns(3)
        col_idx = 0
        
        for group_name, students in teaching_groups.items():
            with cols[col_idx]:
                st.markdown(f"**{group_name}**")
                for sid in students:
                    display_name = get_name_for_id(teacher_id, sid)
                    st.markdown(f"- {display_name}")
            col_idx = (col_idx + 1) % 3

# --- PRACTICE LISTS DISPLAY ---
if st.session_state.practice_lists:
    st.header("AI-Generated Personalized Practice Lists")
    st.caption("Copy the table below to paste into Google Sheets.")
    
    table_df = practice_lists_to_table(st.session_state.practice_lists)
    
    if table_df is not None:
        st.dataframe(table_df, hide_index=False, use_container_width=True)
        st.success(f"Table contains {len(table_df)} words for {len(table_df.columns)} students.")
    
    st.divider()

# Display diagnostic test if generated
if st.session_state.diagnostic_test:
    st.header("New Diagnostic Test")
    st.caption(f"Generated test saved as: {st.session_state.diagnostic_test['file_name']}")
    
    st.subheader("20-Word Diagnostic Test")
    st.write("**Instructions:** Read these words aloud to the student.")
    
    for i, word in enumerate(st.session_state.diagnostic_test['words'], 1):
        st.write(f"{i}. {word}")
    
    st.success(f"Test saved to assessments/{st.session_state.diagnostic_test['file_name']}")
    st.divider()
