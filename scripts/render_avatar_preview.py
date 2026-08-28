"""Render the supplied AptiorDesk avatar GLB into a preview image.

This is a development utility and does not add the third-party model to the
application package. It loads the GLB from its ZIP archive into a temporary
directory, renders with Qt Quick 3D, and saves a PNG for visual inspection.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import wave
import zipfile
from array import array
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtQuick import QQuickView
from PySide6.QtQuick3D import QQuick3D


def _extract_glb(archive_path: Path, destination: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        candidates = [
            name for name in archive.namelist() if name.lower().endswith(".glb")
        ]
        if len(candidates) != 1:
            raise ValueError(
                f"Expected one GLB in {archive_path.name}; found {len(candidates)}"
            )
        member = candidates[0]
        output = destination / "aptiordesk-interviewer.glb"
        output.write_bytes(archive.read(member))
        return output


def _condition_asset(model_path: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    executable = Path(sys.executable).with_name("pyside6-balsam.exe")
    if not executable.exists():
        raise FileNotFoundError(f"Qt asset conditioner not found: {executable}")
    subprocess.run(
        [str(executable), "-o", str(destination), str(model_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    candidates = list(destination.glob("*.qml"))
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected one generated avatar component; found {len(candidates)}"
        )
    component = candidates[0]
    source = component.read_text(encoding="utf-8")

    # The source asset contains six static pose tracks. Balsam enables every
    # imported timeline by default, so make the selected one explicit. This
    # prevents several full-body poses from fighting over the same skeleton.
    header_pattern = re.compile(
        r'(Timeline \{\s+id: [^\n]+\s+objectName: "([^"]+)"'
        r"\s+property real framesPerSecond: [^\n]+\s+startFrame: [^\n]+"
        r"\s+endFrame: [^\n]+\s+currentFrame: [^\n]+\s+enabled:) true"
        r"(\s+animations: TimelineAnimation \{\s+duration: [^\n]+"
        r"\s+from: [^\n]+\s+to: [^\n]+\s+running:) true",
        re.MULTILINE,
    )

    def select_timeline(match: re.Match[str]) -> str:
        animation_name = match.group(2)
        condition = f' avatarAnimation === "{animation_name}"'
        return match.group(1) + condition + match.group(3) + " false"

    source, replacements = header_pattern.subn(select_timeline, source)
    if replacements == 0:
        raise RuntimeError("The conditioned avatar contains no animation timelines")
    source, eye_material_replacements = re.subn(
        r'(objectName: "Std_Eye_Occlusion_[RL]"\s+baseColor:) "#ff000000"',
        r'\1 "#00000000"',
        source,
    )
    if "Std_Eye_Occlusion_" in source and eye_material_replacements not in (0, 2):
        raise RuntimeError(
            "Expected to repair both eye-occlusion materials; "
            f"updated {eye_material_replacements}"
        )
    source = source.replace(
        "currentFrame: 0\n        enabled:",
        "currentFrame: endFrame\n        enabled:",
    )
    component.write_text(source, encoding="utf-8")
    return component


def _audio_envelope(path: Path, fps: int) -> tuple[list[float], float]:
    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        if sample_width != 2:
            raise ValueError("The avatar demo expects 16-bit PCM speech audio")
        samples = array("h")
        samples.frombytes(source.readframes(frame_count))
    if channels > 1:
        samples = array("h", samples[::channels])
    duration = frame_count / sample_rate
    window = max(1, round(sample_rate / fps))
    rms_values: list[float] = []
    for start in range(0, len(samples), window):
        chunk = samples[start : start + window]
        if not chunk:
            continue
        mean_square = sum(value * value for value in chunk) / len(chunk)
        rms_values.append(mean_square**0.5)
    peak = max(rms_values, default=1.0)
    envelope = [min(1.0, (value / peak) ** 0.55) for value in rms_values]
    return envelope, duration


def _viseme_for_character(character: str) -> str | None:
    lowered = character.lower()
    if lowered in "bmp":
        return "Explosive"
    if lowered in "fv":
        return "Dental_Lip"
    if lowered in "oquw":
        return "Tight-O"
    if lowered in "eiy":
        return "Wide"
    if lowered in "cjgxz":
        return "Affricate"
    if lowered == "a":
        return "Open"
    if lowered in "dlnrsthk":
        return "Tight"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--wait-ms", type=int, default=9000)
    parser.add_argument("--pose", default="Pose  14")
    parser.add_argument("--avatar-yaw", type=float, default=0)
    parser.add_argument("--camera-x", type=float, default=0)
    parser.add_argument("--camera-y", type=float, default=1.42)
    parser.add_argument("--camera-yaw", type=float, default=0)
    parser.add_argument("--camera-pitch", type=float, default=0)
    parser.add_argument("--demo-audio", type=Path)
    parser.add_argument("--demo-video", type=Path)
    parser.add_argument("--pose-sheet", type=Path)
    parser.add_argument("--framing-sheet", type=Path)
    parser.add_argument(
        "--demo-text",
        default=(
            "Welcome to your AptiorDesk mock interview. "
            "Tell me about a project you are proud of."
        ),
    )
    parser.add_argument("--fps", type=int, default=15)
    args = parser.parse_args()

    app = QGuiApplication(sys.argv[:1])
    QSurfaceFormat.setDefaultFormat(QQuick3D.idealSurfaceFormat(4))

    temporary = tempfile.TemporaryDirectory(prefix="aptiordesk-avatar-")
    model_path = _extract_glb(args.archive, Path(temporary.name))
    component_path = _condition_asset(
        model_path, Path(temporary.name) / "conditioned"
    )

    view = QQuickView()
    view.setColor("#09090b")
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.rootContext().setContextProperty("avatarAnimation", args.pose)
    qml_path = Path(__file__).with_name("avatar_preview.qml").resolve()
    view.setSource(QUrl.fromLocalFile(str(qml_path)))
    if view.status() == QQuickView.Status.Error:
        for error in view.errors():
            print(error.toString(), file=sys.stderr)
        return 1

    root = view.rootObject()
    if root is None:
        print("Avatar preview QML did not create a root object.", file=sys.stderr)
        return 1
    root.setProperty("componentSource", QUrl.fromLocalFile(str(component_path)))
    root.setProperty("avatarYaw", args.avatar_yaw)
    root.setProperty("cameraX", args.camera_x)
    root.setProperty("cameraY", args.camera_y)
    root.setProperty("cameraYaw", args.camera_yaw)
    root.setProperty("cameraPitch", args.camera_pitch)
    root.setProperty("loadStatus", f"{args.pose.strip()} - facial rig online")
    if args.demo_audio and args.demo_video:
        root.setProperty("meetingStatus", "Speaking")

    view.resize(1200, 760)
    view.show()

    def facial_control_map() -> dict[str, list[QObject]]:
        controls: dict[str, list[QObject]] = {}
        for child in root.findChildren(QObject):
            name = child.objectName()
            if name and child.metaObject().indexOfProperty("weight") >= 0:
                controls.setdefault(name, []).append(child)
        return controls

    def save_preview() -> None:
        controls = facial_control_map()
        facial_objects = sorted(
            {
                name
                for name in controls
                if any(
                    term in name.lower()
                    for term in ("mouth", "open", "blink", "wide", "jaw", "lip")
                )
            }
        )
        print(
            "Runtime facial controls:",
            facial_objects[:24],
            f"({len(facial_objects)} named controls)",
        )
        if args.pose_sheet:
            capture_pose_sheet()
            return
        if args.framing_sheet:
            capture_framing_sheet()
            return
        if args.demo_audio and args.demo_video:
            capture_demo(controls)
            return
        image = view.grabWindow()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if image.isNull() or not image.save(str(args.output)):
            print("Could not capture the avatar preview.", file=sys.stderr)
            app.exit(2)
            return
        print(f"Saved avatar preview to {args.output}")
        app.quit()

    def capture_pose_sheet() -> None:
        from PIL import Image, ImageDraw

        poses = (
            "Am male cartoon|A|TPose",
            "Pose  14",
            "Pose  23",
            "Pose  27",
            "Pose  29",
            "Pose  7",
        )
        images: list[tuple[str, Image.Image]] = []
        state = {"index": 0}

        def select_pose() -> None:
            index = state["index"]
            if index >= len(poses):
                finish_sheet()
                return
            pose = poses[index]
            view.rootContext().setContextProperty("avatarAnimation", pose)
            root.setProperty("loadStatus", f"{pose.strip()} - pose review")
            QTimer.singleShot(180, capture_pose)

        def capture_pose() -> None:
            pose = poses[state["index"]]
            image = view.grabWindow()
            temporary_path = Path(temporary.name) / f"pose-{state['index']}.png"
            image.save(str(temporary_path))
            with Image.open(temporary_path) as rendered:
                images.append((pose, rendered.convert("RGB")))
            state["index"] += 1
            QTimer.singleShot(30, select_pose)

        def finish_sheet() -> None:
            tile_width, tile_height = 600, 380
            sheet = Image.new("RGB", (tile_width * 3, tile_height * 2), "#09090b")
            draw = ImageDraw.Draw(sheet)
            for index, (pose, rendered) in enumerate(images):
                resized = rendered.resize((tile_width, tile_height))
                x = (index % 3) * tile_width
                y = (index // 3) * tile_height
                sheet.paste(resized, (x, y))
                draw.rectangle((x + 12, y + 12, x + 245, y + 45), fill="#111115")
                draw.text((x + 24, y + 21), pose, fill="#ffffff")
            args.pose_sheet.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(args.pose_sheet)
            print(f"Saved avatar pose sheet to {args.pose_sheet}")
            app.quit()

        select_pose()

    def capture_framing_sheet() -> None:
        from PIL import Image, ImageDraw

        framings = (
            ("yaw -35", -35, 0, 1.30, 0, 0),
            ("yaw -20", -20, 0, 1.30, 0, 0),
            ("yaw 0", 0, 0, 1.30, 0, 0),
            ("yaw +20", 20, 0, 1.30, 0, 0),
            ("yaw +35", 35, 0, 1.30, 0, 0),
            ("camera right", 0, 0.42, 1.30, -14, 0),
        )
        images: list[tuple[str, Image.Image]] = []
        state = {"index": 0}

        def select_framing() -> None:
            index = state["index"]
            if index >= len(framings):
                finish_sheet()
                return
            label, avatar_yaw, camera_x, camera_y, camera_yaw, camera_pitch = (
                framings[index]
            )
            root.setProperty("avatarYaw", avatar_yaw)
            root.setProperty("cameraX", camera_x)
            root.setProperty("cameraY", camera_y)
            root.setProperty("cameraYaw", camera_yaw)
            root.setProperty("cameraPitch", camera_pitch)
            root.setProperty("loadStatus", f"{label} - framing review")
            QTimer.singleShot(180, capture_framing)

        def capture_framing() -> None:
            label = framings[state["index"]][0]
            image = view.grabWindow()
            temporary_path = (
                Path(temporary.name) / f"framing-{state['index']}.png"
            )
            image.save(str(temporary_path))
            with Image.open(temporary_path) as rendered:
                images.append((label, rendered.convert("RGB")))
            state["index"] += 1
            QTimer.singleShot(30, select_framing)

        def finish_sheet() -> None:
            tile_width, tile_height = 600, 380
            sheet = Image.new("RGB", (tile_width * 3, tile_height * 2), "#09090b")
            draw = ImageDraw.Draw(sheet)
            for index, (label, rendered) in enumerate(images):
                resized = rendered.resize((tile_width, tile_height))
                x = (index % 3) * tile_width
                y = (index // 3) * tile_height
                sheet.paste(resized, (x, y))
                draw.rectangle((x + 12, y + 12, x + 245, y + 45), fill="#111115")
                draw.text((x + 24, y + 21), label, fill="#ffffff")
            args.framing_sheet.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(args.framing_sheet)
            print(f"Saved avatar framing sheet to {args.framing_sheet}")
            app.quit()

        select_framing()

    def capture_demo(controls: dict[str, list[QObject]]) -> None:
        envelope, duration = _audio_envelope(args.demo_audio, args.fps)
        frame_total = max(1, round(duration * args.fps))
        frame_directory = Path(temporary.name) / "frames"
        frame_directory.mkdir()
        speech_characters = [
            character
            for character in args.demo_text
            if character.isalpha() or character.isspace()
        ]
        driven_names = (
            "Open",
            "V_Open",
            "Explosive",
            "V_Explosive",
            "Dental_Lip",
            "V_Dental_Lip",
            "Tight-O",
            "V_Tight_O",
            "Tight",
            "V_Tight",
            "Wide",
            "V_Wide",
            "Affricate",
            "V_Affricate",
            "Lip_Open",
            "V_Lip_Open",
            "Mouth_Open",
            "jawOpen",
            "A25_Jaw_Open",
            "Eye_Blink",
            "Eyes_Blink",
            "Eye_Blink_L",
            "Eye_Blink_R",
            "eyeBlinkLeft",
            "eyeBlinkRight",
            "A14_Eye_Blink_Left",
            "A15_Eye_Blink_Right",
        )
        control_aliases = {
            "Open": ("Open", "V_Open"),
            "Explosive": ("Explosive", "V_Explosive"),
            "Dental_Lip": ("Dental_Lip", "V_Dental_Lip"),
            "Tight-O": ("Tight-O", "V_Tight_O"),
            "Tight": ("Tight", "V_Tight"),
            "Wide": ("Wide", "V_Wide"),
            "Affricate": ("Affricate", "V_Affricate"),
            "Lip_Open": ("Lip_Open", "V_Lip_Open"),
            "Mouth_Open": ("Mouth_Open", "jawOpen", "A25_Jaw_Open"),
            "Eye_Blink": ("Eye_Blink", "Eyes_Blink"),
            "Eye_Blink_L": (
                "Eye_Blink_L",
                "eyeBlinkLeft",
                "A14_Eye_Blink_Left",
            ),
            "Eye_Blink_R": (
                "Eye_Blink_R",
                "eyeBlinkRight",
                "A15_Eye_Blink_Right",
            ),
        }

        def set_weight(name: str, value: float) -> None:
            for alias in control_aliases.get(name, (name,)):
                for target in controls.get(alias, []):
                    target.setProperty("weight", value)

        state = {"index": 0}

        def prepare_frame() -> None:
            index = state["index"]
            if index >= frame_total:
                finish_video()
                return
            progress = index / max(1, frame_total - 1)
            speech_index = min(
                len(speech_characters) - 1,
                int(progress * max(0, len(speech_characters) - 1)),
            )
            character = speech_characters[speech_index] if speech_characters else " "
            viseme = _viseme_for_character(character)
            energy = envelope[min(index, len(envelope) - 1)] if envelope else 0.0

            for name in driven_names:
                set_weight(name, 0.0)
            if viseme:
                set_weight(viseme, 0.2 + energy * 0.8)
                set_weight("Mouth_Open", energy * 0.24)
                set_weight("Lip_Open", energy * 0.18)

            blink_phase = (index / args.fps) % 3.4
            if blink_phase < 0.14:
                blink_weight = 1.0 - abs(blink_phase - 0.07) / 0.07
                set_weight("Eye_Blink", max(0.0, blink_weight))
                set_weight("Eye_Blink_L", max(0.0, blink_weight))
                set_weight("Eye_Blink_R", max(0.0, blink_weight))

            QTimer.singleShot(24, capture_frame)

        def capture_frame() -> None:
            index = state["index"]
            image = view.grabWindow()
            frame_path = frame_directory / f"frame-{index:04d}.png"
            if image.isNull() or not image.save(str(frame_path)):
                print(f"Could not capture animation frame {index}.", file=sys.stderr)
                app.exit(2)
                return
            state["index"] += 1
            QTimer.singleShot(1, prepare_frame)

        def finish_video() -> None:
            args.demo_video.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-framerate",
                    str(args.fps),
                    "-i",
                    str(frame_directory / "frame-%04d.png"),
                    "-i",
                    str(args.demo_audio),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-shortest",
                    str(args.demo_video),
                ],
                check=True,
            )
            final_image = view.grabWindow()
            args.output.parent.mkdir(parents=True, exist_ok=True)
            final_image.save(str(args.output))
            print(f"Saved synchronized avatar demo to {args.demo_video}")
            app.quit()

        prepare_frame()

    QTimer.singleShot(args.wait_ms, save_preview)
    exit_code = app.exec()
    temporary.cleanup()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
