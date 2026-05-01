"""
Daily post draft generator.
Pulls recent GitHub activity, asks an LLM to suggest post angles,
and files the drafts as a GitHub issue for review.
"""

import os
import json
import requests
from datetime import datetime, timedelta, timezone
from typing import Any

# --- Config (read from env vars set in GitHub Actions) ---
GITHUB_TOKEN = os.environ["GH_PAT"]  # personal access token with repo scope
OPENROUTER_KEY = os.environ["OPENROUTER_KEY"]
GITHUB_USERNAME = os.environ.get("GH_USERNAME", "delbyte")
DRAFT_REPO = os.environ.get("DRAFT_REPO", "delbyte/post-drafts")  # where issues land

# Comma-separated list of repos to scan, e.g. "delbyte/myproject,hercules/platform"
SOURCE_REPOS = [r.strip() for r in os.environ.get("SOURCE_REPOS", "").split(",") if r.strip()]

# Model on OpenRouter — free tier
# DeepSeek V3.2 is currently the strongest free model for instruction-following
# creative tasks (May 2026). Fallback to openrouter/free which auto-routes
# across all available free models if the primary is rate-limited or down.
MODEL = os.environ.get("MODEL", "deepseek/deepseek-v3.2:free")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "openrouter/free")

LOOKBACK_HOURS = 24


def fetch_recent_prs(repo: str, since: datetime) -> list[dict[str, Any]]:
    """Get PRs that were merged or updated in the lookback window."""
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    params = {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 30}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[warn] couldn't fetch {repo}: {e}")
        return []

    prs = []
    for pr in r.json():
        if pr["user"]["login"].lower() != GITHUB_USERNAME.lower():
            continue
        if not pr.get("merged_at"):
            continue
        merged_at = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
        if merged_at < since:
            continue
        prs.append({
            "repo": repo,
            "title": pr["title"],
            "body": (pr["body"] or "")[:500],  # cap to keep prompt small
            "url": pr["html_url"],
            "merged_at": pr["merged_at"],
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
        })
    return prs


def fetch_recent_commits(repo: str, since: datetime) -> list[dict[str, Any]]:
    """Fallback: if no PRs, look at direct commits to default branch."""
    url = f"https://api.github.com/repos/{repo}/commits"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    params = {
        "author": GITHUB_USERNAME,
        "since": since.isoformat(),
        "per_page": 20,
    }
    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"[warn] couldn't fetch commits for {repo}: {e}")
        return []

    return [
        {
            "repo": repo,
            "title": c["commit"]["message"].split("\n")[0],
            "url": c["html_url"],
            "date": c["commit"]["author"]["date"],
        }
        for c in r.json()
    ]


def build_prompt(activity: list[dict]) -> str:
    """Construct the prompt for the model. This is the key file to iterate on."""
    activity_summary = "\n".join(
        f"- [{a['repo']}] {a['title']}" + (f" ({a.get('additions', 0)}+/{a.get('deletions', 0)}-)" if 'additions' in a else "")
        for a in activity
    )

    return f"""You are helping a 19-year-old full-stack engineer named Arnav (handle: delbyte) brainstorm Twitter/X post ideas based on his recent GitHub activity. He works at an AI company but CANNOT post anything that would leak:
- proprietary code, algorithms, architecture decisions
- unreleased features or roadmap signals
- internal performance numbers, customer data, or business strategy
- anything specific to his employer's product that isn't already public

What he CAN post:
- General technical patterns or lessons learned (framed in his own voice, not as if speaking for the company)
- Open-source tools/libraries he used and what worked or didn't
- Debugging stories with the company-specific details abstracted away
- Conceptual takes on AI/full-stack/devtool topics his work touches on

His voice: direct, self-aware, slightly irreverent, no hype, no thread-bro emoji spam, no "🧵👇". Talks like a real engineer, not a content creator. Short sentences. Specific over abstract.

Here is his GitHub activity from the last 24 hours:
{activity_summary}

Generate exactly 3 post ideas. For each:
1. **Angle**: one sentence describing the angle
2. **Why it works**: one sentence on why this would resonate on dev/AI Twitter
3. **Draft**: a post under 280 chars, OR a short thread (2-4 tweets) if the topic genuinely needs it. Write in Arnav's voice as described above.
4. **Risk check**: one sentence flagging any IP/confidentiality concerns to double-check before posting

If the activity is too sparse or all the topics are too company-specific to safely post about, say so honestly and suggest he write about something general from his domain instead. Don't pad with weak ideas.

Output as plain markdown, no preamble."""


def call_openrouter(prompt: str, model: str | None = None) -> str:
    """Call OpenRouter's chat completions API. Retries with fallback model on failure."""
    model = model or MODEL
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json",
            # Optional but recommended by OpenRouter for free tier ranking
            "HTTP-Referer": "https://github.com/delbyte/post-drafts",
            "X-Title": "Post Drafter",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 1500,
        },
        timeout=60,
    )

    # Retry with fallback if primary model fails (rate limit, outage, etc.)
    if response.status_code != 200 and model != FALLBACK_MODEL:
        print(f"[warn] {model} returned {response.status_code}, falling back to {FALLBACK_MODEL}")
        return call_openrouter(prompt, model=FALLBACK_MODEL)

    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def create_github_issue(title: str, body: str) -> str:
    """File the drafts as an issue in the drafts repo."""
    url = f"https://api.github.com/repos/{DRAFT_REPO}/issues"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    r = requests.post(url, headers=headers, json={
        "title": title,
        "body": body,
        "labels": ["draft"],
    }, timeout=30)
    r.raise_for_status()
    return r.json()["html_url"]


def main():
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    print(f"Looking at activity since {since.isoformat()}")

    if not SOURCE_REPOS:
        print("No SOURCE_REPOS configured. Exiting.")
        return

    all_activity = []
    for repo in SOURCE_REPOS:
        prs = fetch_recent_prs(repo, since)
        if prs:
            all_activity.extend(prs)
            print(f"  {repo}: {len(prs)} merged PRs")
        else:
            commits = fetch_recent_commits(repo, since)
            all_activity.extend(commits)
            print(f"  {repo}: {len(commits)} commits (no PRs)")

    if not all_activity:
        print("No activity found. Skipping draft generation.")
        return

    prompt = build_prompt(all_activity)
    print(f"\nCalling {MODEL} with {len(all_activity)} activity items...")
    drafts = call_openrouter(prompt)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    issue_body = f"""**Generated:** {datetime.now(timezone.utc).isoformat()}
**Activity items:** {len(all_activity)}
**Model:** {MODEL}

---

{drafts}

---

<details>
<summary>Raw activity feed</summary>

```json
{json.dumps(all_activity, indent=2)}
```

</details>
"""
    issue_url = create_github_issue(f"Post drafts — {today}", issue_body)
    print(f"\n✓ Drafts filed: {issue_url}")


if __name__ == "__main__":
    main()
