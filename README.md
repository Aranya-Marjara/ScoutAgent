<div align="center">

# 🧭 **ScoutAgent**

### *Autonomous News Intelligence Assistant*

[![Python](https://img.shields.io/badge/Made%20with-Python-3776AB?logo=python&logoColor=white)](https://www.python.org/)
![AI](https://img.shields.io/badge/Powered%20by-AI%20Summarization-ff69b4)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Autonomous](https://img.shields.io/badge/Mode-Fully%20Autonomous-blueviolet?logo=robotframework&logoColor=white)]()

---

🚀 *ScoutAgent automatically searches, summarizes, and generates insights from the latest news —  
analyzing the world in real-time so you don’t have to.*

</div>

---

## ⚙️ **Features**

| 🧩 Function | 🔍 Description |
|--------------|----------------|
| 📰 **Fetches News** | Retrieves recent articles using **Google News RSS** |
| 🧠 **AI Summarization** | Uses a **Transformer-based model** *(e.g., DistilBART)* for concise summaries |
| 💡 **Insight Extraction** | Generates “action items” using heuristic NLP |
| 💾 **Report Saving** | Automatically exports **Markdown** + **Plain Text** reports |
| 🤖 **Fully Autonomous** | From search → summarization → report, no manual steps required |

---

## 🧠 **Setup and Usage**

```bash
# 1. Make sure you have installed 'python3' and 'pip'

# 2. Clone the repository
git clone https://github.com/Aranya-Marjara/ScoutAgent.git

# 3. Go to directory
cd scoutagent

# 4. Create a virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 5. Install dependencies
pip install -r requirements.txt

# 6. Run ScoutAgent with your query
python3 scout-agent.py "AI regulation"
