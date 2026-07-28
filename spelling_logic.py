import os
import json
import re
import time
from model_manager import run_model_chain
from dotenv import load_dotenv
from crewai import Agent, Task, Crew
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import streamlit as st

import database_manager as db
import feature_evaluator

load_dotenv()

# --- 0. API KEY RESOLUTION ---
def get_api_key(provider: str) -> str:
    """Explicitly fetch API keys from environment variables."""
    if provider == "gemini":
        return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    elif provider == "openrouter":
        return (os.getenv("OPENROUTER_API_KEY") or "").strip()
    elif provider == "groq":
        return (os.getenv("GROQ_API_KEY") or "").strip()
    return ""


# --- 1. DYNAMIC WORD LIST LOGIC ---
def get_target_words(file_name="primary_inventory.txt"):
    folder_path = os.path.join("assessments", file_name)
    try:
        with open(folder_path, "r") as f:
            words = [line.strip() for line in f.readlines() if line.strip()]
            return ", ".join(words)
    except FileNotFoundError:
        return "fan, pet, dig, rob, hope, wait, gum, sled, stick, shine"

CURRENT_TEST_WORDS = get_target_words()


# --- 2. QUALITATIVE DIAGNOSIS DATA SCHEMA ---
class DiagnosisResultSchema(BaseModel):
    student_id: str = Field(default="The Student")
    diagnostic_summary: str = Field(description="2-3 sentences explaining primary error trends and strengths")
    phonetic_stage_level: str = Field(description="Developmental spelling stage level (e.g. Letter Name - Alphabetic)")
    recommended_focus_areas: List[str] = Field(description="1-3 targeted linguistic areas for immediate focus")
    coaching_tips: List[str] = Field(description="Actionable mini-lesson ideas or activities for the teacher")


def extract_transcription(raw_output: str) -> str:
    """
    Extracts clean handwriting transcription data from LLM responses.
    Handles single-line (word: attempt) and two-line (target: X / transcription: Y) formats.
    """
    if not raw_output or not isinstance(raw_output, str):
        return ""

    text = raw_output.strip()

    # Phase 1: Strip <think> tags
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<think>.*$', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip()

    if not text and raw_output:
        text = re.sub(r'<[^>]+>', '', raw_output).strip()

    # Phase 2: Strip Markdown code fences
    code_block_match = re.search(
        r'```(?:json|text|markdown)?\s*\n?(.*?)\n?```', 
        text, 
        flags=re.DOTALL | re.IGNORECASE
    )
    if code_block_match:
        text = code_block_match.group(1).strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Phase 3A: Detect Two-Line Format (target: X \n transcription: Y)
    i = 0
    two_line_pairs = []
    while i < len(lines) - 1:
        l1 = re.sub(r'^(?:\d+[\.\)]|\*|-)\s*', '', lines[i]).strip()
        l2 = re.sub(r'^(?:\d+[\.\)]|\*|-)\s*', '', lines[i+1]).strip()
        
        m1 = re.match(r'^(?:target|intended|word)\s*[:=\-]\s*([a-zA-Z\'\-]+)$', l1, re.I)
        m2 = re.match(r'^(?:transcription|attempt|student|student_attempt)\s*[:=\-]\s*([a-zA-Z\'\-]+)$', l2, re.I)
        
        if m1 and m2:
            two_line_pairs.append(f"{m1.group(1).lower()}: {m2.group(1).lower()}")
            i += 2
        else:
            i += 1

    if two_line_pairs:
        return "\n".join(two_line_pairs)

    # Phase 3B: Standard Single-Line Format (word: attempt)
    clean_pairs = []
    for line in lines:
        line = re.sub(r'^(?:\d+[\.\)]|\*|-)\s*', '', line).strip()
        match = re.match(r'^([a-zA-Z]+)\s*[:=\-]\s*([a-zA-Z\'\-]+)$', line)
        if match:
            k, v = match.groups()
            if k.lower() not in ['target', 'intended', 'transcription', 'attempt', 'student']:
                clean_pairs.append(f"{k.lower()}: {v.lower()}")

    if clean_pairs:
        return "\n".join(clean_pairs)

    return text


