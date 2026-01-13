#!/usr/bin/env python3
"""
ScoutAgent - News research automation tool
Author: github.com/Aranya-Marjara

Crawls recent news, extracts actual content, and generates research reports.
Actually reads the articles, not just headlines.

Usage:
    ./scout_agent.py "your topic here"
    ./scout_agent.py "AI policy changes" --days 14
"""

import warnings
import logging
import argparse
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re
import os
import sys
import json
from urllib.parse import urlparse, quote, unquote
import time
import base64

# Kill the *FISHING noise
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
for logger_name in ['transformers', 'torch', 'tensorflow']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# Optional dependencies
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

try:
    from transformers import pipeline
    import transformers
    transformers.logging.set_verbosity_error()
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        SUMMARIZER = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
except Exception:
    SUMMARIZER = None

# Config
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
REQUEST_TIMEOUT = 15
MAX_ARTICLE_LENGTH = 6000
CACHE_DIR = '.scout_cache'
RATE_LIMIT_DELAY = 0.8

def setup_cache():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def get_cache_path(url):
    from hashlib import md5
    url_hash = md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{url_hash}.txt")

def load_from_cache(url):
    cache_path = get_cache_path(url)
    if os.path.exists(cache_path):
        if (datetime.now().timestamp() - os.path.getmtime(cache_path)) < 86400:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return f.read()
    return None

def save_to_cache(url, content):
    cache_path = get_cache_path(url)
    with open(cache_path, 'w', encoding='utf-8') as f:
        f.write(content)

def resolve_google_news_url(google_url):
    """
    Follows Google News RSS redirect URLs to get the actual article URL.
    Returns the original URL if it’s not a Google News link.
    """
    if not google_url or 'google.com' not in google_url:
        return google_url

    try:
        resp = requests.get(
            google_url,
            allow_redirects=True,
            timeout=10,
            headers={'User-Agent': USER_AGENT}
        )
        return resp.url
    except Exception:
        return None


def decode_google_news_url(encoded_url):
    """
    Google News RSS URLs are obfuscated. This tries to decode them.
    The URL contains base64 encoded data with the real URL.
    """
    if not encoded_url or 'news.google.com' not in encoded_url:
        return encoded_url
    
    try:
        # Extract the base64 part from the URL
        # Format: https://news.google.com/rss/articles/CBMi...?oc=5
        if '/articles/' in encoded_url:
            parts = encoded_url.split('/articles/')
            if len(parts) > 1:
                encoded_part = parts[1].split('?')[0]
                
                # The encoded part starts with CBM or similar prefix
                # Try to decode it
                try:
                    # Remove the prefix (usually CBMi, CBMi, etc)
                    if len(encoded_part) > 4:
                        base64_data = encoded_part[4:]  # Skip prefix
                        
                        # Add padding if needed
                        padding = 4 - (len(base64_data) % 4)
                        if padding and padding != 4:
                            base64_data += '=' * padding
                        
                        decoded = base64.urlsafe_b64decode(base64_data).decode('utf-8', errors='ignore')
                        
                        # Look for URLs in the decoded data
                        url_match = re.search(r'https?://[^\s<>"]+', decoded)
                        if url_match:
                            return url_match.group(0)
                except Exception:
                    pass
        
        # Fallback: try to follow the redirect
        try:
            session = requests.Session()
            session.max_redirects = 10
            resp = session.head(encoded_url, allow_redirects=True, timeout=10,
                              headers={'User-Agent': USER_AGENT})
            
            # Check if we got redirected away from google.com
            if 'google.com' not in resp.url:
                return resp.url
        except Exception:
            pass
            
    except Exception:
        pass
    
    return None

