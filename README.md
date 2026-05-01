# post-drafter

Daily cron that pulls your recent GitHub activity, asks an LLM to draft 3 post angles, and files them as a GitHub issue for your review.

## Setup (one-time, ~15 min)

### 1. Create the drafts repo

Create a new **private** repo on GitHub called `post-drafts` (or whatever — match `DRAFT_REPO` in the workflow). This is where daily issues will land.

### 2. Create the runner repo

Create another repo (can be the same one, or separate — separate is cleaner) and put `generate_drafts.py` and `.github/workflows/daily.yml` in it.

### 3. Get an OpenRouter API key

- Sign up at https://openrouter.ai
- Go to https://openrouter.ai/keys → Create Key
- Free tier: 50 requests/day with no credits, 1000/day if you add $10 once. You'll use 1/day.

### 4. Get a GitHub Personal Access Token

- https://github.com/settings/tokens → Generate new token (classic)
- Scopes needed: `repo` (full repo access — needed to read PRs from private repos and create issues)
- Copy the token

### 5. Add secrets to the runner repo

Repo → Settings → Secrets and variables → Actions → New repository secret. Add:

| Name             | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| `GH_PAT`         | The personal access token from step 4                                 |
| `OPENROUTER_KEY` | The OpenRouter key from step 3                                        |
| `GH_USERNAME`    | Your GitHub username, e.g. `delbyte`                                  |
| `DRAFT_REPO`     | The drafts repo from step 1, e.g. `delbyte/post-drafts`              |
| `SOURCE_REPOS`   | Comma-separated repos to scan, e.g. `delbyte/myproject,hercules/api`  |

### 6. Test it

Repo → Actions → "Daily post drafts" → Run workflow. Should complete in ~30s and file an issue in `post-drafts`.

## Tuning

The prompt in `build_prompt()` is the most important thing in this whole script. Iterate on it. Some things to try:

- **Voice samples**: paste 3-5 of your actual past tweets into the prompt so the model matches your voice better
- **Topic targeting**: if you want to focus on AI/agents specifically, add that constraint
- **Format preferences**: if you only want single tweets, not threads, say so
- **Risk strictness**: tighten the IP/confidentiality language if drafts are getting too close to the line

After 1-2 weeks of drafts, you'll have a strong sense of which angles convert into things you actually post. Adjust prompt accordingly.

## Cost

- GitHub Actions: free (you get 2,000 min/month for private repos, this uses ~30s/day = ~15 min/month)
- OpenRouter free tier: free
- Total: $0/month

## Switching models

Default is `deepseek/deepseek-v3.2:free` — strongest free model on OpenRouter as of May 2026 for instruction-following creative tasks. Falls back to `openrouter/free` (auto-router) if rate-limited or down.

If DeepSeek's voice doesn't match yours after a week of iteration, try these:

- `qwen/qwen-3.6-plus:free` — Alibaba's newer model, free during preview, hit #5 on OpenRouter overall in its first week. Possibly even better than DeepSeek for this task but less proven.
- `nvidia/nemotron-3-super:free` — 1M context, good if you ever want to feed in more PR history
- `moonshotai/kimi-k2.6:free` — strong all-rounder
- `meta-llama/llama-3.3-70b-instruct:free` — different style, sometimes better for casual voice

Free tier rate limits: 20 requests/minute, 200 requests/day per model. You use 1/day, so plenty of headroom.

If you eventually pay $5-10 for credits, `anthropic/claude-sonnet-4-6` will give noticeably better drafts (better voice matching, stronger judgment on what's IP-safe) but cost ~$0.01-0.03 per run. Worth it once you've validated the workflow.

## What this script deliberately does NOT do

- **Auto-post anything anywhere.** Drafts go to a GitHub issue for your review. You write the final post yourself.
- **Pull diffs or code.** Only PR titles, descriptions, and stats. Keeps the prompt small and reduces accidental IP leakage.
- **Generate images.** AI images on technical posts almost always look worse than no image. Add later if needed.
