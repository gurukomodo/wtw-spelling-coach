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
        "name": "Short Vowels & CVC Patterns",
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
        "name": "Inflectional Suffixes & Spelling Rules",
        "database_field": "g8_inflectional",
        "description": "Basic grammatical suffixes (-s, -es, -ed, -ing, -er, -est) and base word spelling changes (y-to-i, consonant doubling, drop-e)."
    },
    "g9": {
        "name": "Derivational Affixes & Roots",
        "database_field": "g9_derivational",
        "description": "Prefixes, derivational suffixes (-tion, -ment, -ly), Greek/Latin roots, and morphemic reductions."
    }
}
# 1. The fixed, fallback baseline test list
DEFAULT_TEST_WORDS = ["fan", "pet", "dig", "rob", "hope", "wait", "gum", "sled", "stick", "shine"]

# 2. Control settings for your bi-weekly generator system
ASSESSMENT_CYCLE_DAYS = 14  # Every 2 weeks
WORDS_PER_GENERATED_TEST = 20

# Append to constants.py

PSI_WORD_BANK = {
    "fan": {
        "features": {"g0": ["f", "n"], "g1": ["a"]},
        "sentence": "I could use a fan on a hot day."
    },
    "pet": {
        "features": {"g0": ["p", "t"], "g1": ["e"]},
        "sentence": "I have a pet cat who likes to play."
    },
    "dig": {
        "features": {"g0": ["d", "g"], "g1": ["i"]},
        "sentence": "He will dig a hole in the sand."
    },
    "rob": {
        "features": {"g0": ["r", "b"], "g1": ["o"]},
        "sentence": "A raccoon will rob a bird’s nest for eggs."
    },
    "hope": {
        "features": {"g0": ["h", "p"], "g3": ["o_e"]},
        "sentence": "I hope you will do well on this test."
    },
    "wait": {
        "features": {"g0": ["w", "t"], "g3": ["ai"]},
        "sentence": "You will need to wait for the letter."
    },
    "gum": {
        "features": {"g0": ["g", "m"], "g1": ["u"]},
        "sentence": "I stepped on some bubble gum."
    },
    "sled": {
        "features": {"g0": ["d"], "g1": ["e"], "g6": ["sl"]},
        "sentence": "The dog sled was pulled by huskies."
    },
    "stick": {
        "features": {"g1": ["i"], "g6": ["st", "ck"]},
        "sentence": "I used a stick to poke in the hole."
    },
    "shine": {
        "features": {"g0": ["n"], "g3": ["i_e"], "g4": ["sh"]},
        "sentence": "He rubbed the coin to make it shine."
    },
    "dream": {
        "features": {"g0": ["m"], "g3": ["ea"], "g6": ["dr"]},
        "sentence": "I had a funny dream last night."
    },
    "blade": {
        "features": {"g0": ["d"], "g3": ["a_e"], "g6": ["bl"]},
        "sentence": "The blade of the knife was very sharp."
    },
    "coach": {
        "features": {"g0": ["c"], "g3": ["oa"], "g4": ["ch"]},
        "sentence": "The coach called the team off the field."
    },
    "fright": {
        "features": {"g0": ["t"], "g3": ["igh"], "g6": ["fr"]},
        "sentence": "She was a fright in her Halloween costume."
    },
    "chewed": {
        "features": {"g4": ["ch", "ew", "ed"]},
        "sentence": "The dog chewed on the bone until it was gone."
    },
    "crawl": {
        "features": {"g0": ["l"], "g4": ["aw"], "g6": ["cr"]},
        "sentence": "You will get dirty if you crawl under the bed."
    },
    "wishes": {
        "features": {"g0": ["w"], "g1": ["i"], "g2": ["sh"], "g4": ["es"]},
        "sentence": "In fairy tales wishes often come true."
    },
    "thorn": {
        "features": {"g0": ["n"], "g4": ["th"], "g5": ["or"]},
        "sentence": "The thorn from the rosebush stuck me."
    },
    "shouted": {
        "features": {"g4": ["sh", "ou"], "g0": ["t"], "g4": ["ed"]},
        "sentence": "They shouted at the barking dog."
    },
    "spoil": {
        "features": {"g6": ["sp"], "g4": ["oi"], "g0": ["l"]},
        "sentence": "The food will spoil if it sits out too long."
    },
    "growl": {
        "features": {"g6": ["gr"], "g4": ["ow"], "g0": ["l"]},
        "sentence": "The dog will growl if you bother him."
    },
    "third": {
        "features": {"g4": ["th"], "g5": ["ir"], "g0": ["d"]},
        "sentence": "I was the third person in line."
    },
    "camped": {
        "features": {"g0": ["c"], "g1": ["a"], "g6": ["mp"], "g4": ["ed"]},
        "sentence": "We camped down by the river last weekend."
    },
    "tries": {
        "features": {"g6": ["tr"], "g8": ["ies"]},
        "sentence": "He tries hard every day to finish his work."
    },
    "clapping": {
        "features": {"g6": ["cl"], "g1": ["a"], "g8": ["pping"]},
        "sentence": "The audience was clapping after the program."
    },
    "riding": {
        "features": {"g0": ["r"], "g3": ["i"], "g0": ["d"], "g8": ["ing"]},
        "sentence": "They are riding their bikes to the park today."
    }
}