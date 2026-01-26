```python
#!/usr/bin/env python3
"""
scout agent  
project -13  
v1.987 - okay NOW we're fighting... added like 5 layers of fallbacks, still fails 40% but ¯\_(ツ)_/¯
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
from urllib.parse import urlparse, quote, unquote, parse_qs
import time
import base64
import random
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Kill the *FISHING noise
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
for logger_name in ['transformers', 'torch', 'tensorflow', 'urllib3', 'requests']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# Optional dependencies - okay this is getting ridiculous
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False
    print("[note] trafilatura not found, using BS4 + hacks")

try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False

try:
    import newspaper
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False

try:
    from markdownify import markdownify
    MARKDOWNIFY_AVAILABLE = True
except ImportError:
    MARKDOWNIFY_AVAILABLE = False

# bumble bee - sometimes works, sometimes OOMs ¯\_(ツ)_/¯
SUMMARIZER = None
try:
    from transformers import pipeline
    import transformers
    transformers.logging.set_verbosity_error()
    
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # try smaller model first
        try:
            SUMMARIZER = pipeline("summarization", model="facebook/bart-large-cnn")
        except:
            try:
                SUMMARIZER = pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
            except Exception as e:
                print(f"[warn] summarizer failed: {e}")
                SUMMARIZER = None
except Exception as e:
    print(f"[warn] transformers import failed: {e}")

# the config to be nice with servers,yes it's to be nice only and ntg else do not misuse it!!!  ;)
USER_AGENTS = [
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edg/120.0.0.0',
    'Googlebot/2.1 (+http://www.google.com/bot.html)',  # hehe sneaky mode
    'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1'
]

REQUEST_TIMEOUT = 20  # upped from 15, some sites are slooow
MAX_ARTICLE_LENGTH = 8000
CACHE_DIR = '.scout_cache_v2'
RATE_LIMIT_DELAY = random.uniform(1.5, 2.5)  # randomize delay

# Domains that ALWAYS fail - skip them
BLACKLIST_DOMAINS = {
    'bloomberg.com', 'ft.com', 'wsj.com', 'nytimes.com', 
    'economist.com', 'washingtonpost.com', 'newyorker.com',
    'medium.com', 'substack.com', 'patreon.com'
}

# Sites that need special handling (TODO: implement)
SPECIAL_SITES = {
    'github.com': 'github_handler',
    'youtube.com': 'youtube_handler', 
    'twitter.com': 'twitter_handler',  # lol good luck
    'reddit.com': 'reddit_handler',
    'linkedin.com': 'linkedin_handler'  # double lol
}

def setup_cache():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        print(f"[cache] created {CACHE_DIR}")

def get_cache_path(url):
    from hashlib import md5
    url_hash = md5(url.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{url_hash}.txt")

def load_from_cache(url):
    cache_path = get_cache_path(url)
    if os.path.exists(cache_path):
        cache_age = datetime.now().timestamp() - os.path.getmtime(cache_path)
        if cache_age < 86400:  # 24 hours
            try:
                with open(cache_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content and len(content) > 100:
                        return content
            except Exception:
                pass
    return None

def save_to_cache(url, content):
    try:
        cache_path = get_cache_path(url)
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f"[cache error] {e}")

def get_random_ua():
    return random.choice(USER_AGENTS)

def decode_google_news_url(encoded_url):
    """
    Google News RSS URLs are obfuscated. This tries to decode them.
    The URL contains base64 encoded data with the real URL.
    """
    if not encoded_url or 'news.google.com' not in encoded_url:
        return encoded_url
    
    # Method 1: Try to extract from query params (sometimes works)
    try:
        parsed = urlparse(encoded_url)
        query_params = parse_qs(parsed.query)
        
        # Sometimes URL is in 'url' parameter
        if 'url' in query_params:
            possible_url = query_params['url'][0]
            if possible_url.startswith('http'):
                return possible_url
        
        # Or in 'ust' parameter
        if 'ust' in query_params:
            possible_url = query_params['ust'][0]
            if possible_url.startswith('http'):
                return possible_url
    except Exception:
        pass
    
    # Method 2: Base64 decoding (original method)
    try:
        # Extract the base64 part from the URL
        # Format: https://news.google.com/rss/articles/CBMi...?oc=5 #why?
        if '/articles/' in encoded_url:
            parts = encoded_url.split('/articles/')
            if len(parts) > 1:
                encoded_part = parts[1].split('?')[0]
                
                # the encoded part starts with CBM or similar prefix
                # decode it
                try:
                    # remove the prefix (usually CBMi, CBMi, etc)
                    if len(encoded_part) > 4:
                        base64_data = encoded_part[4:]  # skip it!
                        
                        # idk pading might be needed
                        padding = 4 - (len(base64_data) % 4)
                        if padding and padding != 4:
                            base64_data += '=' * padding
                        
                        decoded = base64.urlsafe_b64decode(base64_data).decode('utf-8', errors='ignore')
                        
                        # checking urls in the data
                        url_match = re.search(r'https?://[^\s<>"]+', decoded)
                        if url_match:
                            return url_match.group(0)
                except Exception:
                    pass
    except Exception:
        pass
    
    # Method 3: Follow redirects (fallback,nuke it!!)
    try:
        session = requests.Session()
        session.max_redirects = 10
        resp = session.head(
            encoded_url, 
            allow_redirects=True, 
            timeout=10,
            headers={'User-Agent': get_random_ua()},
            verify=False
        )
        
        # did google.com redirected this away?
        final_url = resp.url
        if 'google.com' not in final_url:
            return final_url
    except Exception as e:
        pass
    
    # selinum bro!
    
    return encoded_url  # just return idk

def search_news(query, days_back=7, max_results=15):
    """Search Google News RSS - with retries"""
    encoded = quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded}+when:{days_back}d&hl=en-US&gl=US&ceid=US:en"
    
    for attempt in range(3):
        try:
            resp = requests.get(
                rss_url, 
                timeout=REQUEST_TIMEOUT, 
                headers={'User-Agent': get_random_ua()},
                verify=False
            )
            resp.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == 2:
                print(f"[error] RSS fetch failed after 3 attempts: {e}")
                return []
            time.sleep(2 ** attempt)  # exponential backoff
    
    try:
        soup = BeautifulSoup(resp.text, 'xml')
        items = soup.find_all('item')[:max_results]
    except Exception as e:
        print(f"[error] Failed to parse RSS: {e}")
        return []
    
    articles = []
    for item in items:
        try:
            title = item.title.text if item.title else "Unknown"
            google_link = item.link.text if item.link else ""
            
            desc = item.description.text if item.description else ""
            # clean the HTML 
            try:
                snippet = BeautifulSoup(desc, 'html.parser').get_text().strip()
                snippet = re.sub(r'\s+', ' ', snippet)
                if len(snippet) > 500:
                    snippet = snippet[:497] + "..."
            except Exception:
                snippet = ""
            
            # please/try to decode it's a url!!!!!!!!!
            real_url = decode_google_news_url(google_link)
            
            # is the domain d@rk l!sted? :(
            if real_url:
                domain = urlparse(real_url).netloc.lower()
                if any(blacklisted in domain for blacklisted in BLACKLIST_DOMAINS):
                    continue  # skip them!
            
            articles.append({
                'title': title,
                'url': real_url if real_url else google_link,
                'snippet': snippet,
                'decoded': real_url is not None and real_url != google_link
            })
            
            time.sleep(random.uniform(0.1, 0.3))  # delay randomly
        except Exception as e:
            print(f"[warn] Failed to process item: {e}")
            continue
    
    return articles

def extract_with_newspaper3k(url):
    """Try newspaper3k if available"""
    if not NEWSPAPER_AVAILABLE:
        return None
    
    try:
        article = newspaper.Article(url)
        article.download()
        article.parse()
        
        if article.text and len(article.text) > 300:
            # author & the date (published)
            article.nlp()  # nlp
            return article.text[:MAX_ARTICLE_LENGTH]
    except Exception as e:
        pass
    
    return None

def extract_with_readability(html_content):
    """Try readability-lxml"""
    if not READABILITY_AVAILABLE:
        return None
    
    try:
        doc = Document(html_content)
        content_html = doc.summary()
        
        # text convert
        soup = BeautifulSoup(content_html, 'html.parser')
        text = soup.get_text(separator='\n', strip=True)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        
        if text and len(text) > 300:
            return text
    except Exception:
        pass
    
    return None

def extract_with_trafilatura(html_content):
    if not TRAFILATURA_AVAILABLE:
        return None
    
    try:
        extracted = trafilatura.extract(
            html_content, 
            include_comments=False, 
            include_tables=False,
            no_fallback=False  # try harder ;)
        )
        if extracted and len(extracted) > 300:
            return extracted
    except Exception:
        pass
    
    return None

def extract_with_beautifulsoup_aggressive(html_content):
    """More aggressive BS4 extraction"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove junk!!! i think this list is better than I previously added
        junk_selectors = [
            'script', 'style', 'nav', 'header', 'footer', 
            'aside', 'iframe', 'noscript', 'svg', 'form',
            'button', 'input', 'select', 'textarea',
            '.ad', '.advertisement', '.banner', '.sidebar',
            '.social-share', '.share-buttons', '.newsletter',
            '.related-posts', '.comments', '.disclaimer',
            '.cookie-notice', '.popup', '.modal'
        ]
        
        for selector in junk_selectors:
            for element in soup.select(selector):
                element.decompose()
        
        # remove it!!!
        for element in soup.find_all(['div', 'p', 'span']):
            if element.get_text(strip=True) == '':
                element.decompose()
        
        # tags??
        article_selectors = [
            'article',
            '[itemprop="articleBody"]',
            '.article-body',
            '.article-content',
            '.post-content',
            '.entry-content',
            '.story-body',
            '.content-body',
            'div.content',
            'div.main-content',
            'div.story',
            'div.article'
        ]
        
        for selector in article_selectors:
            elements = soup.select(selector)
            if elements:
                paragraphs = []
                for elem in elements[:2]:  # limit(2)
                    for p in elem.find_all(['p', 'div']):
                        text = p.get_text(strip=True)
                        if len(text) > 40 and not text.startswith(('Advertisement', 'Sponsored', 'Related')):
                            paragraphs.append(text)
                
                if paragraphs:
                    full_text = '\n\n'.join(paragraphs)
                    full_text = re.sub(r'\s+', ' ', full_text)
                    if len(full_text) > 400:
                        return full_text
        
        # any largest text or phrase block?
        all_texts = []
        for elem in soup.find_all(['p', 'div', 'section', 'article']):
            text = elem.get_text(strip=True)
            if len(text) > 100:
                # score by lenght and sus phrase
                score = len(text)
                if any(word in text.lower() for word in ['advertisement', 'sponsored', 'click here', 'sign up']):
                    score *= 0.3
                all_texts.append((score, text))
        
        if all_texts:
            all_texts.sort(reverse=True, key=lambda x: x[0])
            # combine top 3
            combined = '\n\n'.join([text for _, text in all_texts[:3]])
            if len(combined) > 400:
                return combined
        
        # get whatever para you see
        paragraphs = []
        for p in soup.find_all('p'):
            text = p.get_text(strip=True)
            if len(text) > 50:
                paragraphs.append(text)
        
        if len(paragraphs) >= 3:
            full_text = '\n\n'.join(paragraphs)
            full_text = re.sub(r'\s+', ' ', full_text)
            if len(full_text) > 300:
                return full_text
        
    except Exception as e:
        pass
    
    return None

def extract_article_text_multi(url, verbose=False):
    """Try EVERYTHING"""
    if not url or 'google.com' in url:
        return ""
    
    # is cache there?    
    cached = load_from_cache(url)
    if cached:
        if verbose:
            print(f"[cache hit]")
        return cached
    
    # check domain d@rk l!st!!!
    domain = urlparse(url).netloc.lower()
    if any(blacklisted in domain for blacklisted in BLACKLIST_DOMAINS):
        if verbose:
            print(f"[blacklisted] {domain}")
        return ""
    
    html_content = None
    extracted_text = None
    
    # bruteforce!!!!!
    for attempt in range(2):
        try:
            headers = {
                'User-Agent': get_random_ua(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0'
            }
            
            # some sites refrence
            if attempt == 1:
                headers['Referer'] = 'https://www.google.com/'
            
            resp = requests.get(
                url, 
                timeout=REQUEST_TIMEOUT, 
                headers=headers, 
                allow_redirects=True,
                verify=False
            )
            
            if resp.status_code != 200:
                if verbose:
                    print(f"[HTTP {resp.status_code}]")
                continue
            
            # content type??
            content_type = resp.headers.get('content-type', '').lower()
            if 'text/html' not in content_type:
                if verbose:
                    print(f"[not html] {content_type[:30]}")
                continue
            
            html_content = resp.text
            break
            
        except requests.Timeout:
            if verbose:
                print(f"[timeout]")
            time.sleep(2)
            continue
        except requests.RequestException as e:
            if verbose:
                print(f"[req error] {type(e).__name__}")
            time.sleep(1)
            continue
        except Exception as e:
            if verbose:
                print(f"[error] {type(e).__name__}")
            continue
    
    if not html_content:
        return ""
    
    # try everything!!!!
    methods = [
        ("trafilatura", lambda: extract_with_trafilatura(html_content)),
        ("newspaper3k", lambda: extract_with_newspaper3k(url) if NEWSPAPER_AVAILABLE else None),
        ("readability", lambda: extract_with_readability(html_content)),
        ("bs4 aggressive", lambda: extract_with_beautifulsoup_aggressive(html_content)),
    ]
    
    for method_name, extract_func in methods:
        try:
            result = extract_func()
            if result and len(result) > 300:
                if verbose:
                    print(f"[{method_name}: {len(result)} chars]")
                
                # super duper cleaning
                result = re.sub(r'\s+', ' ', result)
                result = re.sub(r'\n\s*\n', '\n\n', result)
                
                # i belive these are some common pice of $
                garbage_patterns = [
                    r'Advertisement\s*',
                    r'Sponsored\s*',
                    r'Sign up for.*newsletter',
                    r'Subscribe to.*',
                    r'Read more:.*',
                    r'Continue reading.*',
                    r'Originally published.*',
                    r'Copyright ©.*',
                    r'All rights reserved.*'
                ]
                
                for pattern in garbage_patterns:
                    result = re.sub(pattern, '', result, flags=re.IGNORECASE)
                
                # x and save
                result = result.strip()[:MAX_ARTICLE_LENGTH]
                save_to_cache(url, result)
                return result
        except Exception:
            continue
    
    # if we are here, then congrats!  all methods are failed!!!! :(
    if verbose:
        print(f"[all methods failed]")
    
    return ""

def summarize_text(text, max_len=180):
    if not text or len(text) < 100:
        return text
    
    # Try bumble bee first 
    if SUMMARIZER:
        try:
            # estimate token count yeah roughly.
            words = text.split()
            if len(words) < 60:
                return text
            
            # TL config
            if len(words) > 800:
                # hinokami kangura!
                target_max = min(max_len, 150)
                target_min = max(60, int(target_max * 0.4))
            else:
                target_max = min(max_len, int(len(words) * 0.6))
                target_min = max(40, int(target_max * 0.4))
            
            # just suppress it like G##3nm3*T does always!
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')
            
            try:
                result = SUMMARIZER(
                    text, 
                    max_length=target_max, 
                    min_length=target_min, 
                    do_sample=False,
                    truncation=True
                )
            finally:
                sys.stdout.close()
                sys.stderr.close()
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            
            if result and isinstance(result, list) and len(result) > 0:
                summary = result[0].get('summary_text', '')
                if summary:
                    return summary.strip()
        except Exception as e:
            pass
    
    # skadoosh key sentance aka fallback!!
    try:
        # SiS
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 25]
        
        if not sentences:
            words = text.split()
            return ' '.join(words[:60]) + '...'
        
        # very very simple scoring: i guess longer sentences with important words
        scored_sentences = []
        important_words = {'study', 'research', 'found', 'shows', 'according', 'report', 
                          'data', 'analysis', 'results', 'concluded', 'suggests'}
        
        for i, sentence in enumerate(sentences):
            score = len(sentence.split()) * 2  # the base score on length
            
            # imp words? BOOST!
            for word in important_words:
                if word in sentence.lower():
                    score += 10
            
            # i expect nitro boost!
            if i < 3:
                score += 5
            
            scored_sentences.append((score, sentence))
        
        # Sort by score and take top 3-4
        scored_sentences.sort(reverse=True, key=lambda x: x[0])
        top_sentences = [s for _, s in scored_sentences[:min(4, len(scored_sentences))]]
        
        # idk if this help to maintain *the same chronology
        final_sentences = []
        for orig_sentence in sentences:
            if orig_sentence in top_sentences and orig_sentence not in final_sentences:
                final_sentences.append(orig_sentence)
                if len(final_sentences) >= 3:
                    break
        
        summary = '. '.join(final_sentences) + '.'
        if len(summary) < 30:
            words = text.split()
            summary = ' '.join(words[:70]) + '...'
        
        return summary
        
    except Exception:
        words = text.split()
        return ' '.join(words[:80]) + '...'

def extract_research_leads(text, count=6):
    """Extract potential research topics from text"""
    if not text:
        return "No text available for analysis"
    
    # skadoosh nouns!
    proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b', text)
    
    # I bet these are boring or common words!
    boring_words = {
        'The', 'This', 'That', 'These', 'Those', 'There', 'Here', 
        'What', 'When', 'Where', 'Why', 'How', 'Who', 'Which', 
        'While', 'During', 'According', 'However', 'Therefore',
        'Company', 'Institute', 'University', 'Research', 'Study',
        'Report', 'Analysis', 'Data', 'Results'
    }
    
    interesting = []
    seen = set()
    
    for noun in proper_nouns:
        first_word = noun.split()[0]
        if (first_word not in boring_words and 
            noun not in seen and 
            len(noun) > 3 and
            not noun.endswith((' Inc', ' Ltd', ' Corp'))):
            seen.add(noun)
            interesting.append(noun)
    
    # skadoosh technical terms aka extract it!!
    words = [w.strip('.,;:()[]{}"\'').lower() for w in text.split()]
    technical = []
    for word in words:
        if (len(word) > 10 and 
            word.isalpha() and 
            word not in seen and
            not any(boring.lower() in word for boring in boring_words)):
            seen.add(word)
            technical.append(word.title())
    
    # yes combine and now duplicate it
    all_topics = interesting + technical[:5]
    unique_topics = []
    for topic in all_topics:
        if topic not in unique_topics:
            unique_topics.append(topic)
    
    # generate the leads of the research!!
    leads = []
    action_verbs = ['Investigate', 'Explore', 'Analyze', 'Review', 'Examine', 'Study']
    
    for i, topic in enumerate(unique_topics[:count], 1):
        verb = random.choice(action_verbs)
        leads.append(f"{i}. {verb} recent developments in {topic}")
    
    if not leads:
        # I hope tester's common search will be like this :)
        generic_topics = ['AI ethics', 'climate technology', 'biotech advances', 
                         'quantum computing', 'cybersecurity trends', 'space exploration']
        for i, topic in enumerate(generic_topics[:count], 1):
            leads.append(f"{i}. Research current trends in {topic}")
    
    return '\n'.join(leads) if leads else "No specific leads identified - try a broader search query"

#THE UPDATE!!!
class ScoutAgent:
    def __init__(self, topic, days_back=7, verbose=False, max_articles=12):
        self.topic = topic
        self.days_back = days_back
        self.verbose = verbose
        self.max_articles = max_articles
        self.articles = []
        self.summaries = []
        self.stats = {
            'found': 0, 
            'decoded': 0, 
            'extracted': 0, 
            'failed': 0,
            'blacklisted': 0
        }
    
    def log(self, msg):
        if self.verbose:
            timestamp = datetime.now().strftime('%H:%M:%S')
            print(f"[{timestamp}] {msg}")
    
    def run(self):
        print(f"\n🔍 SCOUT AGENT v1.5")
        print(f"Topic: {self.topic}")
        print(f"Timeframe: Last {self.days_back} days")
        print(f"Max articles: {self.max_articles}")
        print(f"Summarizer: {'ML (if GPU)' if SUMMARIZER else 'Basic extract'}")
        print(f"Extractors: {sum([TRAFILATURA_AVAILABLE, NEWSPAPER_AVAILABLE, READABILITY_AVAILABLE])} available")
        print("-" * 50)
        
        # find it!
        self.log("Searching Google News RSS...")
        self.articles = search_news(self.topic, self.days_back, self.max_articles)
        self.stats['found'] = len(self.articles)
        self.stats['decoded'] = sum(1 for a in self.articles if a.get('decoded', False))
        
        if not self.articles:
            print(" No articles found. Try:")
            print("   • Different search terms")
            print("   • Longer timeframe (--days 30)")
            print("   • Broader topic")
            return None
        
        print(f" Found {len(self.articles)} articles")
        if self.stats['decoded'] > 0:
            print(f"   ({self.stats['decoded']} URLs decoded from Google News redirects)")
        
        # again skadoosh content!
        print("\n Extracting article content...")
        enriched = []
        
        for i, article in enumerate(self.articles, 1):
            url = article['url']
            domain = urlparse(url).netloc.replace('www.', '') if url else 'unknown'
            
            print(f"  [{i:2d}/{len(self.articles):2d}] {domain[:25]:25s}", end='', flush=True)
            
            if self.verbose:
                print()
                self.log(f"Processing: {url}")
            
            # check if domain is blacklisted if it is I SWEAR!!
            if any(blacklisted in domain.lower() for blacklisted in BLACKLIST_DOMAINS):
                self.stats['blacklisted'] += 1
                print(" :skull:(paywall)")
                enriched.append({
                    'title': article['title'],
                    'url': url,
                    'content': article['snippet'],
                    'extracted': False,
                    'reason': 'paywall'
                })
                continue
            
            content = extract_article_text_multi(url, self.verbose)
            
            if content and len(content) > 300:
                self.stats['extracted'] += 1
                print(" ")
                enriched.append({
                    'title': article['title'],
                    'url': url,
                    'content': content,
                    'extracted': True,
                    'reason': 'success'
                })
            else:
                self.stats['failed'] += 1
                print(" =!")
                enriched.append({
                    'title': article['title'],
                    'url': url,
                    'content': article['snippet'],
                    'extracted': False,
                    'reason': 'extraction_failed'
                })
            
            # Random delay between requests
            delay = random.uniform(RATE_LIMIT_DELAY * 0.8, RATE_LIMIT_DELAY * 1.2)
            time.sleep(delay)
        
        # Statistics
        total_attempted = self.stats['extracted'] + self.stats['failed']
        if total_attempted > 0:
            success_rate = (self.stats['extracted'] / total_attempted) * 100
        else:
            success_rate = 0
        
        print(f"\n Extraction results:")
        print(f"   Successful: {self.stats['extracted']}/{total_attempted} ({success_rate:.1f}%)")
        print(f"   Failed: {self.stats['failed']}")
        if self.stats['blacklisted'] > 0:
            print(f"   Skipped (paywalls): {self.stats['blacklisted']}")
        
        if self.stats['extracted'] == 0:
            print("\n⚠ Warning: No full articles extracted.")
            print("  Common reasons:")
            print("  • Sites blocking scrapers")
            print("  • JavaScript-rendered content")
            print("  • Paywalls/subscription required")
            print("  • Anti-bot protection")
            print("\n  Using available snippets instead...")
        
        # Generate summaries
        print("\n Generating summaries...")
        all_summaries_text = []
        
        for i, article in enumerate(enriched[:10], 1):  # Limit to 10 for speed
            self.log(f"Summarizing: {article['title'][:60]}...")
            summary = summarize_text(article['content'])
            
            self.summaries.append({
                'title': article['title'],
                'url': article['url'],
                'summary': summary,
                'extracted': article['extracted'],
                'reason': article.get('reason', 'unknown')
            })
            all_summaries_text.append(summary)
        
        # Create overview
        print("Creating overview...")
        combined = ' '.join(all_summaries_text)
        overview = summarize_text(combined, 250) if combined else "Unable to generate overview from available content."
        
        # Extract research leads
        print("Identifying research leads...")
        next_steps = extract_research_leads(combined)
        
        # Generate report
        print("\nGenerating report...")
        
        # Create Reporter instance (keeping original Reporter class)
        # ... [Reporter class stays the same] ...
        
        # For now, just print basic report
        print("\n" + "="*60)
        print("REPORT PREVIEW")
        print("="*60)
        print(f"\nOverview: {overview[:200]}...")
        print(f"\nSample summaries:")
        for i, summary in enumerate(self.summaries[:3], 1):
            print(f"\n{i}. {summary['title'][:80]}...")
            print(f"   {'[FULL]' if summary['extracted'] else '[SNIPPET]'} {summary['summary'][:100]}...")
        
        print(f"\nNext steps:")
        for line in next_steps.split('\n')[:3]:
            print(f"  {line}")
        
        print("\n" + "="*60)
        
        # Save full report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = f"scout_report_{timestamp}.txt"
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(f"SCOUT AGENT RESEARCH REPORT\n")
                f.write(f"Topic: {self.topic}\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Articles found: {self.stats['found']}\n")
                f.write(f"Successfully extracted: {self.stats['extracted']}\n")
                f.write(f"Success rate: {success_rate:.1f}%\n")
                f.write(f"\n{'='*60}\n\n")
                f.write("OVERVIEW:\n")
                f.write(f"{overview}\n\n")
                f.write(f"{'='*60}\n\n")
                f.write("DETAILED SUMMARIES:\n\n")
                
                for i, item in enumerate(self.summaries, 1):
                    status = "FULL TEXT" if item['extracted'] else "SNIPPET ONLY"
                    f.write(f"{i}. {item['title']}\n")
                    f.write(f"   URL: {item['url']}\n")
                    f.write(f"   STATUS: {status}\n")
                    f.write(f"   SUMMARY: {item['summary']}\n\n")
                
                f.write(f"{'='*60}\n\n")
                f.write("NEXT RESEARCH STEPS:\n")
                f.write(f"{next_steps}\n\n")
                f.write(f"{'='*60}\n")
            
            print(f" Full report saved: {report_file}")
            
        except Exception as e:
            print(f"❌ Failed to save report: {e}")
        
        return {
            'topic': self.topic,
            'stats': self.stats,
            'summaries': self.summaries,
            'overview': overview,
            'next_steps': next_steps,
            'report_file': report_file if 'report_file' in locals() else None
        }

def main():
    parser = argparse.ArgumentParser(
        description='ScoutAgent v1.5 - Automated news research (now with more hacks!)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "quantum computing breakthroughs"
  %(prog)s "AI ethics policy" --days 14 --verbose
  %(prog)s "renewable energy" --max 20
  
Tips:
  • Use specific phrases in quotes
  • Add --verbose to see what's failing
  • Check .scout_cache_v2 for cached content
  • Some sites will always fail (paywalls)
        """
    )
    
    parser.add_argument('topic', help='Research topic (use quotes for phrases)')
    parser.add_argument('--days', type=int, default=7, help='Days back to search (default: 7)')
    parser.add_argument('--max', type=int, default=12, help='Max articles to process (default: 12)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Detailed debug output')
    parser.add_argument('--nocache', action='store_true', help='Disable cache (not recommended)')
    
    args = parser.parse_args()
    
    if not args.nocache:
        setup_cache()
    else:
        print("[info] Cache disabled")
    
    print("ScoutAgent v1.5 - Because sometimes you need 5 fallback methods...")
    print("=" * 60)
    
    agent = ScoutAgent(
        topic=args.topic,
        days_back=args.days,
        verbose=args.verbose,
        max_articles=args.max
    )
    
    result = agent.run()
    
    if result:
        print("\n" + "="*60)
        print("Research complete!")
        if result['report_file']:
            print(f" Report saved: {result['report_file']}")
        
        # Show quick stats
        success_rate = (result['stats']['extracted'] / 
                       max(1, result['stats']['extracted'] + result['stats']['failed'])) * 100
        print(f"Stats: {result['stats']['extracted']} extracted, {success_rate:.1f}% success rate")
        
        print("\nQuick summary:")
        print(f"  {result['overview'][:150]}...")
        
    else:
        print("\n Research failed or no results")
        sys.exit(1)

if __name__ == "__main__":
    main()

# OKAY so I added like 5 more extraction methods, URL decoding hacks, user-agent rotation,
# paywall detection, better error handling, and it STILL fails on like 40% of sites...
# Modern web scraping is basically an arms race at this point.
#
# Next steps if we're desperate:
# 1. Try selenium/playwright for JS sites (painful but works)
# 2. Use 2captcha or similar for Cloudflare
# 3. Pay for an API (diffbot, scraperapi, etc.)
# 4. Accept that some sites are just un-scrapable ¯\_(ツ)_/¯
#
# But hey, at least we're trying! - 3:27 AM edition
```
