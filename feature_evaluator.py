"""
feature_evaluator.py
Deterministic feature-slot evaluation engine for UnBoxEd assessments.
"""

def evaluate_word(target_word: str, student_attempt: str, word_meta: dict) -> dict:
    """
    Evaluates a single word attempt against target feature rules.
    
    :param target_word: Target word string (e.g. "fright")
    :param student_attempt: Raw text typed or transcribed (e.g. "frite")
    :param word_meta: Metadata dict containing 'features' from PSI_WORD_BANK
    :return: Dict containing exact match status and feature slot pass/fails
    """
    attempt_clean = student_attempt.strip().lower()
    target_clean = target_word.strip().lower()
    
    # 1. Exact match check
    is_exact = (attempt_clean == target_clean)
    
    # 2. Feature slot checks
    feature_results = {}
    features = word_meta.get("features", {})
    
    for group_key, target_patterns in features.items():
        # If the word is spelled exactly right, all features pass automatically
        if is_exact:
            feature_results[group_key] = True
            continue
            
        # Check if student's attempt contains the target pattern
        group_passed = False
        for pattern in target_patterns:
            # Handle split silent-e patterns like 'o_e' or 'a_e'
            if "_" in pattern:
                prefix, suffix = pattern.split("_")
                if prefix in attempt_clean and suffix in attempt_clean:
                    group_passed = True
                    break
            elif pattern in attempt_clean:
                group_passed = True
                break
                
        feature_results[group_key] = group_passed
        
    return {
        "target_word": target_clean,
        "student_attempt": attempt_clean,
        "is_exact_match": is_exact,
        "features": feature_results
    }


def evaluate_assessment(transcriptions: dict, word_bank: dict) -> dict:
    """
    Evaluates an entire assessment against a word bank mapping.
    
    :param transcriptions: Dict mapping target words to student attempts
                           e.g., {"fright": "frite", "dream": "jinm"}
    :param word_bank: Word bank dict matching PSI_WORD_BANK in constants.py
    :return: Summary dict with word breakdown and overall G0-G8 accuracy stats
    """
    results = []
    # Initialize tracking across diagnostic groups (g0 to g9)
    group_summary = {f"g{i}": {"passed": 0, "total": 0} for i in range(10)}
    
    for target_word, meta in word_bank.items():
        attempt = transcriptions.get(target_word, "")
        word_eval = evaluate_word(target_word, attempt, meta)
        results.append(word_eval)
        
        # Aggregate stats across feature groups
        for g_key, passed in word_eval["features"].items():
            if g_key in group_summary:
                group_summary[g_key]["total"] += 1
                if passed:
                    group_summary[g_key]["passed"] += 1
                    
    # Calculate group accuracy percentages
    group_scores = {}
    for g_key, stats in group_summary.items():
        if stats["total"] > 0:
            group_scores[g_key] = round((stats["passed"] / stats["total"]) * 100, 1)
        else:
            group_scores[g_key] = None  # Group not tested in this assessment
            
    return {
        "word_evaluations": results,
        "group_scores_pct": group_scores
    }