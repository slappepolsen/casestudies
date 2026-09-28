import base64
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "DNT": "1",
    "Accept": "*/*",
    "Origin": "https://www.iq.com/",
    "Referer": "https://www.iq.com/",
}

TIMEOUT = 30
NS = {"dash": "urn:mpeg:dash:schema:mpd:2011"}


def extract_urls(mpd_file):
    """Get each distinct URL once. Keep the original MPD unchanged."""
    tree = ET.parse(mpd_file)
    root = tree.getroot()

    urls = []
    seen = set()

    # Initialization URLs
    for element in root.findall(".//dash:Initialization", NS):
        url = element.get("sourceURL")
        if url and url not in seen:
            seen.add(url)
            urls.append({
                "type": "initialization",
                "url": url,
                "range": element.get("range"),
            })

    # Media segment URLs: skip repeated URL strings
    for element in root.findall(".//dash:SegmentURL", NS):
        url = element.get("media")
        if url and url not in seen:
            seen.add(url)
            urls.append({
                "type": "segment",
                "url": url,
                "range": element.get("mediaRange"),
            })

    return urls


def request_url(session, item):
    """Request a unique URL and save its response as in the original script."""
    url = item["url"]

    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        encoded_body = base64.b64encode(response.content).decode("ascii")

        return {
            "type": item["type"],
            "url": url,
            "range": item["range"],
            "status": response.status_code,
            "content_type": response.headers.get("Content-Type", ""),
            "content_length": len(response.content),
            "headers": dict(response.headers),
            "body_base64": encoded_body,
        }

    except requests.RequestException as exc:
        return {
            "type": item["type"],
            "url": url,
            "range": item["range"],
            "error": str(exc),
        }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 request_unique.py input.mpd [output.txt]")
        sys.exit(1)

    mpd_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("requests_output.txt")

    if not mpd_file.exists():
        print(f"MPD file not found: {mpd_file}")
        sys.exit(1)

    urls = extract_urls(mpd_file)
    print(f"Found {len(urls)} distinct URLs")

    with requests.Session() as session, output_file.open("w", encoding="utf-8") as out:
        for index, item in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {item['type']}: {item['url']}")
            result = request_url(session, item)

            out.write("=" * 100 + "\n")
            out.write(f"REQUEST #{index}\n")
            out.write("=" * 100 + "\n")
            out.write(f"Type: {result['type']}\n")
            out.write(f"URL: {result['url']}\n")
            out.write(f"First range from MPD: {result.get('range')}\n")

            if "error" in result:
                out.write(f"ERROR: {result['error']}\n\n")
                continue

            out.write(f"HTTP Status: {result['status']}\n")
            out.write(f"Content-Type: {result['content_type']}\n")
            out.write(f"Response Size: {result['content_length']} bytes\n")
            out.write("\nResponse Headers:\n")
            for key, value in result["headers"].items():
                out.write(f"{key}: {value}\n")
            out.write("\nResponse Body (Base64):\n")
            out.write(result["body_base64"])
            out.write("\n\n")

    print(f"Finished. Results saved to: {output_file}")


if __name__ == "__main__":
    main()
