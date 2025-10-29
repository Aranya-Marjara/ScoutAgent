#!/usr/bin/env python3
"""
My news research scraper - ScoutAgent
github.com/Aranya-Marjara

Quick tool to research topics via news articles.
Grabs recent news, summarizes key points, and suggests next steps.

Usage:
    python3 scout-agent.py "your research topic"
"""

import warnings
import logging
from datetime import datetime
import time
import requests
from bs4 import BeautifulSoup
import re
import os
import sys

# Nuclear option for transformer warnings
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)

# Suppress ALL warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Try to load summarizer, but it's optional
summarizer = None
try:
    # Import with warnings suppressed
    import transformers
    transformers.logging.set_verbosity_error()
    
    from transformers import pipeline
    # Suppress the specific max_length warning
    warnings.filterwarnings("ignore", message=".*max_length.*")
    warnings.filterwarnings("ignore", message=".*input_length.*")
    
    summarizer = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
    
except Exception as e:
    print(f"Note: No summarizer available ({e}), using simple fallback")
    summarizer = None

def grab_news_search(query, days_back=7, max_results=10):
    """Search Google News RSS for recent articles about the query."""
    encoded_query = requests.utils.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+when:{days_back}d&hl=en-US&gl=US&ceid=US:en"
    
    print(f"Searching: {rss_url}")
    
    try:
        response = requests.get(rss_url, timeout=15)
        response.raise_for_status()
    except Exception as err:
        print(f"Failed to fetch RSS: {err}")
        return []
    
    soup = BeautifulSoup(response.text, 'xml')
    items = soup.find_all('item')[:max_results]
    
    results = []
    for item in items:
        title = item.title.text if item.title else "No title"
        link = item.link.text if item.link else ""
        # Clean up the description HTML
        desc = item.description.text if item.description else ""
        clean_desc = BeautifulSoup(desc, 'html.parser').get_text()
        
        results.append({
            'title': title,
            'link': link, 
            'snippet': clean_desc
        })
    
    return results

def fetch_full_article(url, max_length=4000):
    """Try to get the main article text from a URL."""
    if not url:
        return ""
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return ""
            
        soup = BeautifulSoup(resp.content, 'html.parser')
        paragraphs = soup.find_all('p')
        text_chunks = [p.get_text().strip() for p in paragraphs if p.get_text().strip()]
        full_text = "\n\n".join(text_chunks)
        
        # Clean up whitespace
        full_text = re.sub(r'\s+', ' ', full_text)
        return full_text[:max_length]
        
    except Exception:
        return ""

def smart_summarize(text, target_length=150):
    """Summarize text using transformer if available, else use simple method."""
    if not text or len(text) < 50:
        return text
    
    # If we have the fancy summarizer, use it
    if summarizer:
        try:
            # Figure out reasonable lengths based on input
            word_count = len(text.split())
            
            # Don't summarize if text is too short
            if word_count < 10:
                return text
            
            max_len = min(target_length, max(30, int(word_count * 0.6)))
            min_len = max(10, int(max_len * 0.3))
            
            # Make sure we're not asking for longer output than input
            if max_len > word_count:
                max_len = max(10, word_count - 5)
                min_len = max(5, int(max_len * 0.5))
            
            # Nuclear option: redirect ALL output
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')
            
            try:
                result = summarizer(text, max_length=max_len, min_length=min_len, do_sample=False)
            finally:
                sys.stdout.close()
                sys.stderr.close()
                sys.stdout = original_stdout
                sys.stderr = original_stderr
            
            if isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], dict):
                    return result[0].get('summary_text', '').strip()
                return str(result[0]).strip()
            return text[:300]  # Fallback
            
        except Exception as e:
            # Don't print the error to avoid more noise
            pass
    
    # Simple method: first few sentences
    sentences = re.split(r'[.!?]+', text)
    clean_sentences = [s.strip() for s in sentences if s.strip()]
    return ' '.join(clean_sentences[:3]).strip()

def generate_follow_up_ideas(summary_text, num_items=5):
    """Generate some follow-up research ideas from the summary."""
    # Look for proper nouns and key phrases
    big_words = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', summary_text)
    
    # Filter out common words
    skip_words = {'The', 'A', 'An', 'This', 'That', 'We', 'You', 'I'}
    interesting_words = [word for word in big_words if word.split()[0] not in skip_words]
    
    # Remove duplicates but keep order
    seen = set()
    unique_words = []
    for word in interesting_words:
        if word not in seen:
            seen.add(word)
            unique_words.append(word)
    
    # If we didn't find good proper nouns, use important sounding words
    if not unique_words:
        words = summary_text.lower().split()
        important = [w for w in words if len(w) > 5 and w not in ['about', 'because', 'however']]
        unique_words = list(dict.fromkeys(important))[:num_items]
    
    actions = []
    for i, topic in enumerate(unique_words[:num_items], 1):
        actions.append(f"{i}. Look into recent developments about {topic}")
    
    return "\n".join(actions)

def save_report(content, filename=None, format='txt'):
    """Save report to file with timestamp."""
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"research_{timestamp}.{format}"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Saved: {os.path.abspath(filename)}")
    return filename

class TaskPlanner:
    """Figures out what steps to take based on the research goal."""
    def __init__(self, goal):
        self.goal = goal.lower()
    
    def get_steps(self):
        """Return the steps needed for this type of research."""
        if any(word in self.goal for word in ['news', 'latest', 'update', 'recent']):
            return ['search', 'fetch', 'summarize', 'suggest_actions', 'save']
        elif any(word in self.goal for word in ['analyze', 'research', 'study']):
            return ['search', 'fetch', 'summarize', 'suggest_actions', 'save']
        else:
            # Default plan
            return ['search', 'fetch', 'summarize', 'suggest_actions', 'save']

