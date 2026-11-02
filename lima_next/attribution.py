"""Explicit text-import conventions, not a speaker recognition model."""

import re
from .evidence_quality import model_evidence_block


def explicit_user_span(content, start, end):
    line_start = content.rfind("\n", 0, start) + 1
    line_end = content.find("\n", start)
    if line_end == -1:
        line_end = len(content)
    return bool(re.match(r"\s*USER:\s*", content[line_start:line_end], re.I)) and end <= line_end


def model_attribution_block(payload, proposer, content, start, end):
    quality = model_evidence_block(payload, proposer, content[start:end])
    if quality:
        return quality
    if payload['kind'] == 'reference' or not proposer.startswith(('ollama:', 'meta:')):
        return None
    if payload['attribution'] == 'user' and not explicit_user_span(content, start, end):
        return 'The source does not explicitly identify this speaker as you. Correct attribution or keep as reference.'
    if payload['attribution'] == 'involved' and not re.search(r'^\s*USER:', content, re.M | re.I):
        return 'Your participation is unverified in this source. Correct attribution or keep as reference.'
    return None
