#!/usr/bin/env python3
"""Extract and decode an escaped DASH MPD from a saved website response."""


import sys
import codecs
import shutil
import subprocess
import xml.etree.ElementTree as ET

# get the original file
if len(sys.argv) < 2:
    print("usage: python3 extract_mpd.py original_response.txt")
    sys.exit(1)

with open(sys.argv[1], "r", encoding="utf-8") as f:
    text = f.read()

# find where the mpd starts and ends
start = text.find(r"\u003c?xml")

end_marker = r"\u003c/MPD\u003e"
end = text.find(end_marker, start)

# sometimes the forward slash is escaped too
if end == -1:
    end_marker = r"\u003c\/MPD\u003e"
    end = text.find(end_marker, start)

if start == -1 or end == -1:
    print("couldn't find the mpd in this file")
    sys.exit(1)

# cut out everything before and after the mpd
mpd = text[start:end + len(end_marker)]

with open("video.txt", "w", encoding="utf-8") as f:
    f.write(mpd)

# decode the unicode escapes
mpd = codecs.decode(mpd, "unicode_escape")
mpd = mpd.replace(r"\/", "/")

with open("video.mpd", "w", encoding="utf-8") as f:
    f.write(mpd)

print("saved video.txt and video.mpd")

# check if the xml is valid
if shutil.which("xmllint"):
    result = subprocess.run(["xmllint", "--noout", "video.mpd"])

    if result.returncode == 0:
        print("valid xml")
    else:
        print("invalid xml")
else:
    try:
        ET.parse("video.mpd")
        print("valid xml")
    except ET.ParseError as e:
        print("invalid xml:", e)
