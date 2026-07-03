"""Generate the INCOSE GtWR v4 knowledge base: one .md per characteristic and
per rule, plus a machine-readable catalog.json.

Source of truth: INCOSE Guide to Writing Requirements v4 Summary Sheet
(INCOSE-TP-2010-006-04, June 2023). Rule/characteristic texts are transcribed
verbatim; `detector` and `terms` are our engineering classification for the
scoring pipeline. The rule<->characteristic mapping (v4 matrix, p.4) is left
`pending` — it is only needed for aggregation/charts, not per-criterion scoring,
and its source OCR needs verification before it drives anything.

Run: python scripts/build_incose_catalog.py
Output: incose/characteristics/*.md, incose/rules/*.md, incose/catalog.json
"""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "incose")
VERSION = "INCOSE GtWR v4 (INCOSE-TP-2010-006-04, June 2023)"

# ── Characteristics (verbatim v4, p.2) ────────────────────────────────
# scope: "individual" (C1-C9) or "set" (C10-C15)
CHARACTERISTICS = [
    ("C1", "Necessary", "individual",
     "The need or requirement statement defines a capability, characteristic, constraint, or quality factor needed or required to satisfy a lifecycle concept, need, source, or higher-level requirement."),
    ("C2", "Appropriate", "individual",
     "The specific intent and amount of detail of the need or requirement statement is appropriate to the level (the level of abstraction, organization, or system architecture) of the entity to which it refers."),
    ("C3", "Unambiguous", "individual",
     "Need and requirement statements must be stated such that their intent is clear and can be interpreted in only one way by all intended audiences."),
    ("C4", "Complete", "individual",
     "The requirement statement sufficiently describes the necessary capability, characteristic, constraint, conditions, or quality factor to meet the need, source, or higher-level requirement from which it was transformed."),
    ("C5", "Singular", "individual",
     "The need or requirement statement should state a single capability, characteristic, constraint, or quality factor."),
    ("C6", "Feasible", "individual",
     "The need or requirement can be realized within entity constraints (for example: cost, schedule, technical, legal, ethical, safety) with acceptable risk."),
    ("C7", "Verifiable", "individual",
     "The requirement statement is structured and worded such that its realization can be verified to the approving authority's satisfaction."),
    ("C8", "Correct", "individual",
     "The requirement statement must be an accurate representation of the need, source, or higher-level requirement from which it was transformed."),
    ("C9", "Conforming", "individual",
     "Statements and expressions of individual needs and requirements should conform to an approved standard pattern and style guide or standard for writing and managing needs and requirements."),
    ("C10", "Complete", "set",
     "The set of requirements for an entity should stand alone such that it sufficiently describes the necessary capabilities, characteristics, functionality, performance, drivers, constraints, conditions, interactions, standards, regulations, safety, security, resilience, and quality factors without requiring other sets of requirements at the appropriate level of abstraction."),
    ("C11", "Consistent", "set",
     "A set of requirements is consistent if it contains individual requirements that are: unique; do not conflict with or overlap with others in the set; make use of homogeneous units and measurement systems; and are developed using a consistent language (the same words are used throughout the set to mean the same thing) consistent with the architectural model, project glossary, and data dictionary."),
    ("C12", "Feasible", "set",
     "A set of requirements is feasible if it can be realized within entity constraints (such as cost, schedule, technical) with acceptable risk."),
    ("C13", "Comprehensible", "set",
     "The set of requirements must be written such that it is clear as to what is expected of the entity and its relation to the macro system of which it is a part."),
    ("C14", "Able to be validated", "set",
     "It must be possible to validate that the set of requirements will lead to the achievement of the set of needs and higher-level requirements within the constraints (such as cost, schedule, technical, and regulatory compliance) with acceptable risk."),
    ("C15", "Correct", "set",
     "The set of requirements must be an accurate representation of the needs, sources, or higher-level requirements from which it was transformed."),
]

