#!/usr/bin/env python3
"""
Hacker News首页文章自动化采集脚本
用途: web导航自动化扩站演示
用法:
  python scripts/hackernews_scraper.py              # 抓取前10条
  python scripts/hackernews_scraper.py --limit 5     # 抓取5条
  python scripts/hackernews_scraper.py --output hn.json
  python scripts/hackernews_scraper.py --test-pass  # 10次通过率验证
"""
import requests, json, sys, time, argparse
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = 'https://news.ycombinator.com/'

def fetch_stories(url=BASE_URL, limit=10, timeout=15):
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    
    stories = []
    for row in soup.select('tr.athing')[:limit]:
        title_el = row.select_one('td.title a')
        if not title_el:
            continue
        
        title = title_el.text.strip()
        href = title_el.get('href', '')
        # Resolve relative URLs
        full_url = urljoin(BASE_URL, href)
        
        # Get rank
        rank_el = row.select_one('td.title span.rank')
        rank = rank_el.text.strip().rstrip('.') if rank_el else ''
        
        # Get subtext (score, author, age, comments) from next row
        subtext_row = row.find_next_sibling('tr')
        score = 0
        author = ''
        comments = 0
        if subtext_row:
            subtext = subtext_row.select_one('td.subtext')
            if subtext:
                score_el = subtext.select_one('span.score')
                if score_el:
                    score = int(score_el.text.strip().split()[0])
                author_el = subtext.select_one('a.hnuser')
                if author_el:
                    author = author_el.text.strip()
                # comments link
                for a in subtext.select('a'):
                    txt = a.text.strip()
                    if 'comment' in txt:
                        try:
                            comments = int(txt.split()[0])
                        except:
                            pass
        
        stories.append({
            'rank': int(rank) if rank.isdigit() else 0,
            'title': title,
            'url': full_url,
            'score': score,
            'author': author,
            'comments': comments,
        })
    return stories

def test_pass_rate(trials=10):
    success = 0
    errors = []
    for i in range(trials):
        try:
            s = fetch_stories(limit=5, timeout=10)
            if len(s) >= 3:
                success += 1
            else:
                errors.append(f"Attempt {i+1}: only {len(s)} stories")
        except Exception as e:
            errors.append(f"Attempt {i+1}: {e}")
        time.sleep(0.3)
    rate = success / trials * 100
    print(f"Pass Rate: {success}/{trials} = {rate:.1f}%")
    if errors:
        print(f"Errors ({len(errors)}/{trials}):")
        for e in errors[:3]:
            print(f"  - {e}")
    return rate

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Hacker News Scraper')
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--output', type=str, help='Save to JSON file')
    parser.add_argument('--test-pass', action='store_true', help='Run pass rate test')
    args = parser.parse_args()
    
    if args.test_pass:
        test_pass_rate()
    else:
        data = fetch_stories(limit=args.limit)
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Saved {len(data)} stories to {args.output}")
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"\n✅ Fetched {len(data)} stories successfully")
