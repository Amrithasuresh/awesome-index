import requests
import os
import re
from datetime import datetime, timedelta
import time
import math

# --- CONFIG ---
MIN_STARS = 500
DAYS_ACTIVE = 365
PER_PAGE = 100
TOKEN = os.getenv("GH_TOKEN")

TOP_N = 25
CHUNK_SIZE = 50

BASE_URL = "https://api.github.com/search/repositories"

# --- CATEGORIES (ordered by priority, multi-keyword scoring) ---
# Each entry: (display_name, must_match_any, bonus_keywords)
CATEGORIES = [
    ("🤖 AI, LLMs & ChatGPT",       ["llm", "gpt", "chatgpt", "openai", "claude", "gemini", "ollama", "langchain", "rag", "agent", "diffusion", "stable-diffusion", "huggingface", "transformers"], []),
    ("📊 Data Science & ML",         ["machine-learning", "deep-learning", "pytorch", "tensorflow", "data-science", "sklearn", "neural-network", "computer-vision", "nlp", "reinforcement-learning"], []),
    ("🖥️ Operating Systems & Platforms", ["linux", "macos", "windows", "kernel", "unix", "bsd", "embedded", "rtos", "firmware"], []),
    ("💼 Career, Jobs & Interview",  ["interview", "resume", "cv", "career", "job", "hiring", "leetcode", "coding-challenge", "system-design"], []),
    ("📚 Books, Courses & Learning", ["book", "course", "tutorial", "learning", "education", "curriculum", "roadmap", "beginner"], []),
    ("🎮 Gaming & Graphics",         ["game", "gaming", "opengl", "vulkan", "directx", "unity", "unreal", "gamedev", "shader", "raytracing", "webgl"], []),
    ("🧬 Science, Medical & Bio",    ["bioinformatics", "genomics", "medical", "biology", "chemistry", "physics", "neuroscience", "imaging", "clinical", "covid"], []),
    ("🛡️ Security & Privacy",        ["security", "privacy", "cryptography", "hacking", "pentest", "ctf", "malware", "vulnerability", "infosec", "osint", "zero-trust"], []),
    ("⚙️ Systems, HPC & Performance", ["hpc", "gpu", "cuda", "parallel", "distributed", "slurm", "performance", "optimization", "benchmark", "low-latency", "simd"], []),
    ("🌐 Web, Backend & APIs",       ["api", "backend", "web", "server", "http", "graphql", "rest", "microservice", "serverless", "nginx", "fastapi", "django", "flask", "express", "nextjs"], []),
    ("🛠️ Developer Tools",           ["cli", "terminal", "shell", "vim", "neovim", "vscode", "devops", "docker", "kubernetes", "ci-cd", "git", "linting", "debugging", "profiling"], []),
    ("📱 Mobile",                    ["android", "ios", "react-native", "flutter", "swift", "kotlin", "mobile", "app"], []),
    ("☁️ Cloud & Infrastructure",    ["cloud", "aws", "azure", "gcp", "terraform", "ansible", "infra", "sre", "monitoring", "logging", "observability"], []),
    ("🗄️ Databases & Storage",       ["database", "sql", "nosql", "postgres", "mysql", "redis", "mongodb", "elasticsearch", "vector-database", "storage", "cache"], []),
    ("🎨 Design & UI",               ["design", "ui", "ux", "figma", "css", "tailwind", "icons", "typography", "color", "accessibility"], []),
]

STAR_TIERS = [
    "500..700", "701..1000", "1001..1500", "1501..2500",
    "2501..5000", "5001..10000", "10001..20000",
    "20001..50000", ">50000"
]

TRENDING_DAYS = 30  # Window for trending score calculation


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def make_anchor(cat):
    """Generate a GitHub-compatible anchor from a heading string."""
    anchor = cat.lower()
    anchor = re.sub(r'[^\w\s-]', '', anchor)   # strip emojis and punctuation
    anchor = re.sub(r'[\s]+', '-', anchor)      # spaces to hyphens
    anchor = re.sub(r'-+', '-', anchor)         # collapse double hyphens
    return anchor.strip('-')


def get_category(repo):
    """Score each category by keyword matches and pick the best fit."""
    name = repo.get("full_name", "").lower()
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in repo.get("topics", [])]
    content = f"{name} {desc} {' '.join(topics)}"

    best_cat = "📦 Miscellaneous"
    best_score = 0

    for cat_name, keywords, bonus in CATEGORIES:
        score = 0
        for kw in keywords:
            if kw in topics:
                score += 3          # Topic match is strongest signal
            elif kw in name:
                score += 2          # Name match is second
            elif kw in desc:
                score += 1          # Description match is weakest
        for kw in bonus:
            if kw in content:
                score += 1

        if score > best_score:
            best_score = score
            best_cat = cat_name

    return best_cat


