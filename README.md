ScoutAgent — Autonomous News Intelligence Assistant

ScoutAgent is a lightweight autonomous research agent that automatically
searches recent news, summarizes articles using AI, and generates concise insight reports.

⚙️ Features

🔍 Fetches recent news via Google News RSS

🧠 Summarizes articles using a Transformer-based model (e.g., DistilBART) if available

🗂 Generates concise “action items” from summaries using heuristic extraction

💾 Saves reports automatically in Markdown and plain text formats

🤖 Fully autonomous workflow — from search to summary to report

🚀 Example
python3 scout-agent.py "AI regulation"


ScoutAgent will automatically:

Search for recent articles about AI regulation

Fetch and summarize them

Generate insights and action items

Save the results as a timestamped report