# --- 3. VISION TRANSCRIPTION (OCR) ---
def clean_ocr_text(text: str) -> str:
    """Strips reasoning blocks, markdown fences, and extra chatter."""
    if not text:
        return ""
    cleaned = re.sub(r"<(thinking|think)>.*?</\1>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<(thinking|think)>.*$", "", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"```[a-zA-Z]*\n?", "", cleaned)
    return cleaned.replace("```", "").strip()


def transcribe_handwriting(image_base64: str, intended_words: str = "") -> list[dict]:
    """
    Transcribes handwriting and pairs each item directly with its target word.
    Returns a list of dicts: [{'number': '1', 'intended': 'blade', 'attempt': 'blad'}, ...]
    """
    prompt = (
        "You are an expert handwriting reader for primary school spelling tests.\n"
        f"The intended target words for this assessment in order are: {intended_words}.\n\n"
        "Instructions:\n"
        "1. Match each line of handwriting to the corresponding intended target word.\n"
        "2. Transcribe the exact letters the student wrote for each item.\n"
        "3. Output strictly line by line in this format: Number | Intended | Attempt\n"
        "Example output:\n"
        "1 | fun | fun\n"
        "12 | blade | blad\n"
        "14 | fright | frite\n\n"
        "CRITICAL: Do NOT include preamble, markdown table headers, or extra commentary. Return ONLY the formatted lines."
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                }
            ]
        }
    ]

    # Delegate OCR call to model manager
    raw_response = run_model_chain(task_type="vision", messages=messages, temperature=0.0)

    if not raw_response:
        raise RuntimeError("All configured OCR vision models failed in model_manager.")

    print(f"\n--- [DEBUG: RAW OCR MODEL OUTPUT] ---\n{raw_response}\n------------------------------------\n")

    cleaned_text = clean_ocr_text(raw_response)

    parsed_results = []
    for line in cleaned_text.splitlines():
        line = line.strip()
        if not line or line.startswith("---"):
            continue

        # Strip outer pipes if model formatted as markdown table "| 1 | word | attempt |"
        if line.startswith("|") and line.endswith("|"):
            line = line[1:-1].strip()

        parts = [p.strip() for p in line.split("|")]

        # Skip header rows
        if len(parts) >= 3 and parts[0].lower() in ["number", "#", "no", "item"]:
            continue

        if len(parts) == 3:
            parsed_results.append({
                "number": parts[0],
                "intended": parts[1],
                "attempt": parts[2]
            })
        else:
            # Fallback regex for formats like "1. blade: blad" or "blade -> blad"
            match = re.match(r'^(?:\d+[\.\)]|\*|-)?\s*(\d+)?\s*\|?\s*([a-zA-Z\'\-]+)\s*[:=\|\-\>]+\s*([a-zA-Z\'\-]+)$', line)
            if match:
                num, target, attempt = match.groups()
                parsed_results.append({
                    "number": num if num else str(len(parsed_results) + 1),
                    "intended": target,
                    "attempt": attempt
                })

    return parsed_results


