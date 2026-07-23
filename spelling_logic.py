import os
import json
import re
import time
import litellm
from dotenv import load_dotenv
from litellm import completion
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
def transcribe_handwriting(image_base64: str, intended_words: str = "") -> str:
    """
    OCR transcription with rate-limit retries and clean model fallbacks.
    """
    # 1. DEFINE THE PROMPT BEFORE CALLING THE MODEL
    prompt = (
        "You are an expert handwriting reader for primary school spelling tests. "
        f"The intended target words for this assessment are: {intended_words}.\n"
        "Transcribe the student's handwritten attempts line by line. "
        "Return ONLY the transcribed list of words, one per line."
    )

    # 2. ACTIVE VISION MODELS (Gemini 2.0 Flash is the primary vision model)
    vision_models = [
        "gemini/gemini-2.0-flash",
        "gemini/gemini-1.5-flash",
    ]

    for model in vision_models:
        try:
            response = litellm.completion(
                model=model,
                messages=[
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
                ],
                timeout=20
            )
            
            result = response.choices[0].message.content.strip()
            
            # Check for generic safety refusal strings
            if result and not result.startswith("User Safety:"):
                return result

        except litellm.exceptions.RateLimitError:
            # Pause briefly if free-tier per-second quota is hit
            time.sleep(3)
            continue
        except Exception as e:
            print(f"[OCR Warning] Model {model} failed -> {e}")
            continue

    raise RuntimeError("All configured OCR vision models failed. Please check your API keys or try again in a few seconds.")


def process_full_assessment(
    student_id, assessment_id, transcriptions, intended_words=None, evaluator_result=None
):
    """Orchestrates Granular Orthographic Analysis + Prescriptive AI Analysis."""
    if isinstance(transcriptions, list) and transcriptions:
        if isinstance(transcriptions[0], dict):
            intended_list = [item.get("intended_word", "").strip() for item in transcriptions]
            transcribed_list = [item.get("student_attempt", "").strip() for item in transcriptions]
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
    Analyze these spelling assessment feature results for Student ID {student_id}:
    {feature_results}
    
    Provide a concise, 3-bullet-point prescriptive coaching guide for the teacher focusing on orthographic patterns, core gaps, and immediate next steps.
    """

    prescriptive_feedback = ""
    try:
        res = completion(
            model="gemini/gemini-1.5-flash",
            api_key=get_api_key("gemini"),
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.3,
        )
        prescriptive_feedback = res.choices[0].message.content
        db.log_model_event("gemini/gemini-1.5-flash", "success", action="prescriptive_analysis")
    except Exception as e:
        print(f"[Prescriptive Analysis Warning] LLM failed: {e}")
        prescriptive_feedback = "Assessment recorded successfully. Feature analysis completed."

    return {
        "feature_results": feature_results,
        "prescriptive_feedback": prescriptive_feedback,
    }


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
        print(f"Notice: Could not retrieve teacher notes for {student_id}: {e}")

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
{{
  "student_id": "{student_id}",
  "diagnostic_summary": "2-3 sentence overview of error patterns, phonological vs orthographic issues, and strengths.",
  "phonetic_stage_level": "Name of developmental spelling stage (Emergent, Letter Name - Alphabetic, Within Word Pattern, Syllables & Affixes, Derivational Relations)",
  "recommended_focus_areas": ["Focus area 1", "Focus area 2"],
  "coaching_tips": ["Actionable mini-lesson or classroom strategy 1", "Actionable strategy 2"]
}}
"""

    try:
        response = completion(
            model="gemini/gemini-1.5-flash",
            api_key=get_api_key("gemini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        raw_output = response.choices[0].message.content.strip()

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
You are an Un.Box.Ed. coach analyzing a student's spelling trajectory.

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
        response = completion(
            model="gemini/gemini-1.5-flash",
            api_key=get_api_key("gemini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Coaching currently unavailable: {str(e)}"


# --- 6. PERSONALIZED PRACTICE WORD GENERATION ---
word_generator = Agent(
    role="Personalized Spelling Word Selector",
    goal="Generate 10 highly targeted spelling words for a specific student based on their G-level and struggle areas",
    backstory="You are an expert literacy specialist creating targeted practice lists for ESL/Mandarin L1 learners.",
    llm="groq/llama-3.3-70b-versatile",
    allow_delegation=False
)


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
    
    task_description = f"""
Create a 10-word practice list for {student_alias}.
Target: {target_group.upper()} - {group_info['name']}
Patterns: {group_info['patterns']}
{notes_context}{struggling_context}{mastered_context}{unit_context}{custom_words_context}

Return ONLY a valid JSON array of 10 strings: ["word1", "word2", ..., "word10"]
"""
    
    task = Task(
        description=task_description,
        agent=word_generator,
        expected_output="JSON array of 10 spelling words"
    )
    
    crew = Crew(agents=[word_generator], tasks=[task])
    
    try:
        crew_output = crew.kickoff()
        output_text = str(crew_output)
        
        json_match = re.search(r'\[.*?\]', output_text, re.DOTALL)
        if json_match:
            words = json.loads(json_match.group(0))
            if isinstance(words, list) and len(words) >= 1:
                return words[:10]
        
        cleaned = output_text.strip('[]').replace('"', '').replace("'", '')
        words = [w.strip() for w in cleaned.split(',') if w.strip()]
        return words[:10] if words else get_fallback_words(group_key)
        
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
    try:
        response = completion(
            model="groq/llama-3.3-70b-versatile",
            api_key=get_api_key("groq"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"AI self-reflection failed: {str(e)}"


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