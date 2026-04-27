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

TRENDING_DAYS = 30


# ---------------------------------------------------------------------------
# FIXED ANCHOR GENERATOR (CRITICAL FIX)
# ---------------------------------------------------------------------------

def make_anchor(cat):
    """Deterministic GitHub-safe anchor"""
    anchor = cat.lower()
    anchor = anchor.encode('ascii', 'ignore').decode()   # remove emojis
    anchor = re.sub(r'[^\w\s-]', '', anchor)              # remove punctuation
    anchor = re.sub(r'\s+', '-', anchor)                  # spaces → hyphen
    anchor = re.sub(r'-+', '-', anchor)                   # collapse
    return anchor.strip('-')


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def get_category(repo):
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
                score += 3
            elif kw in name:
                score += 2
            elif kw in desc:
                score += 1

        for kw in bonus:
            if kw in content:
                score += 1

        if score > best_score:
            best_score = score
            best_cat = cat_name

    return best_cat


def quality_score(repo):
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)
    watchers = repo.get("watchers_count", 0)
    open_issues = repo.get("open_issues_count", 0)

    pushed = repo.get("pushed_at", "")
    recency_bonus = 0

    if pushed:
        try:
            pushed_date = datetime.strptime(pushed[:10], "%Y-%m-%d")
            days_ago = (datetime.utcnow() - pushed_date).days
            recency_bonus = max(0, 1000 - days_ago * 2)
        except:
            pass

    return round(
        math.log1p(stars) * 150 +
        math.log1p(forks) * 50 +
        math.log1p(watchers) * 10 -
        min(open_issues / max(stars, 1) * 200, 150) +
        recency_bonus,
        2
    )


def trending_score(repo):
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


def is_genuinely_awesome(repo):
    if repo.get("fork"):
        return False

    name = repo.get("name", "").lower()
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in repo.get("topics", [])]

    if "awesome" not in name and "awesome" not in desc and "awesome" not in topics:
        return False

    if repo.get("stargazers_count", 0) < MIN_STARS:
        return False

    return True


# ---------------------------------------------------------------------------
# FETCH
# ---------------------------------------------------------------------------

def fetch_all_repos():
    headers = {"Accept": "application/vnd.github.mercy-preview+json"}
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    all_repos = {}
    active_since = (datetime.utcnow() - timedelta(days=DAYS_ACTIVE)).strftime('%Y-%m-%d')

    for tier in STAR_TIERS:
        page = 1

        while page <= 10:
            query = f'awesome in:name,description,topics stars:{tier} pushed:>{active_since}'
            url = f"{BASE_URL}?q={query}&sort=stars&order=desc&per_page={PER_PAGE}&page={page}"

            resp = requests.get(url, headers=headers)
            if resp.status_code != 200:
                break

            data = resp.json()
            items = data.get("items", [])

            if not items:
                break

            for repo in items:
                if is_genuinely_awesome(repo):
                    all_repos[repo["full_name"]] = repo

            page += 1
            time.sleep(1)

    return list(all_repos.values())


# ---------------------------------------------------------------------------
# README GENERATION (FIXED)
# ---------------------------------------------------------------------------

def generate_readme(repos):
    repos.sort(key=lambda x: quality_score(x), reverse=True)

    categorized = {cat[0]: [] for cat in CATEGORIES}
    categorized["📦 Miscellaneous"] = []

    for repo in repos:
        categorized[get_category(repo)].append(repo)

    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')

    with open("README.md", "w", encoding="utf-8") as f:

        f.write("# 🚀 Awesome Index\n\n")
        f.write(f"**Last Updated:** `{now}`\n\n")

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

            # 🔥 FIX HERE
            f.write(f'<a name="{anchor}"></a>\n')
            f.write(f"## {cat}\n\n")

            f.write("| Repository | ⭐ Stars | 🍴 Forks | Description |\n")
            f.write("| :--- | ---: | ---: | :--- |\n")

            for r in items[:TOP_N]:
                f.write(
                    f"| [{r['full_name']}]({r['html_url']}) "
                    f"| ⭐ `{r['stargazers_count']}` "
                    f"| 🍴 `{r['forks_count']}` "
                    f"| {(r.get('description') or '')[:100]} |\n"
                )

            f.write("\n")

    print("✅ README fixed and generated.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    repos = fetch_all_repos()
    generate_readme(repos)
```
