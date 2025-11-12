"""
SCRIPT: fetcher.py
AUTHOR: Agora News System
VERSION: 1.6 (Final Curated Feeds)
DATE: 2025-11-12
DESCRIPTION: Fetches new articles from the final verified list of RSS feeds
             (Nature, Science, Cell families).
             Uses 'requests' with a User-Agent to bypass anti-bot measures.
"""
__version__ = "1.6"

import feedparser
import time
import argparse
import os
import json
import requests
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

# --- CONFIGURATION ---

# We need to send a "User-Agent" to pretend to be a real browser
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.google.com/'
}

# --- FINAL VERIFIED JOURNAL FEEDS (v1.0) ---
# This list is based on your systematic testing.
JOURNAL_FEEDS = {
    # --- Science Family (Your verified URLs) ---
     "Science": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
     "Science (First Release)": "https://www.science.org/action/showFeed?type=axatoc&feed=rss&jc=science",
   "Science (News)": "https://www.science.org/rss/news_current.xml",
   "Science Signaling": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=signaling",
   "Science Translational Medicine": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=stm",
   "Science Advances": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
   "Science Immunology": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciimmunol",
   "Science Robotics": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=scirobotics",
   
   # --- Nature Family (Standardized URLs) ---
   "Nature": "https://www.nature.com/nature.rss",
   "Nature Communications": "https://www.nature.com/ncomms.rss",
   "Nature Aging": "https://www.nature.com/nataging.rss",
   "Nature Machine Intelligence": "https://www.nature.com/natmachintell.rss",
   "Nature Computational Science": "https://www.nature.com/natcomputsci.rss",
   "Nature Biomedical Engineering": "https://www.nature.com/natbiomedeng.rss",
   "Nature Biotechnology": "https://www.nature.com/nbt.rss",
   "Nature Cancer": "https://www.nature.com/natcancer.rss",
   "Nature Medicine": "https://www.nature.com/nm.rss",
   "Nature Reviews Drug Discovery": "https://www.nature.com/nrd.rss",
   "Nature Ecology & Evolution": "https://www.nature.com/natecolevol.rss",
   "Nature Genetics": "https://www.nature.com/ng.rss",
   "Nature Immunology": "https://www.nature.com/ni.rss",
   "Nature Metabolism": "https://www.nature.com/natmetab.rss",
   "Nature Microbiology": "https://www.nature.com/nmicrobiol.rss",
   "Nature Chemical Biology": "https://www.nature.com/nchembio.rss",
   "Nature Plants": "https://www.nature.com/nplants.rss",
   "Nature Methods": "https://www.nature.com/nmeth.rss",
   "Nature Cell Biology": "https://www.nature.com/ncb.rss",
   "Nature Structural & Molecular Biology": "https://www.nature.com/nsmb.rss",
   "npj Systems Biology & Applications": "https://www.nature.com/npjsba.rss",

    # --- Cell Family (Standardized URLs) ---
    "Cell": "https://www.cell.com/cell/inpress.rss",
    "Trends in Biotechnology": "https://www.cell.com/trends/biotechnology/inpress.rss",
    "Cancer Cell": "https://www.cell.com/cancer-cell/inpress.rss",
    "Developmental Cell": "https://www.cell.com/developmental-cell/inpress.rss",
    "Trends in Ecology & Evolution": "https://www.cell.com/trends/ecology-evolution/inpress.rss",
    "Cell Genomics": "https://www.cell.com/cell-genomics/inpress.rss",
    "American Journal of Human Genetics": "https://www.cell.com/ajhg/inpress.rss",
    "Immunity": "https://www.cell.com/immunity/inpress.rss",
    "Cell Metabolism": "https://www.cell.com/cell-metabolism/inpress.rss",
    "Cell Host & Microbe": "https://www.cell.com/cell-host-microbe/inpress.rss",
    "Cell Stem Cell": "https://www.cell.com/cell-stem-cell/inpress.rss",
    "Stem Cell Reports": "https://www.cell.com/stem-cell-reports/inpress.rss",
    "Structure": "https://www.cell.com/structure/inpress.rss",

    # --- JAMA Network ---
        "JAMA": "https://jamanetwork.com/rss/site_3/onlineFirst_67.xml",

        # --- Lancet ---
        "The Lancet": "https://www.addtoany.com/add_to/feed?linkurl=http%3A%2F%2Fwww.thelancet.com%2Frssfeed%2Flancet_online.xml&type=feed&linkname=The%20Lancet%20Online%20First&linknote=",

        # --- NEJM ---
        "NEJM": "https://www.nejm.org/action/showFeed?jc=nejm&type=etoc&feed=rss",

        # --- Others ---
        "Bioinformatics": "https://academic.oup.com/rss/site_5139/3001.xml",
        "Nucleic Acids Research (NAR)": "https://academic.oup.com/rss/site_5127/3091.xml",
        "Cancer Discovery": "https://aacrjournals.org/rss/site_1000003/1000004.xml",
        "Genes & Development (CSHL)": "https://genesdev.cshlp.org/rss/current.xml",
        "Journal of Experimental Medicine (JEM)": "https://rupress.org/rss/site_1000003/LatestArticles_1000004.xml",
        "PLOS Computational Biology": "https://journals.plos.org/ploscompbiol/feed/atom",
        "Genome Biology": "https://genomebiology.biomedcentral.com/articles/most-recent/rss.xml",
}
# --- END OF UPDATE ---


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
# --- END CONFIGURATION ---


