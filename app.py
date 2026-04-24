import os
os.environ["OTEL_SDK_DISABLED"] = "true"
import pandas as pd
import streamlit as st
import random
import csv
import json
from datetime import datetime

from utils import preprocess_image
from spelling_logic import transcribe_handwriting, run_scoring_crew, generate_personalized_practice_words
from database_manager import (
    init_db, get_all_latest_results, assign_unowned_students, get_teacher_settings,
    save_teacher_settings, import_from_csv, get_student_history, get_mastered_words_from_raw,
    get_database_stats, fix_all_teacher_ids, clear_all_data, sync_identity_from_assessments,
    get_all_students_by_teacher, get_anonymized_history, get_all_students_for_allocation,
    update_student_teacher, register_teacher, get_all_teachers, get_all_students_with_status,
    assign_student_to_teacher, bulk_assign_orphans_to_teacher, bulk_assign_students,
    get_orphaned_students, get_all_students_with_status, get_teacher_student_status,
    get_raw_assessments, generate_class_groups, get_latest_teacher_notes, get_struggling_words,
    get_student_id_by_name, save_student_identity, get_student_name, get_pseudonym,
    generate_pseudonym, save_assessment, save_ai_report, get_name_for_id,
    get_all_test_templates, get_test_template, save_test_template, delete_test_template,
    save_draft_assessment, get_draft_assessments, delete_draft_assessment
)

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(page_title="UnBoxEd Spelling Coach", layout="wide", page_icon="logo.svg")

# =============================================================================
# PERSISTENCE HELPERS
# =============================================================================
PROFILES_CSV = "students.csv"
SETTINGS_FILE = "settings.json"
ADMIN_EMAIL = "komododundee@gmail.com" 

def load_settings():
    """Load class-wide settings from JSON."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Error loading settings: {e}")
    return {"unit_description": ""}

def save_settings_to_file(settings):
    """Save class-wide settings to JSON."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        st.error(f"Error saving settings: {e}")

def get_or_create_student_id(teacher_id, name):
    """Returns the ID for a name, creating one if it doesn't exist in DB."""
    existing_id = get_student_id_by_name(teacher_id, name)
    if existing_id:
        return existing_id
    new_id = f"STU_{random.randint(1000, 9999)}"
    save_student_identity(teacher_id, new_id, name)
    return new_id

def migrate_legacy_profiles():
    """Scan students.csv for real names instead of IDs. Migrate them into the SQL student_identity table."""
    if not os.path.exists(PROFILES_CSV):
        return

    updated = False
    profiles_data = []
    teacher_id = st.session_state.get("user_name", "admin@example.com")  # Use user_name which contains the email
    
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

def practice_lists_to_table(practice_lists):
    """Convert practice lists into a transposed DataFrame."""
    if not practice_lists:
        return None
    
    data = {}
    for slip in practice_lists:
        student_name = slip["student_name"]
        words = slip["words"]
        data[student_name] = words
    
    df = pd.DataFrame(data)
    df.index = [f"Word {i+1}" for i in range(len(df))]
    return df