def quality_score(repo):
    """
    Composite quality signal combining multiple GitHub signals.
    Higher = better maintained / more influential repo.
    """
    stars   = repo.get("stargazers_count", 0)
    forks   = repo.get("forks_count", 0)
    watchers = repo.get("watchers_count", 0)
    open_issues = repo.get("open_issues_count", 0)
    has_license = repo.get("license") is not None
    has_desc    = bool(repo.get("description"))
    has_topics  = len(repo.get("topics", [])) > 0

    pushed = repo.get("pushed_at", "")
    recency_bonus = 0
    if pushed:
        try:
            pushed_date = datetime.strptime(pushed[:10], "%Y-%m-%d")
            days_ago = (datetime.utcnow() - pushed_date).days
            # Max bonus for repos pushed within 30 days, decays logarithmically
            recency_bonus = max(0, 1000 - days_ago * 2)
        except Exception:
            pass

    # Fork ratio: high-fork repos are often foundational (templates, etc.)
    fork_ratio = forks / max(stars, 1)
    fork_signal = min(fork_ratio * 500, 300)   # cap contribution

    # Issue health: too many open issues relative to stars is a bad sign
    issue_penalty = min(open_issues / max(stars, 1) * 200, 150)

    score = (
        math.log1p(stars) * 150
        + math.log1p(forks) * 50
        + math.log1p(watchers) * 10
        + fork_signal
        - issue_penalty
        + recency_bonus
        + (200 if has_license else 0)
        + (100 if has_desc else 0)
        + (150 if has_topics else 0)
    )

    return round(score, 2)


def trending_score(repo):
    """
    Stars-per-day over a recent window.
    Approximated from total stars / days since created, weighted by recency.
    A better signal than raw stars.
    """
    stars   = repo.get("stargazers_count", 0)
    created = repo.get("created_at", "")
    pushed  = repo.get("pushed_at", "")

    if not created:
        return 0

    try:
        created_date = datetime.strptime(created[:10], "%Y-%m-%d")
        age_days = max((datetime.utcnow() - created_date).days, 1)
        velocity = stars / age_days

        # Recency multiplier: repos pushed recently get a boost
        recency_mult = 1.0
        if pushed:
            pushed_date = datetime.strptime(pushed[:10], "%Y-%m-%d")
            days_since_push = (datetime.utcnow() - pushed_date).days
            if days_since_push <= TRENDING_DAYS:
                recency_mult = 2.5 - (days_since_push / TRENDING_DAYS) * 1.5
        return velocity * recency_mult
    except Exception:
        return 0


def is_genuinely_awesome(repo):
    """
    Filter out repos that match 'awesome' in name/description but are
    not actually curated lists (e.g., personal portfolios, forks, etc.)
    """
    if repo.get("fork"):
        return False

    name = repo.get("name", "").lower()
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in repo.get("topics", [])]

    # Must have 'awesome' somewhere meaningful
    has_awesome = (
        "awesome" in name
        or "awesome" in desc
        or "awesome" in topics
    )
    if not has_awesome:
        return False

    # Minimum content signal: description + decent star count
    if not repo.get("description"):
        return False

    if repo.get("stargazers_count", 0) < MIN_STARS:
        return False

    return True


# ---------------------------------------------------------------------------
# RATE-LIMIT-AWARE FETCH
# ---------------------------------------------------------------------------

def safe_get(url, headers, retries=5):
    """GET with exponential back-off on rate limit or transient errors."""
    for attempt in range(retries):
        resp = requests.get(url, headers=headers, timeout=20)

        if resp.status_code == 200:
            return resp

        if resp.status_code == 403:
            # Check if it's a rate-limit (X-RateLimit-Remaining == 0)
            remaining = int(resp.headers.get("X-RateLimit-Remaining", 1))
            reset_ts   = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))

            if remaining == 0:
                wait = max(reset_ts - int(time.time()), 0) + 5
                print(f"⏳ Rate limit hit. Sleeping {wait}s until reset...")
                time.sleep(wait)
            else:
                # Secondary rate limit – back off exponentially
                wait = (2 ** attempt) * 15
                print(f"⚠️ 403 (secondary limit). Sleeping {wait}s (attempt {attempt+1})...")
                time.sleep(wait)

        elif resp.status_code in (500, 502, 503, 504):
            wait = (2 ** attempt) * 10
            print(f"🔴 Server error {resp.status_code}. Sleeping {wait}s...")
            time.sleep(wait)

        else:
            print(f"❌ Unexpected status {resp.status_code} for {url}")
            return None

    print(f"❌ Giving up after {retries} attempts: {url}")
    return None