# ── Rules (verbatim v4, p.3) ──────────────────────────────────────────
# fields: num, name, category, scope, detector, text, terms
#   detector: "deterministic" (wordlist/symbol), "nlp" (needs POS/parser),
#             "semantic" (LLM judgment), "tool" (grammar/spell checker)
#   scope:    "individual" or "set"
#   terms:    trigger words/phrases the guide enumerates (deterministic rules)
RULES = [
    (1, "Structured Statements", "Accuracy", "individual", "semantic",
     "Need and requirement statements must conform to one of the agreed patterns, thus resulting in a well-structured complete statement.", None),
    (2, "Active Voice", "Accuracy", "individual", "nlp",
     "Use the active voice in the need or requirement statement with the responsible entity clearly identified as the subject of the sentence.", None),
    (3, "Appropriate Subject-Verb", "Accuracy", "individual", "semantic",
     "Ensure the subject and verb of the need or requirement statement are appropriate to the entity to which the statement refers.", None),
    (4, "Defined Terms", "Accuracy", "individual", "semantic",
     "Define all terms used within the need statement and requirement statement within an associated glossary and/or data dictionary.", None),
    (5, "Definite Articles", "Accuracy", "individual", "deterministic",
     'Use the definite article "the" rather than the indefinite article "a".', ["a", "an"]),
    (6, "Common Units of Measure", "Accuracy", "individual", "nlp",
     "When stating quantities, all numbers should have appropriate and consistent units of measure explicitly stated using a common measurement system in terms of the thing the number refers.", None),
    (7, "Vague Terms", "Accuracy", "individual", "deterministic",
     "Avoid the use of vague terms that provide vague quantification or vague adjectives.",
     ["some", "any", "allowable", "several", "many", "a lot of", "a few", "almost always",
      "very nearly", "nearly", "about", "close to", "almost", "approximate", "ancillary",
      "relevant", "routine", "common", "generic", "significant", "flexible", "expandable",
      "typical", "sufficient", "adequate", "appropriate", "efficient", "effective",
      "proficient", "reasonable", "customary"]),
    (8, "Escape Clauses", "Accuracy", "individual", "deterministic",
     "Avoid the inclusion of escape clauses that state vague conditions or possibilities.",
     ["so far as is possible", "as little as possible", "where possible", "as much as possible",
      "if it should prove necessary", "if necessary", "to the extent necessary", "as appropriate",
      "as required", "to the extent practical", "if practicable"]),
    (9, "Open-Ended Clauses", "Accuracy", "individual", "deterministic",
     "Avoid open-ended, non-specific clauses.",
     ["including but not limited to", "etc.", "and so on"]),
    (10, "Superfluous Infinitives", "Concision", "individual", "deterministic",
     "Avoid the use of superfluous infinitives.",
     ["to be designed to", "to be able to", "to be capable of", "to enable", "to allow"]),
    (11, "Separate Clauses", "Concision", "individual", "semantic",
     "Use a separate clause for each condition or qualification.", None),
    (12, "Correct Grammar", "Non-ambiguity", "individual", "tool",
     "Use correct grammar.", None),
    (13, "Correct Spelling", "Non-ambiguity", "individual", "tool",
     "Use correct spelling.", None),
    (14, "Correct Punctuation", "Non-ambiguity", "individual", "tool",
     "Use correct punctuation.", None),
    (15, "Logical Expressions", "Non-ambiguity", "individual", "semantic",
     'Use a defined convention to express logical expressions such as "[X AND Y]", "[X OR Y]", "[X XOR Y]", "NOT [X OR Y]".', None),
    (16, 'Use of "Not"', "Non-ambiguity", "individual", "deterministic",
     'Avoid the use of "not".', ["not"]),
    (17, "Use of Oblique Symbol", "Non-ambiguity", "individual", "deterministic",
     'Avoid the use of the oblique ("/") symbol except in units (e.g. Km/hr) or fractions.', ["/"]),
    (18, "Single Thought Sentence", "Singularity", "individual", "semantic",
     "Write a single sentence that contains a single thought conditioned and qualified by relevant sub-clauses.", None),
    (19, "Combinators", "Singularity", "individual", "deterministic",
     "Avoid words that join or combine clauses.",
     ["and", "or", "then", "unless", "but", "as well as", "but also", "however", "whether",
      "meanwhile", "whereas", "on the other hand", "otherwise"]),
    (20, "Purpose Phrases", "Singularity", "individual", "deterministic",
     'Avoid phrases that indicate the "purpose of", "intent of", or "reason for" the requirement statement.',
     ["purpose of", "intent of", "reason for", "in order to", "so that", "so as to"]),
    (21, "Parentheses", "Singularity", "individual", "deterministic",
     "Avoid parentheses and brackets containing subordinate text.", ["(", ")", "[", "]"]),
    (22, "Enumeration", "Singularity", "individual", "semantic",
     "Enumerate sets explicitly instead of using a group noun to name the set.", None),
    (23, "Supporting Diagram, Model, or ICD", "Singularity", "individual", "semantic",
     "When a need or requirement is related to complex behavior, refer to a supporting diagram, model, or ICD.", None),
    (24, "Pronouns", "Completeness", "individual", "deterministic",
     "Avoid the use of personal and indefinite pronouns.",
     ["it", "its", "they", "them", "their", "this", "that", "these", "those", "he", "she",
      "his", "her", "we", "our", "you", "your", "anyone", "everyone", "someone", "anything",
      "everything", "something"]),
    (25, "Headings", "Completeness", "individual", "semantic",
     "Avoid relying on headings to support explanation or understanding of the need or requirement.", None),
    (26, "Absolutes", "Realism", "individual", "deterministic",
     "Avoid using unachievable absolutes.",
     ["100%", "all", "every", "always", "never", "none", "total", "complete", "fully", "any"]),
    (27, "Explicit Conditions", "Conditions", "individual", "semantic",
     "State conditions' applicability explicitly instead of leaving applicability to be inferred from the context.", None),
    (28, "Multiple Conditions", "Conditions", "individual", "semantic",
     "Express the propositional nature of a condition explicitly for a single action instead of giving lists of actions for a specific condition.", None),
    (29, "Classification", "Uniqueness", "individual", "semantic",
     "Classify needs and requirements according to the aspects of the problem or system it addresses.", None),
    (30, "Unique Expression", "Uniqueness", "set", "semantic",
     "Express each need and requirement once and only once.", None),
    (31, "Solution Free", "Abstraction", "individual", "semantic",
     "Avoid stating implementation in a need statement or requirement statement unless there is rationale for constraining the design.", None),
    (32, "Universal Qualification", "Quantifiers", "individual", "deterministic",
     'Use "each" instead of "all", "any", or "both" when universal quantification is intended.',
     ["all", "any", "both"]),
    (33, "Range of Values", "Tolerance", "individual", "semantic",
     "Define each quantity with a range of values appropriate to the entity to which the quantity applies and against which the entity will be verified or validated.", None),
    (34, "Measurable Performance", "Quantification", "individual", "semantic",
     "Provide specific measurable performance targets appropriate to the entity to which the need or requirement is stated and against which the entity will be verified to meet.", None),
    (35, "Temporal Dependencies", "Quantification", "individual", "deterministic",
     "Define temporal dependencies explicitly instead of using indefinite temporal keywords.",
     ["eventually", "until", "before", "after", "as", "once", "earliest", "latest",
      "instantaneous", "simultaneous", "at last"]),
    (36, "Consistent Terms and Units", "Uniformity of Language", "set", "semantic",
     "Ensure each term and unit of measure used throughout need and requirement sets, as well as associated models and other SE artefacts, are consistent with the project's defined ontology.", None),
    (37, "Acronyms", "Uniformity of Language", "set", "semantic",
     "If acronyms are used, they must be consistent throughout need and requirement sets as well as associated models and other SE artefacts.", None),
    (38, "Abbreviations", "Uniformity of Language", "individual", "nlp",
     "Avoid the use of abbreviations in needs and requirement statements as well as associated models and other SE lifecycle artefacts.", None),
    (39, "Style Guide", "Uniformity of Language", "set", "semantic",
     "Use a project-wide style guide for individual need statements and requirement statements.", None),
    (40, "Decimal Format", "Uniformity of Language", "individual", "deterministic",
     "Use a consistent format and number of significant digits for the specification of decimal numbers.", None),
    (41, "Related Needs and Requirements", "Modularity", "set", "semantic",
     "Group related needs and requirements together.", None),
    (42, "Structured Sets", "Modularity", "set", "semantic",
     "Conform to a defined structure or template for organizing sets of needs and requirements.", None),
]

