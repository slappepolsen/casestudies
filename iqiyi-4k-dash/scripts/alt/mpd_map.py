#!/usr/bin/env python3
# make a url list from an mpd, then use a filled-in list to replace the urls
# this works offline: it doesn't request any links or download video

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

DASH = "urn:mpeg:dash:schema:mpd:2011"


def get_entries(root):
    # collect every init and segment url, including duplicates
    entries = []

    for element in root.iter():
        if element.tag == "{" + DASH + "}Initialization":
            url_field = "sourceURL"
            range_field = "range"
        elif element.tag == "{" + DASH + "}SegmentURL":
            url_field = "media"
            range_field = "mediaRange"
        else:
            continue

        url = element.get(url_field)
        if url:
            entries.append({
                "element": element,
                "url": url,
                "field": url_field,
                "range": element.get(range_field),
            })

    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mpd", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--make-template", type=Path)
    mode.add_argument("--mapping", type=Path)
    parser.add_argument("--output", type=Path, default=Path("new_video.mpd"))
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--check-local", action="store_true")
    args = parser.parse_args()

    try:
        # keep the original namespace prefixes where possible
        for _, (prefix, url) in ET.iterparse(args.mpd, events=["start-ns"]):
            try:
                ET.register_namespace(prefix or "", url)
            except ValueError:
                pass

        xml_parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
        tree = ET.parse(args.mpd, parser=xml_parser)
        entries = get_entries(tree.getroot())

        if not entries:
            raise ValueError("couldn't find any init or segment urls in the mpd")

        # a dictionary makes it easy to skip repeated urls
        unique = {}
        for entry in entries:
            url = entry["url"]
            if url not in unique:
                unique[url] = {
                    "original": url,
                    "replacement": "",
                    "expires_at": "",
                    "local_file": "",
                    "references": 0,
                }
            unique[url]["references"] += 1

        print(f"found {len(entries)} entries and {len(unique)} distinct urls")

        if args.make_template:
            data = {"mappings": list(unique.values())}
            args.make_template.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(f"saved {args.make_template}. fill in the replacement fields first")
            return 0

        # read the mapping file after you've filled it in
        data = json.loads(args.mapping.read_text(encoding="utf-8"))
        if not isinstance(data.get("mappings"), list):
            raise ValueError("the mapping file needs a mappings list")

        mapping = {}
        for item in data["mappings"]:
            old = item.get("original", "")
            new = item.get("replacement", "")
            if not old or not new:
                continue
            if old in mapping and mapping[old]["replacement"] != new:
                raise ValueError("one original url has two different replacements")
            mapping[old] = item

        missing = [url for url in unique if url not in mapping]
        if args.require_all and missing:
            raise ValueError(f"{len(missing)} distinct urls don't have a replacement yet")

        # optional: reject replacements with a known expiration time in the past
        now = datetime.now(timezone.utc)
        for url in unique:
            info = mapping.get(url)
            if not info or not info.get("expires_at"):
                continue
            expiry = datetime.fromisoformat(info["expires_at"].replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                raise ValueError("expires_at must include a timezone, like 2030-01-01T12:00:00Z")
            if expiry <= now:
                raise ValueError("one of the replacement urls has expired")

        # optional: check the original ranges against local copies of the files
        # this only checks their size, not whether a remote url works
        if args.check_local:
            for url in unique:
                if url not in mapping:
                    continue
                name = mapping[url].get("local_file", "")
                if not name:
                    raise ValueError("--check-local needs a local_file for every mapped url")
                file = Path(name)
                if not file.is_absolute():
                    file = args.mapping.parent / file
                size = file.stat().st_size

                for entry in entries:
                    if entry["url"] != url or not entry["range"]:
                        continue
                    start, end = (int(n) for n in entry["range"].split("-", 1))
                    if start < 0 or end < start or end >= size:
                        raise ValueError(f"range {entry['range']} doesn't fit inside {file.name}")
                print(f"checked local file: {file.name}")

        # remember the original attributes so we can check them afterwards
        original_info = []
        for entry in entries:
            attrs = dict(entry["element"].attrib)
            attrs.pop(entry["field"], None)
            original_info.append((entry["field"], attrs))

        # only change urls, never the original byte ranges
        changed = 0
        for entry in entries:
            if entry["url"] in mapping:
                new_url = mapping[entry["url"]]["replacement"]
                entry["element"].set(entry["field"], new_url)
                changed += 1

        args.output.parent.mkdir(parents=True, exist_ok=True)
        tree.write(args.output, encoding="utf-8", xml_declaration=True)

        # read it back to check the xml and make sure the other attrs are still there
        check = ET.parse(args.output)
        new_entries = get_entries(check.getroot())
        new_info = []
        for entry in new_entries:
            attrs = dict(entry["element"].attrib)
            attrs.pop(entry["field"], None)
            new_info.append((entry["field"], attrs))

        if new_info != original_info:
            args.output.unlink()
            raise ValueError("the new mpd doesn't match the original segment metadata")

        print(f"replaced {changed} references")
        print(f"left {len(missing)} distinct urls unchanged")
        print(f"saved {args.output}, xml and original ranges checked")
        print("remote links and remote byte ranges have not been verified")
        return 0

    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
