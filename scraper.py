"""
SCRIPT: scraper.py
AUTHOR: Agora News System
VERSION: 2.0 (English Logs & Final Fixes)
DATE: 2025-11-12
DESCRIPTION: Reads raw RSS data, filters non-research articles, and enriches
             them with full abstracts/authors IN PARALLEL using asyncio.
             Fixes publication dates by scraping the article page.
             Includes 2-STAGE FILTER (Type Check + Length Check).
             Saves to data/scraped/YYYY-MM-DD-scraped.json.
"""
__version__ = "2.0"

import json
import os
import re
import time
import argparse
import asyncio
import httpx
from bs4 import BeautifulSoup
from dateutil.parser import parse as date_parse
from datetime import timezone

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
DATA_SCRAPED_DIR = os.path.join(BASE_DIR, "data", "scraped")

CONCURRENT_REQUESTS = 10  # Process 10 scrapes at a time
MIN_ABSTRACT_LENGTH = 200 # Minimum abstract length in chars

# Article types to filter out
NON_RESEARCH_TYPES = [
    'news & views', 'news and views', 'commentary', 'editorial', 'news', 
    'correspondence', 'book review', 'obituary', 'retraction', 'correction',
    'perspective', 'world view'
]

SCRAPE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Referer': 'https://www.google.com/'
}
# --- END CONFIGURATION ---

def extract_doi(url):
    """Regex for standard DOI format"""
    doi_match = re.search(r'(10\.\d{4,9}/[-._;()/:a-zA-Z0-9]+)', url)
    if doi_match:
        return doi_match.group(1)
    return None

def get_authors_short(author_list):
    """Returns 'First et al., Last' or 'First & Last'"""
    if not author_list: return "Unknown Authors"
    first_author = author_list[0]
    if len(author_list) == 1: return first_author
    last_author = author_list[-1]
    if len(author_list) == 2: return f"{first_author} & {last_author}"
    return f"{first_author} et al., {last_author}"

def is_likely_research_article(article):
    """
    Heuristic filter to skip news, careers, opinions, etc.
    Returns True if it looks like a primary research article.
    """
    title = article['title'].lower()
    link = article['link'].lower()
    feed_url = article.get('feed_url', '') # Get the feed URL it came from

    # 1. URL Patterns (Strongest indicators)
    if 'nature.com/articles/d41586' in link:
        return False, "Nature News/Feature URL"
    if 'science.org/content/article/' in link:
         return False, "Science News URL"
    # Filter out Science's main "News" feed
    if 'science.org/rss/news_current.xml' in feed_url:
        return False, "Science News Feed"


    # 2. Title Keywords (Skip known non-research formats)
    skip_terms = [
        "author correction", "publisher correction", "retraction note", 
        "obituary:", "q&a:", "news:", "editorial:", "world view:", 
        "career feature", "outlook:", "book review", "comment:", "policy forum",
        "news & views"
    ]
    for term in skip_terms:
        if term in title:
            return False, f"Detected non-research term: '{term}'"

    return True, ""

async def fetch_metadata_api(doi, client):
    """Fetches metadata from Semantic Scholar API (async)"""
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields=title,abstract,authors,year,publicationDate"
    try:
        response = await client.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if not data.get('abstract'): return None
            authors = [a['name'] for a in data.get('authors', [])]
            
            published_date = None
            if data.get('publicationDate'):
                try:
                    published_date = date_parse(data['publicationDate'])
                except:
                    pass 

            return {
                "abstract": data.get('abstract'),
                "authors_full": authors,
                "authors_short": get_authors_short(authors),
                "published_date_obj": published_date,
                "source": "API"
            }
    except Exception as e:
        # print(f"     [!] API Error: {e}") # Uncomment for debugging
        pass
    return None

