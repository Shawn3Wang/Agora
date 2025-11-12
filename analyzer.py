"""
SCRIPT: analyzer.py
AUTHOR: Agora News System
VERSION: 1.2 (Parallel Processing)
DATE: 2025-11-12
DESCRIPTION: Reads scraped data, then (in parallel) uses an AI to:
             1. Assign labels (1-3) + 'Others'
             2. Translate title & abstract to Chinese
             Saves to data/analyzed/YYYY-MM-DD-analyzed.json
"""
__version__ = "1.2"

import json
import os
import time
import argparse
import asyncio
import httpx
from dotenv import load_dotenv
from openai import OpenAI

# --- CONFIGURATION ---
load_dotenv()
API_KEY = os.getenv("AI_API_KEY")
BASE_URL = os.getenv("AI_BASE_URL")

if not API_KEY or not BASE_URL:
    print("⚠️ ERROR: Please ensure AI_API_KEY and AI_BASE_URL are set in your .env file")
    exit(1)

# --- IMPORTANT ---
# We must use an ASYNC client for asyncio
client = httpx.AsyncClient(
    base_url=BASE_URL,
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=60.0  # Increase timeout for complex generation
)
MODEL_NAME = "gemini-2.5-flash"
CONCURRENT_REQUESTS = 10  # Process 10 articles at a time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_SCRAPED_DIR = os.path.join(BASE_DIR, "data", "scraped")
DATA_ANALYZED_DIR = os.path.join(BASE_DIR, "data", "analyzed")

# Added "Others" as per your request
OFFICIAL_LABELS = [
    "Aging", "AI & Computational Biology", "Bioengineering", "Biotechnology",
    "Cancer", "Clinical & Medicine", "Development", "Drug Discovery",
    "Evolution", "Genetics & Epigenetics", "Immunology", "Metabolism",
    "Microbiology", "Molecular Design", "Plants", "Single-cell & Spatial omics",
    "Stem cell", "Structure", "Synthetic Biology", "Virtual Cell", "Others"
]

# --- AI PROMPT ENGINEERING ---
ANALYSIS_SYSTEM_PROMPT = f"""
You are an expert scientific editor and translator. Your task is to analyze a research article and provide two pieces of information:
1.  **Labels**: Assign 1-3 relevant labels from the provided list. If no labels are relevant, assign ONLY ["Others"].
2.  **Translation**: Translate the title and abstract into academic-style Simplified Chinese (学术风格的简体中文).

**Label List:**
{json.dumps(OFFICIAL_LABELS)}

**Rules:**
-   Return ONLY valid JSON.
-   The JSON output MUST have three keys: `labels`, `title_cn`, `abstract_cn`.

**Example Output:**
{{
  "labels": ["Cancer", "Immunology"],
  "title_cn": "一个用于癌症免疫治疗的新型靶点",
  "abstract_cn": "在这项研究中，我们发现..."
}}
"""

def get_analysis_payload(article):
    """Prepares the JSON payload for the API request."""
    text_to_analyze = article.get('abstract') or article.get('summary') or ""
    
    user_prompt = f"""
    Title: {article['title']}
    Abstract: {text_to_analyze[:5000]}
    
    Analyze and translate now. Return JSON only.
    """
    
    return {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }

async def analyze_article(article, semaphore, pbar):
    """
    Coroutine for analyzing a single article.
    Uses a semaphore to limit concurrency.
    """
    async with semaphore:
        payload = get_analysis_payload(article)
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                response = await client.post("/chat/completions", json=payload)
                response.raise_for_status()  # Raise an error for 4xx/5xx status
                
                result_data = json.loads(response.json()["choices"][0]["message"]["content"])
                
                # Validate the output from the AI
                if 'labels' in result_data and 'title_cn' in result_data and 'abstract_cn' in result_data:
                    # Filter labels to ensure they are from the official list
                    valid_labels = [L for L in result_data.get("labels", []) if L in OFFICIAL_LABELS]
                    if not valid_labels:
                        valid_labels = ["Others"] # Default to 'Others' if empty or all invalid
                    
                    article['labels'] = valid_labels
                    article['title_cn'] = result_data['title_cn']
                    article['abstract_cn'] = result_data['abstract_cn']
                    
                    pbar.update(1) # Update progress bar on success
                    return article
                
            except (httpx.HTTPStatusError, json.JSONDecodeError) as e:
                print(f"   [!] API Error processing '{article['title'][:20]}...': {e}. Retrying {attempt+1}/{max_retries}")
                await asyncio.sleep((attempt + 2) * 2) # Exponential backoff
            except Exception as e:
                print(f"   [!] Unexpected Error processing '{article['title'][:20]}...': {e}. Skipping.")
                pbar.update(1) # Update pbar even on fail so it doesn't hang
                return None # Failed to process
                
        pbar.update(1) # Update pbar after all retries fail
        return None # Failed to process

async def analyzer_agent(input_path=None, limit=None):
    # --- 1. Intelligent Input Finding ---
    if not input_path:
        if not os.path.exists(DATA_SCRAPED_DIR):
             print(f"❌ Error: data/scraped/ folder not found. Run scraper.py first.")
             return None
        files = [os.path.join(DATA_SCRAPED_DIR, f) for f in os.listdir(DATA_SCRAPED_DIR) if f.endswith("-scraped.json")]
        if not files:
             print(f"❌ Error: No scraped files found.")
             return None
        input_path = max(files, key=os.path.getctime)

    print(f"🤖 AnalyzerAgent v{__version__}: Reading from {os.path.basename(input_path)}")
    with open(input_path, 'r', encoding='utf-8') as f:
        articles = json.load(f)

    # --- 2. Parallel Processing Loop ---
    articles_to_process = articles[:limit] if limit else articles
    
    if not articles_to_process:
        print("   No articles to process. Exiting.")
        return None

    print(f"   Analyzing & Translating {len(articles_to_process)} articles (in parallel batches of {CONCURRENT_REQUESTS})...")
    
    # Use 'tqdm' for a nice progress bar if installed, otherwise a simple counter
    try:
        from tqdm.auto import tqdm
        pbar = tqdm(total=len(articles_to_process), desc="   Analyzing", unit="article")
    except ImportError:
        print("   (Install 'tqdm' for a nice progress bar: pip install tqdm)")
        # Simple progress bar replacement
        class SimplePBar:
            def __init__(self, total, desc, unit):
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
        pbar = SimplePBar(total=len(articles_to_process), desc="   Analyzing", unit="article")

    
    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = [analyze_article(article, semaphore, pbar) for article in articles_to_process]
    
    results = await asyncio.gather(*tasks)
    pbar.close()

    # Filter out None results (failures)
    analyzed_articles = [res for res in results if res is not None]

    # --- 3. Save Results ---
    if not analyzed_articles:
        print("\n   No articles were successfully analyzed.")
        return None

    os.makedirs(DATA_ANALYZED_DIR, exist_ok=True)
    filename = os.path.basename(input_path).replace("-scraped.json", "-analyzed.json")
    output_path = os.path.join(DATA_ANALYZED_DIR, filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(analyzed_articles, f, indent=4, ensure_ascii=False)

    print(f"\n✨ Success! Analyzed & Translated {len(analyzed_articles)} articles.")
    print(f"💾 Saved to: {output_path}")
    return output_path

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Specific scraped JSON file to analyze")
    parser.add_argument("--limit", type=int, default=None, help="Limit articles for testing")
    args = parser.parse_args()
    
    print(f"--- 🧬 AnalyzerAgent v{__version__} Initializing ---")
    await analyzer_agent(input_path=args.file, limit=args.limit)

if __name__ == "__main__":
    # --- IMPORTANT ---
    # To run an async main function, we use asyncio.run()
    asyncio.run(main())