# =============================================================================
# INITIALIZE SESSION STATE
# =============================================================================
def initialize_session_state():
    """Initialize all session state variables and database."""
    # Initialize database first - must happen before any DB queries
    init_db()
    
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    
    if 'role' not in st.session_state:
        st.session_state.role = None
    
    if "user_email" not in st.session_state and "email" not in st.session_state:
        st.session_state.email = "admin@example.com"
    
    for key, default in [
        ("raw_transcription", ""), ("analysis_result", None), ("practice_lists", None),
        ("diagnostic_test", None), ("struggling_words", ""), ("students", load_profiles()),
        ("edited_transcription", "")
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    if "unit_description" not in st.session_state:
        st.session_state.unit_description = load_settings().get("unit_description", "")

# =============================================================================
# MAIN ROUTER
# =============================================================================
def main():
    """Main router that checks authentication and routes to appropriate page."""
    initialize_session_state()

    # Check for legacy data and migrate it immediately after DB is ready
    migrate_legacy_profiles()
    
    # Handle URL query params - standardize to use 'email'
    query_params = st.query_params
    if "email" in query_params:
        st.session_state.email = query_params["email"]
        st.session_state.authenticated = True
    
    # Route based on authentication
    if not st.session_state.get('authenticated'):
        show_registration_page()
    else:
        show_teacher_dashboard()

# =============================================================================
# PAGE: REGISTRATION
# =============================================================================
def show_registration_page():

    st.image("logo.svg", width=200)
    st.title("Welcome to UnBoxEd Spelling Coach!")
    
    # 1. Get existing teachers from the database
    from database_manager import get_all_teachers
    existing_teachers = get_all_teachers()
    
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Returning Coach")
        if existing_teachers:
            # Create a list of "Name (Email)" for the dropdown
            teacher_options = [f"{t['name']} ({t['email']})" for t in existing_teachers]
            selected = st.selectbox("Choose your account:", ["Select..."] + teacher_options)
            
            if selected != "Select...":
                if st.button("Login"):
                    # Extract email from the string "Name (email@test.com)"
                    email = selected.split('(')[-1].replace(')', '')
                    name = selected.split(' (')[0]
                    
                    st.session_state.authenticated = True
                    st.session_state.user_name = email  # Store email as user_name
                    st.session_state.email = name  # Store name as email (this seems backwards but matches current usage)
                    st.session_state.role = 'teacher'
                    st.rerun()
        else:
            st.info("No accounts found yet. Register on the right!")

    with col2:
        st.subheader("New Coach")
        with st.form("registration_form", clear_on_submit=True, enter_to_submit=False):
            new_name = st.text_input("Full Name")
            new_email = st.text_input("Email Address")
            submit_button = st.form_submit_button("Register & Log In")

            if submit_button:
                if new_name and new_email:
                    from database_manager import register_teacher
                    register_teacher(new_email, new_name)
                    
                    st.session_state.authenticated = True
                    st.session_state.user_name = new_email  # Store email as user_name
                    st.session_state.email = new_name  # Store name as email (this seems backwards but matches current usage)
                    st.session_state.role = 'teacher'
                    st.rerun()

# =============================================================================
# PAGE: TEACHER DASHBOARD (with sidebar navigation)
# =============================================================================
def show_teacher_dashboard():
    """Main dashboard with sidebar navigation for authenticated users."""
    # Sidebar branding and logout
    st.sidebar.image("logo.svg", width=200)
    st.sidebar.success(f"👤 Logged in: {st.session_state.user_name}")
    
    if st.sidebar.button("Log Out"):
        st.session_state.authenticated = False
        st.session_state.role = None
        st.session_state.clear()  # Clear all session state
        st.rerun()
    
    # Sidebar navigation using radio buttons
    page = st.sidebar.radio("Navigation", ["My Class", "Add New Assessment", "Admin"])
    
    # Initialize database and migrate legacy data 
    migrate_legacy_profiles()
    
    # Get current teacher email (standardized)
    current_teacher_email = st.session_state.get('email')
    
    # Route to appropriate page function
    if page == "My Class":
        display_teacher_class()
    elif page == "Add New Assessment":
        display_assessment_form()
    elif page == "Admin":
        display_admin_page()

# =============================================================================
# COMPONENT: TEACHER CLASS (student cards with AI coaching)
# =============================================================================
def display_teacher_class():
    """Display the Teacher Dashboard with student cards and AI coaching."""
    st.header("My Class Dashboard")
    
    teacher_id = st.session_state.get('user_name')  # Use user_name which contains the email
    teacher_students_list = get_all_students_by_teacher(teacher_id)
    
    if not teacher_students_list:
        st.info("No students assigned to you yet. Use 'Add New Assessment' to get started!")
        return

    st.write(f"{len(teacher_students_list)} students in your class")
    
    # Show student cards with AI coaching buttons
    for student in teacher_students_list:
        with st.container():
            col1, col2 = st.columns([2, 1])
            
            current_student_name = student['name']

            with col1:
                st.markdown(f"**{current_student_name}**")
                st.caption(f"Alias: {student['pseudonym']} | Attempts: {student['total_attempts']}")
            
            with col2:
                g_val = student.get('current_g_level', 'N/A')
                st.metric("Current G-Level", g_val.split(',')[0] if g_val else "N/A")

            # AI Coaching button for each student
            if st.button(f"Generate AI Coach Report for {current_student_name}", key=f"ai_{current_student_name}"):
                with st.spinner(f"Consulting AI about {student['pseudonym']}..."):
                    try:
                        # Get full history as list for holistic AI analysis
                        history = get_student_history(student['student_id'], teacher_id=teacher_id, admin=False)
                        from spelling_logic import get_ai_coaching_report
                        raw_report = get_ai_coaching_report(
                            student_alias=student['pseudonym'], 
                            g_level=student.get('current_g_level', 'N/A'), 
                            history=history
                        )
                        # Store raw report in session state for editing
                        st.session_state[f'raw_report_{current_student_name}'] = raw_report
                        st.session_state[f'edit_mode_{current_student_name}'] = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to generate AI coach report: {str(e)}")
                        st.info("Please try again later or contact support if the issue persists.")
            
            # Display editable report if in edit mode
            edit_key = f'edit_mode_{current_student_name}'
            if st.session_state.get(edit_key, False):
                raw_report = st.session_state.get(f'raw_report_{current_student_name}', '')
                
                st.markdown("---*")
                st.subheader(f"AI Coaching Report for {current_student_name}")
                st.caption("Review and edit the AI's suggestions before saving.")
                
                # Editable text area for the report
                edited_report = st.text_area(
                    "Coach Report (editable)",
                    value=raw_report,
                    height=300,
                    key=f'report_editor_{current_student_name}'
                )
                
                # Confirm and Save Report button
                col_save1, col_save2 = st.columns([1, 4])
                with col_save1:
                    if st.button("Confirm & Save Report", key=f'save_report_{current_student_name}', type="primary"):
                        if edited_report.strip():
                            # Save the edited report as part of the assessment
                            from database_manager import save_ai_report
                            save_ai_report(
                                student_id=student['student_id'],
                                teacher_id=teacher_id,
                                report_content=edited_report
                            )
                            st.success(f"Report saved for {current_student_name}!")
                            st.session_state[edit_key] = False
                            st.rerun()
                        else:
                            st.warning("Report cannot be empty.")
                with col_save2:
                    if st.button("Discard", key=f'discard_report_{current_student_name}'):
                        st.session_state[edit_key] = False
                        st.rerun()
                st.markdown("---*")
        
        st.divider()

# =============================================================================
# COMPONENT: ASSESSMENT FORM (photo upload, transcription, scoring)
# =============================================================================
def display_assessment_form():
    """Display the assessment form with photo upload, transcription, and scoring."""
    # Import AI functions needed for assessment
    from spelling_logic import transcribe_handwriting, run_scoring_crew
    
    # Access ADMIN_EMAIL from module scope
    global ADMIN_EMAIL
    
    st.header("Add New Assessment")
    
    # ---- DRAFT NOTIFICATION ----
    teacher_id = st.session_state.get('user_name')
    drafts = get_draft_assessments(teacher_id)
    if drafts:
        st.warning(f"📝 You have {len(drafts)} unfinished assessment draft(s).")
        with st.expander("View Drafts"):
            for draft in drafts:
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"**{draft['student_name']}** - {draft['updated_at'][:16]}")
                with col2:
                    if st.button("Load", key=f"load_draft_{draft['id']}"):
                        # Load draft into session state
                        st.session_state.pending_student_name = draft['student_name']
                        st.session_state.pending_student_id = draft['student_id']
                        st.session_state.edited_transcription = draft['edited_text'] or ""
                        st.session_state.teacher_observations_input = draft['teacher_observations'] or ""
                        st.session_state.struggling_words_input = draft['struggling_words'] or ""
                        st.session_state.intended_words_input = draft['intended_words']
                        st.success(f"Loaded draft for {draft['student_name']}")
                        st.rerun()
                with col3:
                    if st.button("Delete", key=f"delete_draft_{draft['id']}"):
                        delete_draft_assessment(draft['id'])
                        st.success("Draft deleted")
                        st.rerun()
        st.divider()
    
    # ---- SIDEBAR: Student Selection & Settings ----
    with st.sidebar:
        st.header(" Student Profile")
        
        teacher_id = st.session_state.get('user_name')  # Use user_name which contains the email
        all_teacher_students = get_all_students_by_teacher(teacher_id)
        
        # Build dropdown options
        existing_students = []
        for s in all_teacher_students:
            existing_students.append({
                "label": s["name"],
                "id": s["student_id"],
                "pseudonym": s["pseudonym"] or f"Student_{len(existing_students) + 1:02d}"
            })
        
        existing_names = [s["label"] for s in existing_students]
        selection = st.selectbox(" Load Student Profile", options=["None / New Student"] + existing_names)
        
        # Initialize session state for new student
        if "pending_student_name" not in st.session_state:
            st.session_state.pending_student_name = ""
        if "pending_student_id" not in st.session_state:
            st.session_state.pending_student_id = None
        if "pending_pseudonym" not in st.session_state:
            st.session_state.pending_pseudonym = None
        
        student_id = None
        pseudonym = None
        student_name = None
        
        if selection != "None / New Student":
            # Loading existing student from dropdown
            student_name = selection
            for s in existing_students:
                if s["label"] == selection:
                    student_id = s["id"]
                    pseudonym = s["pseudonym"]
                    break
            # Clear pending new student
            st.session_state.pending_student_name = ""
            st.session_state.pending_student_id = None
            st.session_state.pending_pseudonym = None
        else:
            # New student: type name and click Create
            st.text_input("Student Name", key="new_student_name_input", placeholder="Type student name here...")
            
            if st.button(" Create Student", type="primary"):
                typed_name = st.session_state.get("new_student_name_input", "").strip()
                if typed_name:
                    st.session_state.pending_student_name = typed_name
                    st.session_state.pending_student_id = get_or_create_student_id(teacher_id, typed_name)
                    st.session_state.pending_pseudonym = get_pseudonym(teacher_id, st.session_state.pending_student_id)
                    st.success(f"Created: {typed_name}")
                else:
                    st.error("Please enter a student name.")
            
            # Use pending student if created
            if st.session_state.pending_student_name:
                student_name = st.session_state.pending_student_name
                student_id = st.session_state.pending_student_id
                pseudonym = st.session_state.pending_pseudonym
                st.info(f"Selected: {student_name}")
        
        # Store in session state
        if student_id:
            st.session_state.current_student_id = student_id
            st.session_state.current_student_name = student_name
            st.session_state.current_pseudonym = pseudonym or generate_pseudonym(teacher_id, student_id)
        
        # Load student data when switching students
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
        
        st.caption(" Privacy: Student data is anonymized for AI processing.")
        
        # Target Group
        st.write("Target Group")
        target_group_input = st.selectbox(
            "Select student's current G-level",
            options=[f"g{i}" for i in range(9)],
            key="target_group_input"
        )
        
        st.divider()
        
        # Struggling Words
        st.write("Experienced Errors (Long-term Struggles)")
        struggling_words_input = st.text_area(
            "Enter words student has struggled with ('Correct:Attempt')",
            height=100,
            placeholder="e.g., ship:sip, sled:sed (comma-separated)",
            key="struggling_words_input"
        )
        
        st.divider()
        
        # Mastered Words
        st.write("Mastered Words (Spelled Correctly)")
        mastered_words_input = st.text_area(
            "Enter words the student consistently spells correctly",
            placeholder="e.g., cat, bed, sit, run",
            key="mastered_words_input"
        )
        
        st.divider()
        
        # Teacher Observations (for this specific session)
        st.write("Teacher Observations/Context")
        st.caption("Add notes about this student or session for future reference.")
        teacher_observations_input = st.text_area(
            "Session context, behaviors, environmental factors...",
            height=80,
            placeholder="e.g., 'Was tired today', 'Good progress on G2 digraphs', 'Needs visual aids'",
            key="teacher_observations_input"
        )
        
        # Save Student Data
        if st.button(" Save Student Data"):
            if student_name:
                st.session_state.students[student_id] = {
                    "struggles": struggling_words_input,
                    "mastered": mastered_words_input,
                    "target_group": target_group_input
                }
                save_profile(student_id, struggling_words_input, mastered_words_input, target_group_input)
                st.success(f"Saved data for {student_name}!")
                st.rerun()
            else:
                st.error("Please enter a student name first.")
        
        st.divider()
        
        # Spelling Journey History
        if student_id:
            with st.expander(" Spelling Journey (History)"):
                is_admin = teacher_id == ADMIN_EMAIL
                history = get_student_history(student_id, teacher_id=teacher_id, admin=is_admin)
                
                if history:
                    st.caption(f"Showing {len(history)} recorded sessions for {student_name}")
                    
                    history_data = []
                    for row in history:
                        test_date = row[3] if row[3] else row[4][:10]
                        g_scores = [row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12], row[13]]
                        g_names = ["g0", "g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8"]
                        dominant_g = "-"
                        for i, score in enumerate(g_scores):
                            if score is not None and score > 0:
                                dominant_g = g_names[i]
                                break
                        
                        struggling = row[17] if row[17] else ""
                        mastered = ""
                        if all(s == 100 or s is None for s in g_scores):
                            mastered = " 100% All Groups"
                        
                        history_data.append({
                            "Date": test_date[:10] if test_date else row[4][:10],
                            "G-Level": dominant_g.upper(),
                            "Struggling": struggling[:50] + "..." if len(struggling) > 50 else struggling,
                            "Mastered": mastered
                        })
                    
                    history_df = pd.DataFrame(history_data)
                    st.dataframe(history_df, width="stretch", hide_index=True)
                    
                    with st.expander(" View Full Session Details"):
                        for i, row in enumerate(history):
                            st.markdown(f"**Session {i+1}** - {row[4][:16] if row[4] else 'Unknown'}")
                            cols_detail = st.columns(3)
                            cols_detail[0].metric("g0 Phonemic", f"{row[5] if row[5] else 0}%")
                            cols_detail[1].metric("g1 CVC", f"{row[6] if row[6] else 0}%")
                            cols_detail[2].metric("g2 Digraphs", f"{row[7] if row[7] else 0}%")
                            st.divider()
                else:
                    st.info(f"No history found for {student_name}.")
        
        st.divider()
        
        # Word Bank Tools
        st.write("Word Bank Tools")
        
        # AI Generate Practice Lists
        if st.button(" AI-Generate Personalized Practice Lists"):
            with st.spinner("Generating personalized practice lists with AI..."):
                teaching_groups = generate_class_groups()
                word_banks_path = "word_banks"
                student_slips = []
                
                title_to_key = {
                    "Group 0: Phonemic Awareness": "g0", "Group 1: Basic CVC Mapping": "g1",
                    "Group 2: Digraphs": "g2", "Group 3: Silent E": "g3",
                    "Group 4: Vowel Teams": "g4", "Group 5: R-Controlled": "g5",
                    "Group 6: Clusters/Blends": "g6", "Group 7: Multisyllabic": "g7",
                    "Group 8: Reduction & Morphology": "g8"
                }
                
                for group_title, students in teaching_groups.items():
                    g_key = title_to_key.get(group_title)
                    if not g_key:
                        continue
                    
                    file_path = os.path.join(word_banks_path, f"{g_key}.txt")
                    base_words = []
                    if os.path.exists(file_path):
                        with open(file_path, "r") as f:
                            base_words = [line.strip() for line in f.readlines() if line.strip()]
                    
                    for sid in students:
                        display_name = get_name_for_id(teacher_id, sid)
                        teacher_notes = get_latest_teacher_notes(sid)
                        db_struggling_words = get_struggling_words(sid)
                        custom_input = st.session_state.get("struggling_words_input", "")
                        combined_struggling = custom_input if custom_input.strip() else db_struggling_words
                        
                        try:
                            personalized_words = generate_personalized_practice_words(
                                student_id=sid, target_group=g_key, teacher_notes=teacher_notes,
                                struggling_words=combined_struggling,
                                mastered_words=st.session_state.get("mastered_words_input", ""),
                                unit_description=st.session_state.unit_description,
                                custom_words_input=custom_input if custom_input.strip() else None
                            )
                        except Exception as e:
                            st.warning(f"AI generation failed for {display_name}, using fallback: {e}")
                            personalized_words = random.sample(base_words, min(10, len(base_words))) if base_words else ["word" + str(i) for i in range(1, 11)]
                        
                        student_slips.append({
                            "student_name": display_name, "group_title": group_title,
                            "words": personalized_words
                        })
                
                st.session_state.practice_lists = student_slips
                st.rerun()
        
        # Generate Diagnostic Test
        if st.button(" Generate New 20-Word Diagnostic Test"):
            with st.spinner("Creating diagnostic test..."):
                word_banks_path = "word_banks"
                test_words = []
                
                # 5 words from g1/g2
                g1_words, g2_words = [], []
                if os.path.exists(os.path.join(word_banks_path, "g1.txt")):
                    with open(os.path.join(word_banks_path, "g1.txt"), "r") as f:
                        g1_words = [l.strip() for l in f if l.strip()]
                if os.path.exists(os.path.join(word_banks_path, "g2.txt")):
                    with open(os.path.join(word_banks_path, "g2.txt"), "r") as f:
                        g2_words = [l.strip() for l in f if l.strip()]
                test_words.extend(random.sample(g1_words + g2_words, min(5, len(g1_words + g2_words))))
                
                # 5 words from g3/g4
                g3_words, g4_words = [], []
                if os.path.exists(os.path.join(word_banks_path, "g3.txt")):
                    with open(os.path.join(word_banks_path, "g3.txt"), "r") as f:
                        g3_words = [l.strip() for l in f if l.strip()]
                if os.path.exists(os.path.join(word_banks_path, "g4.txt")):
                    with open(os.path.join(word_banks_path, "g4.txt"), "r") as f:
                        g4_words = [l.strip() for l in f if l.strip()]
                test_words.extend(random.sample(g3_words + g4_words, min(5, len(g3_words + g4_words))))
                
                # 5 words from g5/g6
                g5_words, g6_words = [], []
                if os.path.exists(os.path.join(word_banks_path, "g5.txt")):
                    with open(os.path.join(word_banks_path, "g5.txt"), "r") as f:
                        g5_words = [l.strip() for l in f if l.strip()]
                if os.path.exists(os.path.join(word_banks_path, "g6.txt")):
                    with open(os.path.join(word_banks_path, "g6.txt"), "r") as f:
                        g6_words = [l.strip() for l in f if l.strip()]
                test_words.extend(random.sample(g5_words + g6_words, min(5, len(g5_words + g6_words))))
                
                # 5 words from g7/g8
                g7_words, g8_words = [], []
                if os.path.exists(os.path.join(word_banks_path, "g7.txt")):
                    with open(os.path.join(word_banks_path, "g7.txt"), "r") as f:
                        g7_words = [l.strip() for l in f if l.strip()]
                if os.path.exists(os.path.join(word_banks_path, "g8.txt")):
                    with open(os.path.join(word_banks_path, "g8.txt"), "r") as f:
                        g8_words = [l.strip() for l in f if l.strip()]
                test_words.extend(random.sample(g7_words + g8_words, min(5, len(g7_words + g8_words))))
                
                assessments_folder = "assessments"
                if not os.path.exists(assessments_folder):
                    os.makedirs(assessments_folder)
                
                date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                file_name = f"dynamic_test_{date_str}.txt"
                with open(os.path.join(assessments_folder, file_name), "w") as f:
                    for word in test_words:
                        f.write(word + "\n")
                
                st.session_state.diagnostic_test = {"words": test_words, "file_name": file_name}
                st.rerun()
        
        # G-Group Legend
        with st.expander(" Diagnostic Group Description"):
            st.caption("G0 Phonemic Awareness | G1 Basic CVC Mapping | G2 Digraphs")
            st.caption("G3 Silent E | G4 Vowel Teams | G5 R-Controlled")
            st.caption("G6 Clusters (Blends) | G7 Multisyllabic | G8 Reduction & Morphology")
        
        st.divider()
        
        # Class Settings
        st.header(" Class Settings")
        current_unit_desc = get_teacher_settings(st.session_state.email)
        
        if not current_unit_desc:
            st.warning(" Please enter your Unit Description")
        
        unit_desc = st.text_area(
            " Global Unit Description", 
            value=current_unit_desc,
            placeholder="e.g., This unit focuses on long-a vowel teams and silent-e.",
            key="unit_description_input"
        )
        
        if unit_desc != current_unit_desc:
            save_teacher_settings(st.session_state.email, unit_desc)
            st.session_state.unit_description = unit_desc
            st.toast("Unit description saved!")
        
        st.divider()
        
        # Reset button
        if st.button(" Start New Student"):
            st.session_state.raw_transcription = ""
            st.session_state.analysis_result = None
            st.session_state.practice_lists = None
            st.session_state.diagnostic_test = None
            st.session_state.struggling_words = ""
            st.rerun()
    
    # ---- MAIN AREA: Photo Upload & Assessment ----
    student_id = st.session_state.get('current_student_id')
    student_name = st.session_state.get('current_student_name', 'Student')
    
    # Test Template Selector
    st.subheader("Select Test Template")
    templates = get_all_test_templates()
    template_options = {t['test_name']: t for t in templates}
    
    if 'selected_test_template' not in st.session_state:
        st.session_state.selected_test_template = templates[0]['test_name'] if templates else None
    
    selected_template_name = st.selectbox(
        "Choose a diagnostic test:",
        options=list(template_options.keys()),
        key="test_template_selector"
    )
    
    if selected_template_name:
        st.session_state.selected_test_template = selected_template_name
        selected_template = template_options[selected_template_name]
        word_count = len(selected_template['intended_words'].split(','))
        st.caption(f"Selected: {word_count} words | ID: {selected_template['test_id']}")
    
    st.divider()
    
    uploaded_file = st.file_uploader(" Step 1: Upload Test Photo", type=["jpg", "jpeg", "png"])

    # Pre-process & Layout
    if uploaded_file:
        clean_base64, clean_img = preprocess_image(uploaded_file)
        
        col_img, col_text = st.columns([1, 1])
        
        with col_img:
            st.subheader(" AI's View (Cleaned)")
            st.image(clean_img, width="stretch")
            if st.button(" Step 2: Read Handwriting"):
                with st.spinner("AI is reading..."):
                    st.session_state.raw_transcription = transcribe_handwriting(clean_base64)
                    st.rerun()

        with col_text:
            st.subheader(" Step 3: Verify & Edit")
            edited_text = st.text_area(
                "Verify & Edit Transcription", 
                value=st.session_state.get("raw_transcription", ""),
                height=400
            )

        # Run Analysis and Save Draft buttons
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button(" Step 4: Run Analysis"):
                if not student_name:
                    st.warning(" Please select or enter a Student Name in the sidebar!")
                elif not edited_text:
                    st.warning(" Please upload and transcribe a photo first!")
                else:
                    with st.spinner("Running AI analysis..."):
                        # Get the intended words from the selected template
                        if selected_template:
                            intended_words = selected_template['intended_words']
                        else:
                            intended_words = "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine"
                        
                        # Get the teacher observations
                        teacher_observations = st.session_state.get("teacher_observations_input", "")
                        
                        result = run_scoring_crew(student_id, edited_text, intended_words=intended_words)
                        g_scores = result["g_scores"]
                        targets = result["targets"]
                        notes = result["notes"]
                        
                        # Store results in session state
                        st.session_state.analysis_result = {
                            "g_scores": g_scores,
                            "targets": targets,
                            "notes": notes
                        }
                        
                        # Update student profile with struggling words
                        if g_scores:
                            struggling_words = st.session_state.get("struggling_words_input", "")
                            if struggling_words:
                                st.session_state.students[student_id] = {
                                    "struggles": struggling_words,
                                    "mastered": st.session_state.students.get(student_id, {}).get("mastered", ""),
                                    "target_group": st.session_state.students.get(student_id, {}).get("target_group", "g1")
                                }
                                save_profile(student_id, struggling_words, 
                                          st.session_state.students.get(student_id, {}).get("mastered", ""),
                                          st.session_state.students.get(student_id, {}).get("target_group", "g1"))
                        
                        st.success(" Analysis complete! Review and confirm below.")
                        st.rerun()
        
        with col2:
            if st.button("💾 Save Draft"):
                if not student_name:
                    st.warning(" Please select or enter a Student Name in the sidebar!")
                elif not edited_text:
                    st.warning(" Please upload and transcribe a photo first!")
                else:
                    # Get the intended words from the selected template
                    if selected_template:
                        intended_words = selected_template['intended_words']
                    else:
                        intended_words = "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine"
                    
                    # Save draft assessment
                    teacher_id = st.session_state.get('user_name')
                    teacher_observations = st.session_state.get("teacher_observations_input", "")
                    struggling_words = st.session_state.get("struggling_words_input", "")
                    
                    save_draft_assessment(
                        teacher_id, student_id, student_name, intended_words, 
                        edited_text, teacher_observations, struggling_words
                    )
                    
                    st.success(" Draft saved! You can complete it later.")
                    st.info("💡 Tip: Your draft will appear at the top of this page next time you visit.")

        # Display analysis results if available
        if st.session_state.get("analysis_result"):
            g_scores = st.session_state.analysis_result["g_scores"]
            targets = st.session_state.analysis_result["targets"]
            notes = st.session_state.analysis_result["notes"]
            
            # Display scores
            cols = st.columns(3)
            cols[0].metric("g0: Phonemic", f"{g_scores['g0']}%")
            cols[1].metric("g1: CVC", f"{g_scores['g1']}%")
            cols[2].metric("g2: Digraphs", f"{g_scores['g2']}%")
                found_groups = re.findall(r'g[0-8]', raw_text)
                targets = list(dict.fromkeys(found_groups))

        # Display scores
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

        # Instructional Targets
        st.subheader(" Instructional Targets")
        
        GROUP_NAME_MAP = {
            "g0": "G0 Phonemic Awareness", "g1": "G1 Basic CVC Mapping",
            "g2": "G2 Digraphs", "g3": "G3 Silent E", "g4": "G4 Vowel Teams",
            "g5": "G5 R-Controlled", "g6": "G6 Clusters (Blends)",
            "g7": "G7 Multisyllabic", "g8": "G8 Reduction & Morphology"
        }
        
        selected_targets = []
        for g_key, pretty_name in GROUP_NAME_MAP.items():
            is_checked = g_key in targets
            if st.checkbox(pretty_name, value=is_checked, key=f"target_{g_key}"):
                selected_targets.append(g_key)
        
        targets = selected_targets
                
        # Teacher Refinement
        st.write("### Teacher Refinement")
        st.caption("Review the AI's notes above. Verify and record your final diagnostic decision.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            edited_text = st.text_area(
                "Student's Spelling Attempts", 
                value=st.session_state.get('edited_transcription', st.session_state.raw_transcription),
                height=400,
                key="edited_text_final"
            )
        
        with col2:
            default_text_area_val = notes if notes != "No notes generated." else "Type your own diagnostic notes here..."
            final_notes = st.text_area(
                "Final Diagnostic Notes (The 'Gold Standard')", 
                value=default_text_area_val, 
                height=400
            )

        # Save Button
        if st.button(" Confirm & Save to Student History"):
            cleaned_targets = targets

            class SaveObject:
                pass
            save_obj = SaveObject()
            save_obj.student_id = student_id
            save_obj.real_name = student_name  # Pass real name for proper linking
            save_obj.suggested_next_groups = cleaned_targets
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

            struggling_words = st.session_state.get("struggling_words_input", "")
            teacher_observations = st.session_state.get("teacher_observations_input", "")
            current_teacher_id = st.session_state.get("user_name")  # Use user_name which contains the email
            
            # Get test template info
            test_template = selected_template.get('test_id') if selected_template else None
            
            save_assessment(save_obj, edited_text, teacher_refinement=final_notes, 
                        struggling_words=struggling_words, teacher_id=current_teacher_id,
                        teacher_observations=teacher_observations, test_template=test_template)
            
            st.success(f" Final assessment for {student_name} has been saved!")
            st.rerun()

