#!/usr/bin/env python3
# run all our scripts in order so i don't have to do them manually every time
# works with either the original txt response or an already extracted mpd

# default usage: python3 run_workflow.py video.mpd
import subprocess
import sys
from pathlib import Path

folder = Path(__file__).resolve().parent

if len(sys.argv) > 2:
    sys.exit("usage: python3 run_workflow.py [video.mpd | video.txt]")

# use video.mpd by default if i don't specify a file
source = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) == 2 else folder / "video.mpd"

if not source.is_file():
    sys.exit(f"file not found: {source}")

# if i already have the mpd, there's no point extracting it again
if source.suffix.lower() == ".mpd":
    mpd = source
    steps = []
else:
    mpd = folder / "video.mpd"
    steps = [("extract_mpd.py", [str(source)])]

# get the responses, then use them to replace the urls in the mpd
steps.extend([
    ("request_v2.py", [str(mpd)]),
    ("replace_urls_from_log.py", [
        str(mpd),
        "requests_plain.txt",
        "video_urls_replaced.mpd"
    ]),
])

# run everything in order and stop if something fails
for index, (name, args) in enumerate(steps, 1):
    script = folder / name

    if not script.is_file():
        sys.exit(f"missing script: {script}")

    print(f"\n[{index}/{len(steps)}] running {name}", flush=True)

    result = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=folder
    )

    if result.returncode != 0:
        sys.exit(f"{name} failed (exit code {result.returncode})")

print("\ndone! output: video_urls_replaced.mpd")
