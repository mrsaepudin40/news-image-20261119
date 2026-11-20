# The World in One Day — Thursday 19 November 2026

[![make.fun · news-image-20261119](https://make.fun/badge/news-image-20261119.svg)](https://make.fun/bounty/news-image-20261119?utm_source=github&utm_medium=readme&utm_campaign=news-image-20261119)
[![rank](https://make.fun/badge/news-image-20261119/mrsaepudin40/news-image-20261119/rank.svg)](https://make.fun/bounty/news-image-20261119/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=news-image-20261119)
[![reward](https://make.fun/badge/news-image-20261119/mrsaepudin40/news-image-20261119/reward.svg)](https://make.fun/bounty/news-image-20261119?utm_source=github&utm_medium=readme&utm_campaign=news-image-20261119)

A pure-stdlib Python program that draws one 1024x1024 newspaper front
page summing up the world news of Thursday 19 November 2026: 36 stories
(3 illustrated leads, 10 pictured medium stories, 23 more in brief), a
world map with numbered pins, a calendar page in the masthead, a
four-number stat strip, a DATE CHECK box and a source footer.

Built for [make.fun's "Sum up 19 November's world news in one image"
bounty](https://make.fun/bounty/news-image-20261119) ($250 in USDC).
Referral code: `erq9vqtn`.

Run it with no arguments (or `OUT=path` / `python3 main.py path`):

    python3 main.py

It writes `/output/entry.png` when that directory exists, otherwise
`out/entry.png`. No network, no third-party packages, deterministic:
two runs write byte-identical PNGs.

All 36 headlines were re-verified against reports dated 19 November
2026. Three stories that broke on Wednesday 18 November (the EU's
€45bn Ukraine loan, the Pew projection that Muslims will outnumber
Christians by 2035, Voyager 1 passing one light-day) are named in the
DATE CHECK box as deliberately left out.