# =============================================================================
# COMPONENT: ADMIN PAGE (Factory Reset & Student Allocation)
# =============================================================================
def display_admin_page():
    """Display the Admin dashboard with factory reset and student allocation tools."""
    ADMIN_EMAIL = "komododundee@gmail.com"
    
    if st.session_state.get('email', '').lower().strip() != ADMIN_EMAIL.lower().strip():
        st.error(" Admin access required.")
        return
    
    st.header("Admin Dashboard")
    
    # CSV Status & Force Import
    with st.expander(" CSV Data Management"):
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
        st.warning(" This will import ALL data from CSV files as orphaned (teacher_id = NULL)")
        
        if st.button(" FORCE IMPORT FROM CSV", type="primary", width="stretch"):
            with st.spinner("Importing data..."):
                result = import_from_csv()
                sync_result = sync_identity_from_assessments()
                st.success(f" Import Complete!")
                st.write(f"   • Students imported: {result['students']}")
                st.write(f"   • Assessments imported: {result['assessments']}")
                st.write(f"   • Identity records synced: {sync_result['created']}")
                if result['students'] > 0 or result['assessments'] > 0:
                    st.info(" Imported records are marked as ORPHANED.")
                else:
                    st.info("No new records were imported.")
            st.rerun()
    
    st.markdown("---")
    
    # Database Maintenance
    with st.expander(" Database Maintenance"):
        st.subheader(" Maintenance Tools")
        
        stats = get_database_stats()
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.metric("Total Assessments", stats.get('total_assessments', 0))
            st.metric("Total Students", stats.get('total_students', 0))
        with col_s2:
            st.metric("Orphaned Students", stats.get('orphaned_students', 0))
            st.metric("Orphaned Assessments", stats.get('orphaned_assessments', 0))
        
        st.markdown("---")
        
        col_fix1, col_fix2 = st.columns([2, 1])
        with col_fix1:
            st.write("**Fix Teacher ID Consistency**")
            st.caption("Updates ALL assessment rows to match student_identity table")
        with col_fix2:
            if st.button(" Fix All Teacher IDs", width="stretch"):
                result = fix_all_teacher_ids()
                st.success(f" Fixed! Synced {result['students_synced']} students.")
                st.rerun()
    
    st.markdown("---")
    
    # FACTORY RESET
    with st.expander(" FACTORY RESET (Big Red Button)", expanded=False):
        st.error(" This will DELETE ALL assessments and student records. Teacher accounts will be PRESERVED.")
        
        if "confirm_factory_reset" not in st.session_state:
            st.session_state.confirm_factory_reset = False
        
        if not st.session_state.confirm_factory_reset:
            if st.button(" FACTORY RESET", type="primary", width="stretch"):
                st.session_state.confirm_factory_reset = True
                st.rerun()
        else:
            st.warning(" Are you absolutely sure? This cannot be undone!")
            col_reset1, col_reset2 = st.columns(2)
            with col_reset1:
                if st.button(" YES, RESET EVERYTHING", type="primary", width="stretch"):
                    result = clear_all_data()
                    st.success(f" Factory Reset Complete!")
                    st.write(f"   • Assessments deleted: {result['assessments_deleted']}")
                    st.write(f"   • Student identities deleted: {result['identity_deleted']}")
                    st.write(f"   • Teacher accounts: PRESERVED")
                    st.session_state.confirm_factory_reset = False
                    st.rerun()
            with col_reset2:
                if st.button(" Cancel", width="stretch"):
                    st.session_state.confirm_factory_reset = False
                    st.rerun()
    
    st.markdown("---")
    
    # Student Allocation
    with st.expander(" Manage Student Allocations", expanded=False):
        st.subheader("Assign Students to Teachers")
        st.caption("Reassign students to different teachers.")
        
        all_students = get_all_students_for_allocation()
        all_teachers_list = get_all_teachers()
        
        if not all_students:
            st.info("No students found in database.")
        else:
            st.write(f"{len(all_students)} students total")
            st.markdown("---")
            
            for i, student in enumerate(all_students):
                with st.container():
                    col_name, col_teacher, col_btn = st.columns([2, 2, 1])
                    
                    with col_name:
                        st.markdown(f"**{student['name']}**")
                        st.caption(f"ID: {student['student_id'][:16]}... | Alias: {student['pseudonym']}")
                    
                    with col_teacher:
                        # Build dropdown with "Name (email)" format
                        teacher_display_options = ["Unassigned"]
                        teacher_emails = [None]  # None for Unassigned
                        
                        for t in all_teachers_list:
                            teacher_display_options.append(f"{t['name']} ({t['email']})")
                            teacher_emails.append(t['email'])
                        
                        # Find current selection index
                        current_idx = 0
                        if student['current_teacher'] and student['current_teacher'] != "Unassigned":
                            try:
                                current_idx = teacher_emails.index(student['current_teacher'])
                            except ValueError:
                                current_idx = 0
                        
                        selected_display = st.selectbox(
                            f"Assign {student['name']} to:",
                            options=teacher_display_options,
                            index=current_idx,
                            key=f"teacher_select_{i}_{student['student_id']}",
                            label_visibility="collapsed"
                        )
                    
                    with col_btn:
                        if st.button("Update", key=f"update_btn_{i}_{student['student_id']}", width="stretch"):
                            # Extract email from selection
                            if selected_display == "Unassigned":
                                new_teacher = None
                            else:
                                new_teacher = selected_display.split('(')[-1].replace(')', '')
                            
                            result = update_student_teacher(student['student_id'], new_teacher)
                            if result['assessments_updated'] > 0:
                                st.success(f"Updated!")
                            else:
                                st.info(f"No changes needed.")
                            st.rerun()
    
    st.markdown("---")
    
    # Test Templates Management
    with st.expander(" Manage Test Templates", expanded=False):
        st.subheader("Test Library")
        st.caption("Create and manage diagnostic test templates.")
        
        from database_manager import get_all_test_templates, save_test_template, delete_test_template
        
        # Form to add/edit test template
        with st.form("test_template_form", clear_on_submit=True):
            col1, col2 = st.columns([1, 3])
            with col1:
                test_id_input = st.text_input("Test ID", placeholder="e.g., g2_digraphs_v1", help="Unique identifier for this test")
            with col2:
                test_name_input = st.text_input("Test Name", placeholder="e.g., G2 Digraphs Assessment")
            
            intended_words_input = st.text_area(
                "Intended Words (comma-separated)",
                height=100,
                placeholder="e.g., ship, shed, fish, dish, rush, mash, wish, cash, flash"
            )
            
            col_btn1, col_btn2 = st.columns([1, 4])
            with col_btn1:
                submitted = st.form_submit_button("Save Template", type="primary")
            
            if submitted:
                if test_name_input and intended_words_input:
                    save_test_template(test_name_input.strip(), intended_words_input.strip())
                    st.success(f"Saved template: {test_name_input}")
                    st.rerun()
                else:
                    st.error("Please fill in Test Name and Intended Words.")
        
        st.markdown("---")
        st.subheader("Available Templates")
        
        templates = get_all_test_templates()
        if templates:
            for i, t in enumerate(templates):
                with st.container():
                    col1, col2, col3 = st.columns([3, 3, 1])
                    with col1:
                        st.markdown(f"**{t['test_name']}**")
                        st.caption(f"ID: {t.get('id', 'N/A')} | {len(t['intended_words'].split(','))} words")
                    with col2:
                        words_preview = ', '.join(t['intended_words'].split(',')[:5])
                        if len(t['intended_words'].split(',')) > 5:
                            words_preview += '...'
                        st.caption(words_preview)
                    with col3:
                        if t.get('id') != 1:  # Don't allow deleting the first/default template
                            if st.button("Delete", key=f"del_template_{t.get('id', i)}"):
                                success = delete_test_template(t.get('id'))
                                if success:
                                    st.success("Template deleted")
                                else:
                                    st.error("Failed to delete template")
                                st.rerun()
                        else:
                            st.caption("Default")
        else:
            st.info("No test templates found.")
    
    st.markdown("---")
    
    # School-Wide Research Dashboard
    st.subheader("School-Wide Research Dashboard")
    
    sync_result = sync_identity_from_assessments()
    
    stats = get_database_stats()
    col_s1, col_s2, col_s3 = st.columns(3)
    col_s1.metric("Total Assessments", stats.get('total_assessments', 0))
    col_s2.metric("Unique Students", stats.get('unique_students_in_assessments', 0))
    col_s3.metric("Teachers", stats.get('total_teachers', 0))
    
    st.markdown("---")
    
    # Complete Student Table
    st.subheader("All Students in Database")
    
    all_students = get_all_students_with_status()
    
    if not all_students:
        st.info("No students found. Import legacy CSV data or save new assessments.")
    else:
        from database_manager import get_teacher_name
        
        table_data = []
        for s in all_students:
            teacher_display = s["teacher"]
            if s["teacher"] and s["teacher"] != "Unassigned":
                # Show teacher's name instead of email
                teacher_display = get_teacher_name(s["teacher"])
            
            table_data.append({
                "Name": s["name"],
                "Last Assessment": s["last_date"][:10] if s["last_date"] else "Never",
                "Total Attempts": s["total_attempts"],
                "Teacher": teacher_display,
            })
        
        table_df = pd.DataFrame(table_data)
        st.dataframe(table_df, width="stretch", hide_index=True)
        st.caption(f"Showing {len(all_students)} students")
        
        # Quick Assign Section
        st.markdown("### Quick Assign Students")
        orphans = [s for s in all_students if s["teacher"] == "Unassigned"]
        
        if orphans:
            st.warning(f"{len(orphans)} students need assignment")
            
            all_teachers_for_assign = get_all_teachers()
            if all_teachers_for_assign:
                # Show teacher names in dropdown
                teacher_options = [{"email": t["email"], "name": t["name"]} for t in all_teachers_for_assign]
                teacher_display_options = [f"{t['name']} ({t['email']})" for t in teacher_options]
                
                col_bulk, col_btn = st.columns([3, 1])
                with col_bulk:
                    selected_display = st.selectbox("Assign unassigned students to:", options=["Select..."] + teacher_display_options, key="bulk_admin_assign")
                with col_btn:
                    st.write("")
                    if selected_display != "Select..." and st.button("Assign All", type="primary", width="stretch"):
                        # Extract email from selection
                        selected_email = selected_display.split('(')[-1].replace(')', '')
                        orphan_ids = [s["student_id"] for s in orphans]
                        result = bulk_assign_students(orphan_ids, selected_email)
                        st.success(f"Assigned {result['students_assigned']} students to {selected_display}")
                        st.rerun()
        else:
            st.success("All students are assigned to a teacher.")

# =============================================================================
# RUN THE APP
# =============================================================================
if __name__ == "__main__":
    main()
