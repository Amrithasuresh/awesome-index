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

# --- CATEGORIES ---
CATEGORIES = [
    ("🤖 AI, LLMs & ChatGPT", ["llm", "gpt", "chatgpt", "openai", "claude", "gemini", "ollama", "langchain", "rag", "agent"], []),
    ("📊 Data Science & ML", ["machine-learning", "deep-learning", "pytorch", "tensorflow", "data-science", "nlp"], []),
    ("🖥️ Operating Systems & Platforms", ["linux", "windows", "macos", "kernel"], []),
    ("💼 Career, Jobs & Interview", ["interview", "resume", "career", "job"], []),
    ("📚 Books, Courses & Learning", ["book", "course", "tutorial", "learning"], []),
    ("🎮 Gaming & Graphics", ["game", "opengl", "unity", "unreal"], []),
    ("🧬 Science, Medical & Bio", ["bioinformatics", "medical", "biology"], []),
    ("🛡️ Security & Privacy", ["security", "privacy", "hacking", "ctf"], []),
    ("⚙️ Systems, HPC & Performance", ["hpc", "gpu", "cuda", "slurm"], []),
    ("🌐 Web, Backend & APIs", ["api", "backend", "web", "fastapi", "django"], []),
    ("🛠️ Developer Tools", ["cli", "devops", "docker", "kubernetes"], []),
    ("📱 Mobile", ["android", "ios", "flutter"], []),
    ("☁️ Cloud & Infrastructure", ["cloud", "aws", "terraform"], []),
    ("🗄️ Databases & Storage", ["database", "sql", "redis"], []),
    ("🎨 Design & UI", ["design", "ui", "ux"], []),
]

STAR_TIERS = [
    "500..700", "701..1000", "1001..1500", "1501..2500",
    "2501..5000", "5001..10000", "10001..20000",
    "20001..50000", ">50000"
]

# ---------------------------------------------------------------------------
# ANCHOR FIX
# ---------------------------------------------------------------------------

def make_anchor(cat):
    """Generate stable GitHub-safe anchor"""
    anchor = cat.lower()
    anchor = anchor.encode('ascii', 'ignore').decode()
    anchor = re.sub(r'[^\w\s-]', '', anchor)
    anchor = re.sub(r'\s+', '-', anchor)
    anchor = re.sub(r'-+', '-', anchor)
    return anchor.strip('-')


# ---------------------------------------------------------------------------
# TRENDING
# ---------------------------------------------------------------------------

def trending_score(repo):
    """Stars per day metric"""
    stars = repo.get("stargazers_count", 0)
    created = repo.get("created_at", "")

    if not created:
        return 0

    try:
        created_date = datetime.strptime(created[:10], "%Y-%m-%d")
        age_days = max((datetime.utcnow() - created_date).days, 1)
        return stars / age_days
    except:
        return 0


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def get_category(repo):
    text = (repo.get("name", "") + " " + (repo.get("description") or "")).lower()

    best_cat = "📦 Miscellaneous"
    best_score = 0

    for cat, keywords, _ in CATEGORIES:
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat


def is_genuinely_awesome(repo):
    if repo.get("fork"):
        return False

    if repo.get("stargazers_count", 0) < MIN_STARS:
        return False

    text = (repo.get("name", "") + " " + (repo.get("description") or "")).lower()
    return "awesome" in text


# ---------------------------------------------------------------------------
# FETCH
# ---------------------------------------------------------------------------

