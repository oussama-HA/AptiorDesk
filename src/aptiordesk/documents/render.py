"""Render structured resume content to Markdown — used for previews, diffs
between versions, and (in Phase 3+) as the source for file exports."""

from __future__ import annotations

from aptiordesk.database.models.resume import ResumeContent


def resume_to_markdown(content: ResumeContent) -> str:
    lines: list[str] = []
    if content.full_name:
        lines.append(f"# {content.full_name}")
    if content.professional_title:
        lines.append(f"**{content.professional_title}**")
    contact_bits = [
        b
        for b in (
            content.email,
            content.phone,
            content.location,
            content.linkedin_url,
            content.github_url,
            content.portfolio_url,
        )
        if b
    ]
    if contact_bits:
        lines.append(" · ".join(contact_bits))
    if content.summary:
        lines += ["", "## Summary", content.summary]

    if content.experiences:
        lines += ["", "## Experience"]
        for exp in content.experiences:
            dates = _dates(exp.start_date, exp.end_date)
            heading = " — ".join(b for b in (exp.title, exp.organization) if b)
            lines.append(f"\n### {heading}{f' ({dates})' if dates else ''}")
            if exp.location:
                lines.append(f"*{exp.location}*")
            if exp.description:
                lines.append(exp.description)
            lines.extend(f"- {h}" for h in exp.highlights)

    if content.education:
        lines += ["", "## Education"]
        for edu in content.education:
            dates = _dates(edu.start_date, edu.end_date)
            heading = " — ".join(b for b in (edu.degree, edu.field_of_study, edu.institution) if b)
            lines.append(f"- **{heading}**{f' ({dates})' if dates else ''}")
            if edu.details:
                lines.append(f"  {edu.details}")

    if content.skills:
        lines += ["", "## Skills"]
        by_category: dict[str, list[str]] = {}
        for skill in content.skills:
            by_category.setdefault(skill.category or "General", []).append(skill.name)
        for category, names in by_category.items():
            lines.append(f"- **{category}**: {', '.join(n for n in names if n)}")

    if content.projects:
        lines += ["", "## Projects"]
        for project in content.projects:
            title = f"**{project.name}**" + (f" ({project.url})" if project.url else "")
            lines.append(
                f"- {title}" + (f" — {project.description}" if project.description else "")
            )
            lines.extend(f"  - {h}" for h in project.highlights)

    if content.certifications:
        lines += ["", "## Certifications"]
        for cert in content.certifications:
            bits = " — ".join(b for b in (cert.name, cert.issuer, cert.date) if b)
            lines.append(f"- {bits}")

    if content.languages:
        lines += ["", "## Languages"]
        lines.append(
            ", ".join(
                f"{lang.name} ({lang.proficiency})" if lang.proficiency else lang.name
                for lang in content.languages
                if lang.name
            )
        )

    if content.other:
        lines += ["", "## Additional"]
        for entry in content.other:
            bits = " — ".join(b for b in (entry.title, entry.organization, entry.date) if b)
            lines.append(f"- {bits}" + (f": {entry.description}" if entry.description else ""))

    return "\n".join(lines).strip() + "\n"


def _dates(start: str, end: str) -> str:
    if not start and not end:
        return ""
    return f"{start or '?'} – {end or 'present'}"
