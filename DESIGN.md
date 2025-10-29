# 🧠 ScoutAgent — Design & Reasoning Document

## 🎯 Purpose
ScoutAgent is a lightweight autonomous research agent that, given a goal or topic, automatically:
1. Searches recent news (Google News RSS)
2. Fetches and summarizes article content
3. Generates concise action items and insights
4. Saves timestamped Markdown and text reports

Its design focuses on autonomy, transparency, and reproducibility — all in a single Python file.

---

## ⚙️ Architecture Overview

### 🧭 1. Planner
- Interprets the goal and decides what sequence of actions to perform.
- Example:  
  “AI regulation” → `["search", "fetch", "summarize", "actions", "save"]`
- Rules are simple and keyword-based for clarity.

### 🧩 2. Reasoner
- Tracks failed steps and handles retries.
- If the `search` step fails (e.g., no results), it broadens the query automatically by adding `"policy OR regulation"`.

### 🔍 3. Tools
- **search_news_rss()** → uses Google News RSS to find relevant articles.
- **fetch_article_text()** → extracts text from article `<p>` tags.
- **summarize_text()** → uses `transformers` (DistilBART) if installed, else falls back to simple extractive summarization.
- **generate_action_items()** → identifies key entities and generates action steps.

### 🧱 4. Execution Engine
- `ScoutAgent.run()` executes each step sequentially according to the plan.
- Automatically logs progress and stops gracefully on unrecoverable failures.

### 🧾 5. Report Generation
- Two output formats:
  - Markdown report (`.md`)
  - Plain text report (`.txt`)
- Includes:
  - Detailed per-article summaries  
  - Overall summary  
  - Extracted action items  
  - Agent log (for traceability)

---

## 🧮 Decision Logic Example

| Scenario | Action |
|-----------|---------|
| No RSS results | Reasoner triggers query broadening |
| Summarizer fails | Fallback to 3-sentence heuristic |
| Missing article text | Uses RSS snippet instead |
| Task fails 2× | Task skipped, next task aborted for safety |

---

## 💡 Design Philosophy
ScoutAgent emphasizes:
- **Transparency:** Logs and outputs are human-readable.
- **Autonomy:** No manual input required after starting.
- **Simplicity:** One-file design; no external DB or services.
- **Fallback resilience:** Always produces output, even offline.

---

## 🧭 Future Enhancements
- Integrate vector memory for persistent knowledge.
- Upgrade summarizer to use multi-doc transformers (e.g., LongT5).
- Add optional reasoning LLM for smarter action extraction.
- Add asynchronous fetching for faster execution.

---

## 📜 Summary
ScoutAgent’s architecture follows the Agentic AI loop:
**Plan → Act → Observe → Summarize → Output.**

Its fully autonomous nature, reproducibility, and explainable logic make it suitable for transparent AI research agents.
