"""Turn native integration-test screenshots into a timestamped review video.

Usage: python scripts/v2/render_openui_test_video.py ARTIFACT_DIRECTORY --speed 4
Requires ffmpeg on PATH. Original frames and timing manifest are preserved.
"""

import argparse
import json
import pathlib
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=pathlib.Path)
    parser.add_argument("--speed", type=float, default=4)
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("speed must be positive")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        parser.error("ffmpeg is required")
    directory = args.directory.resolve()
    manifest = json.loads((directory / "frames.json").read_text())
    frames = manifest["frames"]
    if not frames:
        parser.error("no recorded frames")
    concat = ["ffconcat version 1.0"]
    subtitles = []
    video_time = 0.0

    def timestamp(seconds):
        ms = round(seconds * 1000)
        return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

    for index, frame in enumerate(frames):
        path = directory / "frames" / frame["file"]
        # ffconcat uses single-quoted paths with shell-like quote escaping.
        escaped = str(path).replace("'", "'\\''")
        concat.append(f"file '{escaped}'")
        delta_ms = (
            frames[index + 1]["elapsed_ms"] - frame["elapsed_ms"]
            if index + 1 < len(frames)
            else 2000
        )
        duration = max(delta_ms / 1000 / args.speed, 1 / 24)
        concat.append(f"duration {duration:.6f}")
        label = (
            f"Native Flutter test | sampled ~1s + actions | {args.speed:g}x playback\n"
            f"{frame['case']} | elapsed {frame['elapsed_ms'] / 1000:.1f}s"
        )
        subtitles.append(
            f"{index + 1}\n{timestamp(video_time)} --> {timestamp(video_time + duration)}\n{label}\n"
        )
        video_time += duration
    concat.append(concat[-2])  # Repeat the last file to honor its duration.
    (directory / "recording.ffconcat").write_text("\n".join(concat) + "\n")
    (directory / "recording.srt").write_text("\n".join(subtitles))
    output = directory / "openui-native-tests.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning",
            "-safe", "0", "-f", "concat", "-i", "recording.ffconcat",
            "-vf", "scale=1600:900:force_original_aspect_ratio=decrease,"
            "pad=1600:900:(ow-iw)/2:(oh-ih)/2,pad=1600:964:0:64,"
            "subtitles=recording.srt:force_style='Fontsize=15,Alignment=8,MarginV=8,Outline=1,BackColour=&H80000000,BorderStyle=3'",
            "-r", "24", "-c:v", "libx264", "-preset", "fast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ],
        cwd=directory,
        check=True,
    )
    print(f"{output}: {len(frames)} screenshots, {video_time:.1f}s at {args.speed:g}x")


if __name__ == "__main__":
    main()
