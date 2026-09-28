# Case study on iQIYI 4K DASH delivery

**People:** slappepolsen and twinkgenius (atlas)   
**Keywords:** 4K, MPD, DASH, HTTP, CDN, Widevine, N_m3u8DL-RE, Python, and subtitles.

## Table of contents

- [Result](#result)
- [1. Extracting and inspecting the MPD](#1-extracting-and-inspecting-the-mpd)
- [2. Tracing the downloader](#2-tracing-the-downloader)
- [3. Python scripts and file handoffs](#3-python-scripts-and-file-handoffs)
- [4. What the HTTP log established](#4-what-the-http-log-established)
- [5. Outcome and limits](#5-outcome-and-limits)
- [6. Subtitles](#6-subtitles)

---

## Result

A correctly extracted 4K DASH MPD was accepted by N_m3u8DL-RE, but its output began with `var videoUrl` text and FFprobe reported `moov atom not found`. The investigation found a difference between the two init URLs and the thirteen distinct media URLs. Replacing the URLs using a saved HTTP response log produced an MPD that Atlas tested successfully. The resulting video played. The test replaced **all 15** distinct URLs, so it does not prove that replacing only the init URLs would have sufficed (might be interesting to look at at a later time?).

## 1. Extracting and inspecting the MPD

The iQIYI playback response stored escaped DASH XML in a JSON property named `m3u8`. The extraction process isolated the text from `\u003c?xml` through the escaped closing `MPD` tag, decoded the escapes, and validated the XML. An earlier malformed extraction had incorrectly suggested that the underlying MPD was invalid.

The valid MPD described 3840x2160 AV1 video (approximately 33 Mb/s) and AAC audio. Both tracks contained CENC/Widevine signaling. The resource count was:

- **Video:** 859 segment entries across 12 media URLs.
- **Audio:** 859 segment entries sharing 1 media URL.
- **init:** 2 entries with 2 distinct URLs.
- **Total:** 1,720 MPD references, but only **15 distinct URLs**.

The difference arises because multiple `SegmentURL` entries reference different `mediaRange` byte intervals within the same resource. A separate 1,072-byte video init file matched the MPD's `0-1071` range and contained the expected `ftyp` and `moov` MP4 boxes. One available video resource was also checked against its 73 contiguous MPD ranges. These local checks do not establish the validity of every remote CDN resource.

## 2. Tracing the downloader

The N_m3u8DL-RE repository was investigated by searching for `DownloadUtil`, `HttpRequestMessage`, and `DownloadSegmentAsync`, then tracing call arguments back to the DASH parser. More specifically, we found that:

1. N_m3u8DL-RE::[DASHExtractor2.cs](https://github.com/nilaoda/N_m3u8DL-RE/blob/main/src/N_m3u8DL-RE.Parser/Extractor/DASHExtractor2.cs) reads `SegmentURL` attributes, including `media` and `mediaRange`.
2. N_m3u8DL-RE::[SimpleDownloadManager.cs](https://github.com/nilaoda/N_m3u8DL-RE/blob/main/src/N_m3u8DL-RE/DownloadManager/SimpleDownloadManager.cs) selects resources and supplies configured headers.
3. N_m3u8DL-RE::[SimpleDownloader.cs](https://github.com/nilaoda/N_m3u8DL-RE/blob/main/src/N_m3u8DL-RE/Downloader/SimpleDownloader.cs) passes URLs, range boundaries, and headers to the download utility.
4. N_m3u8DL-RE::[DownloadUtil.cs](https://github.com/nilaoda/N_m3u8DL-RE/blob/main/src/N_m3u8DL-RE/Util/DownloadUtil.cs) constructs HTTP GET requests, adds `Range` when specified, follows HTTP 30x responses with a `Location` header, and writes other successful response bodies to disk.

The [DASH MPD XML schema](https://github.com/Dash-Industry-Forum/MPEG-Conformance-and-reference-source/blob/master/conformance/MPDValidator/schemas/DASH-MPD.xsd) was used to confirm the meanings of `SegmentList`, `SegmentURL`, `media`, and `mediaRange`. The key implementation distinction is that an HTTP redirect and a `200 OK` response containing a URL as text are not equivalent.

## 3. Python scripts and file handoffs
The scripts were developed incrementally. The current workflow uses [`run_workflow_v2.py`](scripts/run_workflow_v2.py) to execute the required scripts in sequence.

[`extract_mpd.py`](scripts/extract_mpd.py) extracts the escaped DASH MPD from a saved website response and produces `video.txt` and the decoded, validated `video.mpd`. This step is only needed when starting from the original response rather than an existing MPD.

[`request_v2.py`](scripts/request_v2.py) reads `video.mpd`, identifies its distinct resource URLs and requests each URL once. It saves the HTTP status, redirect destination and applicable small text responses to `requests_plain.txt`. It does not Base64-encode or save complete media files. For the investigated manifest, this reduced the request count from 1,720 MPD entries to 15 distinct URLs.

[`replace_urls_from_log.py`](scripts/replace_urls_from_log.py) reads `video.mpd` and `requests_plain.txt`, matches the recorded URL destinations and produces `video_urls_replaced.mpd`. It preserves the original byte ranges and other XML metadata. This step works entirely from the saved files and makes no additional HTTP requests.

[`run_workflow_v2.py`](scripts/run_workflow_v2.py) is the current launcher. It runs the existing scripts in order and stops if any step fails. When given an existing MPD, it skips extraction.

> **Default usage:**
> 
> `python3 run_workflow_v2.py video.mpd`
> 

This runs:

1. `request_v2.py` --> `requests_plain.txt`
2. `replace_urls_from_log.py` --> `video_urls_replaced.mpd`

> When starting from a saved website response instead, 
> 
> `python3 run_workflow.py video.txt`
>  
> also runs `extract_mpd.py` first.
> 


### Earlier and alternative scripts
The original [`request.py`](scripts/alt/request.py) requested every MPD entry and Base64-encoded complete response bodies. Its output reached approximately 8.5 GB after 48 entries. 

[`request_unique.py`](scripts/alt/request_unique.py) reduced duplicate requests but retained the same full-body encoding problem. Subsequent versions introduced streaming, disabled automatic redirects and retained only the relevant response information. The simplified version is now used as [`request_v2.py`](scripts/request_v2.py).

[`mpd_map.py`](scripts/alt/mpd_map.py) is an alternative for creating and applying manually supplied URL mappings. It is not part of the current workflow because [`replace_urls_from_log.py`](scripts/replace_urls_from_log.py) reads the mappings directly from `requests_plain.txt`.

## 4. What the HTTP log established

**init:** Both `.mp4` init URLs returned HTTP `200 OK` with `text/plain` bodies beginning `var videoUrl`. The actual CDN destination appeared under `data.l`. Those bodies were not MP4 init data.

**Media:** All 13 distinct `.m4s` media URLs returned HTTP `302 Found` with CDN destinations in their `Location` headers. N_m3u8DL-RE already implements this standard redirect behavior.

Together, these observations explain why the original binary-merged output could begin with `var videoUrl` even though subsequent data contained media boxes. They strongly implicate the init response format, without proving it was the only issue. Because the Python collector did not send byte-range headers, its HTTP log alone cannot confirm how every server responds to ranged requests.

## 5. Outcome and limits

The investigated MPD contained 1,720 URL references pointing to 15 distinct resources: two initialization resources and 13 media resources.

The successful test used the saved HTTP responses to generate `video_urls_replaced.mpd`, replacing all 1,720 references while preserving their original byte ranges and other XML metadata. Atlas processed the revised MPD with N_m3u8DL-RE and confirmed playable video.

The current workflow automates the preparation stages through [`run_workflow_v2.py`](scripts/run_workflow_v2.py). It produces a revised MPD but does not itself run N_m3u8DL-RE (you know how to do that part).

The replacement CDN URLs contain signed parameters and may expire, so you must always use a fresh `.mpd`.

## 6. Subtitles

The inspected 4K MPD contained no subtitle track. Atlas subsequently found subtitles delivered as a separate XML file and identified Subtitle Edit as a possible route to SRT.
