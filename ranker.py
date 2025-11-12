"""
SCRIPT: ranker.py
AUTHOR: Agora News System
VERSION: 1.3 (Parallel Scoring + Smart Skip)
DATE: 2025-11-12
DESCRIPTION: Reads analyzed data, groups by label.
             If label has > 10 articles, uses parallel AI calls to score them.
             Sorts all labels and saves to data/ranked/
"""
__version__ = "1.3"

import json
import os
import time
import argparse
import asyncio
import httpx
from dotenv import load_dotenv
from openai import OpenAI
from collections import defaultdict

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("AI_API_KEY")
BASE_URL = os.getenv("AI_BASE_URL")

if not API_KEY or not BASE_URL:
    print("⚠️ ERROR: Please ensure AI_API_KEY and AI_BASE_URL are set in your .env file")
    exit(1)

client = httpx.AsyncClient(
    base_url=BASE_URL,
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=30.0
)
MODEL_NAME = "gemini-2.5-flash"
CONCURRENT_REQUESTS = 10  # Score 10 articles at a time
REPORT_LIMIT = 10         # The "Top N" to keep for the report

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_ANALYZED_DIR = os.path.join(BASE_DIR, "data", "analyzed")
DATA_RANKED_DIR = os.path.join(BASE_DIR, "data", "ranked")

# Journal weights for basic sorting
JOURNAL_WEIGHTS = defaultdict(lambda: 1.0, {
    "Nature": 1.5,
    "Science": 1.5,
    "Cell": 1.5,
    "The Lancet": 1.5,
    "NEJM": 1.5,
    "Nature Medicine": 1.2,
    "Nature Biotechnology": 1.2,
    "Nature Genetics": 1.2,
    "Nature Machine Intelligence": 1.2,
    "Cancer Cell": 1.2,
})

def get_journal_score(article):
    return JOURNAL_WEIGHTS[article.get("journal", "")]

def get_relevance_payload(article, label):
    system_prompt = f"""
    You are an expert scientist specializing in {label}.
    On a scale of 1 to 10, how RELEVANT is this article to your field?
    - 1 = Irrelevant or minor mention.
    - 5 = Relevant, but standard work.
    - 10 = A "must-read" breakthrough paper for this specific field.

    Analyze the title and abstract, then return ONLY valid JSON with a single key: "relevance_score".
    
    Example:
    {{"relevance_score": 8}}
    """
    
    user_prompt = f"""
    Title: {article['title']}
    Abstract: {article.get('abstract', '')[:2000]}
    
    Score this article's relevance for {label} (1-10). JSON only.
    """
    
    return {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }

async def score_article(article, label, semaphore, pbar):
    """
    Coroutine for scoring a single article for a single label.
    """
    async with semaphore:
        payload = get_relevance_payload(article, label)
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()
                
                result_data = json.loads(response.json()["choices"][0]["message"]["content"])
                
                ai_score = int(result_data.get('relevance_score', 1))
                journal_score = get_journal_score(article)
                
                article['priority_score'] = ai_score * journal_score
                article['ai_relevance'] = ai_score # Store for debugging
                
                pbar.update(1)
                return article

            except (httpx.HTTPStatusError, json.JSONDecodeError) as e:
                print(f"   [!] Score Error '{article['title'][:20]}...': {e}. Retrying {attempt+1}/{max_retries}")
                await asyncio.sleep((attempt + 2) * 2)
            except Exception as e:
                print(f"   [!] Unexpected Score Error '{article['title'][:20]}...': {e}. Skipping.")
                pbar.update(1)
                break
        
        # Fallback score if AI fails
        article['priority_score'] = get_journal_score(article) # Default to just journal score
        article['ai_relevance'] = 0 # Mark as failed
        pbar.update(1)
        return article

async def ranker_agent(input_path=None):
    # --- 1. Input Finding ---
    if not input_path:
        if not os.path.exists(DATA_ANALYZED_DIR):
             print(f"❌ Error: data/analyzed/ folder not found. Run analyzer.py first.")
             return
        files = [os.path.join(DATA_ANALYZED_DIR, f) for f in os.listdir(DATA_ANALYZED_DIR) if f.endswith("-analyzed.json")]
        if not files:
             print(f"❌ Error: No analyzed files found.")
             return
        input_path = max(files, key=os.path.getctime)

    print(f"🤖 RankerAgent v{__version__}: Reading from {os.path.basename(input_path)}")
    with open(input_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    # --- 2. Group articles by label ---
    grouped_by_label = defaultdict(list)
    for article in articles:
        for label in article.get('labels', ['Others']):
            grouped_by_label[label].append(article.copy()) # Use .copy() to avoid score bleed-over
    
    print(f"   Found {len(articles)} articles across {len(grouped_by_label)} labels.")
    
    # --- 3. Score and Rank ---
    ranked_data = {}
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    
    # Use 'tqdm' for a nice progress bar if installed
    try:
        from tqdm.auto import tqdm
        pbar_class = tqdm
    except ImportError:
        print("   (Install 'tqdm' for a nice progress bar: pip install tqdm)")
        class SimplePBar:
            def __init__(self, total, desc, unit, leave=False):
                self.total = total
                self.desc = desc
                self.unit = unit
                self.count = 0
                print(f"{self.desc}: 0/{self.total} {self.unit}s", end='\r')
            def update(self, n):
                self.count += n
                print(f"{self.desc}: {self.count}/{self.total} {self.unit}s", end='\r')
            def close(self):
                print() # Newline at the end
        pbar_class = SimplePBar


    for label, label_articles in grouped_by_label.items():
        if label == "Others":
            print(f"\n   Skipping 'Others' label...")
            continue
        
        print(f"\n   Processing label: {label} ({len(label_articles)} articles)")
        
        # --- YOUR NEW LOGIC ---
        if len(label_articles) <= REPORT_LIMIT:
            print(f"   -> Count ({len(label_articles)}) is <= limit ({REPORT_LIMIT}). Skipping AI scoring.")
            # Simple sort by journal weight only
            for article in label_articles:
                article['priority_score'] = get_journal_score(article)
                article['ai_relevance'] = "N/A (Skipped)"
            
            ranked_articles = sorted(label_articles, key=lambda x: x['priority_score'], reverse=True)
        
        else:
            print(f"   -> Count ({len(label_articles)}) is > limit ({REPORT_LIMIT}). Starting AI scoring...")
            
            with pbar_class(total=len(label_articles), desc=f"   Scoring {label}", unit="article", leave=False) as pbar:
                tasks = [score_article(article, label, semaphore, pbar) for article in label_articles]
                results = await asyncio.gather(*tasks)
            
            # Sort by the new priority_score
            ranked_articles = sorted(results, key=lambda x: x.get('priority_score', 0), reverse=True)
        
        # Save the Top N (or all, if fewer than N)
        ranked_data[label] = ranked_articles[:REPORT_LIMIT]
        print(f"   -> Saved Top {len(ranked_data[label])} for {label}.")


    # --- 4. Save Results ---
    os.makedirs(DATA_RANKED_DIR, exist_ok=True)
    filename = os.path.basename(input_path).replace("-analyzed.json", "-ranked.json")
    output_path = os.path.join(DATA_RANKED_DIR, filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(ranked_data, f, indent=4, ensure_ascii=False)

    print(f"\n✨ Success! All labels ranked and culled.")
    print(f"💾 Saved to: {output_path}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Specific analyzed JSON file to rank")
    args = parser.parse_args()
    
    print(f"--- 🏅 RankerAgent v{__version__} Initializing ---")
    await ranker_agent(input_path=args.file)

if __name__ == "__main__":
    asyncio.run(main())