def parse_pubdate(entry):
    """
    Tries to parse the publication date from various possible feed keys.
    Returns a timezone-aware datetime object in UTC.
    """
    date_keys = ['published_parsed', 'updated_parsed']
    for key in date_keys:
        if hasattr(entry, key):
            dt_tuple = getattr(entry, key)
            if dt_tuple:
                try:
                    # feedparser returns a time.struct_time, convert to datetime
                    dt = datetime.fromtimestamp(time.mktime(dt_tuple), timezone.utc)
                    return dt
                except Exception:
                    continue # Try next key
    # Fallback / Error
    return None


def fetcher_agent(days=2, output_filename=None):
    """
    Fetches articles from all journals, filters by date, and saves to JSON.
    """
    print(f"🤖 FetcherAgent v{__version__}: Starting to fetch articles...")
    
    # 1. Setup Date Filter
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
    print(f"   -> Filtering for articles published since {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # 2. Flatten feeds and remove duplicates
    # We just need the unique URLs
    unique_feeds = {}
    for journal_name, url in JOURNAL_FEEDS.items():
        if url not in unique_feeds:
            unique_feeds[url] = journal_name # Keep the first name we see

    print(f"   -> Fetching from {len(unique_feeds)} unique journal feeds...")

    articles = []
    seen_links = set() 

    # 3. Fetch all feeds
    for url, journal_name in unique_feeds.items():
        print(f"   -> Fetching: {journal_name} ({url})")
        
        # --- NEW ROBUST FETCHING ---
        try:
            # 1. Fetch content with requests, using headers
            response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
            response.raise_for_status() # Raise error for bad status (404, 403, 500)
            
            # 2. Parse the downloaded content, not the URL
            feed = feedparser.parse(response.content)
            
        except requests.exceptions.RequestException as e:
            print(f"     ❌ FAILED to fetch: {e}")
            continue
        except Exception as e:
            print(f"     ❌ FAILED: An unexpected error occurred: {e}")
            continue

        if feed.bozo:
            print(f"     ⚠️ Warning: Feed for {journal_name} is malformed. (Is it an RSS feed?)")
            # We still try to parse it, as it might be a partial success
        # --- END NEW FETCHING ---

        print(f"     Found {len(feed.entries)} entries.")
        
        for entry in feed.entries:
            # 4. Filter by Date
            pub_date_utc = parse_pubdate(entry)
            
            if pub_date_utc is None:
                continue
                
            if pub_date_utc < cutoff_date:
                continue 

            # 5. Check for Duplicates
            link = entry.get('link', '')
            if not link or link in seen_links:
                continue
            seen_links.add(link)

            # 6. Store Article Data
            summary = entry.get('summary', 'No summary available.')
            if '<' in summary:
                try:
                    summary = BeautifulSoup(summary, "html.parser").get_text(strip=True)
                except Exception:
                    # If bs4 fails, just use the raw summary
                    pass 
            
            article_data = {
                # Use the unique name from our dict for consistency
                "journal": journal_name, 
                "title": entry.get('title', 'No Title').strip(),
                "link": link,
                "summary": summary.strip(),
                "published_iso": pub_date_utc.isoformat(),
                "published_display": pub_date_utc.strftime("%Y-%m-%d"),
            }
            articles.append(article_data)

    print(f"🤖 FetcherAgent: Found {len(articles)} total articles (after filtering).")
    
    # 7. Save to File
    if not articles:
        print("No new articles found matching the criteria.")
        return

    os.makedirs(DATA_RAW_DIR, exist_ok=True)
    
    if not output_filename:
        today_str = datetime.now().strftime("%Y-%m-%d")
        output_filename = f"{today_str}-raw.json"
        
    output_path = os.path.join(DATA_RAW_DIR, output_filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(articles, f, indent=4, ensure_ascii=False)
        
    print(f"💾 Success! Saved {len(articles)} articles to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"Scientific Article Fetcher (v{__version__})")
    
    parser.add_argument(
        "--days", 
        type=int, 
        default=2,
        help="How many days back to fetch articles (default: 2)"
    )
    parser.add_argument(
        "--output", 
        type=str,
        help="Specific output filename (e.g., my_articles.json)"
    )

    args = parser.parse_args()

    print(f"--- 📰 FetcherAgent v{__version__} Initializing ---")
    
    # We need BeautifulSoup for cleaning summaries, so let's import it
    try:
        import bs4
    except ImportError:
        print("   -> NOTE: `beautifulsoup4` not found. Please run: pip install beautifulsoup4")
        exit(1) # Exit if not installed, as it's important

    start_time = time.time()
    fetcher_agent(days=args.days, output_filename=args.output)
    end_time = time.time()
    
    print(f"--- ✅ FetcherAgent Complete ({end_time - start_time:.2f}s) ---")