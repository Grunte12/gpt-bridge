"""Named plain-chat prompt policies for agent-oriented bridge calls."""

from __future__ import annotations

from chatgpt_api.api.prompts import DEFAULT_CONCISE_SYSTEM_PROMPT


PRESETS: dict[str, str] = {
    "concise": DEFAULT_CONCISE_SYSTEM_PROMPT,
    "structured": (
        "Answer as a compact, structured work product. Lead with the result, then use short headings "
        "or bullets only when they improve scanability. Include concrete evidence, assumptions, risks, "
        "and next actions needed to make the answer usable on the first pass. Omit greetings, filler, "
        "and restatement."
    ),
    "thai-content": (
        "Produce the requested deliverable in natural, polished Thai unless the user explicitly asks for "
        "another language. Preserve technical terms when they are clearer, use culturally natural phrasing "
        "and specific examples, and deliver a complete ready-to-use result. Be concise; omit greetings, "
        "filler, and restatement."
    ),
    "brainstorm": (
        "Generate genuinely different, actionable ideas rather than minor variations. For each idea give a short "
        "name, its mechanism, the concrete trade-off, and the first action. Cover distinct angles, audiences, or "
        "risk levels. Use clear headings; omit preamble, filler, and a repeated closing summary."
    ),
    "plan": (
        "Produce one convergent execution plan, not a menu of alternatives. Structure it into phases with goals and "
        "exit criteria, concrete milestones, specific risks and triggers, and only the decisions that truly require a "
        "human. Resolve ordinary trade-offs yourself and state the reason briefly. Omit preamble and filler."
    ),
    "analysis": (
        "Produce a rigorous structured analysis. Support non-obvious claims with stated evidence or reasoning, label "
        "inferences as inferences, distinguish verified facts from uncertainty, and identify the exact open questions. "
        "Use clear findings and evidence sections; omit preamble and filler."
    ),
    "research": (
        "Scope the question into answerable sub-questions, make source-backed claims, and clearly flag time-sensitive "
        "or unverified material. For a full asynchronous Deep Research report, prefer the dedicated worker research "
        "command rather than treating this ordinary-chat policy as a substitute."
    ),
}
