#!/usr/bin/env python3
"""
github:  https://github.com/Aranya-Marjara
Features:
- CLI goal input
- Planner (decides a task plan based on the goal)
- Search via Google News RSS
- Fetch articles (best-effort)
- Per-article summaries + Overall summary
- Action-item extraction
- Save both TXT and Markdown reports (timestamped)
- Uses Hugging Face transformers summarizer if available, otherwise a simple fallback

Run:
    python3 agent.py "your topic here"
"""
import warnings
import logging

# Suppress all unnecessary Hugging Face warnings & info logs
warnings.filterwarnings("ignore", message=r".*max_length.*")
warnings.filterwarnings("ignore", category=UserWarning, module="transformers")
logging.getLogger("transformers").setLevel(logging.ERROR)

from datetime import datetime
import time
import requests
from bs4 import BeautifulSoup
import json
import re
import random
import os
import sys
# Optional summarizer (Hugging Face). If not installed, falls back to simple extractor.
try:
    from transformers import pipeline
    SUMMARIZER = pipeline("summarization")
except Exception:
    SUMMARIZER = None

import contextlib
import io

def safe_summarize(text, **kwargs):
    """Run summarizer silently (no max_length warnings)."""
    if SUMMARIZER is None:
        return text[:300]  # fallback: truncate

    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        try:
            result = SUMMARIZER(text, **kwargs)
            return result[0]["summary_text"].strip()
        except Exception:
            return text[:300]


# ---------- Tools ----------
def search_news_rss(query, days=7, max_items=10):
    """Fetch Google News RSS search results and return list of dicts {title, link, snippet}."""
    q = requests.utils.quote(query)
    url = f"https://news.google.com/rss/search?q={q}+when:7d&hl=en-US&gl=US&ceid=US:en"
    print(f"[tool] fetching RSS: {url}")
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print("[tool] RSS fetch failed:", e)
        return []
    soup = BeautifulSoup(r.text, "xml")
    items = soup.find_all("item")[:max_items]
    results = []
    for it in items:
        title = it.title.text if it.title else "Untitled"
        link = it.link.text if it.link else ""
        desc = it.description.text if it.description else ""
        desc = BeautifulSoup(desc, "html.parser").get_text()  # strip HTML
        results.append({"title": title, "link": link, "snippet": desc})
    return results

def fetch_article_text(url, max_chars=3000):
    """Best-effort article text extraction using <p> tags."""
    if not url:
        return ""
    try:
        r = requests.get(url, timeout=8, headers={"User-Agent": "ScoutAgent/1.0"})
        if r.status_code != 200:
            return ""
        page = BeautifulSoup(r.text, "html.parser")
        paragraphs = page.find_all("p")
        text = "\n\n".join(p.get_text() for p in paragraphs)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception:
        return ""

def summarize_text(text, default_max=130):
    """Summarize text. Use HF pipeline if available, otherwise extractive fallback."""
    if not text:
        return ""

    # Clean stray HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Use model-based summarization if available
    if SUMMARIZER:
        try:
            input_len = max(1, len(text.split()))
            # heuristic: target a shorter summary than input
            max_len = min(default_max, max(30, int(input_len * 0.6)))
            min_len = max(12, int(max_len * 0.4))
            out = safe_summarize(
                text,
                max_length=max_len,
                min_length=min_len,
                do_sample=False
            )

            # Handle different possible return types safely
            if isinstance(out, list):
                result = out[0] if len(out) > 0 else ""
                if isinstance(result, dict):
                    return result.get("summary_text", "").strip()
                elif isinstance(result, str):
                    return result.strip()
            elif isinstance(out, dict):
                return out.get("summary_text", "").strip()
            elif isinstance(out, str):
                return out.strip()

        except Exception as e:
            print("[warn] summarizer failed:", e)
            # fall through to fallback

    # Fallback: just grab the first 3 sentences
    sentences = re.split(r'(?<=[.!?]) +', text)
    return " ".join(sentences[:3]).strip()


def generate_action_items(summary, n=5):
    """Extract candidate entities/topics and produce action items."""
    # Extract capitalized multiword phrases as candidate entities
    entities = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', summary)
    stopwords = {"Title", "Summary", "Link", "Overall", "The", "A", "An", "Investigate", "Report"}
    keywords = [w for w in dict.fromkeys(entities) if w.split()[0] not in stopwords]
    # If none, use common topic words from summary (lowercase nouns)
    if not keywords:
        cand = re.findall(r'\b([a-z]{4,})\b', summary.lower())
        cand = [c for c in dict.fromkeys(cand) if c not in {"this","that","have","will"}]
        keywords = cand[:n] if cand else ["key topics"]
    items = []
    for i, kw in enumerate(keywords[:n], 1):
        items.append(f"{i}. Investigate recent updates related to {kw.strip()}.")
    return "\n".join(items)

# ---------- File saving helpers ----------
def save_text_report(report_text, filename=None):
    if not filename:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"report_{ts}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"[file] saved text report: {os.path.abspath(filename)}")
    return filename

def save_markdown_report(md_text, filename=None):
    if not filename:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"report_{ts}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_text)
    print(f"[file] saved markdown report: {os.path.abspath(filename)}")
    return filename

# ---------- Planner & Reasoner ----------
class Planner:
    def __init__(self, goal):
        self.goal = goal

    def plan(self):
        """Return ordered list of tasks based on goal keywords."""
        g = self.goal.lower()
        if any(k in g for k in ("news", "latest", "headlines")):
            return ["search", "fetch", "summarize", "actions", "save"]
        if any(k in g for k in ("analyze", "analysis", "report")):
            return ["fetch", "summarize", "actions", "save"]
        # default sensible plan
        return ["search", "fetch", "summarize", "actions", "save"]

