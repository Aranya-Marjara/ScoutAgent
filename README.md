# ScoutAgent
An autonomous news intelligence agent that searches, summarizes, and generates actionable insights
=======
# 🧭 ScoutAgent

ScoutAgent is an **autonomous research and summarization agent**.  
It autonomously searches recent news, fetches articles, summarizes them using AI, and generates action items — all towards a goal.

---

##  Features
- 🔍 Fetches recent news articles via Google News RSS  
- 🧠 Summarizes content using Transformer-based AI (DistilBART)  
- 🗂 Generates actionable insights  
- 💾 Saves final reports automatically  
- 🤖 Fully autonomous task planner (no manual steps)

---

## ⚙️ Setup
### 1️⃣ Clone the repository
```bash
git clone https://github.com/Aranya-Marjara/ScoutAgent.git

# Go to the directory
cd ScoutAgent


#creating a virtual environment (highly recommended).
python3 -m venv venv
source venv/bin/activate 
#use the command 'deactivate' to exit


#Installing requirements.
pip install -r requirements.txt 
```

# 🚀 Run the Agent
python3 scout-agent.py "your research topic"

# Example:

python3 scout-agent.py "AI regulation"