def search_news(query, days_back=7, max_results=12):
    """Search Google News RSS"""
    encoded = quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded}+when:{days_back}d&hl=en-US&gl=US&ceid=US:en"
    
    try:
        resp = requests.get(rss_url, timeout=REQUEST_TIMEOUT, headers={'User-Agent': USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"RSS fetch failed: {e}")
        return []
    
    soup = BeautifulSoup(resp.text, 'xml')
    items = soup.find_all('item')[:max_results]
    
    articles = []
    for item in items:
        title = item.title.text if item.title else "Unknown"
        google_link = item.link.text if item.link else ""
        
        desc = item.description.text if item.description else ""
        snippet = BeautifulSoup(desc, 'html.parser').get_text().strip()
        
        # Try to decode the Google News URL
        real_url = decode_google_news_url(google_link)
        
        articles.append({
            'title': title,
            'url': real_url if real_url else google_link,
            'snippet': snippet,
            'decoded': real_url is not None
        })
        
        time.sleep(0.1)
    
    return articles

def extract_with_trafilatura(html_content):
    if not TRAFILATURA_AVAILABLE:
        return None
    
    try:
        extracted = trafilatura.extract(html_content, include_comments=False, 
                                       include_tables=False)
        if extracted and len(extracted) > 300:
            return extracted
    except Exception:
        pass
    return None

def extract_with_beautifulsoup(html_content):
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove junk
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 
                            'aside', 'iframe', 'noscript', 'svg']):
            element.decompose()
        
        # Try common article containers
        article_containers = soup.find_all(['article', 'div'], 
                                          class_=re.compile(r'article|content|post|entry|story', re.I))
        
        if article_containers:
            paragraphs = []
            for container in article_containers[:3]:
                for p in container.find_all('p'):
                    text = p.get_text().strip()
                    if len(text) > 50:
                        paragraphs.append(text)
            
            if paragraphs:
                full_text = '\n\n'.join(paragraphs)
                full_text = re.sub(r'\s+', ' ', full_text)
                return full_text
        
        # Fallback: all paragraphs
        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text().strip()
            if len(text) > 50:
                paragraphs.append(text)
        
        if len(paragraphs) > 2:
            full_text = '\n\n'.join(paragraphs)
            full_text = re.sub(r'\s+', ' ', full_text)
            return full_text
        
    except Exception:
        pass
    
    return None

def extract_article_text(url, verbose=False):
    if not url or 'google.com' in url:
        return ""
    
    cached = load_from_cache(url)
    if cached:
        if verbose:
            print(f"    [cache]")
        return cached
    
    try:
        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers, allow_redirects=True)
        
        if resp.status_code != 200:
            if verbose:
                print(f"    [HTTP {resp.status_code}]")
            return ""
        
        html_content = resp.content
        
        # Try trafilatura
        extracted = extract_with_trafilatura(html_content)
        if extracted:
            if verbose:
                print(f"    [trafilatura: {len(extracted)} chars]")
            save_to_cache(url, extracted)
            return extracted[:MAX_ARTICLE_LENGTH]
        
        # Try BeautifulSoup
        extracted = extract_with_beautifulsoup(html_content)
        if extracted and len(extracted) > 300:
            if verbose:
                print(f"    [bs4: {len(extracted)} chars]")
            save_to_cache(url, extracted)
            return extracted[:MAX_ARTICLE_LENGTH]
        
        if verbose:
            print(f"    [too short]")
        
    except requests.Timeout:
        if verbose:
            print(f"    [timeout]")
    except requests.RequestException as e:
        if verbose:
            print(f"    [{type(e).__name__}]")
    except Exception as e:
        if verbose:
            print(f"    [error: {type(e).__name__}]")
    
    return ""

def summarize_text(text, max_len=150):
    if not text or len(text) < 100:
        return text
    
    if SUMMARIZER:
        try:
            words = text.split()
            word_count = len(words)
            
            if word_count < 50:
                return text
            
            target_max = min(max_len, int(word_count * 0.5))
            target_min = max(30, int(target_max * 0.4))
            
            if target_max > word_count:
                target_max = word_count - 10
                target_min = max(20, int(target_max * 0.5))
            
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = open(os.devnull, 'w')
            
            try:
                result = SUMMARIZER(text, max_length=target_max, min_length=target_min, do_sample=False)
            finally:
                sys.stdout.close()
                sys.stderr.close()
                sys.stdout, sys.stderr = old_stdout, old_stderr
            
            if result and isinstance(result, list) and len(result) > 0:
                summary = result[0].get('summary_text', '')
                if summary:
                    return summary.strip()
        
        except Exception:
            pass
    
    # Manual fallback
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if len(s.strip()) > 20]
    
    if not sentences:
        words = text.split()
        return ' '.join(words[:50]) + '...'
    
    return '. '.join(sentences[:3]) + '.'

