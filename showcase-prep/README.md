# FlickPond showcase study guide

Public site: **https://collaboration95.github.io/dc2/**

Open `index.html` in a browser. All study content, diagrams, fonts, icons and
interactions work locally without a server, npm install, CDN or login.

Use **Basics**, **+ Design**, and **+ Details** to reveal each layer. The AWS and
CI/CD chapters have their own diagrams. The Q&A page supports active recall;
the glossary explains terminology in the context of this project.

`all-in-one.html` contains every chapter and can be printed or saved as PDF from
the browser. Printing reveals all levels, diagram notes and answers. Source
links refer to the parent repository; keep this folder inside it for those links.

To rebuild after editing the source JSON:

```sh
python3 showcase-prep/build.py
```

The public edition is built and checked with:

```sh
python3 showcase-prep/publish.py --output /tmp/flickpond-public-site
```

Use a new output directory. The export includes only the generated study pages and
static assets. Code/evidence links point to the reviewed GitHub commit, so readers
do not need a checkout. Course PDF/DOCX references point to a public guidance summary;
the original attachments and meeting access details are excluded.

`.github/workflows/showcase-pages.yml` validates this export on pull requests and
publishes it from Main through GitHub Pages. Configure the repository's Pages source
as **GitHub Actions** once. The workflow uses scoped Pages/OIDC permissions and pinned
actions; it does not need a personal access token. Subsequent guide changes publish
automatically after they reach Main.

The diagram renderer, style and font come from the user's local
`exam-prep/explainer` and `agent-skills/sketch-diagrams` assets. No remote runtime
dependencies are added to the application. This folder is study documentation;
it does not change or deploy the product.

Source snapshot: Main `8152ede`; verified runtime source `629119c`, 20 October 2026.
Both local presentation guides list Team 17 on 26 October, 14:35–15:15 SGT;
the user confirmed 26 October on 21 October.
Check Canvas for later changes and confirm meeting access with the team.
