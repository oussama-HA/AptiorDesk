# Maintainer scripts

- `generate_release_icons.py` creates native platform icons from the canonical
  AptiorDesk artwork.
- `fetch_release_avatar.py` stages licensed interviewer assets from protected
  release storage without committing them.
- `validate_interview_room.py`, `validate_avatar_stage.py`, and
  `validate_provider_settings.py` render focused UI smoke-test screenshots.
- `validate_onboarding.py` renders the first-run AI-provider choice without
  probing the developer's Ollama installation.
- `inspect_glb.py`, `restore_glb_materials.py`,
  `export_authored_idle_glb.py`, and `render_avatar_preview.py` are avatar
  maintenance tools used to inspect and validate a privately licensed source
  model. They do not contain or redistribute that model.

Generated images, videos, conditioned models, and diagnostics belong in an
ignored artifact directory, never in the public source tree.
