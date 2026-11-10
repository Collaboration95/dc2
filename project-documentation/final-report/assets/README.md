# Conduct and introduction asset register

Prepared for final report v1.1 on 10 November 2026. Report-relative links use `assets/<filename>`.

## Persona illustration

| Report asset | Source | Provenance |
|---|---|---|
| `conduct-persona-cast.png` | `project-roadmap/assets/persona-cast.png` | Exact copy of the generated four-person illustration, left to right: Maya, Arun, Jules, Sam. Content register dated 9 October 2026 in `project-roadmap/business-scope.json`; context page `business-scope.html`; original prompt `assets/persona-cast-prompt.txt` beside that page. Fictional planning personas, not research participants or photographs of team members. |

## Presentation recording frames

Source directory: `/Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/`.
The retained presentation deck documents D1–D5 as recorded on `dc2-live` on **23 October 2026**.
That is the documented capture date; filesystem modification time is not used as the recording date.
The files are local gitignored demonstration recordings. These extracted frames do not establish
new November runtime acceptance, a unique source SHA, or shared assessor access to the full clips.

| Report asset | Source clip | Timecode | Frame content | Output size |
|---|---|---|---|---|
| `ui-upload.png` | `D1.mp4` | 00:02.000 | Owner upload screen and supported-file drop area. | 1440 × 810 |
| `ui-processing.png` | `D1.mp4` | 00:06.000 | Uploaded file accepted; banner says it is waiting for Processing to become available. | 1440 × 810 |
| `ui-library-playback.png` | `D1.mp4` | 00:18.000 | Owner library with completed items and video playback in the first card. | 1440 × 810 |
| `ui-publisher-batch.png` | `D2.mp4` | 00:28.000 | Publisher public-API batch status results for three files. | 1440 × 810 |
| `ui-foreign-access-denied.png` | `D3.mp4` | 00:24.000 | Owner A gets done status; owner B is refused with `Asset absent or unavailable to this owner`; anonymous request returns HTTP 401. | 1440 × 810 |
| `ui-bounded-capacity.png` | `D4.mp4` | 00:35.000 | Terminal watcher reports finite Fargate encoder activity and queue counts during the demonstration. The clip includes a 16× speed-up label. | 1120 × 630 |

D5 is a load/performance recording; its measured results remain in the report's quality section.
No frame was selected from it for the compact owner/operator journey. The supplied clips do not
show a stored-source retry UI sequence, so the report links retry to UC-4's tests and models.

## Reproduction

Extract one frame with ffmpeg; retain the timecode and source clip from the table:

```sh
ffmpeg -loglevel error -y -ss 18 \
  -i /Users/speedpowermac/Documents/projects/CODE_MAIN/NUS/dc2-rescue/project-documentation/presentation/site/clips/D1.mp4 \
  -frames:v 1 -vf scale=1440:-1 -compression_level 9 ui-library-playback.png
```

Use `scale=1120:-1` for the D4 capacity frame. Frames are scaled uniformly with no crop, annotation,
or content replacement. Every UI PNG is below 400,000 bytes. Only the library/playback frame is
embedded inline; the other UI frames and persona illustration are linked from the introduction.
No GIF is included.
