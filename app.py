import streamlit as st
import json
import os
os.environ["OTEL_SDK_DISABLED"] = "true"
import pandas as pd
import random
import csv
import time
import base64
import database_manager as db
import datetime
import feature_evaluator
import spelling_logic
from constants import DIAGNOSTIC_GROUPS, DEFAULT_TEST_WORDS, PSI_WORD_BANK
from utils import preprocess_image, clean_ai_formatting
from spelling_logic import (
    get_ai_discrepancy_feedback,
    transcribe_handwriting,
    generate_personalized_practice_words,
    process_assessment_response
)

try:
    from feature_evaluator import evaluate_spelling_attempt
except ImportError:
    evaluate_spelling_attempt = None

from database_manager import (
    init_db, get_teacher_settings, import_from_csv, get_student_history,
    get_database_stats, fix_all_teacher_ids, clear_all_data, sync_identity_from_assessments,
    get_all_students_by_teacher, get_all_students_for_allocation,
    update_student_teacher, register_teacher, get_all_teachers,
    get_latest_teacher_notes, get_struggling_words,
    get_student_id_by_name, save_student_identity, get_student_name, get_name_for_id,
    save_named_list, get_named_lists, get_named_list_by_id, init_correction_tables,
    get_student_current_group_focus, update_student_current_group_focus,
    delete_assessment, add_student, get_sheet_data,
    save_student_practice_list, get_student_practice_lists, delete_student_practice_list,
    delete_student, save_diagnostic_assessment, get_diagnostic_assessments
)
import constants
from ai_learning_engine import ingest_teacher_calibration

# Initialize correction tables on boot
# Initialize SQLite schema if missing
init_db()
init_correction_tables()

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
    """Scan students.csv for real names instead of IDs. Migrate them into SQL table."""
    if not os.path.exists(PROFILES_CSV):
        return

    updated = False
    profiles_data = []
    teacher_id = st.session_state.get("user_name", "admin@example.com")

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
                        "Struggles": row.get("Struggles", ""),
                        "Mastered Words": row.get("Mastered Words", ""),
                        "Target_Group": row.get("Target_Group", "g1")
                    }
                    writer.writerow(updated_row)
            st.toast("Legacy student profiles migrated to Cloud-hosted Map.")

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
                    teacher_id = row.get("teacher_id", st.session_state.get("user_email"))
                    if sid:
                        profiles[sid] = {
                            "struggles": row.get("Struggles", ""),
                            "mastered": row.get("Mastered Words", ""),
                            "target_group": row.get("Target_Group", "g1"),
                            "teacher_id": teacher_id
                        }
        except Exception as e:
            st.error(f"Error loading profiles: {e}")
    return profiles

def save_profile(student_id, struggles, mastered, target_group):
    """Save/Update a student profile in the CSV."""
    profiles = load_profiles()
    profiles[student_id] = {"struggles": struggles, "mastered": mastered, "target_group": target_group, "teacher_id": st.session_state.get("user_email")}

    try:
        with open(PROFILES_CSV, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=["Student ID", "Struggles", "Mastered Words", "Target_Group", "teacher_id"])
            writer.writeheader()
            for sid, data in profiles.items():
                writer.writerow({
                    "Student ID": sid,
                    "Struggles": data["struggles"],
                    "Mastered Words": data["mastered"],
                    "Target_Group": data["target_group"],
                    "teacher_id": data["teacher_id"]
                })
    except Exception as e:
        st.error(f"Error saving profile: {e}")

# =============================================================================
# INITIALIZE SESSION STATE
# =============================================================================
def initialize_session_state():
    """Initialize session state variables and database."""
    init_db()

    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if 'role' not in st.session_state:
        st.session_state.role = None

    if "user_email" not in st.session_state:
        st.session_state.user_email = None

    defaults = [
        ("raw_transcription", ""), ("evaluator_result", None), ("analysis_result", None),
        ("practice_lists", None), ("diagnostic_test", None), ("struggling_words", ""),
        ("students", load_profiles()), ("student_attempts_for_report", ""),
        ("classroom_data", None), ("selected_student", None), ("is_admin", False),
        ("logged_in", False), ("intended_words_input", ""), ("processed_intended_words", ""),
        ("current_word_list_mode", "select_existing"), ("last_used_assessment_list_id", None)
    ]
    for key, default in defaults:
        if key not in st.session_state:
            st.session_state[key] = default

    if "unit_description" not in st.session_state:
        st.session_state.unit_description = load_settings().get("unit_description", "")

# =============================================================================
# MAIN ROUTER
# =============================================================================
def main():
    if 'next_page' in st.session_state:
        st.session_state.navigation_menu = st.session_state.next_page
        del st.session_state.next_page

    initialize_session_state()

    if 'navigation_menu' not in st.session_state:
        st.session_state.navigation_menu = 'Class'

    if st.session_state.get('login_button'):
        selection = st.session_state.get('login_teacher_select')
        if selection:
            if '(' in selection:
                name = selection.split(' (')[0].strip()
                email = selection.split('(')[-1].replace(')', '').strip()
            else:
                name = selection.strip()
                email = selection.strip()

            st.session_state.logged_in = True
            st.session_state.user_email = email
            st.session_state.user_name = name
            st.session_state.authenticated = True

            if email == ADMIN_EMAIL:
                st.session_state.is_admin = True

            st.rerun()

    if st.query_params.get("email"):
        st.session_state.logged_in = True
        st.session_state.user_email = st.query_params.get("email")

    if st.session_state.get('logged_in'):
        show_teacher_dashboard()
    elif st.session_state.get('go_to_login'):
        show_login_page()
    else:
        show_registration_page()

# =============================================================================
# PAGE: REGISTRATION & LOGIN
# =============================================================================
def show_registration_page():
    st.image("logo.svg", width=200)
    st.title("Welcome to UnBoxEd Spelling Coach")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Returning Coach")
        st.info("Already have an account? Click below to select your profile and log in.")
        if st.button("Go to Login Page →", use_container_width=True):
            st.session_state.go_to_login = True
            st.rerun()

    with col2:
        st.subheader("New Coach")
        with st.form("registration_form", clear_on_submit=True):
            new_name = st.text_input("Full Name")
            new_email = st.text_input("Email Address")
            submit_button = st.form_submit_button("Register & Log In")

            if submit_button:
                if new_name and new_email:
                    register_teacher(new_email, new_name)
                    st.session_state.authenticated = True
                    st.session_state.user_email = new_email
                    st.session_state.logged_in = True
                    st.session_state.role = 'teacher'
                    st.query_params["email"] = new_email
                    st.rerun()
                else:
                    st.error("Please provide both name and email.")

def show_login_page():
    st.image("logo.svg", width=200)
    st.title("Teacher Login")
    existing_teachers = get_all_teachers()

    if existing_teachers:
        teacher_options = []
        for t in existing_teachers:
            name = t['name'] if (t['name'] and t['name'].strip()) else t['email'].split('@')[0]
            teacher_options.append(f"{name} ({t['email']})")

        selected_teacher = st.selectbox("Select your account:", teacher_options, key='login_teacher_select')

        if st.button("Login", key="login_button"):
            if '(' in selected_teacher and ')' in selected_teacher:
                email = selected_teacher.split('(')[-1].replace(')', '')
                name = selected_teacher.split(' (')[0]
            else:
                email = selected_teacher
                name = selected_teacher.split('@')[0] if '@' in selected_teacher else selected_teacher

            st.session_state.authenticated = True
            st.session_state.user_name = name
            st.session_state.user_email = email
            st.session_state.logged_in = True
            st.session_state.role = 'teacher'

            if 'reg_teacher_select' in st.session_state:
                del st.session_state['reg_teacher_select']

            st.query_params["email"] = email
            st.query_params["login"] = email
            st.rerun()
    else:
        st.info("No accounts found. Please register first.")

    if st.button("← Back to Registration", key="back_to_reg"):
        if 'reg_teacher_select' in st.session_state:
            del st.session_state['reg_teacher_select']
        st.rerun()

