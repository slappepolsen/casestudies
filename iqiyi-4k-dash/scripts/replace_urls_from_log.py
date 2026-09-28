#!/usr/bin/env python3
"""Use previously saved HTTP responses to replace matching URLs in an MPD.

Offline only: the script does not contact a CDN. Only share the output privately
because it contains signed URLs from the input log.
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def read_log(filename):
    # The log contains one original URL and either an HTTP redirect or a
    # var videoUrl text response for each request.
    mappings = {}
    item = {}

    def save():
        if not item:
            return
        old = item.get("original")
        status = item.get("status")
        target = item.get("target")
        if not old or not target or status not in (200, 302):
            raise ValueError(f"Incomplete response for request {item.get('number', '?')}")
        if old in mappings and mappings[old] != target:
            raise ValueError("Conflicting replacement URLs for the same original URL")
        mappings[old] = target

    for line in filename.read_text(encoding="utf-8").splitlines():
        if m := re.match(r"^request\s+(\d+):", line, re.I):
            save()
            item = {"number": int(m.group(1))}
        elif line.startswith("original url: "):
            item["original"] = line.removeprefix("original url: ").strip()
        elif line.startswith("status: "):
            item["status"] = int(line.removeprefix("status: ").strip())
        elif line.startswith("redirect: "):
            item["target"] = line.removeprefix("redirect: ").strip()
        elif line.startswith("var videoUrl"):
            match = re.search(r'data:\s*\{\s*"l"\s*:\s*"((?:\\.|[^"\\])*)"', line)
            if not match:
                raise ValueError("A var videoUrl response has no readable data.l URL")
            item["target"] = json.loads('"' + match.group(1) + '"')
    save()
    return mappings


def references(root):
    # Include the attribute name and its value for every referenced resource.
    result = []
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1]
        attribute = "sourceURL" if name == "Initialization" else "media" if name == "SegmentURL" else None
        if attribute and element.get(attribute):
            result.append((name, attribute, element.get(attribute),
                           element.get("range" if name == "Initialization" else "mediaRange")))
    return result


def replace(mpd_path, log_path, output_path):
    mapping = read_log(log_path)
    original = mpd_path.read_text(encoding="utf-8")
    root_before = ET.fromstring(original)
    refs_before = references(root_before)
    found = {url for _, _, url, _ in refs_before}
    missing = found - mapping.keys()
    if missing:
        raise ValueError(f"The log is missing replacements for {len(missing)} distinct MPD URLs")
    if len(mapping.keys() - found):
        raise ValueError("The log contains original URLs that do not match this MPD")

    # Replace only the value of the relevant XML attributes, not whole XML
    # elements. This preserves the exact original formatting and byte ranges.
    changed = 0
    pattern = re.compile(r'(?P<prefix>\b(?:sourceURL|media)\s*=\s*"|\b(?:sourceURL|media)\s*=\s*\')(?P<value>.*?)(?P<suffix>\1)', re.DOTALL)
    # A simpler capture avoids dependence on the opening quote in a backref.
    pattern = re.compile(r'\b(?P<attribute>sourceURL|media)\s*=\s*(?P<quote>["\'])(?P<value>.*?)(?P=quote)', re.DOTALL)

    def change(match):
        nonlocal changed
        old = html.unescape(match.group("value"))
        if old not in mapping:
            return match.group(0)
        changed += 1
        new = html.escape(mapping[old], quote=True)
        quote = match.group("quote")
        if quote == "'":
            # Use numeric entities when the original attribute uses single quotes.
            new = new.replace("&#x27;", "&apos;")
        return match.group(0)[:match.start("value") - match.start()] + new + quote

    updated = pattern.sub(change, original)
    root_after = ET.fromstring(updated)
    refs_after = references(root_after)
    if len(refs_before) != len(refs_after) or changed != len(refs_before):
        raise ValueError("Some MPD URLs could not be replaced")
    for before, after in zip(refs_before, refs_after):
        if before[0:2] != after[0:2] or before[3] != after[3] or mapping[before[2]] != after[2]:
            raise ValueError("Verification failed: a URL or a byte range did not match")
    # Sanity-check every element: nothing other than sourceURL/media changed.
    for old_element, new_element in zip(root_before.iter(), root_after.iter()):
        if old_element.tag != new_element.tag or old_element.text != new_element.text or old_element.tail != new_element.tail:
            raise ValueError("Unexpected XML changes")
        old_attrs = {k: v for k, v in old_element.attrib.items() if k not in ("sourceURL", "media")}
        new_attrs = {k: v for k, v in new_element.attrib.items() if k not in ("sourceURL", "media")}
        if old_attrs != new_attrs:
            raise ValueError("Unexpected non-URL attribute changes")

    output_path.write_text(updated, encoding="utf-8")
    print(f"Matched {len(mapping)} distinct URLs and replaced {changed} references")
    print("XML parses successfully and all original ranges were preserved")
    print(f"Saved {output_path}")
    print("Note: Signed URLs may have expired; live CDN responses are not verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mpd", type=Path)
    parser.add_argument("log", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.resolve() in (args.mpd.resolve(), args.log.resolve()):
        parser.error("Choose a different output filename; input files must not be overwritten")
    try:
        replace(args.mpd, args.log, args.output)
    except (ValueError, OSError, ET.ParseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