class Reasoner:
    def __init__(self, max_retries=2):
        self.retries = {}
        self.max_retries = max_retries

    def record_failure(self, name):
        self.retries[name] = self.retries.get(name, 0) + 1
        return self.retries[name] <= self.max_retries

    def decide_expansion(self, search_results):
        return len(search_results) == 0

# ---------- Agent ----------
class ScoutAgent:
    def __init__(self, goal):
        self.goal = goal
        self.context = {}
        self.log = []
        self.reasoner = Reasoner()
        self.planner = Planner(goal)

    def run(self):
        print(f"ScoutAgent starting on goal: {self.goal}")

        # 🧠 Log which summarization model (if any) is active
        if SUMMARIZER:
            try:
                print("[model] Using summarizer:", SUMMARIZER.model.name_or_path)
            except AttributeError:
                print("[model] Using summarizer: Transformer-based model (unknown name)")
        else:
            print("[model] Using fallback heuristic summarizer")

        # 🧭 Agentic planning
        plan = self.planner.plan()
        self.context["plan"] = plan
        print(f"[agent] plan: {plan}")

        for step in plan:
            print(f"[agent] executing step: {step}")
            ok = self.execute_task(step)
            if ok:
                self.log.append(f"{step} succeeded")
            else:
                self.log.append(f"{step} failed")
                # allow reasoner to decide retry/expand when appropriate
                if step == "search" and self.reasoner.record_failure(step):
                    print("[agent] retrying search with broadened query")
                    # broaden query and retry one time
                    self.goal = self.goal + " policy OR regulation"
                    ok = self.execute_task("search")
                    if ok:
                        self.log.append("search (broadened) succeeded")
                        continue
                print("[agent] aborting remaining steps due to failure.")
                break


        # Generate and save reports
        md = self.generate_markdown_report()
        txt = self.generate_text_report()
        md_file = save_markdown_report(md)
        txt_file = save_text_report(txt)
        return {"md": md_file, "txt": txt_file}

    def execute_task(self, task_name):
        if task_name == "search":
            results = search_news_rss(self.goal, days=7, max_items=8)
            self.context["search_results"] = results
            return len(results) > 0

        if task_name == "fetch":
            results = self.context.get("search_results", [])
            articles = []
            for it in results:
                text = fetch_article_text(it.get("link", ""))
                if not text:
                    text = it.get("snippet", "")
                articles.append({"meta": it, "text": text})
            self.context["articles"] = articles
            return len(articles) > 0

        if task_name == "summarize":
            arts = self.context.get("articles", [])
            detailed = []
            all_summaries = []
            for art in arts[:5]:
                title = art["meta"].get("title", "Untitled")
                link = art["meta"].get("link", "")
                text = art.get("text", "")
                short = summarize_text(text)
                detailed.append({"title": title, "link": link, "summary": short})
                all_summaries.append(short)
            overall = summarize_text(" ".join(all_summaries)) if all_summaries else ""
            self.context["detailed_summaries"] = detailed
            self.context["overall_summary"] = overall
            return len(detailed) > 0

        if task_name == "actions":
            # generate action items from overall summary + detailed summaries
            overall = self.context.get("overall_summary", "")
            details_text = " ".join(d["summary"] for d in self.context.get("detailed_summaries", []))
            seed_text = overall + " " + details_text
            items = generate_action_items(seed_text, n=5)
            self.context["actions"] = items
            return bool(items)

        if task_name == "save":
            # prepare final report in context; actual writing is done in run()
            return True

        return False

    def generate_text_report(self):
        # Create a human-readable plain text report
        goal = self.goal
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = []
        lines.append(f"Goal: {goal}")
        lines.append(f"Time: {ts}")
        lines.append("\n---\n")
        lines.append("Detailed Summaries:\n")
        for i, d in enumerate(self.context.get("detailed_summaries", []), 1):
            lines.append(f"{i}. {d['title']}")
            lines.append(f"Link: {d['link']}")
            lines.append(f"Summary: {d['summary']}\n")
        lines.append("\nOverall Summary:\n" + (self.context.get("overall_summary", "") or ""))
        lines.append("\nAction Items:\n" + (self.context.get("actions", "") or ""))
        lines.append("\nAgent log:\n" + "\n".join(self.log))
        return "\n".join(lines)

    def generate_markdown_report(self):
        # Create a markdown report for GitHub friendly output
        goal = self.goal
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        md = []
        md.append(f"# ScoutAgent Report")
        md.append(f"**Goal:** {goal}  ")
        md.append(f"**Time:** {ts}  \n---\n")
        md.append("## Detailed Summaries\n")
        for i, d in enumerate(self.context.get("detailed_summaries", []), 1):
            md.append(f"### {i}. {d['title']}")
            md.append(f"[Source]({d['link']})  \n")
            md.append(f"{d['summary']}  \n")
        md.append("## Overall Summary\n")
        md.append(self.context.get("overall_summary", "") or "No overall summary available.")
        md.append("\n## Action Items\n")
        md.append(self.context.get("actions", "") or "No action items generated.")
        md.append("\n## Agent Log\n")
        md.append("```\n" + "\n".join(self.log) + "\n```")
        md.append("\n*Generated autonomously by ScoutAgent.*")
        return "\n\n".join(md)

# ---------- CLI ----------
def main():
    goal = sys.argv[1] if len(sys.argv) > 1 else "AI regulation"
    agent = ScoutAgent(goal)
    res = agent.run()
    print("Done. Reports:", res)

if __name__ == "__main__":
    main()
