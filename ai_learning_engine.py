"""
AI Learning Engine Module for UnBoxEd.
Handles teacher calibration logs, discrepancy analysis, and fine-tuning ingestion hooks.
"""
import logging
from datetime import datetime
import database_manager as db

# Configure logging for calibration insights
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_learning_engine")


def generate_calibration_note(ai_suggested_group, teacher_assigned_group, original_notes, refined_notes):
    """
    Generates a diagnostic discrepancy summary comparing the AI suggestion 
    against the teacher override and notes.
    """
    ai_group = (ai_suggested_group or "Unassigned").upper()
    teacher_group = (teacher_assigned_group or "Unassigned").upper()
    
    if ai_group != teacher_group:
        note = f"Shifted placement from {ai_group} → {teacher_group}."
    else:
        note = f"Group placement confirmed ({teacher_group})."

    if original_notes and refined_notes and original_notes.strip() != refined_notes.strip():
        note += " Diagnostic notes refined by teacher."
    
    return note


def ingest_teacher_calibration(
    student_id, 
    assessment_id, 
    ai_suggested_group, 
    teacher_assigned_group, 
    teacher_feedback, 
    original_notes, 
    refined_notes
):
    """
    Ingests and processes teacher refinement actions to track where the AI 
    scoring model deviates from actual teacher diagnostic insights.
    
    Acts as the core feedback loop for continuous model calibration.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    ai_grp_clean = str(ai_suggested_group or "").strip().lower()
    teacher_grp_clean = str(teacher_assigned_group or "").strip().lower()
    
    # Identify if a discrepancy actually occurred
    has_discrepancy = 1 if (ai_grp_clean and teacher_grp_clean and ai_grp_clean != teacher_grp_clean) else 0
    
    calibration_note = generate_calibration_note(
        ai_suggested_group, 
        teacher_assigned_group, 
        original_notes, 
        refined_notes
    )
    
    logger.info(
        f"[{timestamp}] Ingesting calibration for student {student_id}. "
        f"Discrepancy: {bool(has_discrepancy)} ({ai_grp_clean} vs {teacher_grp_clean})"
    )

    try:
        logged = False

        # Hook 1: Primary macro discrepancy logger in database_manager
        if hasattr(db, 'log_ai_discrepancy'):
            db.log_ai_discrepancy(
                student_id=student_id,
                ai_suggested_group=ai_suggested_group,
                teacher_assigned_group=teacher_assigned_group,
                teacher_feedback=teacher_feedback
            )
            logged = True

        # Hook 2: Full calibration log table entry if function exists
        if hasattr(db, 'save_ai_calibration_log'):
            db.save_ai_calibration_log(
                student_id=student_id,
                assessment_id=assessment_id,
                ai_suggested=ai_suggested_group,
                teacher_assigned=teacher_assigned_group,
                feedback=teacher_feedback,
                has_discrepancy=has_discrepancy,
                calibration_note=calibration_note
            )
            logged = True

        # Hook 3: Fallback generic logger
        if not logged and hasattr(db, 'log_calibration_discrepancy'):
            db.log_calibration_discrepancy(
                student_id, 
                ai_suggested_group, 
                teacher_assigned_group, 
                teacher_feedback
            )
            logged = True

        if logged:
            logger.info(f"Calibration discrepancy event successfully persisted for student {student_id}.")
        else:
            logger.warning("Calibration received, but no active matching storage hook found in database_manager.py.")
        
        return True

    except Exception as e:
        logger.error(f"Failed to process teacher calibration context: {e}")
        return False


def get_unified_learning_ledger():
    """
    Fetches and unifies calibration logs and discrepancy entries across 
    database tables into a single ledger for the Admin Dashboard display.
    """
    ledger_entries = []

    try:
        # Check custom calibration log table first
        if hasattr(db, 'get_ai_calibration_logs'):
            logs = db.get_ai_calibration_logs()
            if logs:
                for entry in logs:
                    ledger_entries.append({
                        "timestamp": entry.get("timestamp", "N/A"),
                        "student_id": entry.get("student_id", "Unknown"),
                        "ai_suggested_group": (entry.get("ai_suggested") or entry.get("ai_suggested_group") or "N/A").upper(),
                        "teacher_assigned_group": (entry.get("teacher_assigned") or entry.get("teacher_assigned_group") or "N/A").upper(),
                        "teacher_feedback": entry.get("feedback") or entry.get("teacher_feedback") or "-",
                        "calibration_note": entry.get("calibration_note", "Macro-logic override recorded.")
                    })

        # Fallback to historical corrections / ai_discrepancies query interface
        if not ledger_entries and hasattr(db, 'get_historical_corrections'):
            corrections = db.get_historical_corrections()
            if corrections:
                for item in corrections:
                    ledger_entries.append({
                        "timestamp": item.get("created_at") or item.get("timestamp", "N/A"),
                        "student_id": item.get("student_id", "Unknown"),
                        "ai_suggested_group": str(item.get("ai_suggested_group", "N/A")).upper(),
                        "teacher_assigned_group": str(item.get("teacher_assigned_group", "N/A")).upper(),
                        "teacher_feedback": item.get("teacher_feedback", "-"),
                        "calibration_note": item.get("calibration_note", "Discrepancy logged.")
                    })

    except Exception as e:
        logger.error(f"Error reading unified learning ledger: {e}")

    return ledger_entries


def analyze_model_accuracy_trends():
    """
    Analyzes historical calibration data to report accuracy drifts 
    across different phonics focus levels ($G0\text{--}G8$).
    """
    ledger = get_unified_learning_ledger()
    if not ledger:
        return {"total_events": 0, "discrepancy_rate": 0.0, "level_accuracy": {}}

    total = len(ledger)
    discrepancies = 0
    level_counts = {}

    for entry in ledger:
        ai_grp = entry.get("ai_suggested_group", "").lower()
        teacher_grp = entry.get("teacher_assigned_group", "").lower()
        
        if ai_grp not in level_counts:
            level_counts[ai_grp] = {"total": 0, "matches": 0}
        
        level_counts[ai_grp]["total"] += 1
        if ai_grp == teacher_grp:
            level_counts[ai_grp]["matches"] += 1
        else:
            discrepancies += 1

    discrepancy_rate = (discrepancies / total) if total > 0 else 0.0
    
    level_accuracy = {}
    for grp, stats in level_counts.items():
        if stats["total"] > 0:
            level_accuracy[grp] = round(stats["matches"] / stats["total"], 2)

    return {
        "total_events": total,
        "discrepancy_rate": round(discrepancy_rate, 2),
        "level_accuracy": level_accuracy
    }