"""The 14 error codes, in one place.

This is the single source of truth referenced by docs/HARNESS_SPEC.md
section 2. The harness uses it to build prompts; the API uses it to
validate harness output. Never duplicate this list elsewhere.
"""

from enum import Enum


class ErrorCode(str, Enum):
    SP = "SP"
    P = "P"
    CAP = "CAP"
    S = "S"
    VT = "VT"
    SV = "SV"
    VF = "VF"
    ART = "ART"
    PREP = "PREP"
    WF = "WF"
    PRO = "PRO"
    WO = "WO"
    M = "M"
    X = "X"


CODE_DESCRIPTIONS: dict[ErrorCode, str] = {
    ErrorCode.SP: "Spelling",
    ErrorCode.P: "Punctuation (not capitalization)",
    ErrorCode.CAP: "Capitalization",
    ErrorCode.S: "Sentence boundary: fragment, run-on, comma splice",
    ErrorCode.VT: "Verb tense",
    ErrorCode.SV: "Subject-verb agreement",
    ErrorCode.VF: "Verb form (participle, gerund vs infinitive, modal + verb)",
    ErrorCode.ART: "Article/determiner: missing, extra, wrong",
    ErrorCode.PREP: "Preposition",
    ErrorCode.WF: "Word form, plurals, countability",
    ErrorCode.PRO: "Pronoun agreement or reference",
    ErrorCode.WO: "Word order",
    ErrorCode.M: "Missing word (not article/preposition)",
    ErrorCode.X: "Unnecessary word (not article/preposition)",
}