async def fetch_metadata_scrape(url, client):
    """Scrapes metadata from the article webpage (async)"""
    try:
        response = await client.get(url, headers=SCRAPE_HEADERS, timeout=10, follow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # --- (STAGE 1 FILTER: Check article type) ---
        article_type_meta = soup.find('meta', attrs={'name': 'dc.type'}) or \
                            soup.find('meta', attrs={'property': 'og:type'}) or \
                            soup.find('meta', attrs={'name': 'article:section'})
        
        if article_type_meta and article_type_meta.get('content'):
            article_type = article_type_meta.get('content').lower()
            for non_research_term in NON_RESEARCH_TYPES:
                if non_research_term in article_type:
                    print(f"     [!] Skipping: Article type is '{article_type}'")
                    return None
        
        # --- (STAGE 2 FILTER: Check abstract length) ---
        abstract_meta = soup.find('meta', attrs={'name': 'citation_abstract'}) or \
                        soup.find('meta', attrs={'name': 'dc.description'}) or \
                        soup.find('meta', attrs={'property': 'og:description'})
        abstract = abstract_meta.get('content', '').strip() if abstract_meta else None
        
        if not abstract or len(abstract) < MIN_ABSTRACT_LENGTH:
            print(f"     [!] Skipping: Abstract is missing or too short (Length: {len(abstract or '')})")
            return None
        
        # --- PASSED FILTERS: Get remaining data ---
        author_metas = soup.find_all('meta', attrs={'name': 'citation_author'})
        authors = [m.get('content') for m in author_metas if m.get('content')]
        
        date_meta = soup.find('meta', attrs={'name': 'citation_publication_date'}) or \
                    soup.find('meta', attrs={'name': 'dc.date'})
        
        published_date = None
        if date_meta and date_meta.get('content'):
            try:
                published_date = date_parse(date_meta.get('content'))
            except Exception as e:
                print(f"     [!] Could not parse date: {e}")
        
        if abstract and authors:
             return {
                "abstract": abstract,
                "authors_full": authors,
                "authors_short": get_authors_short(authors),
                "published_date_obj": published_date,
                "source": "Scrape"
            }
    except Exception as e:
        # print(f"     [!] Scrape Error: {e}") # Uncomment for debugging
        pass
    return None

async def process_article(article, api_client, scrape_client, semaphore, pbar):
    """
    Coroutine for processing a single article (Filter -> API -> Scrape)
    """
    async with semaphore:
        try:
            # --- Step 1: Filter (Quick, by title) ---
            is_research, reason = is_likely_research_article(article)
            if not is_research:
                print(f"   ⏭️ Skipping: {article['title'][:30]}... ({reason})")
                pbar.update(1)
                return None

            print(f"   -> Processing: {article['title'][:40]}...")
            
            # --- Step 2: Enrich (Slow, w/ 2-stage filter) ---
            doi = extract_doi(article['link'])
            article['doi'] = doi
            metadata = None
            
            if doi:
                metadata = await fetch_metadata_api(doi, api_client)
                if metadata: 
                    print("      ✅ Found via API")
            
            if not metadata:
                metadata = await fetch_metadata_scrape(article['link'], scrape_client)
                if metadata: 
                    print("      ✅ Found via Direct Scrape")
                else:
                    # Note: 'Skipped' message is printed inside fetch_metadata_scrape
                    pbar.update(1)
                    return None

            # --- Step 3: Update Date & Return ---
            if metadata:
                # --- Date override logic ---
                if metadata.get('published_date_obj'):
                    scraped_date = metadata['published_date_obj']
                    if scraped_date.tzinfo is None:
                        scraped_date = scraped_date.replace(tzinfo=timezone.utc)
                        
                    article['published_iso'] = scraped_date.isoformat()
                    article['published_display'] = scraped_date.strftime("%Y-%m-%d")
                    print(f"      🔄 Date updated to: {article['published_display']}")
                
                # --- BUG FIX: Remove non-serializable object ---
                metadata.pop('published_date_obj', None)
                
                article.update(metadata)
                
                pbar.update(1)
                return article
                
        except Exception as e:
            print(f"   [!] CRITICAL error processing {article['link']}: {e}")
        
        pbar.update(1)
        return None

async def scraper_agent(input_path=None, limit=None):
    if not input_path:
        if not os.path.exists(DATA_RAW_DIR): 
            print("   -> No 'data/raw' folder found. Run fetcher.py first.")
            return
        files = [os.path.join(DATA_RAW_DIR, f) for f in os.listdir(DATA_RAW_DIR) if f.endswith("-raw.json")]
        if not files: 
            print("   -> No raw JSON files found in 'data/raw'.")
            return
        input_path = max(files, key=os.path.getctime)

    print(f"🤖 ScraperAgent v{__version__}: Reading from {os.path.basename(input_path)}")
    with open(input_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    articles_to_process = articles[:limit] if limit else articles
    if not articles_to_process:
        print("   No articles to process. Exiting.")
        return

    print(f"   Scraping {len(articles_to_process)} articles (in parallel batches of {CONCURRENT_REQUESTS})...")

    # TQDM progress bar setup
    try:
        from tqdm.auto import tqdm
        pbar = tqdm(total=len(articles_to_process), desc="   Scraping", unit="article")
    except ImportError:
        print("   (Install 'tqdm' for a nice progress bar: pip install tqdm)")
        class SimplePBar:
            def __init__(self, total, desc, unit):
                self.total = total; self.desc = desc; self.unit = unit; self.count = 0
                print(f"{self.desc}: 0/{self.total} {self.unit}s", end='\r')
            def update(self, n):
                self.count += n
                print(f"{self.desc}: {self.count}/{self.total} {self.unit}s", end='\r')
            def close(self): print()
        pbar = SimplePBar(total=len(articles_to_process), desc="   Scraping", unit="article")

    
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = []

    # Use async clients for parallel requests
    async with httpx.AsyncClient(timeout=10, http2=True) as api_client:
        async with httpx.AsyncClient(headers=SCRAPE_HEADERS, timeout=15, http2=True, follow_redirects=True) as scrape_client:
            for article in articles_to_process:
                # Add the feed URL to the article object for filtering
                article['feed_url'] = article['link'] 
                tasks.append(process_article(article, api_client, scrape_client, semaphore, pbar))
            
            results = await asyncio.gather(*tasks)
    
    pbar.close()
    
    scraped_articles = [res for res in results if res is not None]

    # --- Save Results ---
    os.makedirs(DATA_SCRAPED_DIR, exist_ok=True)
    filename = os.path.basename(input_path).replace("-raw.json", "-scraped.json")
    output_path = os.path.join(DATA_SCRAPED_DIR, filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(scraped_articles, f, indent=4, ensure_ascii=False)

    print(f"\n✨ Success! Saved {len(scraped_articles)} high-quality research articles.")
    print(f"💾 File: {output_path}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Specific raw JSON file")
    parser.add_argument("--limit", type=int, default=None, help="Limit articles to process")
    args = parser.parse_args()
    
    print(f"--- 🕷️ ScraperAgent v{__version__} Initializing ---")
    
    try:
        import dateutil
    except ImportError:
        print("   -> ❌ ERROR: `python-dateutil` not found. Please run: pip install python-dateutil")
        exit(1)
        
    await scraper_agent(input_path=args.file, limit=args.limit)

if __name__ == "__main__":
    asyncio.run(main())