# =============================================================================
# PAGE: TEACHER DASHBOARD & ROUTER
# =============================================================================
def show_teacher_dashboard():
    st.sidebar.image("logo.svg", width=200)
    st.sidebar.success(f"👤 Logged in: {st.session_state.user_name}")

    if st.sidebar.button("Log Out", key="logout_button"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    page_options = ["Class", "Student", "Admin"]
    if 'navigation_menu' in st.session_state:
        page = st.sidebar.radio("Navigation", page_options, key="navigation_menu")
    else:
        page = st.sidebar.radio("Navigation", page_options, index=0, key="navigation_menu")

    migrate_legacy_profiles()
    current_teacher_email = st.session_state.get('user_email')

    student_id = None
    if page == "Student":
        all_students = get_all_students_by_teacher(current_teacher_email)
        student_options = {s['name']: s['student_id'] for s in all_students}

        if student_options:
            current_names = list(student_options.keys())
            start_index = 0

            if st.session_state.get('student_id'):
                try:
                    selected_sid = st.session_state.get('student_id')
                    selected_name = get_student_name(current_teacher_email, selected_sid)
                    if selected_name in current_names:
                        start_index = current_names.index(selected_name)
                except Exception:
                    start_index = 0

            selected_name = st.sidebar.selectbox("Select Student", options=current_names, index=start_index, key="sidebar_student_selector")
            newly_student_id = student_options[selected_name]

            if st.session_state.get('current_student_id') != newly_student_id:
                st.session_state.current_student_id = newly_student_id
                st.session_state.current_student_name = selected_name

                keys_to_clear = [
                    'uploaded_file', 'raw_transcription', 'edited_transcription', 'evaluator_result',
                    'analysis_result', 'practice_lists', 'diagnostic_test', 'struggling_words',
                    'struggling_words_input', 'mastered_words_input', 'teacher_observations_input',
                    'final_diagnostic_notes', 'analysis_notes', 'raw_ai_result', 'shadow_data',
                    'last_fetched_student', 'student_attempts_for_report', 'pending_student_name',
                    'pending_student_id', 'pending_pseudonym', 'selected_student',
                    f'progress_review_{st.session_state.get("current_student_id")}',
                    f'shadow_data_{st.session_state.get("current_student_id")}', 'selected_test_template'
                ]
                for key in keys_to_clear:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()

            student_id = newly_student_id

    if page == "Class":
        display_class_page()
    elif page == "Student":
        if student_id:
            display_student_detail_view(student_id, current_teacher_email)
        else:
            st.info("No students assigned to your class yet. Add a student via the 'Class' page.")
    elif page == "Admin":
        display_admin_page()

# =============================================================================
# CLASS OVERVIEW PAGE
# =============================================================================
def display_class_page():
    st.title("Class Overview")

    if "class_diagnostic_history" not in st.session_state:
        from database_manager import get_diagnostic_assessments
        st.session_state["class_diagnostic_history"] = get_diagnostic_assessments(
            st.session_state.user_email
        )

    students = get_all_students_by_teacher(st.session_state.user_email)

    if not students:
        st.info("No students in your class yet. Use the form below to add one.")
        class_levels = ['g1']
    else:
        st.subheader("Your Students")
        h1, h2, h3 = st.columns([3, 1, 2])
        h1.caption("NAME")
        h2.caption("GROUP")
        h3.caption("ACTION")

        class_levels = []
        for s in students:
            sid = s.get('student_id')
            sname = s.get('name')
            sgroup = s.get('current_g_level', 'g1')
            class_levels.append(sgroup)

            col1, col2, col3 = st.columns([3, 1, 2])
            col1.write(f"**{sname}**")
            col2.write(f"Group {sgroup[-1] if sgroup else '1'}")

            if col3.button("View Profile", key=f"btn_{sid}"):
                st.session_state.student_id = sid
                st.session_state.next_page = "Student"
                st.rerun()

    st.divider()

    with st.expander("Add New Student"):
        with st.form("add_new_student", clear_on_submit=True):
            name = st.text_input("Full Name")
            group = st.selectbox(
                "Assign to Group",
                options=list(constants.DIAGNOSTIC_GROUPS.keys()),
                format_func=lambda x: constants.DIAGNOSTIC_GROUPS[x]['name'],
                index=1
            )

            if st.form_submit_button("Create Student Record"):
                if name:
                    if add_student(st.session_state.user_email, name, group):
                        st.success(f"Success! {name} added.")
                        st.rerun()
                else:
                    st.error("Please enter a name.")

    st.divider()

    st.header("Generate Class Diagnostic Assessments")
    st.write("Construct evaluation sheets to assess spelling mastery across active class profiles.")

    st.subheader("Primary Spelling Inventory (PSI)")
    st.write("The standardised 26-word baseline assessment. Use this first with any new student.")
    from assessment_generator import generate_psi_baseline, render_assessment_pdf
    from io import BytesIO
    _psi = generate_psi_baseline()
    _col1, _col2, _col3 = st.columns(3)
    with _col1:
        st.download_button(
            label="Teacher Copy",
            data=render_assessment_pdf(_psi, is_teacher=True).getvalue(),
            file_name="PSI_Teacher_Copy.pdf",
            mime="application/pdf",
            key="psi_teacher_dl"
        )
    with _col2:
        st.download_button(
            label="Student Recording Copy",
            data=render_assessment_pdf(_psi, is_teacher=False).getvalue(),
            file_name="PSI_Student_Copy.pdf",
            mime="application/pdf",
            key="psi_student_dl"
        )
    with _col3:
        from pypdf import PdfWriter, PdfReader
        _writer = PdfWriter()
        for _pdf in [render_assessment_pdf(_psi, is_teacher=True).getvalue(),
                     render_assessment_pdf(_psi, is_teacher=False).getvalue()]:
            _reader = PdfReader(BytesIO(_pdf))
            for _page in _reader.pages:
                _writer.add_page(_page)
        _both_buf = BytesIO()
        _writer.write(_both_buf)
        st.download_button(
            label="Download Both",
            data=_both_buf.getvalue(),
            file_name="PSI_Both.pdf",
            mime="application/pdf",
            key="psi_both_dl"
        )
    st.divider()

    if st.button("Create Diagnostic Assessment", key="generate_diagnostic_btn", type="primary"):
        with st.spinner("Building diagnostic assessment..."):
            from assessment_generator import generate_psi_baseline, generate_class_diagnostics
            from database_manager import save_diagnostic_assessment
            new_tests = []
            if not any(t['assessment_id'] == 'DIAG-PSI-BASE' for t in st.session_state["class_diagnostic_history"]):
                new_tests.append(generate_psi_baseline())
            dynamic = generate_class_diagnostics(class_levels)
            new_tests.extend(dynamic)
            for test in new_tests:
                save_diagnostic_assessment(test, st.session_state.user_email)
            st.session_state["class_diagnostic_history"].extend(new_tests)
            if new_tests:
                st.success(f"Created {len(new_tests)} assessment(s).")
                st.rerun()
            else:
                st.info("All assessments already exist in the ledger below.")

    if st.session_state["class_diagnostic_history"]:
        st.write("---")
        st.subheader("Available Class Diagnostic Assessments")

        for idx, test in enumerate(st.session_state["class_diagnostic_history"]):
            with st.expander(f"**{test['test_name']}** — {test['assessment_id']} · {test['created_at']}"):
                st.caption(f"Words: {', '.join(test['words'])}")
                from assessment_generator import render_assessment_pdf
                from io import BytesIO

                teacher_bytes = render_assessment_pdf(test, is_teacher=True).getvalue()
                student_bytes = render_assessment_pdf(test, is_teacher=False).getvalue()

                # Combine both PDFs into one download
                from pypdf import PdfWriter
                writer = PdfWriter()
                for pdf_bytes in [teacher_bytes, student_bytes]:
                    from pypdf import PdfReader
                    reader = PdfReader(BytesIO(pdf_bytes))
                    for page in reader.pages:
                        writer.add_page(page)
                both_buf = BytesIO()
                writer.write(both_buf)
                both_bytes = both_buf.getvalue()

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.download_button(
                        label="⬇ Teacher Copy",
                        data=teacher_bytes,
                        file_name=f"Teacher_{test['assessment_id']}.pdf",
                        mime="application/pdf",
                        key=f"dl_teach_{test['assessment_id']}_{idx}",
                        use_container_width=True
                    )
                with col2:
                    st.download_button(
                        label="⬇ Student Recording Copy",
                        data=student_bytes,
                        file_name=f"Student_{test['assessment_id']}.pdf",
                        mime="application/pdf",
                        key=f"dl_stud_{test['assessment_id']}_{idx}",
                        use_container_width=True
                    )
                with col3:
                    st.download_button(
                        label="⬇ Download Both",
                        data=both_bytes,
                        file_name=f"Both_{test['assessment_id']}.pdf",
                        mime="application/pdf",
                        key=f"dl_both_{test['assessment_id']}_{idx}",
                        use_container_width=True
                    )

# Batch Print Practice Lists Section
    st.header("Batch Print Practice Lists")
    st.write("Generate printable practice list cards for multiple students at once.")

    if students:
        student_options = {f"{s.get('name')} ({s.get('student_id')})": s.get('student_id') for s in students}
        selected_students = st.multiselect(
            "Select Students for Batch Print",
            options=list(student_options.keys()),
            default=[],
            key="batch_print_students"
        )

        if selected_students:
            # --- Mode selector ---
            batch_mode = st.radio(
                "Word list source",
                options=["Use existing saved lists", "Generate new lists with AI"],
                horizontal=True,
                key="batch_print_mode"
            )
            practice_batch = []
            missing_lists = []
            generation_errors = []

            if batch_mode == "Use existing saved lists":
                for student_display in selected_students:
                    student_id = student_options[student_display]
                    student_name = student_display.split(" (")[0]
                    saved_lists = get_student_practice_lists(student_id)
                    if saved_lists:
                        latest = saved_lists[0]
                        practice_batch.append({
                            'student_name': student_name,
                            'student_id': student_id,
                            'list_title': latest['list_name'],
                            'group_title': latest['group_title'],
                            'words': latest['words']
                        })
                    else:
                        missing_lists.append(student_name)

                if missing_lists:
                    st.warning(
                        f"No saved lists found for: {', '.join(missing_lists)}. "
                        "Switch to 'Generate new lists with AI' to create them now."
                    )
            else:  # Generate new lists with AI
                st.info(
                    "New lists will be generated from each student's latest assessment "
                    "notes and struggling words. You can edit individual lists from each "
                    "student's page after printing."
                )
                if st.button("Generate Lists for Selected Students", key="batch_generate_btn", type="primary"):
                    progress = st.progress(0, text="Starting...")
                    for i, student_display in enumerate(selected_students):
                        student_id = student_options[student_display]
                        student_name = student_display.split(" (")[0]
                        progress.progress(
                            (i + 1) / len(selected_students),
                            text=f"Generating for {student_name}..."
                        )
                        try:
                            target_group = get_student_current_group_focus(student_id) or 'g1'
                            teacher_notes = get_latest_teacher_notes(student_id) or ""
                            struggling_words = get_struggling_words(student_id) or ""
                            group_name = constants.DIAGNOSTIC_GROUPS.get(
                                target_group, {}
                            ).get('name', target_group.upper())

                            words_raw = spelling_logic.generate_personalized_practice_words(
                                student_id=student_id,
                                target_group=target_group,
                                teacher_notes=teacher_notes,
                                struggling_words=struggling_words,
                            )
                            # Handle model output
                            if isinstance(words_raw, str):
                                import json, re as _re
                                clean = _re.sub(r'```json|```', '', words_raw).strip()
                                words = json.loads(clean)
                            else:
                                words = words_raw

                            list_data = {
                                'student_name': student_name,
                                'student_id': student_id,
                                'list_title': f"{group_name} Practice",
                                'group_title': group_name,
                                'words': words
                            }
                            practice_batch.append(list_data)
                            # Cache so student page shows it immediately
                            st.session_state[f'practice_list_{student_id}'] = {
                                'words': words,
                                'group_title': group_name,
                                'student_name': student_name,
                            }
                            save_student_practice_list(
                                student_id=student_id,
                                teacher_id=st.session_state.user_email,
                                list_name=f"{group_name} Practice",
                                group_title=group_name,
                                words_list=words
                            )
                        except Exception as e:
                            generation_errors.append(f"{student_name}: {e}")
                    progress.empty()
                    if generation_errors:
                        st.error("Some lists failed to generate:\n" + "\n".join(generation_errors))
                    if practice_batch:
                        st.session_state['batch_practice_ready'] = practice_batch
                        st.success(f"Generated {len(practice_batch)} list(s).")
                        st.rerun()

            # Retrieve generated batch from session state if already done
            if not practice_batch and 'batch_practice_ready' in st.session_state and batch_mode == "Generate new lists with AI":
                practice_batch = st.session_state.get('batch_practice_ready', [])

            # --- Download button ---
            if practice_batch:
                from pdf_generator import render_batch_practice_lists_pdf
                pdf_bytes = render_batch_practice_lists_pdf(practice_batch)
                st.download_button(
                    label="Download Batch Practice PDF",
                    data=pdf_bytes,
                    file_name=f"Class_Practice_Lists_{datetime.datetime.now().strftime('%Y-%m-%d')}.pdf",
                    mime="application/pdf",
                    key="download_batch_practice_pdf",
                    type="primary"
                )
                st.write(f"**{len(practice_batch)} list(s) ready to print:**")
                for item in practice_batch:
                    st.caption(f"• {item['student_name']}: {item['list_title']} ({len(item['words'])} words)")
        else:
            st.info("Select at least one student to generate batch practice lists.")
    else:
        st.info("No students available. Add students to your class first.")
# =============================================================================
# REFACTORED WORKFLOW ROUTER: EVALUATOR -> LOGIC -> DISPLAY -> OVERRIDE UI
# =============================================================================
def display_student_detail_view(student_id, current_teacher_email):
    """Display student detail view with modular Pipeline workflow."""
    student_name = get_name_for_id(current_teacher_email, student_id) or f"Student {student_id}"
    st.title(student_name)

    current_student_group_focus = get_student_current_group_focus(student_id)

    def on_group_focus_change():
        update_student_current_group_focus(student_id, st.session_state[f"group_focus_selector_{student_id}"])
        st.rerun()

    group_keys = list(constants.DIAGNOSTIC_GROUPS.keys())
    default_group_index = group_keys.index(current_student_group_focus) if current_student_group_focus in group_keys else 0

    st.subheader("Current Group Focus")
    st.selectbox(
        label="Select Focus Group",
        label_visibility="collapsed",
        options=group_keys,
        index=default_group_index,
        format_func=lambda k: f"{k.upper()}: {constants.DIAGNOSTIC_GROUPS[k]['name']}",
        key=f"group_focus_selector_{student_id}",
        on_change=on_group_focus_change
    )

    history = get_student_history(student_id, teacher_id=current_teacher_email, admin=False)
    target_group = current_student_group_focus
    classroom_data_key = f"shadow_data_{student_id}"

    current_settings = get_teacher_settings(current_teacher_email)
    sheet_url = current_settings.get('google_sheet_url', '')

    if sheet_url and not st.session_state.get(classroom_data_key):
        with st.spinner("Fetching classroom observation data..."):
            try:
                shadow_data_result = get_sheet_data(sheet_url, student_name, None)
                if isinstance(shadow_data_result, dict) and "error" in shadow_data_result:
                    st.error(f"Failed to fetch classroom data: {shadow_data_result['error']}")
                elif isinstance(shadow_data_result, list):
                    st.session_state[classroom_data_key] = shadow_data_result
            except Exception as e:
                st.error(f"Failed to fetch classroom data: {e}.")

    st.markdown("---")

    st.subheader("AI-Generated Practice Lists")
    if st.button("Generate Personalized Practice Lists", key=f"gen_practice_{student_id}"):
        with st.spinner("Generating personalized practice lists with AI..."):
            try:
                teacher_notes = get_latest_teacher_notes(student_id)
                db_struggling_words = get_struggling_words(student_id)
                mastered_words = st.session_state.get("mastered_words_input", "")
                unit_description = st.session_state.get("unit_description", "")

                # TEMP DEBUG - remove once confirmed
                print(f"\n🔍 [DEBUG] student_id={student_id}")
                print(f"🔍 [DEBUG] teacher_notes={teacher_notes!r}")
                print(f"🔍 [DEBUG] db_struggling_words={db_struggling_words!r}\n")

                personalized_words = generate_personalized_practice_words(
                    student_id=student_id,
                    target_group=target_group,
                    teacher_notes=teacher_notes,
                    struggling_words=db_struggling_words,
                    mastered_words=mastered_words,
                    unit_description=unit_description,
                    custom_words_input=None
                )

                st.session_state[f'practice_list_{student_id}'] = {
                    "student_name": student_name, "group_title": target_group,
                    "words": personalized_words,
                    'student_name': student_name,
                }
                st.success("Personalized practice list generated!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate practice lists: {str(e)}.")

    practice_list_key = f'practice_list_{student_id}'
    if st.session_state.get(practice_list_key):
        practice_data = st.session_state[practice_list_key]
        st.write(f"**Practice List for {practice_data['student_name']} ({practice_data['group_title']}):**")

        # Editable widget for practice words
        default_words_text = ", ".join(practice_data['words'])
        edited_words = st.text_area(
            "Edit Practice Words (comma-separated or one per line):",
            value=default_words_text,
            height=150,
            key=f"edit_practice_words_{student_id}"
        )

        # List Title input
        default_title = f"{practice_data['group_title'].upper()} Practice - {datetime.datetime.now().strftime('%Y-%m-%d')}"
        list_title = st.text_input(
            "List Title:",
            value=default_title,
            key=f"practice_list_title_{student_id}"
        )

        col_save, col_clear = st.columns([2, 1])
        with col_save:
            if st.button("Save Practice List", key=f"save_practice_{student_id}", type="primary"):
                # Parse edited words
                if "," in edited_words:
                    words_list = [w.strip() for w in edited_words.split(",") if w.strip()]
                else:
                    words_list = [w.strip() for w in edited_words.split("\n") if w.strip()]

                if words_list and list_title.strip():
                    if save_student_practice_list(
                        student_id=student_id,
                        teacher_id=current_teacher_email,
                        list_name=list_title.strip(),
                        group_title=practice_data['group_title'],
                        words_list=words_list
                    ):
                        st.success("Practice list saved successfully!")
                        del st.session_state[practice_list_key]
                        st.rerun()
                    else:
                        st.error("Failed to save practice list.")
                else:
                    st.warning("Please provide both a title and at least one word.")

        with col_clear:
            if st.button("Clear Practice List", key=f"clear_practice_{student_id}"):
                del st.session_state[practice_list_key]
                st.rerun()

    # Saved Practice Lists History
    st.markdown("---")
    st.subheader("Saved Practice Lists")
    saved_lists = get_student_practice_lists(student_id)

    if saved_lists:
        for saved_list in saved_lists:
            with st.expander(f"{saved_list['list_name']} (Created: {saved_list['created_at']})"):
                st.write(f"**Group:** {saved_list['group_title']}")
                st.write("**Words:**")
                for word in saved_list['words']:
                    st.write(f"- {word}")

                col_edit, col_delete = st.columns([1, 1])
                with col_edit:
                    if st.button("Edit", key=f"edit_saved_{saved_list['id']}"):
                        # Load into editor
                        st.session_state[practice_list_key] = {
                            "student_name": student_name,
                            "group_title": saved_list['group_title'],
                            "words": saved_list['words'],
                            "list_id": saved_list['id'],
                            "is_edit": True
                        }
                        st.session_state[f"practice_list_title_{student_id}"] = saved_list['list_name']
                        st.rerun()
                with col_delete:
                    if st.button("Delete", key=f"delete_saved_{saved_list['id']}"):
                        if delete_student_practice_list(saved_list['id']):
                            st.success("Practice list deleted.")
                            st.rerun()
                        else:
                            st.error("Failed to delete practice list.")
    else:
        st.info("No saved practice lists yet.")

    st.divider()

    # Diagnostic History Section
    st.subheader("Diagnostic Assessment History")
    if history:
        for assessment in reversed(history):
            # 1. Fetch Teacher Notes (checks all common DB column names)
            teacher_notes = (
                assessment.get('teacher_refined_notes')
                or assessment.get('teacher_notes')
                or assessment.get('refinement_notes')
                or assessment.get('notes')
                or assessment.get('analysis')
                or assessment.get('ai_analysis')
                or assessment.get('summary')
                or assessment.get('feedback')
            )

            # 2. Extract Test Name (Checks "Word List:" header first)
            extracted_title = None
            notes_str = str(teacher_notes or "").strip()
            if notes_str.startswith("Word List:"):
                extracted_title = notes_str.split('\n')[0].replace("Word List: ", "").strip()

            raw_name = (
                extracted_title
                or assessment.get('list_name')
                or assessment.get('test_name')
                or assessment.get('assessment_type')
                or assessment.get('stage')
            )

            ignored_names = [
                "ad-hoc assessment", "ad-hoc", "adhoc",
                "unspecified assessment list", "select a saved list...",
                "none", "", "n/a"
            ]

            if raw_name and str(raw_name).strip().lower() not in ignored_names:
                raw_str = str(raw_name).strip()
                test_name = f"{raw_str.upper()} Assessment" if not raw_str.upper().endswith("ASSESSMENT") else raw_str
            else:
                test_name = "Ad-hoc Assessment"

            test_date = assessment.get('test_date')
            created_at = assessment.get('created_at') or 'N/A'
            date_only = test_date if test_date else (created_at.split(' ')[0] if ' ' in created_at else created_at)

            raw_next = assessment.get('suggested_next') or 'N/A'
            suggested_group = raw_next.upper()

            if suggested_group != 'N/A':
                expander_title = f"**{test_name}** – {date_only} (Suggested: {suggested_group})"
            else:
                expander_title = f"**{test_name}** – {date_only}"

            with st.expander(expander_title, expanded=False):
                # Student Responses Table Display
                st.subheader("Student Responses")
                responses_raw = (
                    assessment.get('student_responses')
                    or assessment.get('transcriptions')
                    or assessment.get('raw_transcription')
                )

                responses_list = None
                if isinstance(responses_raw, str):
                    try:
                        responses_list = json.loads(responses_raw)
                    except (json.JSONDecodeError, TypeError):
                        responses_list = None
                elif isinstance(responses_raw, list):
                    responses_list = responses_raw

                if isinstance(responses_list, list) and len(responses_list) > 0:
                    df_responses = pd.DataFrame(responses_list)
                    rename_map = {
                        "number": "#",
                        "intended": "Target Word",
                        "attempt": "Student Attempt",
                        "correct": "Correct?"
                    }
                    df_responses = df_responses.rename(
                        columns={k: v for k, v in rename_map.items() if k in df_responses.columns}
                    )
                    st.dataframe(df_responses, use_container_width=True, hide_index=True)
                elif isinstance(responses_raw, str) and responses_raw.strip():
                    st.code(responses_raw, language='text')
                else:
                    st.info("No student responses recorded for this assessment.")

                # Teacher Notes Display
                st.subheader("Teacher Notes")
                if teacher_notes and str(teacher_notes).strip():
                    st.markdown(str(teacher_notes).strip())
                else:
                    st.info("No teacher notes recorded for this assessment.")

                # G-Level Scores
                diagnostic_groups = getattr(constants, 'DIAGNOSTIC_GROUPS', {})
                if diagnostic_groups:
                    g_scores_found = {
                        k: assessment.get(k)
                        for k in assessment.keys()
                        if k in diagnostic_groups and assessment.get(k) is not None
                    }
                    if not g_scores_found:
                        g_scores_found = {
                            group_key: assessment.get(db_key)
                            for group_key in diagnostic_groups.keys()
                            for db_key in assessment.keys()
                            if db_key.startswith(f"{group_key}_") and assessment.get(db_key) is not None
                        }

                    if g_scores_found:
                        st.subheader("G-Level Scores")
                        for k, v in g_scores_found.items():
                            group_name = diagnostic_groups[k].get('name', 'Unknown Focus')
                            st.write(f"- **{k.upper()}** ({group_name}): {v}")

                # Delete Assessment Popover

                col_del_btn, col_edit_btn = st.columns([1, 1])
                with col_del_btn:
                    with st.popover("Delete this assessment?", use_container_width=True):
                        st.write("Are you sure you want to delete this assessment?")
                        if st.button("Confirm Delete", type="primary", key=f"confirm_delete_assessment_{assessment['id']}"):
                            if db.delete_assessment(assessment['id']):
                                st.success("Assessment deleted successfully!")
                                st.rerun()
                            else:
                                st.error("Failed to delete assessment.")
                with col_edit_btn:
                    with st.popover("Edit Assessment", use_container_width=True):
                        st.subheader("Edit Assessment Details")

                        initial_date = assessment.get("test_date")
                        if isinstance(initial_date, str):
                            try:
                                initial_date = datetime.datetime.strptime(str(initial_date), "%Y-%m-%d").date()
                            except Exception:
                                initial_date = datetime.datetime.now().date()

                        edit_date = st.date_input("Assessment Date", value=initial_date, key=f"edit_date_{assessment['id']}")
                        edit_name = st.text_input("Assessment Name", value=test_name, key=f"edit_name_{assessment['id']}")
                        group_keys = list(constants.DIAGNOSTIC_GROUPS.keys())
                        current_suggested = assessment.get("suggested_next", "g1")
                        if current_suggested not in group_keys:
                            current_suggested = "g1"
                        edit_group = st.selectbox(
                            "Target Focus Group",
                            options=group_keys,
                            format_func=lambda k: f"{k.upper()}: {constants.DIAGNOSTIC_GROUPS[k]['name']}",
                            index=group_keys.index(current_suggested),
                            key=f"edit_group_{assessment['id']}"
                        )
                        edit_notes = st.text_area("Teacher Notes / Comments", value=teacher_notes or "", key=f"edit_notes_{assessment['id']}")
                        if st.button("Save Changes", type="primary", key=f"save_edit_{assessment['id']}"):
                            original_notes = teacher_notes or ""
                            final_notes = edit_notes
                            if original_notes.startswith("Word List:"):
                                header = original_notes.split("\n")[0]
                                final_notes = f"{header}\n{edit_notes}"
                            if db.update_assessment(
                                assessment_id=assessment["id"],
                                test_date=edit_date.strftime("%Y-%m-%d"),
                                test_name=edit_name,
                                teacher_notes=final_notes,
                                suggested_next=edit_group
                            ):
                                st.toast("Assessment updated successfully!")
                                st.rerun()
                            else:
                                st.error("Failed to update assessment.")
    else:
        st.info("No diagnostic assessments recorded yet for this student.")

    st.divider()

    display_assessment_pipeline(student_id, student_name, current_teacher_email)

    # =============================================================================
    # ASSESSMENT EXECUTION PIPELINE
    # =============================================================================
def display_assessment_pipeline(student_id, student_name, current_teacher_email):
    """
    Modular 4-Stage Workflow:
    1. Input Preparation & Handwriting OCR
    2. STAGE 1: Evaluator (Deterministic Feature Scoring against PSI_WORD_BANK)
    3. STAGE 2: Logic (Qualitative Diagnostic AI Crew)
    4. STAGE 3: Display (Feature Matrix & Qualitative Error Views)
    5. STAGE 4: Override UI (Teacher Refinement, Calibration, & Save)
    """
    st.header("Assessment Evaluation")

    transcription_key = f"edited_transcription_{student_id}"
    file_cache_key = f"uploaded_file_cache_{student_id}"

    if st.session_state.get(transcription_key):
        st.session_state['student_attempts_for_report'] = st.session_state[transcription_key]
    if 'student_attempts_for_report' not in st.session_state:
        st.session_state['student_attempts_for_report'] = ""

    # -----------------------------------------------------------------------------
    # 0. INPUT PREPARATION: TARGET WORDS & OCR TRANSCRIPTION
    # -----------------------------------------------------------------------------
    with st.expander("Step 0: Target Words & Handwriting OCR", expanded=True):
        st.session_state.current_word_list_mode = st.radio(
            "Choose word list method:",
            options=["Select Existing List", "Create New List"],
            key=f"word_list_mode_{student_id}",
            horizontal=True
        )

        named_lists = get_named_lists(current_teacher_email)
        list_options = {"Select a saved list...": None}
        for lst in named_lists:
            list_name = lst.get('name') or lst.get('list_name') or f"List #{lst['id']}"
            list_options[list_name] = lst['id']

        default_index = 0
        keys_list = list(list_options.keys())
        if st.session_state.get("last_used_assessment_list_id"):
            last_used_list = get_named_list_by_id(st.session_state.last_used_assessment_list_id)
            if last_used_list:
                last_name = last_used_list.get('name') or last_used_list.get('list_name')
                if last_name in list_options:
                    default_index = keys_list.index(last_name)

        if st.session_state.current_word_list_mode == "Select Existing List":
            selected_list_name = st.selectbox(
                "Select existing list:",
                options=keys_list,
                index=default_index,
                key=f"select_word_list_{student_id}"
            )
            if selected_list_name != "Select a saved list..." and selected_list_name in list_options:
                list_id = list_options[selected_list_name]
                list_data = get_named_list_by_id(list_id)
                if list_data:
                    raw_words = list_data.get('word_list') or list_data.get('target_words') or ""
                    if isinstance(raw_words, list):
                        raw_words = ", ".join(raw_words)

                    st.session_state.intended_words_input = raw_words
                    st.session_state.current_list_id = list_data['id']
                    st.session_state.last_used_assessment_list_id = list_data['id']
            else:
                st.session_state.intended_words_input = ""
                st.session_state.current_list_id = None
        else:
            new_list_name = st.text_input("Name for new list:", key=f"new_list_name_{student_id}")
            st.session_state.intended_words_input = st.text_area(
                "Enter target words (comma-separated):",
                value=st.session_state.get("intended_words_input", ""),
                height=100,
                key=f"intended_words_input_{student_id}"
            )
            if st.button("Save New Word List", key=f"save_new_list_btn_{student_id}"):
                if new_name and st.session_state.intended_words_input:
                    if save_named_list(current_teacher_email, new_name.strip(), st.session_state.intended_words_input.strip()):
                        st.success(f"List '{new_name}' saved!")
                        st.session_state.current_word_list_mode = "Select Existing List"
                        st.rerun()

        if st.session_state.get("intended_words_input"):
            processed = [w.strip() for part in st.session_state.intended_words_input.split(',') for w in part.split('\n') if w.strip()]
            st.session_state.processed_intended_words = ", ".join(processed)
        else:
            st.session_state.processed_intended_words = ""

        st.markdown("---")

        assessment_date = st.date_input(
            "Assessment Date",
            value=datetime.datetime.now().date(),
            key=f"assessment_date_{student_id}"
        )

        uploaded_file = st.file_uploader(
            "Upload photo of student's handwritten test sheet (PNG, JPG, JPEG):",
            type=['png', 'jpg', 'jpeg'],
            key=f"raw_uploader_{student_id}"
        )

        if uploaded_file is not None:
            st.session_state[file_cache_key] = uploaded_file

        active_file = st.session_state.get(file_cache_key)

        if active_file:
            clean_base64, clean_img = preprocess_image(active_file)
            col_img, col_text = st.columns([1, 1])

            with col_img:
                st.image(clean_img, caption="Cleaned Image Input")
                if st.button("Read Handwriting via OCR", key=f"read_handwriting_{student_id}"):
                    with st.spinner('Decoding student handwriting...'):
                        try:
                            ocr_data = transcribe_handwriting(
                                clean_base64,
                                intended_words=st.session_state.get('processed_intended_words', "")
                            )
                            if ocr_data:
                                st.session_state[transcription_key] = ocr_data
                                st.session_state['student_attempts_for_report'] = ocr_data
                                st.success("Handwriting transcribed successfully!")
                                st.rerun()
                        except Exception as e:
                            st.error(f"OCR Error: {e}")

            with col_text:
                st.subheader("Verify & Edit Transcription")
                current_data = st.session_state.get(transcription_key)

                if current_data:
                    if isinstance(current_data, list):
                        df = pd.DataFrame(current_data)
                    else:
                        df = pd.DataFrame(columns=["number", "intended", "attempt"])

                    edited_df = st.data_editor(
                        df,
                        column_config={
                            "number": st.column_config.TextColumn("#", disabled=True),
                            "intended": st.column_config.TextColumn("Target Word", disabled=True),
                            "attempt": st.column_config.TextColumn("Student Attempt (Editable)"),
                        },
                        hide_index=True,
                        key=f"editor_{student_id}"
                    )

                    updated_records = edited_df.to_dict(orient="records")
                    st.session_state['student_attempts_for_report'] = updated_records
                    st.session_state[transcription_key] = updated_records
                else:
                    st.info("Click **'Read Handwriting via OCR'** to analyze the student work.")

    # -----------------------------------------------------------------------------
    # STAGE 1 & 2: PIPELINE RUNNER
    # -----------------------------------------------------------------------------
    st.subheader("Run Automated Formative Analytics")

    col_opt1, col_opt2 = st.columns([2, 1])
    with col_opt1:
        analysis_complexity = st.select_slider(
            "AI Logic Complexity Level",
            options=["Brief", "Standard", "Detailed"],
            value="Standard",
            key=f"analysis_complexity_{student_id}"
        )

    with col_opt2:
        st.write("")
        st.write("")
        run_pipeline = st.button(
            "Click to Run",
            key=f"run_pipeline_{student_id}",
            type="primary",
            use_container_width=True
        )

    if run_pipeline:
        raw_attempts = st.session_state.get('student_attempts_for_report')

        if not raw_attempts:
            st.warning("Please upload and transcribe student handwriting before running analytics.")
        else:
            # Preserve number-aware dict structure for proper alignment
            if not raw_attempts:
                st.warning("Please upload and transcribe student handwriting before running analytics.")
            else:
            # Sort by word number first if we have dicts (preserves correct pairing
            # even when student wrote across instead of down the page).
                if isinstance(raw_attempts, list) and raw_attempts and isinstance(raw_attempts[0], dict):
                    def safe_num(item):
                        try:
                            return int(item.get("number", 0))
                        except (ValueError, TypeError):
                            return 0
                    raw_attempts_sorted = sorted(raw_attempts, key=safe_num)
                else:
                    raw_attempts_sorted = raw_attempts

                # Build flat lists for feature_evaluator, in correct order
                if isinstance(raw_attempts_sorted, list) and raw_attempts_sorted and isinstance(raw_attempts_sorted[0], dict):
                # OCR already identified intended/attempt pairs — use them directly.
                # This correctly handles out-of-order sheets.
                    transcribed_words = []
                    intended_words = []
                    for item in raw_attempts_sorted:
                        attempt = str(item.get("attempt") or item.get("word") or "").strip()
                        intended = str(item.get("intended") or item.get("intended_word") or "").strip()
                        if attempt or intended:  # skip completely empty rows
                            transcribed_words.append(attempt)
                            intended_words.append(intended)
                elif isinstance(raw_attempts_sorted, str):
                    transcribed_words = [w.strip() for w in raw_attempts_sorted.split(",") if w.strip()]
                    # fall back to teacher word list below
                    intended_words = []
                else:
                    transcribed_words = [str(raw_attempts_sorted)]
                    intended_words = []

                # Only fall back to the teacher's positional word list if OCR
                # didn't give us intended words (e.g. raw string input, no image).
                if not intended_words:
                    raw_intended = st.session_state.get(
                        "processed_intended_words",
                        "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine"
                    )
                    if isinstance(raw_intended, str):
                        intended_words = [w.strip() for w in raw_intended.split(",") if w.strip()]
                    elif isinstance(raw_intended, list):
                        intended_words = [str(w).strip() for w in raw_intended]
                    else:
                        intended_words = raw_intended

                # Phase 1: Feature Evaluator
                eval_result = None
                with st.spinner("Phase 1/2: Analyzing orthographic patterns..."):
                    if evaluate_spelling_attempt is not None:
                        try:
                            eval_result = evaluate_spelling_attempt(
                                student_id=student_id,
                                transcribed_words=transcribed_words,
                                intended_words=intended_words
                            )
                            st.session_state['eval_result'] = eval_result
                            st.session_state['evaluator_result'] = eval_result
                        except Exception as e:
                            st.error(f"Error during feature evaluation: {str(e)}")
                    else:
                        st.warning("Feature evaluator module is not available.")

                # Phase 2: AI Logic Engine
                with st.spinner("Phase 2/2: Prescriptive Learning Analytics..."):
                    try:
                        current_assessment_id = st.session_state.get('assessment_id', None)

                        analysis_result = spelling_logic.process_full_assessment(
                            student_id=student_id,
                            assessment_id=current_assessment_id,
                            transcriptions=raw_attempts_sorted,   # <-- dicts, sorted, intact
                            intended_words=intended_words,
                            evaluator_result=eval_result,
                            teacher_id=current_teacher_email
                        )

                        analysis_result = process_assessment_response(
                            response_data=analysis_result,
                            student_name=student_name,
                            raw_student_id=student_id
                        )

                        st.session_state["analysis_result"] = analysis_result

                        ai_notes = ""
                        ai_target = "g1"
                        if isinstance(analysis_result, dict):
                            ai_notes = (
                                analysis_result.get("prescriptive_feedback")
                                or analysis_result.get("teacher_notes")
                                or analysis_result.get("notes")
                                or ""
                            )
                            ai_target = analysis_result.get("suggested_next", "g1") or analysis_result.get("phonetic_stage_level", "g1")
                        elif analysis_result:
                            ai_notes = getattr(analysis_result, "teacher_notes", "") or getattr(analysis_result, "notes", "")
                            ai_target = getattr(analysis_result, "suggested_next", "g1") or getattr(analysis_result, "phonetic_stage_level", "g1")

                        if ai_notes:
                            # 1. Preserve the raw markdown with bolding for reports
                            st.session_state["raw_report_notes"] = ai_notes
                            # 2. Store clean plain-text (no asterisks) for the teacher's text area
                            st.session_state["final_diagnostic_notes"] = clean_ai_formatting(ai_notes)

                        st.session_state["targets_display"] = [ai_target]

                        if "teacher_refined_group" in st.session_state:
                            del st.session_state["teacher_refined_group"]

                        st.success("Orthographic analysis completed successfully!")
                    except Exception as logic_err:
                        st.error(f"Logic Engine Execution Failed: {logic_err}")

    # -----------------------------------------------------------------------------
    # STAGE 3: DISPLAY (DIAGNOSTIC VISUAL MATRIX & COMPARISON)
    # -----------------------------------------------------------------------------
    if st.session_state.get("analysis_result") or st.session_state.get("evaluator_result"):
        st.markdown("---")

        # 1. Render G0-G8 Stage Accuracy Chart & Feature Badges
        eval_data = st.session_state.get("evaluator_result")
        if eval_data and isinstance(eval_data, dict):
            render_orthographic_analysis(eval_data)

        # 2. Render Side-by-Side Attempt List
        st.markdown("### Side-by-Side Attempt Analysis")
        highlighted_content = ""
        if st.session_state.get("processed_intended_words") and st.session_state.get('student_attempts_for_report'):
            intended_words_raw = st.session_state.get("processed_intended_words", "")
            student_attempts_raw = st.session_state.get('student_attempts_for_report') or st.session_state.get('student_attempts_raw', '')

            if isinstance(intended_words_raw, list):
                intended_list = [str(w).strip().lower() for w in intended_words_raw if str(w).strip()]
            elif isinstance(intended_words_raw, str):
                intended_list = [w.strip().lower() for w in intended_words_raw.replace(',', '\n').split('\n') if w.strip()]
            else:
                intended_list = []

            # Check if student attempts have number metadata (number-aware OCR output)
            is_numbered = (
                isinstance(student_attempts_raw, list) and
                student_attempts_raw and
                isinstance(student_attempts_raw[0], dict) and
                'number' in student_attempts_raw[0]
            )

            if is_numbered:
                # Number-aware alignment: map attempts by item number
                attempts_by_number = {}
                for item in student_attempts_raw:
                    if isinstance(item, dict):
                        num_str = str(item.get('number', '')).strip()
                        if num_str.isdigit():
                            attempt = item.get('attempt') or item.get('word') or ''
                            attempts_by_number[int(num_str)] = attempt.strip().lower()

                # Pair by item number
                highlighted_content += "<ul style='list-style-type: none; padding-left: 0; margin: 0; font-family: monospace;'>"
                for idx, target in enumerate(intended_list, start=1):
                    attempt = attempts_by_number.get(idx, '')
                    if attempt == target:
                        highlighted_content += f"<li style='margin-bottom: 6px;'>#{idx} {target}: <span style='color:#5cb85c; font-weight:bold;'>{attempt} ✓</span></li>"
                    else:
                        highlighted_content += f"<li style='margin-bottom: 6px;'>#{idx} {target}: <span style='color:#d9534f; font-weight:bold;'>{attempt} ✗</span></li>"
            else:
                # Legacy positional alignment
                if isinstance(student_attempts_raw, list):
                    attempts_list = [
                        item.get("attempt") or item.get("word") or item.get("text") or str(item)
                        if isinstance(item, dict) else str(item)
                        for item in student_attempts_raw
                    ]
                elif isinstance(student_attempts_raw, str):
                    attempts_list = [line.strip() for line in student_attempts_raw.replace(',', '\n').split('\n') if line.strip()]
                else:
                    attempts_list = []

                import re
                attempts_raw = []
                for line in attempts_list:
                    cleaned_line = str(line).strip().lower()
                    if not cleaned_line:
                        continue
                    if ":" in cleaned_line:
                        student_word = cleaned_line.split(":", 1)[1].strip()
                    else:
                        student_word = re.sub(r'^\d+[\.\-\s)]+', '', cleaned_line).strip()
                    if student_word:
                        attempts_raw.append(student_word)

                min_len = min(len(intended_list), len(attempts_raw))
                highlighted_content += "<ul style='list-style-type: none; padding-left: 0; margin: 0; font-family: monospace;'>"
                for i in range(min_len):
                    target = intended_list[i]
                    attempt = attempts_raw[i]
                    if attempt == target:
                        highlighted_content += f"<li style='margin-bottom: 6px;'>{i+1}. {target}: <span style='color:#5cb85c; font-weight:bold;'>{attempt} ✓</span></li>"
                    else:
                        highlighted_content += f"<li style='margin-bottom: 6px;'>{i+1}. {target}: <span style='color:#d9534f; font-weight:bold;'>{attempt}</span></li>"

                if len(attempts_raw) > min_len:
                    for i in range(min_len, len(attempts_raw)):
                        highlighted_content += f"<li style='margin-bottom: 6px;'>{i+1}. Extra: <span style='color:#d9534f; font-weight:bold;'>{attempts_raw[i]}</span></li>"
                highlighted_content += "</ul>"
        else:
            highlighted_content = "*No comparative data parsed.*"

        st.markdown(
            f"""<div style="background-color: #1e1e1e; padding: 15px; border-radius: 8px; border: 1px solid #333; color: #f0f2f6; line-height: 1.6;">
            {highlighted_content}
            </div>""",
            unsafe_allow_html=True
        )

    # -----------------------------------------------------------------------------
    # STAGE 4: OVERRIDE UI (TEACHER REFINEMENT & CALIBRATION SAVE)
    # -----------------------------------------------------------------------------
    if st.session_state.get("analysis_result"):
        st.markdown("---")
        st.subheader("Stage 4: AI Diagnosis (Teachers can adjust and refine when necessary)")
        st.caption("Review AI diagnostic recommendations, log blind spots, and confirm final student placement.")

        group_keys = list(constants.DIAGNOSTIC_GROUPS.keys())
        analysis_obj = st.session_state.get('analysis_result')

        g1_score = getattr(analysis_obj, 'g1_cvc_mapping', 0) or getattr(analysis_obj, 'g1', 0)
        ai_suggested_list = st.session_state.get('targets_display', [])
        ai_suggested = ai_suggested_list[0] if ai_suggested_list else 'g1'

        if g1_score and int(g1_score) < 3 and 'g1' in group_keys:
            ai_suggested = 'g1'
        elif ai_suggested not in group_keys:
            ai_suggested = 'g1'

        if "teacher_refined_group" not in st.session_state:
            st.session_state.teacher_refined_group = ai_suggested

        col_ovr1, col_ovr2 = st.columns(2)
        with col_ovr1:
            st.selectbox(
                "AI Group Assignment (modifiable):",
                options=group_keys,
                format_func=lambda k: f"{k.upper()}: {constants.DIAGNOSTIC_GROUPS[k]['name']}",
                key="teacher_refined_group"
            )

        with col_ovr2:
            st.write("")
            st.info(f"AI System Recommendation: **{ai_suggested.upper()}**")

        teacher_logic_feedback = st.text_area(
            "Feedback on AI Logic / System Blind Spots",
            placeholder="e.g., The AI miscategorized vowel digraph errors as CVC mapping issues...",
            key=f"logic_feedback_{student_id}"
        )

        # ---------------------------------------------------------------------
        # PLACEMENT HERE: Extract AI output & prepare dual storage for notes
        # ---------------------------------------------------------------------
        if isinstance(analysis_obj, dict):
            raw_feedback = (
                analysis_obj.get("prescriptive_feedback")
                or analysis_obj.get("teacher_notes")
                or analysis_obj.get("notes")
                or ""
            )
        else:
            raw_feedback = (
                getattr(analysis_obj, "prescriptive_feedback", None)
                or getattr(analysis_obj, "teacher_notes", "")
                or ""
            )

        # 1. Preserve raw Markdown for rich-text reports
        st.session_state["raw_report_notes"] = raw_feedback

        st.text_area(
            "Final Diagnostic Notes (modifiable)",
            height=250,
            key="final_diagnostic_notes"
        )

        if st.button("Confirm & Send to Database", key=f"save_btn_{student_id}", type="primary", use_container_width=True):
            student_attempts_raw = st.session_state.get('student_attempts_for_report', "")
            final_group = st.session_state.get("teacher_refined_group", 'g1')
            teacher_feedback = st.session_state.get(f"logic_feedback_{student_id}", "")

            mode = st.session_state.get(f"word_list_mode_{student_id}")
            assessment_name = "Ad-hoc Assessment"

            if mode == "Select Existing List":
                raw_list = st.session_state.get(f"select_word_list_{student_id}")
                if raw_list and raw_list != "Select a saved list...":
                    assessment_name = raw_list
            else:
                new_name = st.session_state.get(f"new_list_name_{student_id}")
                if new_name and new_name.strip():
                    assessment_name = new_name.strip()

            notes_content = st.session_state.get("final_diagnostic_notes", "")
            refined_notes_with_header = f"Word List: {assessment_name}\n{notes_content}"

            # Derive struggling words from the deterministic word-level evaluation,
            # not from analysis_result (which never contained this field).
            eval_result_for_save = st.session_state.get('eval_result') or {}
            word_evals_for_save = eval_result_for_save.get('word_evaluations', []) if isinstance(eval_result_for_save, dict) else []
            struggling_words_str = ", ".join(
                w.get('intended_word', '') for w in word_evals_for_save
                if not w.get('is_correct') and w.get('intended_word')
            )

            resolved_teacher_email = st.session_state.get('user_email') or "authenticated_teacher@unboxed.edu"

            assessment_data_dict = {
                "student_id": student_id,
                "teacher_id": resolved_teacher_email,
                "raw_transcription": student_attempts_raw,
                "teacher_refined_notes": refined_notes_with_header,
                "suggested_next": final_group,
                "suggested_next_groups": [final_group],
                "test_name": assessment_name,
                "g0_phonemic_awareness": getattr(st.session_state.get('analysis_result'), 'g0_phonemic_awareness', 0),
                "g1_cvc_mapping": getattr(st.session_state.get('analysis_result'), 'g1_cvc_mapping', 0),
                "g2_digraphs": getattr(st.session_state.get('analysis_result'), 'g2_digraphs', 0),
                "g3_silent_e": getattr(st.session_state.get('analysis_result'), 'g3_silent_e', 0),
                "g4_vowel_teams": getattr(st.session_state.get('analysis_result'), 'g4_vowel_teams', 0),
                "g5_r_controlled": getattr(st.session_state.get('analysis_result'), 'g5_r_controlled', 0),
                "g6_clusters": getattr(st.session_state.get('analysis_result'), 'g6_clusters', 0),
                "g7_multisyllabic": getattr(st.session_state.get('analysis_result'), 'g7_multisyllabic', 0),
                "g8_reduction_morphology": getattr(st.session_state.get('analysis_result'), 'g8_reduction_morphology', 0),
                "teacher_notes": getattr(st.session_state.get('analysis_result'), 'teacher_notes', ''),
                "struggling_words": struggling_words_str,
            }

            class AssessmentDataObject:
                def __init__(self, d):
                    self.__dict__ = d

            assessment_data_obj = AssessmentDataObject(assessment_data_dict)

            if db.save_assessment(
                assessment_data_obj,
                student_id=student_id,
                raw_text=student_attempts_raw,
                teacher_id=resolved_teacher_email,
                teacher_refinement=refined_notes_with_header,
                struggling_words=struggling_words_str,
                test_name=assessment_name,
                test_date=st.session_state.get(f"assessment_date_{student_id}"),
            ):
                # 1. Ingest calibration data as before
                original_notes = getattr(st.session_state.get('analysis_result'), 'teacher_notes', '')
                ai_suggested_list_for_calibration = st.session_state.get('targets_display', [])
                ai_suggested_group_for_calibration = ai_suggested_list_for_calibration[0] if ai_suggested_list_for_calibration else 'Unassigned'

                ingest_teacher_calibration(
                    student_id=student_id,
                    assessment_id=None,
                    ai_suggested_group=ai_suggested_group_for_calibration,
                    teacher_assigned_group=final_group,
                    teacher_feedback=teacher_feedback,
                    original_notes=original_notes,
                    refined_notes=refined_notes_with_header
                )

                st.toast("Assessment saved and calibration logged!")
                st.success("Assessment saved and calibration logged successfully!")
                time.sleep(1)

                # Clean up state ON SUCCESS so UI resets to default state
                for key in [
                    f"edited_transcription_{student_id}", "final_diagnostic_notes", "raw_report_notes",
                    f"logic_feedback_{student_id}", "analysis_result", "evaluator_result",
                    "g_scores_display", "targets_display", "processed_intended_words",
                    f"uploaded_file_cache_{student_id}", "teacher_refined_group", "student_attempts_for_report"
                ]:
                    if key in st.session_state:
                        del st.session_state[key]

                st.rerun()
            else:
                st.error("Failed to save assessment. Please check terminal logs.")

def render_orthographic_analysis(evaluation_result: dict):
    """
    Renders the Granular Orthographic Analysis view:
    1. Target Stage Placement Banner (lowest stage below 90% accuracy).
    2. Visual Stage Accuracy Profile (Bar chart) + Numerical breakdown for G0-G8.
    """
    if not evaluation_result:
        st.warning("No evaluation data available to display.")
        return

    assigned_group_key = evaluation_result.get("assigned_group_key", "")
    assigned_group_name = evaluation_result.get("assigned_group_name", "Undetermined")
    word_evals = evaluation_result.get("word_evaluations", [])

    # ---------------------------------------------------------
    # 1. FILTER STRICTLY FOR ATTEMPTED WORDS
    # ---------------------------------------------------------
    attempted_word_evals = [
        w for w in word_evals
        if w.get("student_attempt") and str(w.get("student_attempt")).strip()
    ]

    # Recalculate group stats based ONLY on attempted words
    group_stats = {g_key: {"earned": 0, "total": 0} for g_key in constants.DIAGNOSTIC_GROUPS.keys()}

    for w in attempted_word_evals:
        target = w.get("target_features", {})
        passed = w.get("passed_features", {})
        for g_key, patterns in target.items():
            if g_key in group_stats:
                passed_pats = passed.get(g_key, [])
                group_stats[g_key]["total"] += len(patterns)
                group_stats[g_key]["earned"] += len(passed_pats)

    # Build active group data list
    active_group_data = []
    for g_key, group_info in constants.DIAGNOSTIC_GROUPS.items():
        total = group_stats[g_key]["total"]
        earned = group_stats[g_key]["earned"]
        if total > 0:
            pct = round((earned / total) * 100, 1)
            active_group_data.append({
                "Group": g_key.upper(),
                "Group Name": group_info.get("name", "Feature"),
                "Accuracy (%)": pct,
                "Earned": earned,
                "Total": total,
                "Status": "Mastered" if pct >= 90.0 else "Focus Area"
            })

    # ---------------------------------------------------------
    # 2. TARGET FOCUS STAGE DISPLAY (NO OVERALL SCORE)
    # ---------------------------------------------------------
    st.markdown("## Granular Orthographic Analysis")

    if assigned_group_key and assigned_group_key != "mastered":
        st.info(
            f"**Target Focus Stage:** {assigned_group_key.upper()} ({assigned_group_name}) — "
            f"Lowest stage with accuracy below the 90% threshold."
        )
    else:
        st.success(
            f"**Stage Mastered ({assigned_group_name}):** "
            f"Student demonstrated 90% or higher accuracy across evaluated stages."
        )

    st.markdown("---")

    # ---------------------------------------------------------
    # 3. VISUAL CHART & NUMERICAL BREAKDOWN (G0 - G9)
    # ---------------------------------------------------------
    st.markdown("### Stage Accuracy Profile (G0 - G9)")

    if active_group_data:
        df_groups = pd.DataFrame(active_group_data)

        st.caption("Feature Accuracy Profile (%)")
        chart_df = df_groups.set_index("Group")[["Accuracy (%)"]]
        st.bar_chart(chart_df, height=260)
    else:
        st.info("No diagnostic feature targets found in the attempted words.")

    st.markdown("---")

    # =========================================================
    # 3-4. GRANULAR WORD-BY-WORD FEATURE BADGES
    # =========================================================
    st.markdown("### Word-by-Word Feature Breakdown")

    for word_eval in word_evals:
        intended = word_eval.get("intended_word", "")
        attempt = word_eval.get("student_attempt", "")
        is_correct = word_eval.get("is_correct", False)
        passed = word_eval.get("passed_features", {})
        missed = word_eval.get("missed_features", {})
        target = word_eval.get("target_features", {})

        status_icon = "✅" if is_correct else "❌"

        # Build inline colored pills for each feature
        badges_html = []
        for g_key, patterns in target.items():
            g_upper = g_key.upper()
            passed_pats = passed.get(g_key, [])

            for pat in patterns:
                if pat in passed_pats:
                    # Green pill for successfully encoded feature
                    badges_html.append(
                        f'<span style="background-color:#d4edda; color:#155724; border: 1px solid #c3e6cb; '
                        f'padding:3px 8px; border-radius:12px; font-weight:600; margin-right:4px; font-size:13px;">'
                        f'[{g_upper}] {pat} ✓</span>'
                    )
                else:
                    # Red pill for missed feature
                    badges_html.append(
                        f'<span style="background-color:#f8d7da; color:#721c24; border: 1px solid #f5c6cb; '
                        f'padding:3px 8px; border-radius:12px; font-weight:600; margin-right:4px; font-size:13px;">'
                        f'[{g_upper}] {pat} ✗</span>'
                    )

        badge_str = " ".join(badges_html) if badges_html else "<em>No feature targets</em>"

        # Correct words start collapsed; incorrect words automatically expand for quick inspection
        with st.expander(f"{status_icon} **{intended.upper()}** → Student attempt: *'{attempt}'*", expanded=not is_correct):
            st.markdown(f"**Features Tested:** {badge_str}", unsafe_allow_html=True)

# =============================================================================
# ADMIN PAGE
# =============================================================================
def display_admin_page():
    if st.session_state.get('user_email', '').lower().strip() != ADMIN_EMAIL.lower().strip():
        st.error("Admin access required.")
        return

    st.header("Admin Dashboard")

    # Teacher Account Management Section
    st.subheader("Teacher Account Management")
    with st.expander("Create Teacher Account", expanded=False):
        with st.form("create_teacher_form", clear_on_submit=True):
            teacher_email = st.text_input("Teacher Email (required)", placeholder="teacher@example.com")
            teacher_name = st.text_input("Teacher Full Name (optional)", placeholder="Jane Doe")

            if st.form_submit_button("Create Teacher Account", type="primary"):
                if teacher_email:
                    # Normalize email to lowercase
                    normalized_email = teacher_email.lower().strip()
                    name = teacher_name.strip() if teacher_name else normalized_email.split('@')[0].title()

                    if register_teacher(normalized_email, name):
                        st.success(f"Teacher account created for {normalized_email}")
                        st.rerun()
                    else:
                        st.error("Failed to create teacher account. Email may already exist.")
                else:
                    st.error("Teacher email is required.")

    st.markdown("---")

    with st.expander("CSV Data Management"):
        st.subheader("CSV File Status")
        students_csv_exists = os.path.exists("students.csv")
        assessments_csv_exists = os.path.exists("assessments.csv")

        col_status1, col_status2 = st.columns(2)
        with col_status1:
            if students_csv_exists:
                st.success("students.csv: FOUND")
            else:
                st.error("students.csv: MISSING")
        with col_status2:
            if assessments_csv_exists:
                st.success("assessments.csv: FOUND")
            else:
                st.error("assessments.csv: MISSING")

        st.markdown("---")
        if st.button("FORCE IMPORT FROM CSV", type="primary", use_container_width=True):
            with st.spinner("Importing data..."):
                result = import_from_csv()
                sync_result = sync_identity_from_assessments()
                st.success("Import Complete!")
                st.write(f"• Students imported: {result['students']}")
                st.write(f"• Assessments imported: {result['assessments']}")
                st.write(f"• Identity records synced: {sync_result['created']}")
            st.rerun()

    st.markdown("---")

    with st.expander("Database Maintenance"):
        stats = get_database_stats()
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.metric("Total Assessments", stats.get('total_assessments', 0))
            st.metric("Total Students", stats.get('total_students', 0))
        with col_s2:
            st.metric("Orphaned Students", stats.get('orphaned_students', 0))
            st.metric("Orphaned Assessments", stats.get('orphaned_assessments', 0))

        if st.button("Fix All Teacher IDs", use_container_width=True):
            result = fix_all_teacher_ids()
            st.success(f"Fixed! Synced {result['students_synced']} students.")
            st.rerun()

    st.markdown("---")

    # Student Management Section
    st.subheader("Student Management")
    with st.expander("Student Management Control Panel", expanded=False):
        # Add Student under Teacher
        st.write("### Add New Student")
        all_teachers_list = get_all_teachers()

        if not all_teachers_list:
            st.warning("No teachers available. Create a teacher account first.")
        else:
            with st.form("add_student_form", clear_on_submit=True):
                col_name, col_teacher, col_group = st.columns([2, 2, 1])
                with col_name:
                    new_student_name = st.text_input("Student Name", placeholder="John Smith")
                with col_teacher:
                    teacher_options = {f"{t['name']} ({t['email']})": t['email'] for t in all_teachers_list}
                    selected_teacher = st.selectbox("Assign to Teacher", options=list(teacher_options.keys()))
                with col_group:
                    group_options = list(constants.DIAGNOSTIC_GROUPS.keys())
                    selected_group = st.selectbox("Starting Group", options=group_options, index=1)

                if st.form_submit_button("Add Student", type="primary"):
                    if new_student_name:
                        teacher_email = teacher_options[selected_teacher]
                        if add_student(teacher_email, new_student_name, selected_group):
                            st.success(f"Student {new_student_name} added to {selected_teacher}")
                            st.rerun()
                        else:
                            st.error("Failed to add student.")
                    else:
                        st.error("Student name is required.")

        st.markdown("---")

        # Move & Delete Student List
        st.write("### All Students")
        all_students = get_all_students_for_allocation()

        if not all_students:
            st.info("No students found in database.")
        else:
            st.write(f"{len(all_students)} students total")

            for i, student in enumerate(all_students):
                with st.container():
                    col_name, col_teacher, col_move, col_delete = st.columns([2, 2, 2, 1])

                    with col_name:
                        st.markdown(f"**{student['name']}**")
                        st.caption(f"ID: {student['student_id']}")

                    with col_teacher:
                        current_teacher = student['teacher_id'] or "Unassigned"
                        st.write(f"Teacher: {current_teacher}")

                    with col_move:
                        teacher_display_options = ["Unassigned"] + [f"{t['name']} ({t['email']})" for t in all_teachers_list]
                        teacher_emails = [None] + [t['email'] for t in all_teachers_list]

                        current_idx = 0
                        if student['teacher_id'] and student['teacher_id'] in teacher_emails:
                            current_idx = teacher_emails.index(student['teacher_id'])

                        selected_display = st.selectbox(
                            "Move to:",
                            options=teacher_display_options,
                            index=current_idx,
                            key=f"move_select_{i}_{student['student_id']}",
                            label_visibility="collapsed"
                        )

                    with col_delete:
                        if st.button("Delete", key=f"delete_btn_{i}_{student['student_id']}", type="secondary"):
                            st.session_state[f"confirm_delete_{student['student_id']}"] = True
                            st.rerun()

                    # Update button for move
                    col_move_btn, _ = st.columns([1, 3])
                    with col_move_btn:
                        if st.button("Update", key=f"move_btn_{i}_{student['student_id']}", use_container_width=True):
                            new_teacher = None if selected_display == "Unassigned" else selected_display.split('(')[-1].replace(')', '')
                            if update_student_teacher(student['student_id'], new_teacher):
                                st.success("Student moved!")
                                st.rerun()
                            else:
                                st.error("Failed to move student.")

                    # Delete confirmation
                    if st.session_state.get(f"confirm_delete_{student['student_id']}"):
                        st.warning(f"⚠️ Are you sure you want to delete {student['name']}? This will also delete all their assessment records.")
                        col_confirm, col_cancel = st.columns([1, 1])
                        with col_confirm:
                            if st.button("Yes, Delete", key=f"confirm_yes_{student['student_id']}", type="primary"):
                                if delete_student(student['student_id']):
                                    st.success("Student deleted successfully.")
                                    del st.session_state[f"confirm_delete_{student['student_id']}"]
                                    st.rerun()
                                else:
                                    st.error("Failed to delete student.")
                        with col_cancel:
                            if st.button("Cancel", key=f"confirm_cancel_{student['student_id']}"):
                                del st.session_state[f"confirm_delete_{student['student_id']}"]
                                st.rerun()

                    st.divider()

    st.markdown("---")

    st.subheader("Platform Administrator Report: Active AI Corrections")
    from ai_learning_engine import get_unified_learning_ledger
    ledger_data = get_unified_learning_ledger()

    if not ledger_data:
        st.info("No AI calibrations recorded yet.")
    else:
        df_ledger = pd.DataFrame(ledger_data)
        cols_to_show = {
            "timestamp": "Timestamp",
            "student_id": "Student ID",
            "ai_suggested_group": "AI Group",
            "teacher_assigned_group": "Teacher Group",
            "teacher_feedback": "Teacher Note",
            "calibration_note": "AI Calibration"
        }
        available_cols = [c for c in cols_to_show.keys() if c in df_ledger.columns]
        display_df = df_ledger[available_cols].rename(columns=cols_to_show)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
    # Insert inside display_admin_page()
    st.markdown("---")
    with st.expander("AI Models & Health Dashboard", expanded=True):
        st.subheader("Model Usage & Error Monitoring")

        summary, recent_logs = db.get_model_logs()

        if summary:
            # Display aggregated stats
            df_summary = pd.DataFrame(
                summary, columns=["Model Name", "Status", "Total Calls"]
            )
            st.dataframe(df_summary, use_container_width=True, hide_index=True)
        else:
            st.info("No AI model activity logged yet.")

        if recent_logs:
            st.subheader("Recent Execution Logs & Errors")
            df_logs = pd.DataFrame(
                recent_logs,
                columns=[
                    "Timestamp",
                    "Model Name",
                    "Status",
                    "Function",
                    "Error Details",
                ],
            )
            st.dataframe(df_logs, use_container_width=True, hide_index=True)

# =============================================================================
# MAIN ENTRYPOINT
# =============================================================================
if __name__ == "__main__":
    main()