class ResearchAgent:
    """Main class that runs the research process."""
    
    def __init__(self, research_goal):
        self.goal = research_goal
        self.data = {}  # Store our findings
        self.steps_log = []
        self.planner = TaskPlanner(research_goal)
    
    def run_research(self):
        """Run the complete research process."""
        print(f"Starting research: {self.goal}")
        print(f"Summarizer: {'Available' if summarizer else 'Basic fallback'}")
        
        steps = self.planner.get_steps()
        print(f"Plan: {steps}")
        
        for step in steps:
            print(f"-> Step: {step}")
            success = self._do_step(step)
            
            if success:
                self.steps_log.append(f"✓ {step}")
            else:
                self.steps_log.append(f"✗ {step}")
                # For search failures, try a broader search
                if step == 'search':
                    print("Trying broader search...")
                    self.goal += " news"
                    success = self._do_step('search')
                    if success:
                        self.steps_log.append("✓ search (broadened)")
                        continue
                print("Stopping due to failure")
                break
        
        # Save our findings
        text_report = self._make_text_report()
        md_report = self._make_markdown_report()
        
        txt_file = save_report(text_report, format='txt')
        md_file = save_report(md_report, format='md')
        
        return {'text': txt_file, 'markdown': md_file}
    
    def _do_step(self, step_name):
        """Execute a single step of the research."""
        if step_name == 'search':
            results = grab_news_search(self.goal)
            self.data['articles_found'] = results
            return len(results) > 0
        
        elif step_name == 'fetch':
            articles = self.data.get('articles_found', [])
            detailed_articles = []
            
            for article in articles:
                url = article.get('link', '')
                full_text = fetch_full_article(url)
                # If we can't get full text, use the snippet
                if not full_text:
                    full_text = article.get('snippet', '')[:1000]
                
                detailed_articles.append({
                    'info': article,
                    'content': full_text
                })
            
            self.data['articles_with_content'] = detailed_articles
            return len(detailed_articles) > 0
        
        elif step_name == 'summarize':
            articles = self.data.get('articles_with_content', [])
            summaries = []
            all_summary_text = []
            
            for article in articles[:6]:  # Limit to 6 articles
                title = article['info'].get('title', 'Untitled')
                link = article['info'].get('link', '')
                content = article['content']
                
                summary = smart_summarize(content)
                summaries.append({
                    'title': title,
                    'link': link,
                    'summary': summary
                })
                all_summary_text.append(summary)
            
            # Create overall summary
            combined_text = " ".join(all_summary_text)
            overall = smart_summarize(combined_text, 200) if combined_text else "No summary available"
            
            self.data['article_summaries'] = summaries
            self.data['big_picture'] = overall
            return True
        
        elif step_name == 'suggest_actions':
            overall = self.data.get('big_picture', '')
            details_text = " ".join([s['summary'] for s in self.data.get('article_summaries', [])])
            combined = overall + " " + details_text
            
            actions = generate_follow_up_ideas(combined, 5)
            self.data['next_steps'] = actions
            return True
        
        elif step_name == 'save':
            return True  # We'll handle saving separately
        
        return False
    
    def _make_text_report(self):
        """Create a plain text version of the report."""
        lines = []
        lines.append(f"RESEARCH REPORT")
        lines.append(f"Topic: {self.goal}")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 50)
        
        lines.append("\nKEY FINDINGS:")
        lines.append(self.data.get('big_picture', 'No summary available'))
        
        lines.append("\nDETAILED SUMMARIES:")
        for i, article in enumerate(self.data.get('article_summaries', []), 1):
            lines.append(f"\n{i}. {article['title']}")
            lines.append(f"   Link: {article['link']}")
            lines.append(f"   Summary: {article['summary']}")
        
        lines.append("\nNEXT RESEARCH STEPS:")
        lines.append(self.data.get('next_steps', 'No suggestions generated'))
        
        lines.append("\nPROCESS LOG:")
        lines.append("\n".join(self.steps_log))
        
        return "\n".join(lines)
    
    def _make_markdown_report(self):
        """Create a markdown version of the report."""
        lines = []
        lines.append(f"# Research Report: {self.goal}")
        lines.append(f"*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")
        
        lines.append("## Executive Summary")
        lines.append(self.data.get('big_picture', 'No summary available'))
        lines.append("")
        
        lines.append("## Detailed Findings")
        for i, article in enumerate(self.data.get('article_summaries', []), 1):
            lines.append(f"### {i}. {article['title']}")
            lines.append(f"[Source]({article['link']})  ")
            lines.append(f"{article['summary']}  ")
            lines.append("")
        
        lines.append("## Recommended Next Steps")
        lines.append(self.data.get('next_steps', 'No suggestions generated'))
        lines.append("")
        
        lines.append("## Research Process")
        lines.append("```")
        lines.append("\n".join(self.steps_log))
        lines.append("```")
        
        return "\n".join(lines)

def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scout_agent.py 'research topic'")
        print("Example: python scout_agent.py 'AI regulation'")
        sys.exit(1)
    
    topic = " ".join(sys.argv[1:])
    agent = ResearchAgent(topic)
    results = agent.run_research()
    
    print(f"\nResearch complete! Check:")
    print(f"  - {results['text']}")
    print(f"  - {results['markdown']}")

if __name__ == "__main__":
    main()
