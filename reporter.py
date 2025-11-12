"""
SCRIPT: reporter.py
AUTHOR: Agora News System
VERSION: 1.7 (Add Table of Contents)
DATE: 2025-11-12
DESCRIPTION: Reads the final ranked data and generates
             beautiful HTML and clean Markdown reports for each label.
             Optimized for mobile/WeChat reading.
"""
__version__ = "1.7"

import json
import os
import argparse
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

# --- CONFIGURATION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_RANKED_DIR = os.path.join(BASE_DIR, "data", "ranked")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
REPORT_LIMIT = 10 

# --- JINJA SETUP ---
env = Environment(
    loader=FileSystemLoader(BASE_DIR), 
    autoescape=select_autoescape(['html', 'xml'])
)

# --- (更新) MARKDOWN TEMPLATE v1.4 ---
# 1. 增加 "本期目录" 模块
MARKDOWN_TEMPLATE = """
# {{ report_label }} | 每日最新研究 （{{ generation_date_simple }}）
***

### 本期目录
{% for article in articles %}
1.  **{{ article.journal }} | {{ article.published_display }}**
    {{ article.title }}
{% endfor %}
***
{% for article in articles %}

## {{ article.title }}
{% if article.title_cn %}
### {{ article.title_cn }}
{% endif %}

**Journal:** {{ article.journal }}
**Published:** {{ article.published_display }}
**Authors:** {{ article.authors_short | default('Not Available') }}

### 摘要

> {{ article.abstract_cn | default('N/A') | replace('\n', '\n> ') }}

原文链接： {{ article.link }}
***
{% endfor %}
"""
# --- END TEMPLATE ---

def reporter_agent(input_path=None):
    # --- 1. Input Finding ---
    if not input_path:
        if not os.path.exists(DATA_RANKED_DIR):
             print(f"❌ Error: data/ranked/ folder not found. Run ranker.py first.")
             return
        files = [os.path.join(DATA_RANKED_DIR, f) for f in os.listdir(DATA_RANKED_DIR) if f.endswith("-ranked.json")]
        if not files:
             print(f"❌ Error: No ranked files found.")
             return
        input_path = max(files, key=os.path.getctime)
    
    print(f"🤖 ReporterAgent v{__version__}: Reading from {os.path.basename(input_path)}")
    with open(input_path, 'r', encoding='utf-8') as f:
        grouped_data = json.load(f)

    # --- 2. Create Output Directory ---
    today_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = os.path.join(REPORTS_DIR, today_str)
    os.makedirs(output_dir, exist_ok=True)
    print(f"   Reports will be saved to: {output_dir}")

    # --- 3. Load Templates ---
    try:
        html_template = env.get_template("report_template.html")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: Could not load 'report_template.html'. Make sure it exists.")
        print(e)
        return
        
    md_template = env.from_string(MARKDOWN_TEMPLATE)
    
    # --- 4. Generate Reports per Label ---
    generated_count = 0
    for label, articles in grouped_data.items():
        # Skip "Others"
        if label == "Others":
            continue
            
        print(f"   -> Generating report for: {label}")
        
        template_data = {
            "report_label": label,
            "generation_date_simple": datetime.now().strftime("%Y-%m-%d"), 
            "articles": articles[:REPORT_LIMIT] 
        }
        
        safe_filename = label.replace('/', '_').replace(' ', '_')
        
        # --- Generate HTML ---
        try:
            html_content = html_template.render(template_data)
            html_path = os.path.join(output_dir, f"{safe_filename}.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
        except Exception as e:
            print(f"     ❌ Error rendering HTML for {label}: {e}")
            
        # --- Generate Markdown ---
        try:
            md_content = md_template.render(template_data)
            md_path = os.path.join(output_dir, f"{safe_filename}.md")
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
        except Exception as e:
            print(f"     ❌ Error rendering Markdown for {label}: {e}")

        generated_count += 1

    print(f"\n✨ Success! Generated {generated_count} label reports.")
    print(f"💾 View reports in: {output_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, help="Specific ranked JSON file to report on")
    args = parser.parse_args()
    
    print(f"--- 📣 ReporterAgent v{__version__} Initializing ---")
    reporter_agent(input_path=args.file)