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
    ("🤖 AI, LLMs & ChatGPT", ["llm", "gpt", "chatgpt", "openai", "claude", "gemini", "ollama", "langchain", "rag", "agent", "diffusion", "stable-diffusion", "huggingface", "transformers"], []),
    ("📊 Data Science & ML", ["machine-learning", "deep-learning", "pytorch", "tensorflow", "data-science", "sklearn", "neural-network", "computer-vision", "nlp", "reinforcement-learning"], []),
    ("🖥️ Operating Systems & Platforms", ["linux", "macos", "windows", "kernel", "unix", "bsd", "embedded", "rtos", "firmware"], []),
    ("💼 Career, Jobs & Interview", ["interview", "resume", "cv", "career", "job", "hiring", "leetcode", "coding-challenge", "system-design"], []),
    ("📚 Books, Courses & Learning", ["book", "course", "tutorial", "learning", "education", "curriculum", "roadmap", "beginner"], []),
    ("🎮 Gaming & Graphics", ["game", "gaming", "opengl", "vulkan", "directx", "unity", "unreal", "gamedev", "shader", "raytracing", "webgl"], []),
    ("🧬 Science, Medical & Bio", ["bioinformatics", "genomics", "medical", "biology", "chemistry", "physics", "neuroscience", "imaging", "clinical", "covid"], []),
    ("🛡️ Security & Privacy", ["security", "privacy", "cryptography", "hacking", "pentest", "ctf", "malware", "vulnerability", "infosec", "osint", "zero-trust"], []),
    ("⚙️ Systems, HPC & Performance", ["hpc", "gpu", "cuda", "parallel", "distributed", "slurm", "performance", "optimization", "benchmark", "low-latency", "simd"], []),
    ("🌐 Web, Backend & APIs", ["api", "backend", "web", "server", "http", "graphql", "rest", "microservice", "serverless", "nginx", "fastapi", "django", "flask", "express", "nextjs"], []),
    ("🛠️ Developer Tools", ["cli", "terminal", "shell", "vim", "neovim", "vscode", "devops", "docker", "kubernetes", "ci-cd", "git", "linting", "debugging", "profiling"], []),
    ("📱 Mobile", ["android", "ios", "react-native", "flutter", "swift", "kotlin", "mobile", "app"], []),
    ("☁️ Cloud & Infrastructure", ["cloud", "aws", "azure", "gcp", "terraform", "ansible", "infra", "sre", "monitoring", "logging", "observability"], []),
    ("🗄️ Databases & Storage", ["database", "sql", "nosql", "postgres", "mysql", "redis", "mongodb", "elasticsearch", "vector-database", "storage", "cache"], []),
    ("🎨 Design & UI", ["design", "ui", "ux", "figma", "css", "tailwind", "icons", "typography", "color", "accessibility"], []),
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
    """Generate stable anchor (fix for GitHub jump issue)."""
    anchor = cat.lower()
    anchor = anchor.encode('ascii', 'ignore').decode()
    anchor = re.sub(r'[^\w\s-]', '', anchor)
    anchor = re.sub(r'\s+', '-', anchor)
    anchor = re.sub(r'-+', '-', anchor)
    return anchor.strip('-')


# ---------------------------------------------------------------------------
# TRENDING (NEW)
# ---------------------------------------------------------------------------

def trending_score(repo):
    """Simple trending: stars per day since creation."""
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
    name = repo.get("full_name", "").lower()
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in repo.get("topics", [])]
    content = f"{name} {desc} {' '.join(topics)}"

    best_cat = "📦 Miscellaneous"
    best_score = 0

    for cat_name, keywords, _ in CATEGORIES:
        score = sum(1 for kw in keywords if kw in content)
        if score > best_score:
            best_score = score
            best_cat = cat_name

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
            "auto-updated every Sunday. Covers AI, LLMs, Security, DevTools, Mobile, "
            "Cloud, Databases, and more.\n\n"
        )

        # 🔥 TRENDING
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

        # SECTIONS
        for cat, items in categorized.items():
            if not items:
                continue

            anchor = make_anchor(cat)

            f.write(f'<a name="{anchor}"></a>\n')
            f.write(f"## {cat}\n\n")

            for r in items[:TOP_N]:
                desc = (r.get("description") or "").replace("|", " ")[:100]
                f.write(f"- [{r['full_name']}]({r['html_url']}) — ⭐ {r['stargazers_count']}\n")

            f.write("\n")

    print("✅ README generated")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    repos = fetch_all_repos()
    generate_readme(repos)