def process_full_assessment(
    student_id, assessment_id, transcriptions, intended_words=None, evaluator_result=None, teacher_id=None
):
    """Orchestrates Granular Orthographic Analysis + Prescriptive AI Analysis."""
    if isinstance(transcriptions, list) and transcriptions:
        if isinstance(transcriptions[0], dict):
            # Sort by word number first so out-of-order sheets (student wrote
            # across instead of down) still pair correctly with the word list.
            def safe_num(item):
                try:
                    return int(item.get("number", 0))
                except (ValueError, TypeError):
                    return 0

            sorted_transcriptions = sorted(transcriptions, key=safe_num)

            intended_list = [
                (item.get("intended_word") or item.get("intended") or "").strip()
                for item in sorted_transcriptions
            ]
            transcribed_list = [
                (item.get("student_attempt") or item.get("attempt") or "").strip()
                for item in sorted_transcriptions
            ]
        else:
            transcribed_list = transcriptions
            intended_list = intended_words if intended_words is not None else []
    else:
        transcribed_list = []
        intended_list = intended_words if intended_words is not None else []

    if evaluator_result is not None:
        feature_results = evaluator_result
    else:
        feature_results = feature_evaluator.evaluate_spelling_attempt(
            student_id=str(student_id),
            transcribed_words=transcribed_list,
            intended_words=intended_list,
        )

    try:
        if hasattr(db, "save_assessment_results"):
            db.save_assessment_results(assessment_id, feature_results)
        elif hasattr(db, "save_assessment"):
            db.save_assessment(assessment_id, feature_results)
        elif hasattr(db, "save_assessment_data"):
            db.save_assessment_data(assessment_id, feature_results)
    except Exception as db_err:
        print(f"[DB Warning] Failed to save assessment results: {db_err}")

    
    summary_prompt = f"""
    You are an expert primary school literacy coach.

    Analyze these spelling assessment feature results for [Student]:
    {feature_results}

    RULES:
    - Always refer to the child as '[Student]' in your commentary.
    - Provide clear, actionable feedback for the teacher.

    TASK:
    First, identify the SINGLE most urgent skill gap [Student] needs to work on next —
    the one issue that, if addressed first, will unlock the most progress. State it as
    one specific, narrow pattern (e.g. "short vowel vs. long vowel with silent-e (CVC
    vs CVCe)" or "sh/ch/ck digraph confusion"), not a broad category like "vowels."

    Then provide a concise, 3-bullet-point prescriptive coaching guide, formatted
    EXACTLY like this:

    IMMEDIATE PRIORITY: <one sentence naming the single most urgent, specific pattern
    to address first, and why it matters most right now>

    • Orthographic Strengths & Core Gaps: <observation>
    • Targeted Instructional Focus: <how to teach the immediate priority above>
    • Immediate Actionable Next Steps: <activities/strategies>
    """
    prescriptive_feedback = run_model_chain(
        task_type="text",
        messages=[{"role": "user", "content": summary_prompt}],
        temperature=0.3
    ) or "Assessment recorded successfully. Feature analysis completed."

    return {
        "feature_results": feature_results,
        "prescriptive_feedback": prescriptive_feedback,
    }

