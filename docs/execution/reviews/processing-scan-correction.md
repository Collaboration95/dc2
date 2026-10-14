# Processing image scan correction

PR40 head `93efe63`, CI38575591230, failed the Processing image scan with one
fixable HIGH finding: `librsvg2-2` CVE-2026-96889, installed
`2.60.0+dfsg-1`, fixed in `2.60.0+dfsg-1+deb13u1`. This is separate from the
reviewed experimental rejection decisions. No vulnerability waiver is used.

Source: [failed scan job](https://github.com/Collaboration95/dc2/actions/runs/38575591230/job/115891703031).
The [Debian package security tracker](https://security-tracker.debian.org/tracker/source-package/librsvg)
lists the patched Trixie security version and the issue as fixed.

The Processing Dockerfile now explicitly requests `librsvg2-2` alongside FFmpeg,
which invalidates the cached package-install layer and installs the current
security candidate even if an older compatible dependency was already present.
A Debian version comparison refuses an image older than the known fixed floor.
The pinned Python base, Python dependencies, encoding settings, service code and
the existing zero-fixable-HIGH/CRITICAL Trivy policy remain unchanged.

The experiment measurements retain their original source/image identities.
They are not relabelled as measurements of this later packaging correction.
The new artifact needs fresh build, scan, integration/playback and exact PR/Main
checks. Those results are not claimed by this source record.
