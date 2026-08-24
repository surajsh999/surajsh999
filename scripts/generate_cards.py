#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regenerate the profile stat cards from live GitHub data.

Produces (in repo root):
  stats-card.svg         real commits / PRs / contributions / repos
  langs-card.svg         language share averaged per repo
  achievements-card.svg  earned GitHub achievement badges
  activity-card.svg      last-30-days contribution bar chart

Usage:  GH_TOKEN=<token> python scripts/generate_cards.py
"""

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import re

LOGIN = os.environ.get("PROFILE_LOGIN", "Nikkat-Afrin")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
OUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG, BR, CY = "#0a1222", "#1e3a4c", "#22d3ee"
TXT, HI, DIM = "#c9d1d9", "#e6f6ff", "#8b949e"
FONT = "'Segoe UI',Ubuntu,Helvetica,Arial,sans-serif"
PAL = ["#22d3ee", "#38bdf8", "#67e8f9", "#0ea5e9", "#7dd3fc", "#164e63"]


def gql(query, variables):
    if not TOKEN:
        sys.exit("ERROR: set GH_TOKEN or GITHUB_TOKEN")
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, method="POST")
    req.add_header("Authorization", "bearer " + TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "profile-card-generator")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                out = json.loads(r.read().decode())
            if "errors" in out:
                sys.exit("GraphQL errors: %s" % out["errors"])
            return out["data"]
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 502, 503):
                time.sleep(5 * (attempt + 1))
                continue
            sys.exit("HTTP %s: %s" % (e.code, e.read().decode()[:400]))
    sys.exit("giving up after retries")


ACH_META = {
    "pull-shark":          ("Pull Shark", "\u25c6"),
    "galaxy-brain":        ("Galaxy Brain", "\u2726"),
    "pair-extraordinaire": ("Pair Extraordinaire", "\u25c9"),
    "yolo":                ("YOLO", "\u25b2"),
    "quickdraw":           ("Quickdraw", "\u26a1"),
    "starstruck":          ("Starstruck", "\u2605"),
    "public-sponsor":      ("Public Sponsor", "\u2665"),
    "developer-program":   ("Dev Program", "\u2b21"),
    "security-bug-bounty-hunter": ("Bug Bounty", "\u26e8"),
    "heart-on-your-sleeve":("Heart On Sleeve", "\u2665"),
    "open-sourcerer":      ("Open Sourcerer", "\u2756"),
}
TIER_NAME = {"2": "x2", "3": "x3", "4": "x4",
             "bronze": "BRONZE", "silver": "SILVER", "gold": "GOLD"}


def scrape_achievements(login):
    """Read earned achievements straight off the public profile page.

    GitHub exposes no API for achievements, so we parse the profile HTML.
    Returns [] on any failure so the caller can fall back to cache.
    """
    url = "https://github.com/%s?tab=achievements" % login
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; profile-card-generator)",
        "Accept": "text/html",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            htm = r.read().decode("utf-8", "replace")
    except Exception as e:
        print("  achievements: fetch failed (%s)" % e)
        return []

    found, seen = [], set()
    slugs = []
    # 1) badge links:  ...?achievement=<slug>&tab=achievements
    slugs += re.findall(r"achievement=([a-z0-9\-]+)", htm)
    # 2) badge images: .../assets/<slug>-default-<hash>.png  (also -bronze/-silver/-gold)
    slugs += re.findall(r"assets/([a-z0-9\-]+?)-(?:default|bronze|silver|gold)-[0-9a-f]{6,}\.png", htm)
    # 3) alt text:     alt="Achievement: Pull Shark"
    for alt in re.findall(r'alt="Achievement:\s*([^"]+)"', htm):
        slugs.append(alt.strip().lower().replace(" ", "-"))

    for slug in slugs:
        slug = slug.strip().lower()
        if not slug or slug in seen or slug in ("achievements",):
            continue
        seen.add(slug)
        idx = htm.find(slug)
        window = htm[idx:idx + 1500] if idx >= 0 else ""
        tier = ""
        t = re.search(r">\s*x(\d+)\s*<", window)
        if t:
            tier = TIER_NAME.get(t.group(1), "x" + t.group(1))
        else:
            t = re.search(r"%s-(bronze|silver|gold)-" % re.escape(slug), htm, re.I)
            if t:
                tier = TIER_NAME.get(t.group(1).lower(), t.group(1).upper())
        name, icon = ACH_META.get(slug, (slug.replace("-", " ").title(), "\u25c6"))
        found.append({"slug": slug, "name": name, "icon": icon, "tier": tier})
    return found


def load_achievements(login):
    cache = os.path.join(OUT, "achievements.json")
    live = scrape_achievements(login)
    if live:
        try:
            json.dump(live, open(cache, "w", encoding="utf-8"), indent=2)
        except Exception:
            pass
        print("  achievements: %d found live (%s)"
              % (len(live), ", ".join(a["slug"] for a in live)))
        return live
    if os.path.exists(cache):
        data = json.load(open(cache, encoding="utf-8"))
        print("  achievements: using cached list (%d)" % len(data))
        return data
    print("  achievements: none found")
    return []


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def card(w, h, title=None, extra=""):
    s = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
         'viewBox="0 0 %d %d" fill="none" role="img">' % (w, h, w, h)]
    s.append("""<style>
 .ttl{font-family:%s;font-size:16px;font-weight:700;fill:%s}
 .lb{font-family:%s;font-size:13px;fill:%s}
 .vl{font-family:%s;font-size:13px;font-weight:700;fill:%s}
 .sm{font-family:%s;font-size:11px;fill:%s}
