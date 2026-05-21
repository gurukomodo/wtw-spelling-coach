# WTW Spelling Coach Architecture

This document describes the high-level architecture and data flow of the WTW Spelling Coach application.

## Data Flow: Assessment Lifecycle

The path of a student assessment from capture to storage:

1.  **Image Upload & Preprocessing**: The teacher uploads a photo of student handwriting in `app.py`. The image is cleaned and converted to base64 via `utils.py`.
2.  **AI Transcription**: `app.py` calls `spelling_logic.transcribe_handwriting()`. An AI model (Gemini/Groq) reads the image and returns a raw `intended:attempt` transcription.
3.  **Human Verification**: The teacher reviews and corrects the transcription in the UI to ensure the "ground truth" is accurate before analysis.
4.  **Contextual Analysis**: `app.py` triggers `spelling_logic.run_scoring_crew()`. This sends the transcription and any external classroom data (from Google Sheets) to a CrewAI agent team.
5.  **Diagnostic Scoring**: The AI Assessor Agent evaluates the attempts against the 9 diagnostic groups (g0-g8) defined in `constants.py`.
6.  **Teacher Refinement**: Results are returned to the UI. The teacher reviews the AI's notes and adds their own "Gold Standard" refinement.
7.  **Persistence**: `app.py` calls `database_manager.save_assessment()`, which commits the scores, raw text, and refined notes to the SQLite database.

## Component Map

### `app.py` (UI Layer)
*   **Role**: Entry point and Orchestrator.
*   **Functions**: Manages Streamlit page routing (Registration, Login, Dashboard, Class View, Student View, Admin), handles session state, and provides the interactive workflow for teachers.

### `database_manager.py` (Data Layer)
*   **Role**: Persistence and Schema Management.
*   **Functions**: Handles all SQLite interactions. Manages tables for `assessments`, `student_identity`, `teacher_settings`, and `test_templates`. It ensures data integrity and provides helper functions for fetching student history and class statistics.

### `constants.py` (Domain Rules)
*   **Role**: Linguistic Source of Truth.
*   **Functions**: Defines the `DIAGNOSTIC_GROUPS` (g0-g8), their names, descriptions, and corresponding database fields. It also holds the default word banks and assessment cycle configurations.

### `spelling_logic.py` (Intelligence Layer)
*   **Role**: AI Interface and Pedagogical Logic.
*   **Functions**: Defines CrewAI agents and tasks. It handles the prompt engineering for handwriting transcription, linguistic analysis, and the generation of personalized coaching reports and practice lists.

---

## 🏆 The 'Golden Rule'

**Linguistic group definitions must NEVER be hardcoded in the UI (`app.py`) or Logic (`spelling_logic.py`).**

All definitions for the 9 diagnostic groups (g0 to g8), including their display names and database column mappings, must be managed within `constants.py`. If the scope of a group changes (e.g., changing "Vowel Digraphs" to "Consonant Digraphs"), update it in `constants.py` to ensure the change propagates correctly across the analysis engine and the dashboard.
