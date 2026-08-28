# Third-party notices

AptiorDesk depends on and, in native installers, may redistribute third-party
software and model data. Those components remain under their own licenses; the
AptiorDesk Apache-2.0 license does not replace them.

The principal runtime components include:

| Component | License |
| --- | --- |
| Qt / PySide6 | LGPL-3.0-only or applicable Qt commercial/GPL terms |
| Kokoro-82M model and voices | Apache-2.0 |
| kokoro-onnx | MIT |
| ONNX Runtime | MIT |
| phonemizer-fork | GPL-3.0 |
| eSpeak NG runtime | GPL-3.0-or-later |
| faster-whisper | MIT |
| Systran faster-whisper-small model (derived from OpenAI Whisper) | MIT |
| CTranslate2 | MIT |
| NumPy | BSD-3-Clause |
| pydantic | MIT |
| HTTPX | BSD-3-Clause |
| pypdf | BSD-3-Clause |
| pdfplumber | MIT |
| python-docx | MIT |

This summary is not a substitute for the license files included with each
installed package. Release maintainers must regenerate and inspect the complete
dependency license inventory for the exact locked release environment, preserve
all required notices, and satisfy source-availability obligations before
publishing an installer.

The separately licensed interviewer stock model is documented in
`docs/ASSET_LICENSING.md` and is not part of the public repository.