DETECTOR_NOTE = {
    "deterministic": "Detectable by matching the trigger terms / symbol below — exact, cites the offending token. No LLM needed.",
    "nlp": "Needs light NLP (POS tagging / number+unit parsing). Semi-deterministic; verify edge cases.",
    "tool": "Delegate to a grammar/spell/punctuation checker.",
    "semantic": "Requires LLM judgment — no reliable lexical trigger.",
}


def slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[\s_]+", "-", s).strip("-")


def write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def rule_md(num, name, category, scope, detector, text, terms) -> str:
    rid = f"R{num}"
    lines = [
        f"# {rid} — {name}", "",
        f"- **ID:** {rid}",
        f"- **Category (quality focus):** {category}",
        f"- **Scope:** {scope} requirement" + ("" if scope == "individual" else " set"),
        f"- **Detector type:** {detector}",
        f"- **Source:** {VERSION}", "",
        "## Rule", text, "",
    ]
    if terms:
        lines += ["## Trigger terms", "", "```", ", ".join(terms), "```", ""]
    lines += [
        "## Detector notes", DETECTOR_NOTE[detector], "",
        "## Supporting characteristics", "_Mapping pending verification of the v4 Rules→Characteristics matrix._", "",
        "## Examples", "_To be added from the full GtWR (good vs. violating)._", "",
    ]
    return "\n".join(lines) + "\n"


