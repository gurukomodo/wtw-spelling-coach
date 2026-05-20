# constants.py
# =====================================================================
# LINGUISTIC TARGETS
# =====================================================================
DIAGNOSTIC_GROUPS = {
    "g0": {
        "name": "Phonemic Awareness",
        "database_field": "g0_phonemic",
        "description": "Minimal pairs, rhyme, syllable segmentation, and initial sound isolation."
    },
    "g1": {
        "name": "Basic CVC Mapping",
        "database_field": "g1_cvc",
        "description": "Short vowel matching, initial/final consonant blending in single-syllable words."
    },
    "g2": {
        "name": "Consonant Digraphs",  # <--- Cleaned up from "Vowel Digraphs" code smell
        "database_field": "g2_digraphs",
        "description": "Consonant digraph sounds like sh, ch, th, wh, and ph."
    },
    "g3": {
        "name": "Silent E & Long Vowels",
        "database_field": "g3_silent_e",
        "description": "CVCe spelling patterns and common long-vowel markers."
    },
    "g4": {
        "name": "Vowel Teams & Digraphs",
        "database_field": "g4_vowel_teams",
        "description": "Advanced vowel teams, diphthongs (oi, oy, ou, ow), and complex spelling markers."
    },
    "g5": {
        "name": "R-Controlled Vowels",
        "database_field": "g5_r_controlled",
        "description": "Vowels modified by 'r' sounds (ar, er, ir, or, ur)."
    },
    "g6": {
        "name": "Consonant Clusters & Blends",
        "database_field": "g6_clusters",
        "description": "Initial and final consonant blends (str, spl, bl, nd, mp)."
    },
    "g7": {
        "name": "Multisyllabic Words",
        "database_field": "g7_multisyllabic",
        "description": "Syllable junctures, unaccented final syllables, and basic compounding."
    },
    "g8": {
        "name": "Morphemic Reduction & Suffixes",
        "database_field": "g8_reduction",
        "description": "Bases, roots, derivational affixes, and consonant changes during suffixation."
    }
}
# 1. The fixed, fallback baseline test list
DEFAULT_TEST_WORDS = ["fan", "pet", "dig", "rob", "hope", "wait", "gum", "sled", "stick", "shine"]

# 2. Control settings for your bi-weekly generator system
ASSESSMENT_CYCLE_DAYS = 14  # Every 2 weeks
WORDS_PER_GENERATED_TEST = 20