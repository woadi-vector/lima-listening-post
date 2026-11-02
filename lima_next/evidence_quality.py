"""Conservative checks for known extraction failures, not semantic verification."""

import re


def vague_evidence(quote):
    text = re.sub(r"[^\w\s']", "", quote.casefold()).strip()
    return bool(re.fullmatch(
        r"(?:we're|we are) going to (?:learn|discuss|cover) (?:that|this|it)(?: today)?"
        r"|i believe|(?:this|that|it) is important", text))


def educational_guidance(quote):
    # Require specific program/instruction language; ordinary promises stay work.
    return bool(re.search(
        r"\b(?:we(?:'re| are) (?:not )?looking for (?:teams|foundational|proposals|technologies)"
        r"|(?:applicants|proposals|teams) (?:must|are required to)"
        r"|(?:course|program|funding|eligibility) requirements)\b", quote, re.I))


def model_evidence_block(payload, proposer, quote):
    if not proposer.startswith(('ollama:', 'meta:')):
        return None
    if vague_evidence(quote):
        return 'The quotation is too vague to support this interpretation. Select fuller evidence or reject it.'
    if payload['kind'] != 'reference' and educational_guidance(quote):
        return 'This quotation describes program guidance, not an agreed assignment. Keep as reference or correct it.'
    return None