def extract_research_leads(text, count=5):
    proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b', text)
    
    boring_words = {'The', 'This', 'That', 'These', 'Those', 'There', 'Here', 'What', 
                    'When', 'Where', 'Why', 'How', 'Who', 'Which', 'While', 'During',
                    'Baker', 'Services', 'Law', 'Monitor', 'Legal', 'Federal', 'National'}
    
    interesting = []
    seen = set()
    
    for noun in proper_nouns:
        first_word = noun.split()[0]
        if first_word not in boring_words and noun not in seen and len(noun) > 3:
            seen.add(noun)
            interesting.append(noun)
    
    # Also look for technical terms
    if len(interesting) < count:
        words = [w.strip('.,;:') for w in text.split()]
        technical = [w for w in words if len(w) > 8 and w[0].islower() and w.isalnum()]
        for word in technical:
            if word not in seen and len(interesting) < count * 2:
                seen.add(word)
                interesting.append(word)
    
    leads = []
    for i, topic in enumerate(interesting[:count], 1):
        leads.append(f"{i}. Investigate recent developments in {topic}")
    
    return '\n'.join(leads) if leads else "No specific leads identified - try broader search"

class Reporter:
    def __init__(self, topic, articles, summaries, overview, next_steps, stats):
        self.topic = topic
        self.articles = articles
        self.summaries = summaries
        self.overview = overview
        self.next_steps = next_steps
        self.stats = stats
    
    def as_text(self):
        lines = [
            "=" * 70,
            f"SCOUT AGENT RESEARCH REPORT",
            f"Topic: {self.topic}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 70,
            "",
            "OVERVIEW:",
            self.overview,
            "",
            "=" * 70,
            "ARTICLE SUMMARIES:",
            ""
        ]
        
        for i, item in enumerate(self.summaries, 1):
            status = "✓ Full text" if item['extracted'] else "⚠ Snippet only"
            lines.extend([
                f"{i}. {item['title']}",
                f"   URL: {item['url']}",
                f"   Status: {status}",
                "",
                f"   {item['summary']}",
                ""
            ])
        
        extraction_rate = (self.stats['extracted']/self.stats['found']*100) if self.stats['found'] > 0 else 0
        
        lines.extend([
            "=" * 70,
            "NEXT RESEARCH STEPS:",
            self.next_steps,
            "",
            "=" * 70,
            "STATISTICS:",
            f"Articles found: {self.stats['found']}",
            f"URLs decoded: {self.stats['decoded']}",
            f"Full text extracted: {self.stats['extracted']}",
            f"Using snippets: {self.stats['failed']}",
            f"Extraction rate: {extraction_rate:.1f}%",
            "=" * 70
        ])
        
        return '\n'.join(lines)
    
    def as_markdown(self):
        lines = [
            f"# Research Report: {self.topic}",
            f"*Generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}*",
            "",
            "## Executive Summary",
            "",
            self.overview,
            "",
            "## Detailed Analysis",
            ""
        ]
        
        for i, item in enumerate(self.summaries, 1):
            status = "✓ Full text" if item['extracted'] else "⚠ Snippet only"
            domain = urlparse(item['url']).netloc.replace('www.', '')
            lines.extend([
                f"### {i}. {item['title']}",
                f"**Source:** [{domain}]({item['url']}) • {status}",
                "",
                item['summary'],
                ""
            ])
        
        extraction_rate = (self.stats['extracted']/self.stats['found']*100) if self.stats['found'] > 0 else 0
        
        lines.extend([
            "## Recommended Next Steps",
            "",
            self.next_steps,
            "",
            "---",
            "",
            f"**Stats:** {self.stats['extracted']}/{self.stats['found']} extracted ({extraction_rate:.1f}%) • {self.stats['decoded']} URLs decoded"
        ])
        
        return '\n'.join(lines)
    
    def save(self, format='both'):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        base_name = f"scout_report_{timestamp}"
        
        saved = []
        
        if format in ['text', 'both']:
            txt_path = f"{base_name}.txt"
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(self.as_text())
            saved.append(os.path.abspath(txt_path))
        
        if format in ['markdown', 'both']:
            md_path = f"{base_name}.md"
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(self.as_markdown())
            saved.append(os.path.abspath(md_path))
        
        return saved

