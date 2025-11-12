#!/bin/bash
#
# SCRIPT: pipeline.sh
# AUTHOR: Agora News System
# VERSION: 1.1 (English Logs)
# DATE: 2025-11-12
# DESCRIPTION: Runs the full news processing pipeline (Fetch -> Scrape -> Analyze -> Rank -> Report)
#
# USAGE:
#   ./pipeline.sh       (Default: runs for the last 2 days)
#   ./pipeline.sh 7     (Runs for the last 7 days)
#

# --- 1. CONFIGURATION ---

# Exit immediately if a command fails
set -e

# Set the '--days' parameter.
# Uses the first argument ($1) if provided, otherwise defaults to 2.
DAYS=${1:-2}

echo "--- 🚀 STARTING AGORA NEWS PIPELINE (v1.1) ---"
echo "--- Searching for articles from the last ${DAYS} day(s) ---"
echo ""

# --- 2. RUN PIPELINE ---

echo "--- (1/5) Fetcher: Fetching RSS feeds... ---"
python fetcher.py --days $DAYS

echo ""
echo "--- (2/5) Scraper: Scraping abstracts... ---"
# Automatically finds the latest -raw.json file
python scraper.py

echo ""
echo "--- (3/5) Analyzer: Analyzing & Translating... ---"
# Automatically finds the latest -scraped.json file
python analyzer.py

echo ""
echo "--- (4.1/5) Ranker: Ranking & Scoring... ---"
# Automatically finds the latest -analyzed.json file
python ranker.py

echo ""
echo "--- (5/5) Reporter: Generating Reports... ---"
# Automatically finds the latest -ranked.json file
python reporter.py

echo ""
echo "--- ✅ PIPELINE COMPLETE ---"
echo "--- Reports are available in the /reports folder. ---"