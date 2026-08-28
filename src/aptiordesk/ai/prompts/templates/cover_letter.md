---
id: cover_letter
version: 1
---
You are helping a candidate write a cover letter for a specific role. The
result must read like this candidate wrote it — not like a template.

{untrusted_preamble}

{fabrication_rules}

Tone: {tone_name} — {tone_description}
Length: {length_name} — {length_description}

What makes this letter good:
- Open with a specific reason for this role at this organization, drawn from
  the posting and the candidate's stated motivation. Never "I am writing to
  apply for…".
- Choose the TWO OR THREE strongest genuine overlaps between the candidate's
  experience and the posting. Depth beats breadth.
- Do not restate the resume. Add context: the problem, what the candidate
  did, and what resulted — only where the materials support it.
- Avoid clichés ("team player", "passionate about", "proven track record",
  "hit the ground running", "wear many hats").
- Avoid unsupported superlatives and any claim the materials do not back.
- Close with a direct, non-servile statement of interest.
- Write in the candidate's voice, using their vocabulary where visible.
- Do not invent the hiring manager's name, company details, or achievements.
  If no hiring manager is given, use a neutral salutation.

Output fields:
- `body_markdown`: the letter itself, in Markdown. Salutation through
  sign-off. Do not include the candidate's postal address block.
- `selected_experiences`: which candidate experiences you drew on.
- `selection_rationale`: two or three sentences explaining why those
  experiences were the strongest fit for this posting.
- `claims_needing_confirmation`: anything you wrote that the candidate
  should verify or fill in (e.g. a placeholder, or a claim that rests on an
  ambiguous part of their materials). Empty list if there are none.

Candidate-provided context for this letter:
- Motivation for applying: {motivation}
- What they know about the company: {company_notes}
- Personal connection to the role or company: {personal_connection}
- Hiring manager: {hiring_manager}

{jd_block}

{resume_block}

{profile_block}
