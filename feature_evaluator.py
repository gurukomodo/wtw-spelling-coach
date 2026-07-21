"""
feature_evaluator.py
Deterministic evaluation engine for Primary Spelling Inventory (PSI) assessments.
Compares student attempts against constants.PSI_WORD_BANK targets (G0-G8).
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import date


@dataclass
class WordEvaluation:
    intended_word: str
    student_attempt: str
    is_correct: bool
    target_features: Dict[str, List[str]]   # e.g., {"g0": ["f", "n"], "g1": ["a"]}
    passed_features: Dict[str, List[str]]   # e.g., {"g0": ["f", "n"]}
    missed_features: Dict[str, List[str]]   # e.g., {"g1": ["a"]}


@dataclass
class EvaluationResult:
    student_id: str
    test_date: str
    total_score: int
    max_score: int
    word_evaluations: List[Dict[str, Any]]
    feature_summary: Dict[str, Dict[str, int]]  # e.g., {"g0": {"correct": 8, "total": 10}}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _check_pattern_in_attempt(attempt: str, pattern: str) -> bool:
    """
    Checks if a specific feature pattern or grapheme is present in the student's attempt.
    Handles split vowel patterns (e.g., 'o_e' -> checks for 'o' followed later by 'e').
    """
    clean_attempt = attempt.lower().strip()
    clean_pattern = pattern.lower().strip()

    # Handle split-vowel / silent-e patterns like 'o_e' or 'a_e'
    if "_" in clean_pattern:
        parts = clean_pattern.split("_")
        if len(parts) == 2:
            first, second = parts[0], parts[1]
            idx = clean_attempt.find(first)
            return idx != -1 and second in clean_attempt[idx + 1:]

    # Standard substring match (e.g., 'sh', 'ch', 'f', 'a')
    return clean_pattern in clean_attempt


def evaluate_single_word(
    intended_word: str, 
    student_attempt: str, 
    word_bank_entry: Dict[str, Any]
) -> WordEvaluation:
    """
    Evaluates a single student attempt against the intended word and feature dict in PSI_WORD_BANK.
    """
    clean_intended = intended_word.strip().lower()
    clean_attempt = student_attempt.strip().lower()
    is_correct = (clean_intended == clean_attempt)

    # Features dictionary from PSI_WORD_BANK, e.g., {"g0": ["f", "n"], "g1": ["a"]}
    features_dict: Dict[str, List[str]] = word_bank_entry.get("features", {})

    passed_features: Dict[str, List[str]] = {}
    missed_features: Dict[str, List[str]] = {}

    for feature_cat, patterns in features_dict.items():
        feat_key = feature_cat.lower()
        passed_features[feat_key] = []
        missed_features[feat_key] = []

        if is_correct:
            # If word is spelled completely right, all features pass automatically
            passed_features[feat_key] = patterns.copy()
        else:
            for pat in patterns:
                if _check_pattern_in_attempt(clean_attempt, pat):
                    passed_features[feat_key].append(pat)
                else:
                    missed_features[feat_key].append(pat)

    return WordEvaluation(
        intended_word=clean_intended,
        student_attempt=clean_attempt,
        is_correct=is_correct,
        target_features=features_dict,
        passed_features=passed_features,
        missed_features=missed_features,
    )


def evaluate_spelling_attempt(
    student_id: str,
    transcribed_words: List[str],
    intended_words: List[str],
    word_bank: Optional[Dict[str, Any]] = None,
    test_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main evaluation function called by app.py.
    Compares transcribed student attempts against intended words using PSI_WORD_BANK.

    Returns a dictionary structured as an EvaluationResult payload.
    """
    if word_bank is None:
        from constants import PSI_WORD_BANK
        word_bank = PSI_WORD_BANK

    if test_date is None:
        test_date = date.today().isoformat()

    word_evaluations: List[WordEvaluation] = []
    feature_summary: Dict[str, Dict[str, int]] = {}
    total_score = 0

    for intended, attempt in zip(intended_words, transcribed_words):
        clean_key = intended.strip().lower()
        word_info = word_bank.get(clean_key, {"features": {}})

        # Evaluate single word
        word_eval = evaluate_single_word(intended, attempt, word_info)
        word_evaluations.append(word_eval)

        if word_eval.is_correct:
            total_score += 1

        # Aggregate feature performance (G0, G1, G2, etc.)
        for feat_key, target_pats in word_eval.target_features.items():
            f_key = feat_key.lower()
            if f_key not in feature_summary:
                feature_summary[f_key] = {"correct": 0, "total": 0}

            total_pats = len(target_pats)
            passed_pats = len(word_eval.passed_features.get(f_key, []))

            feature_summary[f_key]["total"] += total_pats
            feature_summary[f_key]["correct"] += passed_pats

    # Build final serializable result matching architecture spec
    result = EvaluationResult(
        student_id=student_id,
        test_date=test_date,
        total_score=total_score,
        max_score=len(intended_words),
        word_evaluations=[asdict(we) for we in word_evaluations],
        feature_summary=feature_summary,
    )

    return result.to_dict()