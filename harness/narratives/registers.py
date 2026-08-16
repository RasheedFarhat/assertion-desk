"""Five render_<register>() functions, each turning one FAULT_NARRATIVE_FACTS entry into
a differently-worded customer report. The underlying facts never change between
registers -- only how clearly, calmly, and accurately the customer communicates them.
This is what Job A (Phase 4) is actually being asked to handle: recovering the same
structured facts regardless of how badly or well they're expressed.

Directly authored templates, not live-model output (see facts.py's docstring for why).
Deterministic: the same facts dict always renders to the same string, which is what lets
corpus/MANIFEST.json pin a sha256 to narrative text and mean it.

register -> what it stresses:
  precise                    clear, organized, uses the right vocabulary
  vague                      minimal detail, "it's broken", makes Job A's job hard
  confident_misdiagnosis     customer states a wrong cause with full confidence
  hostile                    frustrated, escalated, urgent, blame-forward
  non_native                 imperfect but understandable non-native English phrasing
"""

from __future__ import annotations

from typing import TypedDict

from harness.narratives.facts import NarrativeFacts

SCOPE_PHRASES = {
    "all_users": "every user",
    "subset": "some users",
    "single_user": "one user",
    "new_users_only": "only our newest users",
}


class Narrative(TypedDict):
    subject: str
    body: str


def render_precise(facts: NarrativeFacts) -> Narrative:
    scope = SCOPE_PHRASES[facts["scope"]]
    lines = [
        f"We're seeing single sign-on failures affecting {scope}, starting {facts['onset']}.",
    ]
    if facts.get("recent_change"):
        lines.append(f"The one change on our side around that time: {facts['recent_change']}.")
    tried = facts.get("already_tried") or []
    if tried:
        lines.append("What we've already checked: " + "; ".join(tried) + ".")
    lines.append("Please let us know what artifact or evidence you need from us to pin this down.")
    return {"subject": "SSO login failure - details attached", "body": " ".join(lines)}


def render_vague(facts: NarrativeFacts) -> Narrative:
    scope = facts["scope"]
    if scope == "all_users":
        body = "SSO is broken, nobody can log in. Please look into this."
    elif scope == "single_user":
        body = "One of our people can't log in with SSO. Not sure what's going on."
    else:
        body = "SSO login is acting up for some of our team. Can you take a look?"
    return {"subject": "SSO broken", "body": body}


def render_confident_misdiagnosis(facts: NarrativeFacts) -> Narrative:
    scope = SCOPE_PHRASES[facts["scope"]]
    wrong = facts.get("wrong_belief") or "something must be wrong on your end"
    body = (
        f"Login is failing for {scope}, {facts['onset']}. We've looked into it and "
        f"we're pretty confident {wrong}. Can you confirm and get this fixed on your side?"
    )
    return {"subject": "SSO is down on your end", "body": body}


def render_hostile(facts: NarrativeFacts) -> Narrative:
    scope = SCOPE_PHRASES[facts["scope"]]
    body = (
        f"This is the THIRD time I'm writing about this. SSO login has been broken for "
        f"{scope} {facts['onset']} and nobody has given us a straight answer. Our team "
        f"cannot work. We need this fixed TODAY or we are escalating this to our account "
        f"manager and reconsidering the renewal."
    )
    return {"subject": "URGENT - SSO still broken, need answers now", "body": body}


def render_non_native(facts: NarrativeFacts) -> Narrative:
    scope = facts["scope"]
    scope_text = {
        "all_users": "all of peoples in company cannot login",
        "subset": "some of peoples cannot login, not all",
        "single_user": "one of my colleague cannot login, only him",
        "new_users_only": "only new added peoples cannot login, old is ok",
    }[scope]
    body = f"Hello, sorry for my english. We have problem with SSO, {scope_text}. This start {facts['onset']}. "
    if facts.get("recent_change"):
        body += f"Maybe is because we make change: {facts['recent_change']}. "
    body += "Please help us for fix this, is important for our company. Thank you."
    return {"subject": "problem with SSO login please help", "body": body}


RENDER_FUNCTIONS = {
    "precise": render_precise,
    "vague": render_vague,
    "confident_misdiagnosis": render_confident_misdiagnosis,
    "hostile": render_hostile,
    "non_native": render_non_native,
}

REGISTERS = list(RENDER_FUNCTIONS)