def fetch_all_repos():
    headers = {"Accept": "application/vnd.github.mercy-preview+json"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    repos = {}
    active_since = (datetime.utcnow() - timedelta(days=DAYS_ACTIVE)).strftime('%Y-%m-%d')

    for tier in STAR_TIERS:
        page = 1
        while page <= 10:
            query = f'awesome in:name,description stars:{tier} pushed:>{active_since}'
            url = f"{BASE_URL}?q={query}&per_page={PER_PAGE}&page={page}"

            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                break

            items = resp.json().get("items", [])
            if not items:
                break

            for repo in items:
                if is_genuinely_awesome(repo):
                    repos[repo["full_name"]] = repo

            page += 1
            time.sleep(1)

    return list(repos.values())


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

def generate_readme(repos):
    categorized = {cat[0]: [] for cat in CATEGORIES}
    categorized["📦 Miscellaneous"] = []

    for repo in repos:
        categorized[get_category(repo)].append(repo)

    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    with open("README.md", "w", encoding="utf-8") as f:

        # HEADER
        f.write("# 🚀 Awesome Index\n\n")
        f.write(
            f"**Last Updated:** `{now}`  \n"
            f"**Total Repositories:** `{len(repos)}`  \n"
            f"**Active Categories:** `{sum(1 for v in categorized.values() if v)}`  \n"
            "**Criteria:** `500+ ⭐ · Actively maintained · Curated list`\n\n"
        )

        # WHAT IS THIS
        f.write("## 🔍 What is this?\n\n")
        f.write(
            f"A single searchable index of `{len(repos):,}` curated awesome lists across GitHub, "
            "auto-updated every Sunday.\n\n"
        )

        # TRENDING
        f.write("## 🔥 Trending Now\n\n")
        f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
        f.write("| :--- | ---: | ---: | :--- |\n")

        trending = sorted(repos, key=trending_score, reverse=True)[:15]

        for r in trending:
            desc = (r.get("description") or "").replace("|", " ")[:100]
            f.write(
                f"| [{r['full_name']}]({r['html_url']}) "
                f"| ⭐ `{r['stargazers_count']}` "
                f"| 🍴 `{r['forks_count']}` "
                f"| {desc} |\n"
            )

        f.write("\n---\n\n")

        # NAV
        f.write("## 📂 Categories\n\n")
        for cat, items in categorized.items():
            if items:
                f.write(f"- [{cat}](#{make_anchor(cat)}) `{len(items)}`\n")

        f.write("\n---\n\n")

        # SECTIONS WITH TOGGLE
        for cat, items in categorized.items():
            if not items:
                continue

            anchor = make_anchor(cat)

            f.write(f'<a name="{anchor}"></a>\n')
            f.write(f"## {cat}\n\n")

            # TOP
            f.write(f"### 🏆 Top {min(TOP_N, len(items))}\n\n")
            f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
            f.write("| :--- | ---: | ---: | :--- |\n")

            for r in items[:TOP_N]:
                desc = (r.get("description") or "").replace("|", " ")[:100]
                f.write(
                    f"| [{r['full_name']}]({r['html_url']}) "
                    f"| ⭐ `{r['stargazers_count']}` "
                    f"| 🍴 `{r['forks_count']}` "
                    f"| {desc} |\n"
                )

            # FULL LIST TOGGLE
            if len(items) > TOP_N:
                f.write("\n<details>\n")
                f.write(f"<summary><b>👉 View all {len(items)} repositories</b></summary>\n\n")

                for i in range(0, len(items), CHUNK_SIZE):
                    chunk = items[i:i + CHUNK_SIZE]

                    f.write(f"#### 📄 Page {(i // CHUNK_SIZE) + 1}\n\n")
                    f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
                    f.write("| :--- | ---: | ---: | :--- |\n")

                    for r in chunk:
                        desc = (r.get("description") or "").replace("|", " ")[:100]
                        f.write(
                            f"| [{r['full_name']}]({r['html_url']}) "
                            f"| ⭐ `{r['stargazers_count']}` "
                            f"| 🍴 `{r['forks_count']}` "
                            f"| {desc} |\n"
                        )

                    f.write("\n")

                f.write("</details>\n\n")

            f.write("\n")

    print("✅ README generated with toggle restored.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    repos = fetch_all_repos()
    generate_readme(repos)
