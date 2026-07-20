Architecture Specification: Decoupled Assessment & AI Coaching Pipeline
1. System Overview & Philosophy
The Un.Box.Ed. assessment pipeline separates deterministic phonetic evaluation from qualitative pedagogical coaching:
    1. Deterministic Rule Engine (feature_evaluator.py): Computes objective scores, target feature checks (G0–G8), and spelling error flags directly against constants.PSI_WORD_BANK. Eliminates LLM math/scoring hallucinations.  
    2.AI Pedagogical Engine (spelling_logic.py): Acts purely as a master reading coach. Takes structured outputs from feature_evaluator.py to generate qualitative error diagnoses and actionable teacher recommendations.  
    3. Teacher Feedback & Calibration Loop (app.py & ai_learning_engine.py): Teachers review and approve assessments. Any discrepancies or edits fuel the calibration system to refine AI performance over time.  
2. End-to-End Pipeline WorkflowPlaintext       
    ┌────────────────────────┐
    │   Student Photo / OCR  │
    └───────────┬────────────┘
                │
                ▼
    ┌────────────────────────┐
    │  feature_evaluator.py  │ ◄── Reads constants.PSI_WORD_BANK (G0–G8)
    └───────────┬────────────┘
                │
                ├─── Writes Raw Deterministic Scores ───► [ Database ]
                │
                ▼
    ┌────────────────────────┐
    │   spelling_logic.py    │ ◄── LLM Pedagogical Diagnosis Engine
    └───────────┬────────────┘
                │
                ├─── Writes Qualitative Diagnosis ────► [ Database ]
                │
                ▼
    ┌────────────────────────┐
    │     app.py UI          │ ◄── Teacher Reviews & Validates Assessment
    └───────────┬────────────┘
                │
     (If Discrepancy / Edit Occurs)
                │
                ▼
    ┌────────────────────────┐
    │ ai_learning_engine.py  │ ─── Logs Calibration Data ───► [ Database ]
    └────────────────────────┘

3. Component Responsibilities

3.1. constants.py (PSI_WORD_BANK)
Serves as the single source of truth for the diagnostic word list.  
Maps each word to its target features (G0: Initial Consonants through G8: Derivational Suffixes). 

3.2. feature_evaluator.py (Deterministic Scoring)
Input: Transcribed student spellings (list[str]) and intended words (list[str])
Logic:
    Cross-references intended words with PSI_WORD_BANK.  
    Compares attempt against intended target features deterministically.
    Calculates feature-level mastery counts (e.g., G0: 5/5, G1: 3/5).
Output: Structured JSON/Dictionary (EvaluationResult).
Zero AI / LLM involvement.

3.3. spelling_logic.py (Qualitative AI Intelligence)
Handles handwriting OCR transcription.  
Consumes EvaluationResult from feature_evaluator.py.  
Prompts the AI model to:
    Interpret phonetic error patterns across target feature stages.
    Generate a human-readable diagnostic summary for teachers.
    Suggest targeted mini-lessons or coaching strategies.
Does NOT compute raw scores or check phonetic rules manually.

3.4. app.py (Streamlit UI Orchestrator)
Manages the Step-by-Step UI flow:
    Capture / Upload handwriting photo.
    OCR transcription.
    Execute deterministic evaluation + trigger AI diagnosis.
    Present scores, feature matrices, and AI coaching notes to the teacher.  
Captures teacher overrides/corrections and routes them to ai_learning_engine.py.  

3.5. ai_learning_engine.py (Calibration & Learning Loop)
Listens for teacher edits/overrides on AI diagnoses or evaluations.  
Stores calibration logs (AI output vs. Teacher Correction) in the database.  
Provides metrics to fine-tune AI prompts and system instructions over time.  

3.6. database_manager.py (Persistence Layer)
Stores raw transcription text, deterministic scoring objects, AI qualitative notes, and teacher feedback logs.

4. Data Contracts (Module Communication Payload Specs)

4.1. EvaluationResult (Output of feature_evaluator.py)

JSON

{
  "student_id": "STU_123",
  "test_date": "2026-07-20",
  "total_score": 17,
  "max_score": 20,
  "word_evaluations": [
    {
      "intended_word": "ship",
      "student_attempt": "sip",
      "is_correct": false,
      "target_features": ["G0", "G1", "G2"],
      "missed_features": ["G0"]
    }
  ],
  "feature_summary": {
    "G0_initial_consonants": {"correct": 4, "total": 5},
    "G1_short_vowels": {"correct": 5, "total": 5},
    "G2_digraphs": {"correct": 2, "total": 5}
  }
}

4.2. DiagnosisResult (Output of spelling_logic.py)

JSON

{
  "student_id": "STU_123",
  "diagnostic_summary": "Student demonstrates solid mastery of short vowels (G1) but consistently misses initial consonant digraphs (G0/G2), substituting 's' for 'sh'.",
  "phonetic_stage_level": "Letter Name - Alphabetic (Middle Stage)",
  "recommended_focus_areas": [
    "Consonant Digraphs: /sh/ vs /s/ distinction"
  ],
  "coaching_tips": [
    "Use tactile cards contrasting 's' and 'sh' words.",
    "Practice auditory discrimination games emphasizing the unvoiced postalveolar fricative."
  ]
}

4.3. DiscrepancyLog (Output to ai_learning_engine.py)

JSON

{
  "assessment_id": "ASSESS_456",
  "student_id": "STU_123",
  "original_ai_diagnosis": "...",
  "teacher_edited_diagnosis": "...",
  "discrepancy_type": "QUALITATIVE_OVERRIDE",
  "timestamp": "2026-07-20T14:00:00Z"
}

5. Implementation Roadmap

[ ] Update feature_evaluator.py: Build evaluate_spelling_attempt() returning EvaluationResult.

[ ] Update spelling_logic.py: Refactor diagnose_errors() to accept EvaluationResult instead of raw text scoring.

[ ] Update database_manager.py: Add table columns for storing deterministic_eval, ai_diagnosis, and teacher_calibration_logs.

[ ] Update app.py: Update UI workflow to step through evaluator -> logic -> display -> override UI.

[ ] Update ai_learning_engine.py: Connect teacher edit handlers to save discrepancy events.