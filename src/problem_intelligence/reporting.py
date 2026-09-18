"""Opportunity report rendering that preserves evidence scope and uncertainty."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .domain import (
    EvidenceCitation,
    EvidenceScope,
    EvidenceScopeSummary,
    EvidenceState,
    OpportunityStatus,
    ResearchCaseReportData,
)
from .repository import IntegrityError, Repository


@dataclass(frozen=True, slots=True)
class OpportunityReport:
    data: ResearchCaseReportData
    evidence_state: EvidenceState

    def to_markdown(
        self,
        *,
        include_unapproved_excerpts: bool = False,
        language: str = "de",
    ) -> str:
        if language not in {"de", "en"}:
            raise ValueError("report language must be 'de' or 'en'")
        global_citations = [
            citation
            for citation in self.data.citations
            if citation.evidence_scope is EvidenceScope.GLOBAL
        ]
        dach_citations = [
            citation
            for citation in self.data.citations
            if citation.evidence_scope is EvidenceScope.DACH
        ]
        lines = [
            f"# {self.data.title}",
            "",
            f"Evidence state: `{self.evidence_state.value}`",
            "Opportunity types: "
            + ", ".join(f"`{item.value}`" for item in self.data.opportunity_types),
            "",
            "This report summarizes evidence and validation needs. "
            "It is not a build recommendation.",
            "",
        ]
        _append_problem_context(lines, self.data)
        _append_evidence_summary(
            lines,
            "Global evidence",
            self.data.global_evidence_summary,
        )
        _append_original_evidence(
            lines,
            global_citations,
            dach_citations,
            include_unapproved_excerpts=include_unapproved_excerpts,
        )
        _append_section_values(lines, "Impact", self.data.problem_profile.impacts)
        _append_section_values(
            lines, "Payment evidence", self.data.problem_profile.payment_evidence
        )
        _append_competition(lines, self.data)
        _append_solution_gaps(lines, self.data)
        _append_dach_assessment(lines, self.data)
        _append_evidence_summary(
            lines,
            "DACH evidence",
            self.data.dach_evidence_summary,
        )
        _append_local_solutions(lines, self.data)
        _append_stakeholders(lines, self.data)
        _append_local_dependencies(lines, self.data)
        _append_switching_barriers(lines, self.data)
        _append_counter_evidence(lines, self.data)
        lines.extend(["## Required research findings", ""])
        for finding in self.data.findings:
            note = f" — {finding.note}" if finding.note else ""
            finding_text = finding.claim_text or "No additional evidence found."
            lines.append(
                f"- **{finding.requirement.value} "
                f"({finding.outcome.value}):** {finding_text}{note}"
            )
        lines.extend(["", "## What we do not know", ""])
        lines.extend(f"- {unknown}" for unknown in self.data.unknowns)
        lines.extend(["", "## Validation questions", ""])
        for question in self.data.validation_questions:
            rationale = f" — {question.rationale}" if question.rationale else ""
            lines.append(f"- {question.question}{rationale}")
        lines.append("")
        if language == "de":
            lines = _localize_german(lines)
        return "\n".join(lines)


def build_opportunity_report(repository: Repository, opportunity_id: int) -> OpportunityReport:
    data = repository.opportunity_report_data(opportunity_id)
    if data.opportunity_status is not OpportunityStatus.REPORT_READY:
        raise IntegrityError("opportunity reports require REPORT_READY status")
    return OpportunityReport(data=data, evidence_state=data.evidence_state)


def _append_evidence_summary(
    lines: list[str],
    heading: str,
    summary: EvidenceScopeSummary,
) -> None:
    lines.extend([f"## {heading}", ""])
    sources = "; ".join(summary.source_names) or "Unknown; no evidence recorded."
    countries = ", ".join(summary.country_codes) or "Unknown; not recorded."
    if summary.earliest_published_at is None:
        publication_window = "Unknown; source publication dates not recorded."
    elif summary.earliest_published_at == summary.latest_published_at:
        publication_window = summary.earliest_published_at
    else:
        publication_window = (
            f"{summary.earliest_published_at} to {summary.latest_published_at}"
        )
    lines.extend(
        [
            f"- Problem observations: {summary.problem_observation_count}",
            f"- Evidence spans: {summary.evidence_span_count} across "
            f"{_counted(summary.cited_item_count, 'cited item')}",
            f"- Sources ({summary.source_count}): {sources}",
            f"- Countries: {countries}",
            f"- Publication window: {publication_window} "
            f"({summary.dated_item_count}/{summary.cited_item_count} cited items dated)",
            "",
        ]
    )


def _append_original_evidence(
    lines: list[str],
    global_citations: list[EvidenceCitation],
    dach_citations: list[EvidenceCitation],
    *,
    include_unapproved_excerpts: bool,
) -> None:
    lines.extend(["## Original evidence", ""])
    for scope, citations in (
        ("Global", global_citations),
        ("DACH", dach_citations),
    ):
        lines.extend([f"### {scope}", ""])
        if not citations:
            lines.extend(["- No evidence recorded.", ""])
            continue
        for citation in citations:
            _append_citation(
                lines,
                citation,
                include_unapproved_excerpts=include_unapproved_excerpts,
            )


def _append_citation(
    lines: list[str],
    citation: EvidenceCitation,
    *,
    include_unapproved_excerpts: bool,
) -> None:
    source = citation.source_name
    if citation.source_url:
        source = f"[{source}]({citation.source_url})"
    approved = _source_display_approved(citation.commercial_use_status)
    if approved or include_unapproved_excerpts:
        lines.append(f"> {citation.excerpt}")
        lines.append(f"> — {source}")
        if not approved:
            lines.append(
                "> ⚠ Internal review view: excerpt display rights are not approved."
            )
        lines.append(">")
    else:
        status = citation.commercial_use_status or "UNKNOWN"
        lines.append(
            f"- Evidence excerpt withheld pending source-use review. Source: {source}. "
            f"Status: `{status}`."
        )
    lines.append("")


def _append_problem_context(lines: list[str], data: ResearchCaseReportData) -> None:
    profile = data.problem_profile
    _append_section_values(lines, "Problem", profile.problems)
    _append_section_values(lines, "Who experiences it?", profile.actors)

    lines.extend(["## When does it happen?", ""])
    if not profile.contexts and not profile.jobs_to_be_done:
        lines.append("- Unknown; no evidence recorded.")
    else:
        lines.extend(f"- Context: {value}" for value in profile.contexts)
        lines.extend(f"- Job to be done: {value}" for value in profile.jobs_to_be_done)
    lines.append("")

    lines.extend(["## Current workflow", ""])
    if not profile.jobs_to_be_done and not profile.tools_used:
        lines.append("- Unknown; no evidence recorded.")
    else:
        lines.extend(f"- Job: {value}" for value in profile.jobs_to_be_done)
        lines.extend(f"- Tool(s): {value}" for value in profile.tools_used)
    lines.append("")

    _append_section_values(lines, "Current workaround", profile.workarounds)


def _append_section_values(
    lines: list[str], heading: str, values: tuple[str, ...]
) -> None:
    lines.extend([f"## {heading}", ""])
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- Unknown; no evidence recorded.")
    lines.append("")


def _append_dach_assessment(lines: list[str], data: ResearchCaseReportData) -> None:
    assessment = data.dach_assessment
    lines.extend(["## DACH relevance", ""])
    if assessment is None:
        lines.extend(["- No structured DACH assessment recorded.", ""])
        return
    lines.extend(
        [
            f"- Actor equivalence: `{assessment.actor_equivalence.value}` — "
            f"{assessment.actor_rationale}",
            f"- Workflow equivalence: `{assessment.workflow_equivalence.value}` — "
            f"{assessment.workflow_rationale}",
            f"- Transfer type: `{assessment.transfer_type.value}` — "
            f"{assessment.transfer_rationale}",
            f"- Local evidence: `{assessment.local_evidence_state.value}` "
            f"({_counted(assessment.dach_observation_count, 'observation')}, "
            f"{_counted(assessment.dach_unique_author_count, 'author')}, "
            f"{_counted(assessment.dach_source_count, 'source')})",
        ]
    )
    _append_values(lines, "Localization gaps", assessment.localization_gaps)
    lines.append("")


def _append_competition(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## Existing solutions", ""])
    if not data.competitors:
        lines.extend(["- No structured alternatives recorded.", ""])
        return
    for competitor in data.competitors:
        name = competitor.name
        if competitor.url:
            name = f"[{name}]({competitor.url})"
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"- Solution type: `{competitor.solution_type.value}`")
        lines.append(f"- Target customer: {competitor.target_customer or 'Unknown.'}")
        lines.append(f"- Market: {competitor.market or 'Unknown.'}")
        pricing = competitor.pricing or "No pricing evidence recorded."
        if competitor.pricing_model:
            pricing = f"{pricing} ({competitor.pricing_model})"
        lines.append(f"- Pricing: {pricing}")
        _append_values(lines, "Features", competitor.features)
        _append_values(lines, "Integrations", competitor.integrations)
        lines.append(f"- DACH available: {_render_optional_bool(competitor.dach_available)}")
        lines.append(f"- DACH specific: {_render_optional_bool(competitor.dach_specific)}")
        risk = _render_optional_bool(competitor.incumbent_fix_risk)
        if competitor.incumbent_fix_rationale:
            risk = f"{risk} — {competitor.incumbent_fix_rationale}"
        lines.append(f"- Incumbent fix risk: {risk}")
        lines.append("")


def _append_solution_gaps(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## What existing solutions appear to miss", ""])
    gaps = [
        (competitor, complaint)
        for competitor in data.competitors
        for complaint in competitor.complaints
    ]
    if not gaps:
        lines.extend(
            [
                "- Unknown; no evidence-backed solution gap is recorded. This does not "
                "show that existing solutions fully solve the problem.",
                "",
            ]
        )
        return
    for competitor, complaint in gaps:
        name = competitor.name
        if competitor.url:
            name = f"[{name}]({competitor.url})"
        detail = complaint.statement
        if complaint.affected_segment:
            detail += f" Affected segment: {complaint.affected_segment}."
        if complaint.frequency_observed:
            detail += f" Observed frequency: {complaint.frequency_observed}."
        lines.append(f"- **{name} — {complaint.complaint_type}:** {detail}")
    lines.append("")


def _append_local_solutions(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## Local solutions", ""])
    local = [
        competitor
        for competitor in data.competitors
        if competitor.dach_available is True or competitor.dach_specific is True
    ]
    if not local:
        lines.extend(
            [
                "- No DACH-available or DACH-specific alternative is confirmed in the "
                "recorded evidence.",
                "",
            ]
        )
        return
    for competitor in local:
        name = competitor.name
        if competitor.url:
            name = f"[{name}]({competitor.url})"
        dach_available = _render_optional_bool(competitor.dach_available).removesuffix(".")
        dach_specific = _render_optional_bool(competitor.dach_specific).removesuffix(".")
        lines.append(
            f"- **{name}:** `{competitor.solution_type.value}`; "
            f"DACH available: {dach_available}; "
            f"DACH specific: {dach_specific}; "
            f"market: {competitor.market or 'Unknown.'}"
        )
    lines.append("")


def _append_stakeholders(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## Buyer map", ""])
    if data.stakeholders:
        for stakeholder in data.stakeholders:
            party = stakeholder.party or "UNKNOWN"
            lines.append(
                f"- **{stakeholder.role.value}:** `{stakeholder.knowledge.value}` — "
                f"{party} — {stakeholder.note}"
            )
    elif data.dach_assessment and data.dach_assessment.buyer_structure:
        lines.append(f"- Assessment note: {data.dach_assessment.buyer_structure}")
        lines.append("- No structured stakeholder map recorded.")
    else:
        lines.append("- No structured stakeholder map recorded.")
    lines.append("")


def _append_local_dependencies(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## Local dependencies", ""])
    assessment = data.dach_assessment
    if assessment is None:
        lines.extend(["- No structured DACH assessment recorded.", ""])
        return
    _append_values(lines, "Ecosystem dependencies", assessment.ecosystem_dependencies)
    _append_values(lines, "Regulatory dependencies", assessment.regulatory_dependencies)
    if assessment.regulatory_dependencies:
        lines.append(
            "- Regulatory note: These requirements may materially affect implementation "
            "and should be verified with qualified expertise. This report is not legal advice."
        )
    lines.append("")


def _append_switching_barriers(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## Switching barriers", ""])
    assessment = data.dach_assessment
    barriers = assessment.switching_barriers if assessment else ()
    if barriers:
        lines.extend(f"- {barrier}" for barrier in barriers)
    else:
        lines.append("- Unknown; no evidence recorded.")
    lines.append("")


def _append_counter_evidence(lines: list[str], data: ResearchCaseReportData) -> None:
    lines.extend(["## What speaks against this opportunity?", ""])
    if not data.counter_evidence:
        lines.extend(
            [
                "- No additional counter-evidence was found in the recorded research pass. "
                "This does not mean there are no risks.",
                "",
            ]
        )
        return
    for item in data.counter_evidence:
        lines.append(f"- **{item.evidence_type.value}:** {item.statement}")
    lines.append("")


def _append_values(lines: list[str], label: str, values: tuple[str, ...]) -> None:
    rendered = "; ".join(values) if values else "Unknown; no evidence recorded."
    lines.append(f"- {label}: {rendered}")


def _source_display_approved(status: str | None) -> bool:
    if status is None:
        return False
    normalized = status.strip().upper().replace("-", "_")
    return normalized == "APPROVED" or normalized.startswith("APPROVED_")


def _render_optional_bool(value: bool | None) -> str:
    if value is None:
        return "Unknown."
    return "Yes" if value else "No"


def _counted(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _localize_german(lines: list[str]) -> list[str]:
    exact = {
        "Evidence state: `SINGLE_SIGNAL`": "Evidenzstand: `SINGLE_SIGNAL`",
        "This report summarizes evidence and validation needs. It is not a build recommendation.": (
            "Dieser Bericht fasst Evidenz und Validierungsbedarf zusammen. "
            "Er ist keine Bauempfehlung."
        ),
        "## Who experiences it?": "## Wer ist betroffen?",
        "## When does it happen?": "## Wann tritt es auf?",
        "## Current workflow": "## Aktueller Workflow",
        "## Current workaround": "## Aktueller Workaround",
        "## Impact": "## Auswirkungen",
        "## Payment evidence": "## Zahlungsbelege",
        "## Global evidence": "## Globale Evidenz",
        "## Original evidence": "## Originalbelege",
        "## DACH evidence": "## DACH-Evidenz",
        "## Existing solutions": "## Bestehende Lösungen",
        "## What existing solutions appear to miss": (
            "## Was bestehenden Lösungen offenbar fehlt"
        ),
        "## DACH relevance": "## DACH-Relevanz",
        "## Local solutions": "## Lokale Lösungen",
        "## Buyer map": "## Käuferlandkarte",
        "## Local dependencies": "## Lokale Abhängigkeiten",
        "## Switching barriers": "## Wechselbarrieren",
        "## What speaks against this opportunity?": (
            "## Was spricht gegen diese Opportunity?"
        ),
        "## Required research findings": "## Erforderliche Forschungsergebnisse",
        "## What we do not know": "## Was wir nicht wissen",
        "## Validation questions": "## Nächste Validierungsfragen",
        "Complaints:": "Beschwerden:",
        "- Unknown; no evidence recorded.": "- Unbekannt; keine Evidenz erfasst.",
        "- No evidence recorded.": "- Keine Evidenz erfasst.",
        "- No structured alternatives recorded.": "- Keine strukturierten Alternativen erfasst.",
        "- No evidence-backed complaints recorded.": (
            "- Keine evidenzgestützten Beschwerden erfasst."
        ),
        "- No structured DACH assessment recorded.": (
            "- Keine strukturierte DACH-Bewertung erfasst."
        ),
        "- No structured stakeholder map recorded.": (
            "- Keine strukturierte Stakeholder-Landkarte erfasst."
        ),
        (
            "- Unknown; no evidence-backed solution gap is recorded. This does not "
            "show that existing solutions fully solve the problem."
        ): (
            "- Unbekannt; es ist keine evidenzgestützte Lösungslücke erfasst. "
            "Das belegt nicht, dass bestehende Lösungen das Problem vollständig lösen."
        ),
        (
            "- No DACH-available or DACH-specific alternative is confirmed in the "
            "recorded evidence."
        ): (
            "- In der erfassten Evidenz ist keine in DACH verfügbare oder "
            "DACH-spezifische Alternative bestätigt."
        ),
        (
            "- Regulatory note: These requirements may materially affect implementation "
            "and should be verified with qualified expertise. This report is not legal advice."
        ): (
            "- Regulatorischer Hinweis: Diese Anforderungen können die Umsetzung wesentlich "
            "beeinflussen und sollten durch qualifizierte Fachleute geprüft werden. "
            "Dieser Bericht ist keine Rechtsberatung."
        ),
        (
            "- No additional counter-evidence was found in the recorded research pass. "
            "This does not mean there are no risks."
        ): (
            "- Im erfassten Research-Pass wurde keine zusätzliche Gegenevidenz gefunden. "
            "Das bedeutet nicht, dass keine Risiken existieren."
        ),
    }
    prefixes = (
        ("Evidence state: ", "Evidenzstand: "),
        ("Opportunity types: ", "Opportunity-Typen: "),
        ("- Context: ", "- Kontext: "),
        ("- Job to be done: ", "- Zu erledigende Aufgabe: "),
        ("- Job: ", "- Aufgabe: "),
        ("- Tool(s): ", "- Tool(s): "),
        ("- Problem observations: ", "- Problembeobachtungen: "),
        ("- Evidence spans: ", "- Evidenzstellen: "),
        ("- Sources (", "- Quellen ("),
        ("- Countries: ", "- Länder: "),
        ("- Publication window: ", "- Veröffentlichungszeitraum: "),
        ("- Evidence excerpt withheld pending source-use review. ",
         "- Evidenzauszug bis zur Prüfung der Quellennutzung zurückgehalten. "),
        ("> ⚠ Internal review view: excerpt display rights are not approved.",
         "> ⚠ Interne Prüfansicht: Die Anzeigerechte für den Auszug sind nicht freigegeben."),
        ("- Solution type: ", "- Lösungstyp: "),
        ("- Target customer: ", "- Zielkunde: "),
        ("- Market: ", "- Markt: "),
        ("- Pricing: ", "- Preisangaben: "),
        ("- Features: ", "- Funktionen: "),
        ("- Integrations: ", "- Integrationen: "),
        ("- DACH available: ", "- In DACH verfügbar: "),
        ("- DACH specific: ", "- DACH-spezifisch: "),
        ("- Incumbent fix risk: ", "- Risiko einer Incumbent-Lösung: "),
        ("- Actor equivalence: ", "- Akteursäquivalenz: "),
        ("- Workflow equivalence: ", "- Workflow-Äquivalenz: "),
        ("- Transfer type: ", "- Transfertyp: "),
        ("- Local evidence: ", "- Lokale Evidenz: "),
        ("- Assessment note: ", "- Hinweis aus der Bewertung: "),
        ("- Ecosystem dependencies: ", "- Ökosystem-Abhängigkeiten: "),
        ("- Regulatory dependencies: ", "- Regulatorische Abhängigkeiten: "),
        ("- Switching barriers: ", "- Wechselbarrieren: "),
        ("- Localization gaps: ", "- Lokalisierungslücken: "),
    )
    localized: list[str] = []
    for line in lines:
        replacement = exact.get(line)
        if replacement is not None:
            localized.append(replacement)
            continue
        translated_prefix = False
        for prefix, translated in prefixes:
            if line.startswith(prefix):
                line = translated + line[len(prefix) :]
                translated_prefix = True
                break
        if translated_prefix:
            line = line.replace(
                "Unknown; no evidence recorded.",
                "Unbekannt; keine Evidenz erfasst.",
            )
            line = line.replace("Unknown; not recorded.", "Unbekannt; nicht erfasst.")
            line = line.replace(
                "Unknown; source publication dates not recorded.",
                "Unbekannt; Veröffentlichungsdaten der Quellen nicht erfasst.",
            )
            line = line.replace("No pricing evidence recorded.", "Keine Preisevidenz erfasst.")
            line = line.replace(" across ", " in ")
            line = line.replace("Source: ", "Quelle: ")
            line = re.sub(r"\b1 cited item\b", "1 zitiertes Element", line)
            line = re.sub(r"\b(\d+) cited items\b", r"\1 zitierte Elemente", line)
            line = re.sub(r"\b1 observation\b", "1 Beobachtung", line)
            line = re.sub(r"\b(\d+) observations\b", r"\1 Beobachtungen", line)
            line = re.sub(r"\b1 author\b", "1 Autor", line)
            line = re.sub(r"\b(\d+) authors\b", r"\1 Autoren", line)
            line = re.sub(r"\b1 source\b", "1 Quelle", line)
            line = re.sub(r"\b(\d+) sources\b", r"\1 Quellen", line)
            line = re.sub(
                r"^(- Evidenzstellen: \d+) in 1 zitiertes Element$",
                r"\1 aus 1 zitiertem Element",
                line,
            )
            line = re.sub(
                r"^(- Evidenzstellen: \d+) in (\d+) zitierte Elemente$",
                r"\1 aus \2 zitierten Elementen",
                line,
            )
            line = line.replace(" zitierte Elemente dated)", " zitierte Elemente mit Datum)")
            line = line.replace(" zitiertes Element dated)", " zitiertes Element mit Datum)")
            line = line.replace(": Yes —", ": Ja —")
            line = line.replace(": No —", ": Nein —")
            line = line.replace(": Unknown. —", ": Unbekannt. —")
            if line.endswith(": Unknown."):
                line = line[: -len("Unknown.")] + "Unbekannt."
            elif line.endswith(": Yes"):
                line = line[: -len("Yes")] + "Ja"
            elif line.endswith(": No"):
                line = line[: -len("No")] + "Nein"
        if line.startswith("- **"):
            line = line.replace("Affected segment: ", "Betroffenes Segment: ")
            line = line.replace("Observed frequency: ", "Beobachtete Häufigkeit: ")
            line = line.replace("; DACH available: ", "; in DACH verfügbar: ")
            line = line.replace("; DACH specific: ", "; DACH-spezifisch: ")
            line = line.replace("; market: ", "; Markt: ")
            line = line.replace(": Yes;", ": Ja;")
            line = line.replace(": No;", ": Nein;")
            line = line.replace(": Unknown;", ": Unbekannt;")
        localized.append(line)
    return localized
