#!/usr/bin/env python3

# get each different url from the mpd once and save the text responses
# no base64 and no downloading entire video files this time lol

import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

import requests


headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
    "DNT": "1",
    "Accept": "*/*",
    "Origin": "https://www.iq.com/",
    "Referer": "https://www.iq.com/",
}

namespace = {"dash": "urn:mpeg:dash:schema:mpd:2011"}
max_text_size = 64 * 1024  # 64 kb is plenty for a text response

if len(sys.argv) < 2:
    print("usage: python3 request_unique_plain_simple.py video.mpd [output.txt]")
    sys.exit(1)

input_file = sys.argv[1]
output_file = sys.argv[2] if len(sys.argv) > 2 else "requests_plain.txt"

# read the mpd
try:
    root = ET.parse(input_file).getroot()
except (OSError, ET.ParseError) as e:
    print("couldn't open the mpd:", e)
    sys.exit(1)

# collect the urls, but skip any we've already seen
urls = []
seen = set()

for element in root.findall(".//dash:Initialization", namespace):
    url = element.get("sourceURL")
    if url and url not in seen:
        seen.add(url)
        urls.append(("initialization", url, element.get("range")))

for element in root.findall(".//dash:SegmentURL", namespace):
    url = element.get("media")
    if url and url not in seen:
        seen.add(url)
        urls.append(("segment", url, element.get("mediaRange")))

print("found", len(urls), "distinct urls")

# request each url once and save only small text responses
with requests.Session() as session, open(output_file, "w", encoding="utf-8") as out:
    for number, (kind, url, byte_range) in enumerate(urls, start=1):
        print(f"[{number}/{len(urls)}] {kind}: {urlsplit(url).path}", flush=True)
        out.write(f"\n{'=' * 60}\nrequest {number}: {kind}\n")
        out.write(f"original url: {url}\n")
        out.write(f"first range in mpd: {byte_range}\n")

        try:
            # stream=True means we don't load the whole response into memory
            # don't follow redirects into an entire media file either
            with session.get(url, headers=headers, timeout=(10, 20),
                             stream=True, allow_redirects=False) as response:
                content_type = response.headers.get("Content-Type", "")
                mime = content_type.split(";")[0].strip().lower()

                out.write(f"status: {response.status_code}\n")
                out.write(f"content type: {content_type}\n")
                out.write(f"content length: {response.headers.get('Content-Length', 'unknown')}\n")

                if response.headers.get("Location"):
                    out.write(f"redirect: {response.headers['Location']}\n")

                if mime.startswith("text/") or mime in (
                    "application/json", "application/javascript", "application/x-javascript"
                ):
                    data = response.raw.read(max_text_size + 1, decode_content=True)
                    text = data[:max_text_size].decode(response.encoding or "utf-8", errors="replace")
                    out.write("\nresponse:\n" + text + "\n")
                    if len(data) > max_text_size:
                        out.write("[response cut off at 64 kb]\n")
                else:
                    out.write("body skipped (not a text response)\n")

        except requests.RequestException as e:
            out.write(f"request failed: {e}\n")

        out.flush()

print("done! saved to", output_file)
