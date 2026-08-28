---
id: job_extraction
version: 1
---
You are analyzing a job posting for a candidate preparing an application.
Extract structured facts from the job description below.

{untrusted_preamble}

Rules:
- Extract only information stated in the posting; leave absent fields empty.
- `keywords`: terms an applicant-tracking system or recruiter would likely
  search for (skills, tools, methodologies, certifications).
- `red_flags`: concrete signals worth a candidate's attention (e.g. unusually
  broad responsibilities for the level, vague compensation, contradictory
  requirements). Only list what the text supports — do not speculate.
- `missing_or_ambiguous`: important information the posting does NOT provide
  (e.g. no salary range, unclear seniority, no location policy).

{jd_block}