def char_md(cid, name, scope, definition) -> str:
    lines = [
        f"# {cid} — {name}", "",
        f"- **ID:** {cid}",
        f"- **Applies to:** {'individual requirement' if scope == 'individual' else 'requirement SET'}",
        f"- **Source:** {VERSION}", "",
        "## Definition", definition, "",
        "## Supporting rules", "_Mapping pending verification of the v4 Rules→Characteristics matrix._", "",
        "## How to assess",
        ("Scored per requirement by aggregating its mapped rules plus an LLM judgment where the characteristic is semantic."
         if scope == "individual" else
         "Set-level: assessed over the whole requirement set, not a single requirement (separate analysis)."), "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    catalog = {"version": VERSION, "characteristics": [], "rules": []}

    for cid, name, scope, definition in CHARACTERISTICS:
        fn = f"{cid}-{slug(name)}.md"
        write(os.path.join(ROOT, "characteristics", fn), char_md(cid, name, scope, definition))
        catalog["characteristics"].append(
            {"id": cid, "name": name, "scope": scope, "definition": definition,
             "supports_rules": "pending", "file": f"characteristics/{fn}"})

    for num, name, category, scope, detector, text, terms in RULES:
        rid = f"R{num}"
        fn = f"R{num:02d}-{slug(name)}.md"
        write(os.path.join(ROOT, "rules", fn), rule_md(num, name, category, scope, detector, text, terms))
        catalog["rules"].append(
            {"id": rid, "name": name, "category": category, "scope": scope,
             "detector": detector, "text": text, "terms": terms,
             "characteristics": "pending", "file": f"rules/{fn}"})

    write(os.path.join(ROOT, "catalog.json"), json.dumps(catalog, indent=2) + "\n")
    det = sum(1 for r in RULES if r[4] == "deterministic")
    print(f"characteristics: {len(CHARACTERISTICS)} | rules: {len(RULES)} "
          f"(deterministic={det}, semantic={sum(1 for r in RULES if r[4]=='semantic')}, "
          f"nlp={sum(1 for r in RULES if r[4]=='nlp')}, tool={sum(1 for r in RULES if r[4]=='tool')})")


if __name__ == "__main__":
    main()