class ScoutAgent:
    def __init__(self, topic, days_back=7, verbose=False):
        self.topic = topic
        self.days_back = days_back
        self.verbose = verbose
        self.articles = []
        self.summaries = []
        self.stats = {'found': 0, 'decoded': 0, 'extracted': 0, 'failed': 0}
    
    def log(self, msg):
        if self.verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    
    def run(self):
        print(f"Researching: {self.topic}")
        print(f"Timeframe: Last {self.days_back} days")
        print(f"Summarizer: {'ML-powered' if SUMMARIZER else 'Basic extraction'}")
        print(f"Extractor: {'Trafilatura' if TRAFILATURA_AVAILABLE else 'BeautifulSoup'}")
        print()
        
        # Search
        self.log("Searching Google News...")
        self.articles = search_news(self.topic, self.days_back)
        self.stats['found'] = len(self.articles)
        self.stats['decoded'] = sum(1 for a in self.articles if a.get('decoded'))
        
        if not self.articles:
            print("No articles found. Try different terms or longer timeframe.")
            return None
        
        print(f"Found {len(self.articles)} articles")
        print(f"Decoded {self.stats['decoded']} Google News URLs")
        
        # Extract content
        print("\nExtracting article content...")
        enriched = []
        
        for i, article in enumerate(self.articles, 1):
            url = article['url']
            domain = urlparse(url).netloc.replace('www.', '') if url else 'unknown'
            print(f"  [{i}/{len(self.articles)}] {domain[:30]}", end='')
            
            if self.verbose:
                print()
                self.log(f"URL: {url}")
            
            content = extract_article_text(url, self.verbose)
            
            if content:
                self.stats['extracted'] += 1
                print(" ✓")
                enriched.append({
                    'title': article['title'],
                    'url': url,
                    'content': content,
                    'extracted': True
                })
            else:
                self.stats['failed'] += 1
                print(" ✗")
                enriched.append({
                    'title': article['title'],
                    'url': url,
                    'content': article['snippet'],
                    'extracted': False
                })
            
            time.sleep(RATE_LIMIT_DELAY)
        
        extraction_rate = (self.stats['extracted']/self.stats['found']*100) if self.stats['found'] > 0 else 0
        print(f"\nExtraction: {self.stats['extracted']}/{self.stats['found']} ({extraction_rate:.1f}%)")
        
        if self.stats['extracted'] == 0:
            print("⚠ No full articles extracted. Using snippets.")
            print("  (Sites may be blocking scrapers or using paywalls)")
        
        # Summarize
        print("\nGenerating summaries...")
        all_summaries_text = []
        
        for article in enriched[:8]:
            self.log(f"Summarizing: {article['title'][:50]}...")
            summary = summarize_text(article['content'])
            
            self.summaries.append({
                'title': article['title'],
                'url': article['url'],
                'summary': summary,
                'extracted': article['extracted']
            })
            all_summaries_text.append(summary)
        
        # Overview
        print("Creating overview...")
        combined = ' '.join(all_summaries_text)
        overview = summarize_text(combined, 250) if combined else "Unable to generate overview"
        
        # Next steps
        print("Identifying research leads...")
        next_steps = extract_research_leads(combined)
        
        # Report
        print("\nGenerating report...")
        reporter = Reporter(
            self.topic,
            self.articles,
            self.summaries,
            overview,
            next_steps,
            self.stats
        )
        
        saved_files = reporter.save()
        
        print("\nReport saved:")
        for path in saved_files:
            print(f"  {path}")
        
        return reporter

def main():
    parser = argparse.ArgumentParser(
        description='ScoutAgent - Automated news research',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "quantum computing"
  %(prog)s "climate policy" --days 14
  %(prog)s "cybersecurity" --verbose
        """
    )
    
    parser.add_argument('topic', help='Research topic')
    parser.add_argument('--days', type=int, default=7, help='Days back (default: 7)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Detailed output')
    
    args = parser.parse_args()
    
    setup_cache()
    
    agent = ScoutAgent(args.topic, args.days, args.verbose)
    result = agent.run()
    
    if result:
        print("\n✓ Research complete!")
    else:
        print("\n✗ Research failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
#Hell yeah it cannot extract now "snippet only!" lol I wil try to fix it in future, if you can please fix it :)