</style>%s""" % (FONT, CY, FONT, TXT, FONT, HI, FONT, DIM, extra))
    s.append('<rect x="0.5" y="0.5" width="%d" height="%d" rx="10" fill="%s" stroke="%s"/>'
             % (w - 1, h - 1, BG, BR))
    if title:
        s.append('<text x="24" y="32" class="ttl">%s</text>' % esc(title))
    return s


QUERY = """
query($login:String!){
 user(login:$login){
  name
  repositories(first:100, privacy:PUBLIC, ownerAffiliations:OWNER, isFork:false){
    totalCount
    nodes{ languages(first:12, orderBy:{field:SIZE,direction:DESC}){ edges{ size node{name} } } }
  }
  contributionsCollection{
    totalCommitContributions
    totalRepositoriesWithContributedCommits
    contributionCalendar{ totalContributions weeks{ contributionDays{ date contributionCount } } }
  }
  pullRequests{totalCount}
 }}
"""


def main():
    u = gql(QUERY, {"login": LOGIN})["user"]
    cc = u["contributionsCollection"]
    repos = u["repositories"]
    cal = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]

    name = u["name"] or LOGIN
    commits = cc["totalCommitContributions"]
    prs = u["pullRequests"]["totalCount"]
    total = cc["contributionCalendar"]["totalContributions"]
    nrepos = repos["totalCount"]
    contributed = cc["totalRepositoriesWithContributedCommits"]

    # ---------- language share, averaged per repo ----------
    acc, counted = {}, 0
    for n in repos["nodes"]:
        edges = n["languages"]["edges"]
        tot = sum(e["size"] for e in edges)
        if not tot:
            continue
        counted += 1
        for e in edges:
            acc[e["node"]["name"]] = acc.get(e["node"]["name"], 0) + e["size"] / tot
    ranked = sorted(acc.items(), key=lambda kv: -kv[1])[:6]
    tot = sum(v for _, v in ranked) or 1
    langs = [(k, v / tot * 100) for k, v in ranked]

    # ---------- 1. stats ----------
    W, H = 460, 200
    s = card(W, H, "%s's GitHub Stats" % name)
    rows = [("Total Commits (last yr)", "{:,}".format(commits)),
            ("Total Pull Requests", "{:,}".format(prs)),
            ("Total Contributions", "{:,}".format(total)),
            ("Public Repositories", str(nrepos)),
            ("Contributed to (last yr)", str(contributed))]
    for i, (k, v) in enumerate(rows):
        y = 64 + i * 25
        s.append('<text x="24" y="%d" class="lb">%s:</text>' % (y, k))
        s.append('<text x="320" y="%d" text-anchor="end" class="vl">%s</text>' % (y, v))
    score = min(1.0, commits / 500 * 0.4 + prs / 150 * 0.4 + total / 600 * 0.2)
    rank = "S" if score > 0.85 else ("A+" if score > 0.7 else "A")
    cx, cy, r = 390, 110, 42
    circ = 2 * math.pi * r
    s.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="#123047" stroke-width="7"/>' % (cx, cy, r))
    s.append('<circle cx="%d" cy="%d" r="%d" fill="none" stroke="%s" stroke-width="7" '
             'stroke-linecap="round" stroke-dasharray="%d" stroke-dashoffset="%d" '
             'transform="rotate(-90 %d %d)"><animate attributeName="stroke-dashoffset" from="%d" '
             'to="%d" dur="1.4s" fill="freeze" calcMode="spline" keySplines="0.3 0 0.2 1" '
             'keyTimes="0;1"/></circle>'
             % (cx, cy, r, CY, circ, circ, cx, cy, circ, circ * (1 - score)))
    s.append('<text x="%d" y="%d" text-anchor="middle" font-family="%s" font-size="26" '
             'font-weight="700" fill="%s">%s</text>' % (cx, cy + 8, FONT, HI, rank))
    s.append("</svg>")
    open(os.path.join(OUT, "stats-card.svg"), "w", encoding="utf-8").write("\n".join(s))

    # ---------- 2. languages ----------
    W, H = 460, 200
    s = card(W, H, "Most Used Languages")
    barw, x, y = 412, 24, 56
    s.append('<clipPath id="bc"><rect x="%d" y="%d" width="%d" height="11" rx="5.5"/></clipPath>'
             '<g clip-path="url(#bc)">' % (x, y, barw))
    cur = float(x)
    for i, (n, p) in enumerate(langs):
        w = barw * p / 100.0
        s.append('<rect x="%.1f" y="%d" width="%.1f" height="11" fill="%s"/>'
                 % (cur, y, w, PAL[i % len(PAL)]))
        cur += w
    s.append("</g>")
    for i, (n, p) in enumerate(langs):
        lx = 24 + (i % 2) * 215
        ly = 94 + (i // 2) * 26
        s.append('<circle cx="%d" cy="%d" r="5" fill="%s"/>' % (lx + 5, ly - 4, PAL[i % len(PAL)]))
        s.append('<text x="%d" y="%d" class="lb">%s</text>' % (lx + 18, ly, esc(n)))
        s.append('<text x="%d" y="%d" text-anchor="end" class="vl">%.1f%%</text>' % (lx + 190, ly, p))
    s.append('<text x="24" y="182" class="sm">Average language share across %d public repositories</text>'
             % counted)
    s.append("</svg>")
    open(os.path.join(OUT, "langs-card.svg"), "w", encoding="utf-8").write("\n".join(s))

    # ---------- 3. achievements ----------
    ach = load_achievements(LOGIN)

    W, H = 940, 132
    s = card(W, H, "GitHub Achievements")
    n_ach = max(1, len(ach))
    bw = (W - 48 - (n_ach - 1) * 10) / float(n_ach)
    for i, a in enumerate(ach):
        nm, tier, ic = a["name"], a.get("tier", ""), a.get("icon", "\u25c6")
        bx = 24 + i * (bw + 10)
        s.append('<rect x="%.0f" y="52" width="%.0f" height="60" rx="8" fill="#0b1a2b" stroke="%s"/>'
                 % (bx, bw, BR))
        s.append('<text x="%.0f" y="76" text-anchor="middle" font-size="17" fill="%s">%s</text>'
                 % (bx + bw / 2, CY, ic))
        s.append('<text x="%.0f" y="94" text-anchor="middle" font-family="%s" font-size="11" '
                 'font-weight="700" fill="%s">%s</text>' % (bx + bw / 2, FONT, HI, nm))
        if tier:
            s.append('<text x="%.0f" y="107" text-anchor="middle" class="sm" font-size="9.5">%s</text>'
                     % (bx + bw / 2, tier))
    s.append("</svg>")
    open(os.path.join(OUT, "achievements-card.svg"), "w", encoding="utf-8").write("\n".join(s))

    # ---------- 4. activity (last 30 days) ----------
    import datetime
    DAYS = 30
    recent = cal[-DAYS:]
    W, H = 940, 240
    s = card(W, H, "Contribution Activity  \u00b7  last 30 days")
    maxv = max(1, max(c["contributionCount"] for c in recent))
    x0, y0, x1, y1 = 60, 62, W - 40, H - 52
    n = len(recent)
    slot = (x1 - x0) / float(n)
    barw = slot * 0.62
    month_total = sum(c["contributionCount"] for c in recent)
    active = sum(1 for c in recent if c["contributionCount"])

    # gridlines (sqrt-spaced labels keep small days readable next to a big spike)
    for g in range(4):
        gy = y0 + (y1 - y0) * g / 3.0
        s.append('<line x1="%d" y1="%.0f" x2="%d" y2="%.0f" stroke="#122b3d" stroke-width="1"/>'
                 % (x0 - 12, gy, x1, gy))
        s.append('<text x="%d" y="%.0f" text-anchor="end" class="sm">%d</text>'
                 % (x0 - 20, gy + 4, int(round(maxv * (((3 - g) / 3.0) ** 2)))))

    for i, c in enumerate(recent):
        v = c["contributionCount"]
        cxb = x0 + slot * i + slot / 2.0
        bh = (y1 - y0) * ((v / float(maxv)) ** 0.5)
        by = y1 - bh
        col = CY if v else "#16324a"
        if bh < 2:
            bh, by = 2.0, y1 - 2
        s.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2.5" fill="%s" opacity="0.9">'
                 '<animate attributeName="height" from="0" to="%.1f" dur="0.7s" begin="%.2fs" '
                 'fill="freeze" calcMode="spline" keySplines="0.3 0 0.2 1" keyTimes="0;1"/>'
                 '<animate attributeName="y" from="%.1f" to="%.1f" dur="0.7s" begin="%.2fs" '
                 'fill="freeze" calcMode="spline" keySplines="0.3 0 0.2 1" keyTimes="0;1"/></rect>'
                 % (cxb - barw / 2, by, barw, bh, col, bh, i * 0.02, y1, by, i * 0.02))
        # label only the peak day to avoid clutter
        if v == maxv and v > 0:
            s.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="vl">%d</text>'
                     % (cxb, by - 8, v))
        # date ticks roughly weekly
        if i % 7 == 0 and i <= n - 4:
            s.append('<text x="%.1f" y="%.1f" text-anchor="middle" class="sm">%s</text>'
                     % (cxb, y1 + 22, c["date"][5:]))

    s.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s"/>' % (x0 - 12, y1, x1, y1, BR))
    s.append('<text x="%d" y="32" text-anchor="end" class="sm">%d contributions</text>'
             % (W - 24, month_total))
    s.append('<text x="%d" y="%d" class="sm">sqrt scale</text>' % (x0 - 12, y1 + 38))
    s.append("</svg>")
    open(os.path.join(OUT, "activity-card.svg"), "w", encoding="utf-8").write("\n".join(s))

    print("cards regenerated: commits=%d prs=%d contributions=%d repos=%d rank=%s"
          % (commits, prs, total, nrepos, rank))


if __name__ == "__main__":
    main()