def process_assessment_response(response_data, student_name: str, raw_student_id: str):
    """
    Cleans up LLM JSON/dict responses:
    - Replaces '[Student]' placeholders with student_name for UI display.
    - Preserves raw_student_id under 'student_id' for backend database storage.
    """
    def replace_placeholder(obj):
        if isinstance(obj, str):
            return obj.replace("[Student]", student_name)
        elif isinstance(obj, list):
            return [replace_placeholder(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: replace_placeholder(v) for k, v in obj.items()}
        return obj

    if isinstance(response_data, dict):
        formatted_data = replace_placeholder(response_data)
        formatted_data["student_id"] = raw_student_id
        return formatted_data
    elif isinstance(response_data, str):
        return response_data.replace("[Student]", student_name)
    
    return response_data
# --- 4. QUALITATIVE AI DIAGNOSIS ENGINE ---
def diagnose_errors(
    student_id: str,
    evaluation_result: Dict[str, Any],
    analysis_complexity: str = "Standard"
) -> Dict[str, Any]:
    """
    Consumes deterministic EvaluationResult output from feature_evaluator.py
    and generates qualitative pedagogical coaching.
    """
    teacher_notes = None
    try:
        teacher_notes = db.get_latest_teacher_notes(student_id)
    except Exception as e:
        print(f"Notice: Could not retrieve teacher notes for [Student]: {e}")

    notes_context = f"\nPREVIOUS TEACHER NOTES FOR THIS STUDENT:\n{teacher_notes}\n" if teacher_notes else ""

    total_score = evaluation_result.get("total_score", 0)
    max_score = evaluation_result.get("max_score", 0)
    word_evals = evaluation_result.get("word_evaluations", [])
    feature_summary = evaluation_result.get("feature_summary", {})

    word_details_formatted = []
    for w in word_evals:
        status = "CORRECT" if w.get("is_correct") else "INCORRECT"
        missed = f" (Missed features: {w.get('missed_features')})" if w.get("missed_features") else ""
        word_details_formatted.append(
            f"- Intended: '{w.get('intended_word')}' | Attempt: '{w.get('student_attempt')}' | {status}{missed}"
        )

    word_details_str = "\n".join(word_details_formatted)
    feature_summary_str = json.dumps(feature_summary, indent=2)

    prompt = f"""
        You are an expert literacy specialist and reading coach evaluating a student's Primary Spelling Inventory (PSI) assessment.

        CRITICAL INSTRUCTION:
        Do NOT recalculate total scores or re-evaluate right/wrong answers. The deterministic evaluation engine has already scored this assessment.
        Focus strictly on qualitative pedagogical diagnosis, stage level placement, and teacher coaching recommendations.

        === DETERMINISTIC EVALUATION DATA ===
        - Overall Score: {total_score} / {max_score}
        - Feature Summary (G0-G8 Performance Matrix):
        {feature_summary_str}

        - Word-by-Word Analysis:
        {word_details_str}
        {notes_context}
        ANALYSIS COMPLEXITY: {analysis_complexity}

        === FORMATTING RULES ===
        - When referring to a SOUND (Phoneme), use slashes (e.g., /θ/, /d/, /st/).
        - When referring to a WRITTEN LETTER or PATTERN (Grapheme), use angle brackets (e.g., <th>, <ed>, <st>).

        Respond ONLY with a valid JSON object matching this structure:
{
  "student_id": "[Student]",
  "diagnostic_summary": "2-3 sentence overview of [Student]'s error patterns, phonological vs orthographic issues, and strengths.",
  "phonetic_stage_level": "Name of developmental spelling stage (Emergent, Letter Name - Alphabetic, Within Word Pattern, Syllables & Affixes, Derivational Relations)",
  "recommended_focus_areas": ["Focus area 1", "Focus area 2"],
  "coaching_tips": ["Actionable mini-lesson or classroom strategy 1", "Actionable strategy 2"]
}
"""

    try:
        raw_output = run_model_chain(
            task_type="text",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        if not raw_output:
            raise ValueError("No response from model manager")

        raw_output = raw_output.strip()
        if raw_output.startswith("```json"):
            raw_output = raw_output.split("```json")[1].split("```")[0].strip()
        elif raw_output.startswith("```"):
            raw_output = raw_output.split("```")[1].split("```")[0].strip()

        return json.loads(raw_output)

    except Exception as e:
        print(f"Error in diagnose_errors: {e}")
        return {
            "student_id": student_id,
            "diagnostic_summary": f"Qualitative analysis unavailable due to an engine response error: {str(e)}",
            "phonetic_stage_level": "Undetermined",
            "recommended_focus_areas": [],
            "coaching_tips": []
        }


# --- 5. HOLISTIC COACHING REPORT ---
# --- 5. HOLISTIC COACHING REPORT ---
def get_ai_coaching_report(student_alias, g_level, history=None):
    """Sends holistic student history to Gemini and returns a coaching plan."""
    history_context = "No previous assessments."
    recent_context = ""
    
    if history and len(history) > 0:
        history_entries = []
        for i, entry in enumerate(history):
            test_date = entry.get('created_at', f"Assessment {i+1}")
            g_scores = f"G0:{entry.get('g0_phonemic', 0)}%, G1:{entry.get('g1_cvc', 0)}%, G2:{entry.get('g2_digraphs', 0)}%, G3:{entry.get('g3_silent_e', 0)}%, G4:{entry.get('g4_vowel_teams', 0)}%, G5:{entry.get('g5_r_controlled', 0)}%, G6:{entry.get('g6_clusters', 0)}%, G7:{entry.get('g7_multisyllabic', 0)}%, G8:{entry.get('g8_reduction', 0)}%"
            struggles = entry.get('struggling_words', "")
            notes = entry.get('teacher_refined_notes', "") or entry.get('teacher_notes', "")
            observations = entry.get('teacher_observations', "")
            raw_transcription = entry.get('raw_transcription', "")

            entry_str = f"--- {test_date[:10]} ---\nScores: {g_scores}\n"
            if raw_transcription:
                entry_str += f"Student's Writing: {raw_transcription}\n"
            if struggles:
                entry_str += f"Struggles: {struggles}\n"
            if observations:
                entry_str += f"Teacher Notes: {observations}\n"
            if notes:
                entry_str += f"AI Analysis: {notes}\n"

            history_entries.append(entry_str)

        history_context = "\n\n".join(history_entries)
        
        recent = history[-2:] if len(history) >= 2 else history
        recent_entries = []
        for entry in recent:
            struggles = entry.get('struggling_words', "")
            observations = entry.get('teacher_observations', "")
            raw_transcription = entry.get('raw_transcription', "")
            evidence_parts = []
            if raw_transcription:
                evidence_parts.append(f"Writing: {raw_transcription[:100]}...")
            if struggles:
                evidence_parts.append(f"Struggles: {struggles[:100]}...")
            if observations:
                evidence_parts.append(f"Notes: {observations[:100]}...")
            if evidence_parts:
                recent_entries.append("Recent: " + " | ".join(evidence_parts))
        recent_context = "\n".join(recent_entries) if recent_entries else ""
    
    prompt = f"""
You are an UnBoxEd coach analyzing a student's spelling trajectory.

Student: '{student_alias}'
Current G-Level: {g_level}

=== FULL ASSESSMENT HISTORY (Oldest to Newest) ===
{history_context}

=== RECENT ENTRIES (Higher Priority) ===
{recent_context}

Based on this holistic review:
1. Identify persistent phonetic struggles
2. Note any improvements or regression
3. Factor in teacher observations for context

Provide a coaching report with:
1. **Diagnostic Insight**: What phonetic patterns are they consistently missing?
2. **Evidence Section (CRITICAL)**: Provide specific word-level evidence for each mentioned G-Level.
3. **Progress Analysis**: Trajectory changes over time.
4. **Three Targeted Activities**: Specific practice for this week.
5. **Next Step Recommendation**: Clear direction for continued growth.
"""
    
    try:
        response = run_model_chain(
            task_type="text",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response if response else "AI Coaching currently unavailable."
    except Exception as e:
        print(f"Error generating coaching report: {e}")
        return "AI Coaching currently unavailable due to an engine error."


# --- 6. PERSONALIZED PRACTICE WORD GENERATION ---
def generate_personalized_practice_words(
    student_id, target_group, teacher_notes, struggling_words, 
    mastered_words="", unit_description="", custom_words_input=None
):
    student_alias = "The Student"
    
    GROUP_INFO = {
        "g0": {"name": "Phonemic Awareness", "patterns": "sound segmentation, blending", "examples": "bat-pat, cat-cut"},
        "g1": {"name": "Basic CVC Mapping", "patterns": "single consonants and short vowels", "examples": "cat, bed, sit"},
        "g2": {"name": "Digraphs", "patterns": "sh, ch, th, ng", "examples": "shop, chip, thin"},
        "g3": {"name": "Silent-e", "patterns": "a_e, i_e, o_e, u_e", "examples": "make, bike, hope"},
        "g4": {"name": "Vowel Teams", "patterns": "ee, ea, ai, oa, ou, oi", "examples": "see, rain, boat"},
        "g5": {"name": "R-Controlled Vowels", "patterns": "ar, or, er, ir, ur", "examples": "car, fork, her"},
        "g6": {"name": "Consonant Clusters/Blends", "patterns": "initial/final blends", "examples": "sled, stick, swim"},
        "g7": {"name": "Multisyllabic Words", "patterns": "syllable division", "examples": "rainbow, sunshine"},
        "g8": {"name": "Reduction & Morphology", "patterns": "schwa, -ed, -ing, suffixes", "examples": "walked, jumping"}
    }
    
    group_key = target_group.lower().strip()
    group_info = GROUP_INFO.get(group_key, GROUP_INFO["g1"])
    
    custom_words_context = f"\nTEACHER CUSTOM WORDS: {custom_words_input}" if custom_words_input else ""
    struggling_context = f"\nSTRUGGLING WORDS: {struggling_words}" if struggling_words else ""
    mastered_context = f"\nMASTERED WORDS: {mastered_words}" if mastered_words else ""
    notes_context = f"\nTEACHER NOTES: {teacher_notes}" if teacher_notes else ""
    unit_context = f"\nUNIT DESCRIPTION: {unit_description}" if unit_description else ""
    
    prompt = f"""
You are an expert literacy specialist creating a targeted spelling practice list for an ESL/Mandarin L1 learner.

Target Group: {target_group.upper()} - {group_info['name']}
General patterns for this group: {group_info['patterns']}
{notes_context}{struggling_context}{mastered_context}{unit_context}{custom_words_context}

INSTRUCTIONS:
1. If the notes above contain a line starting with "IMMEDIATE PRIORITY:", that names
   the single skill gap to address — build the entire list around it and ignore any
   other gaps mentioned elsewhere in the notes for this list.
2. If no such line is present, use your judgment to identify the single most urgent
   gap described in TEACHER NOTES or STRUGGLING WORDS, prioritizing these over the
   general group patterns below.
3. Once you've identified the one priority, use minimal pairs and closely related
   words that isolate exactly that contrast (e.g. hop/hope, rob/robe, slid/slide for
   short-vs-long vowel work) — don't mix in words touching unrelated patterns.
4. Do not repeat any word already listed under STRUGGLING WORDS above.

Return ONLY a valid JSON array of 10 strings: ["word1", "word2", ..., "word10"]
Do NOT include markdown formatting or extra text outside the JSON array.
"""
    
    try:
        raw_output = run_model_chain(
            task_type="text",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        
        if raw_output:
            json_match = re.search(r'\[.*?\]', raw_output, re.DOTALL)
            if json_match:
                words = json.loads(json_match.group(0))
                if isinstance(words, list) and len(words) >= 1:
                    return words[:10]
            
            cleaned = raw_output.strip('[]').replace('"', '').replace("'", '')
            words = [w.strip() for w in cleaned.split(',') if w.strip()]
            if words:
                return words[:10]
                
        return get_fallback_words(group_key)
        
    except Exception as e:
        print(f"Word generation error: {e}")
        return get_fallback_words(group_key)


# --- 7. DISCREPANCY & REFLECTION FEEDBACK ---
def get_ai_discrepancy_feedback(ai_analysis_context, teacher_correction_context, teacher_group_context, teacher_direct_feedback):
    prompt = f"""
You are an AI diagnostic system reflecting on your own performance.
ORIGINAL ANALYSIS: {ai_analysis_context}
TEACHER CORRECTION: {teacher_correction_context}
TEACHER GROUP ASSIGNMENT: {teacher_group_context}
TEACHER DIRECT FEEDBACK: {teacher_direct_feedback if teacher_direct_feedback else "None"}

Define your specific diagnostic error in 1-2 concise sentences.
Focus on where your diagnostic process diverged from the teacher's assessment.
"""
    response = run_model_chain(
        task_type="text",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2
    )
    return response.strip() if response else "AI self-reflection failed."



def get_fallback_words(target_group):
    fallback_by_group = {
        "g0": ["bat", "pat", "cat", "mat", "sat", "hat", "rat", "fat", "vat", "zat"],
        "g1": ["cat", "bed", "sit", "run", "hop", "map", "red", "big", "sun", "cup"],
        "g2": ["shop", "chip", "thin", "ring", "chin", "ship", "this", "that", "fish", "wish"],
        "g3": ["make", "bike", "hope", "cute", "cake", "side", "home", "note", "size", "game"],
        "g4": ["see", "sea", "rain", "boat", "sound", "day", "green", "team", "play", "snow"],
        "g5": ["car", "fork", "her", "bird", "turn", "star", "form", "burn", "hard", "work"],
        "g6": ["sled", "stick", "swim", "dress", "crash", "plant", "sleep", "green", "brick", "flash"],
        "g7": ["rainbow", "sunshine", "basket", "pencil", "window", "rabbit", "flower", "garden", "purple", "yellow"],
        "g8": ["walked", "jumping", "cats", "boxes", "unhappy", "quickly", "happier", "largest", "playing", "stopped"]
    }
    return fallback_by_group.get(target_group, fallback_by_group["g1"])