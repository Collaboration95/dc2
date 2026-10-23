# Presenting the deck with the demo clips

The slides are `site/deck.html`. The recorded clips are in `site/clips/D1.mp4` … `D5.mp4`. The clips
are not in Git and not on GitHub Pages, so present from the laptop that has them.

## 1. If you present from another laptop

Copy the folder `project-documentation/presentation/site/clips/` from Guruprasath's Mac (AirDrop or
a private Drive folder) into the same place in your checkout of this branch.

## 2. Open the deck

```bash
cd project-documentation/presentation/site
python3 -m http.server 8766
```

Open Chrome at <http://127.0.0.1:8766/deck.html>. Press `F` for full screen.

| Key | Does |
|---|---|
| → / ← | next / previous slide |
| `P` or click | play / pause the clip on a demo slide |
| `N` | speaker notes (with the source of each number) |
| `O` | overview of all slides; click one to jump |
| number + Enter | jump to that slide |

## 3. Zoom

Share screen → pick the Chrome window → tick **Optimize for video clip**. The clips have no sound.

## 4. The demo section (slides 41–45)

All clips are real runs against dc2-live on 23 Oct 2026. Only processing waits are cut. Each starts
with a 3-second title card. Pause any time with `P` to talk over a frame.

| Slide | Clip | What is on screen |
|---|---|---|
| 41 | D1, 0:33 | Owner A signs in to the web app, uploads `week1-intro.mp4`, sees "Accepted", then "Processing complete"; the Library plays the converted video. |
| 42 | D2, 0:24 | The Publisher CLI lists three lecture files, publishes them in one command (three job IDs), then all three show `done`. |
| 43 | D3, 0:20 | The same job ID: owner A gets the video, owner B gets "Asset absent or unavailable to this owner", no session gets HTTP 401. |
| 44 | D4, 0:34 | Five 72 MiB uploads go to the Fargate lane. The watcher prints each change: encoders rise to 3 (the cap), fall back, start again as the launcher picks up queued work, and end at 0. All five jobs `done`. |
| 45 | D5, 1:08 | The load generator runs 10 users for 60 s against the live API, then the report is built from its own samples and scrolled: targets vs actuals, per-route latency, histogram, throughput, lane comparison. |
| 46 | D6 | Not recorded yet (push to production). |

Two things people ask about D4:
- Encoders drop to 0 and come back while work is still queued. Each Fargate task runs one attempt and
  exits; the launcher starts new tasks on its next one-minute tick.
- "waiting in queue" is SQS's approximate message count on the work queue, so it can briefly read
  more than five.

## 5. Links in the slide footers

Some slides have a small link next to the slide number (CI and CD runs, workflow files, result
files, code scanning). They open GitHub in a new tab; the repository is public.

- Slide 37, "Trivy blocks release": open the failed **Deploy** step and search for `fixable`. The
  line reads `media: FAIL: Trivy has 1 fixable HIGH/CRITICAL`.
- Slide 38, "Smoke 503 fail": the failed run's log shows `processing-jobs:503`.

## 6. Re-recording a clip

Everything needed is in `~/dc2-demo-private/` on Guruprasath's Mac (accounts, fixtures, scripts,
`tools/edit.sh` for the title card). The commands for the live parts are in `scripts/demo/README.md`.