def fetch_all_repos():
    headers = {
        "Accept": "application/vnd.github.mercy-preview+json"
    }
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    all_repos = {}
    active_since = (datetime.utcnow() - timedelta(days=DAYS_ACTIVE)).strftime('%Y-%m-%d')

    for tier in STAR_TIERS:
        print(f"🔎 Scanning {tier} stars...")
        page = 1

        while page <= 10:
            query = f'awesome in:name,description,topics stars:{tier} pushed:>{active_since}'
            url = (
                f"{BASE_URL}?q={query}"
                f"&sort=stars&order=desc&per_page={PER_PAGE}&page={page}"
            )

            resp = safe_get(url, headers)
            if resp is None:
                break

            data = resp.json()

            # GitHub caps search at 1000 results; warn if we hit it
            total = data.get("total_count", 0)
            if page == 1 and total > 1000:
                print(f"   ℹ️  {total} total results for tier {tier} — GitHub caps at 1000.")

            items = data.get("items", [])
            if not items:
                break

            added = 0
            for repo in items:
                if is_genuinely_awesome(repo):
                    key = repo["full_name"]
                    if key not in all_repos:
                        all_repos[key] = repo
                        added += 1

            print(f"   Page {page}: {len(items)} fetched, {added} new quality repos.")

            if len(items) < PER_PAGE:
                break

            page += 1
            time.sleep(1.5)   # Stay well under 30 req/min for authenticated calls

    return list(all_repos.values())


# ---------------------------------------------------------------------------
# README GENERATION
# ---------------------------------------------------------------------------

def generate_readme(repos):
    # Sort globally by quality
    repos.sort(key=lambda x: quality_score(x), reverse=True)

    categorized = {cat[0]: [] for cat in CATEGORIES}
    categorized["📦 Miscellaneous"] = []

    for repo in repos:
        categorized[get_category(repo)].append(repo)

    # Each category already in quality order; no need to re-sort

    # Trending: top 15 by trending score, from all repos
    trending = sorted(repos, key=trending_score, reverse=True)[:15]

    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    stats_total = len(repos)
    stats_cats  = sum(1 for v in categorized.values() if v)

    def repo_row(r, desc_len=120):
        stars = f"{r['stargazers_count']:,}"
        forks = f"{r['forks_count']:,}"
        desc  = (r.get("description") or "").replace("|", "｜")[:desc_len]
        qs    = quality_score(r)
        return (
            f"| [{r['full_name']}]({r['html_url']}) "
            f"| ⭐ `{stars}` | 🍴 `{forks}` | {desc} |\n"
        )

    with open("README.md", "w", encoding="utf-8") as f:

        # ── HEADER ──────────────────────────────────────────────────────────
        f.write("# 🚀 Awesome Index\n\n")
        f.write(
            f"**Last Updated:** `{now}`  \n"
            f"**Total Repositories:** `{stats_total}`  \n"
            f"**Active Categories:** `{stats_cats}`  \n"
            "**Criteria:** `500+ ⭐ · Actively maintained · Curated list`\n\n"
        )
        f.write("> 💡 Press `Ctrl + F` to search instantly. "
                "Sorted by a composite quality score (stars, forks, recency, topics).\n\n")

        # ── TRENDING ─────────────────────────────────────────────────────────
        f.write("## 🔥 Trending Now\n\n")
        f.write(
            "> Repos gaining stars fastest relative to their age, "
            "boosted by recent activity.\n\n"
        )
        f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
        f.write("| :--- | ---: | ---: | :--- |\n")
        for r in trending:
            f.write(repo_row(r))
        f.write("\n---\n\n")

        # ── NAVIGATION ───────────────────────────────────────────────────────
        f.write("## 📂 Categories\n\n")
        for cat, items in categorized.items():
            if items:
                f.write(f"- [{cat}](#{make_anchor(cat)}) `{len(items)}`\n")
        f.write("\n---\n\n")

        # ── CATEGORY SECTIONS ────────────────────────────────────────────────
        for cat, items in categorized.items():
            if not items:
                continue

            f.write(f"## {cat}\n\n")

            # Top N
            f.write(f"### 🏆 Top {min(TOP_N, len(items))} by Quality Score\n\n")
            f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
            f.write("| :--- | ---: | ---: | :--- |\n")
            for r in items[:TOP_N]:
                f.write(repo_row(r))

            # Collapsible full list
            if len(items) > TOP_N:
                f.write(f"\n<details>\n")
                f.write(
                    f"<summary><b>👉 View all {len(items)} repositories in this category</b></summary>\n\n"
                )
                for i, chunk in enumerate(chunk_list(items, CHUNK_SIZE)):
                    f.write(f"#### 📄 Page {i + 1}\n\n")
                    f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
                    f.write("| :--- | ---: | ---: | :--- |\n")
                    for r in chunk:
                        f.write(repo_row(r))
                    f.write("\n")
                f.write("</details>\n\n")

        # ── FOOTER ───────────────────────────────────────────────────────────
        f.write("---\n")
        f.write(
            "⭐ Auto-curated by [Awesome Index](https://github.com). "
            "Quality score combines stars, forks, recency, licensing, and topic richness.\n"
        )

    print(f"✅ README.md written — {stats_total} repos across {stats_cats} categories.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    repos = fetch_all_repos()

    if repos:
        generate_readme(repos)
    else:
        print("❌ No repositories found. Check your GH_TOKEN and network access.")
