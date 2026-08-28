"""Render AptiorDesk AI-provider settings for native visual QA."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from aptiordesk.database.db import connect, migrate
from aptiordesk.database.models.provider import (
    CLIAdapterKind,
    ProviderConfig,
    ProviderKind,
)
from aptiordesk.database.repositories.provider_repo import ProviderRepository
from aptiordesk.features.settings.page import SettingsPage
from aptiordesk.ui.theme import apply_theme


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate_provider_settings.py OUTPUT.png")
    output = Path(sys.argv[1]).resolve()
    app = QApplication(sys.argv[:1])
    apply_theme("dark", app)
    connection = connect(":memory:")
    migrate(connection)
    repository = ProviderRepository(connection)
    local = repository.create(
        ProviderConfig(
            name="Private workspace",
            kind=ProviderKind.OLLAMA,
            model="qwen3:8b",
        )
    )
    repository.set_active(local.id)
    repository.create(
        ProviderConfig(
            name="Cloud reasoning",
            kind=ProviderKind.OPENAI_COMPAT,
            model="gpt-5-mini",
        )
    )
    repository.create(
        ProviderConfig(
            name="Codex on this device",
            kind=ProviderKind.CLI,
            cli_adapter=CLIAdapterKind.CODEX,
        )
    )
    page = SettingsPage(connection)
    page.resize(
        int(os.environ.get("APTIORDESK_QA_WIDTH", "1500")),
        int(os.environ.get("APTIORDESK_QA_HEIGHT", "900")),
    )
    page.show()
    result = {"code": 2}

    def capture() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        image = page.grab()
        if not image.isNull() and image.save(str(output)):
            print(f"Saved provider settings to {output}")
            result["code"] = 0
        page.close()
        connection.close()
        app.quit()

    QTimer.singleShot(500, capture)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
