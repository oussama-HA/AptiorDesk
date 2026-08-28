"""Native desktop smoke-check for the packaged AptiorDesk avatar stage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtQuick3D import QQuick3D
from PySide6.QtWidgets import QApplication

from aptiordesk.features.interviews.avatar import AvatarController, AvatarStage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("component", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--control",
        action="append",
        help="Set one named facial control before capture (useful for rig validation).",
    )
    parser.add_argument("--weight", type=float, default=1.0)
    parser.add_argument(
        "--allow-no-controls",
        action="store_true",
        help="Capture a static conditioned asset even when it has no facial controls.",
    )
    args = parser.parse_args()
    QSurfaceFormat.setDefaultFormat(QQuick3D.idealSurfaceFormat(4))
    app = QApplication(sys.argv[:1])
    controller = AvatarController()
    stage = AvatarStage(controller)
    stage.resize(1000, 650)
    stage.load_component(args.component.resolve())
    stage.show()
    result = {"code": 2}
    elapsed = QElapsedTimer()
    elapsed.start()

    def capture() -> None:
        for control in args.control or ():
            stage._set_weight(control, args.weight)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        image = stage.grab()
        if not image.isNull() and image.save(str(args.output)):
            print(f"Saved live avatar stage to {args.output}")
            print(f"Bound {len(stage._controls)} facial controls")
            result["code"] = 0
        controller.shutdown()
        app.quit()

    def wait_until_ready() -> None:
        if stage._controls:
            QTimer.singleShot(400, capture)
            return
        if args.allow_no_controls and elapsed.elapsed() >= 2_500:
            capture()
            return
        if elapsed.elapsed() >= 60_000:
            print("Avatar controls did not bind within 60 seconds.")
            controller.shutdown()
            app.quit()
            return
        QTimer.singleShot(250, wait_until_ready)

    QTimer.singleShot(250, wait_until_ready)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
