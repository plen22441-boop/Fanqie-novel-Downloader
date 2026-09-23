import requests
import random
import json
import os
import time
import re
from bs4 import BeautifulSoup
from config import CONFIG


class CookieGenerationError(Exception):
    """自定义 Cookie 生成错误"""
    pass

class RequestHandler:
    def __init__(self):
        self.config = CONFIG["request"]

        self.session = requests.Session()

    def get_headers(self, cookie=None):
        """生成随机请求头"""
        return {
            "User-Agent": random.choice(self.config["user_agents"]),
            "Cookie": cookie if cookie else self.get_cookie()
        }

    def get_cookie(self):
        """生成或加载Cookie"""
        cookie_path = CONFIG["file"]["cookie_file"]
        last_error = None

        if os.path.exists(cookie_path):
            try:
                with open(cookie_path, 'r', encoding='utf-8') as f:
                    cookie_data = json.load(f)
                    # 确保加载的是字符串类型
                    if isinstance(cookie_data, str):
                        return cookie_data
                    else:
                        last_error = f"Cookie 文件 '{cookie_path}' 格式不正确"
            except FileNotFoundError:
                pass # 文件不存在，继续生成
            except json.JSONDecodeError:
                last_error = f"Cookie 文件 '{cookie_path}' 解析失败"
            except Exception as e:
                last_error = f"读取 Cookie 文件时发生错误: {e}"
        
        # 生成新Cookie
        for attempt in range(10):
            novel_web_id = random.randint(10**18, 10**19-1)
            cookie = f'novel_web_id={novel_web_id}'
            try:
                resp = self.session.get(
                    'https://fanqienovel.com',
                    headers={"User-Agent": random.choice(self.config["user_agents"])},
                    cookies={"novel_web_id": str(novel_web_id)},
                    timeout=10
                )
                if resp.ok:
                    # 确保目录存在
                    os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
                    with open(cookie_path, 'w', encoding='utf-8') as f:
                        json.dump(cookie, f, ensure_ascii=False, indent=4)
                    return cookie
            except Exception as e:
                last_error = f"Cookie生成失败(尝试{attempt+1}/10): {str(e)}"
                time.sleep(0.5)
        
        raise CookieGenerationError(
            f"无法获取有效Cookie\n"
            f"可能原因:\n"
            f"1. 网络连接问题\n"
            f"2. 番茄小说服务器限制\n"
            f"3. 文件权限问题\n"
            f"最后一次错误: {last_error}"
        )

    def get_book_info(self, book_id):
        """获取书名、作者、简介"""
        url = f'https://fanqienovel.com/page/{book_id}'
        response = self.session.get(url, headers=self.get_headers())
        if response.status_code != 200:
            print(f"网络请求失败，状态码: {response.status_code}")
            return None, None, None

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 获取书名
        name_element = soup.find('h1')
        name = name_element.text if name_element else "未知书名"
        
        # 获取作者
        author_name_element = soup.find('div', class_='author-name')
        author_name = None
        if author_name_element:
            author_name_span = author_name_element.find('span', class_='author-name-text')
            author_name = author_name_span.text if author_name_span else "未知作者"
        
        # 获取简介
        description_element = soup.find('div', class_='page-abstract-content')
        description = None
        if description_element:
            description_p = description_element.find('p')
            description = description_p.text if description_p else "无简介"
        
        return name, author_name, description

    def extract_chapters(self, book_id):
        """解析章节列表"""
        url = f'https://api5-normal-lf.fqnovel.com/reading/bookapi/search/{book_id}/v'
        response = self.session.get(url, headers=self.get_headers())
        soup = BeautifulSoup(response.text, 'html.parser')
        
        chapters = []
        for idx, item in enumerate(soup.select('div.chapter-item')):
            a_tag = item.find('a')
            if not a_tag:
                continue
            
            raw_title = a_tag.get_text(strip=True)
            
            # 特殊章节
            if re.match(r'^(番外|特别篇|if线)\s*', raw_title):
                final_title = raw_title
            else:
                clean_title = re.sub(
                    r'^第[一二三四五六七八九十百千\d]+章\s*',
                    '', 
                    raw_title
                ).strip()
                final_title = f"第{idx+1}章 {clean_title}"
            
            chapters.append({
                "id": a_tag['href'].split('/')[-1],
                "title": final_title,
                "url": f"https://fanqienovel.com{a_tag['href']}",
                "index": idx
            })
        
        return chapters

    def parse_xxsypro_url(self, url):
        """Parse m.xxsypro.com category URL into components.

        URL format: /category/{catId}_{filter}_{page}_{perPage}_{sort}_{extra}
        Returns dict with keys: base, cat_id, filter_, page, per_page, sort, extra
        """
        import re
        m = re.search(r'/category/([^/_]+)_([^/_]+)_(\d+)_(\d+)_(\d+)_(\d+)', url)
        if not m:
            return None
        return {
            'base': 'https://m.xxsypro.com/category',
            'cat_id': m.group(1),
            'filter_': m.group(2),
            'page': int(m.group(3)),
            'per_page': int(m.group(4)),
            'sort': m.group(5),
            'extra': m.group(6),
        }

    def build_xxsypro_url(self, params, page):
        """Build an m.xxsypro.com category URL for the given page number."""
        return (
            f"{params['base']}/"
            f"{params['cat_id']}_{params['filter_']}_{page}_"
            f"{params['per_page']}_{params['sort']}_{params['extra']}"
        )

    def get_xxsypro_novels(self, category_url):
        """Fetch all pages of novel listings from an m.xxsypro.com category URL.

        Paginates through every page (not just the first 3) and returns a list of
        dicts with 'title', 'url', and optionally 'author'.
        """
        params = self.parse_xxsypro_url(category_url)
        if not params:
            raise ValueError(f"Unrecognised m.xxsypro.com URL format: {category_url}")

        all_novels = []
        page = 1

        while True:
            url = self.build_xxsypro_url(params, page)
            try:
                response = self.session.get(url, headers=self.get_headers(), timeout=self.config["request_timeout"])
            except Exception as e:
                print(f"请求第{page}页失败: {e}")
                break

            if response.status_code != 200:
                print(f"第{page}页返回状态码 {response.status_code}，停止翻页")
                break

            soup = BeautifulSoup(response.text, 'html.parser')

            # Collect novel entries — try common CSS selectors used by aggregator sites
            items = (
                soup.select('li.book-item') or
                soup.select('div.book-item') or
                soup.select('ul.book-list li') or
                soup.select('.novel-list .item') or
                soup.select('a.book-name')
            )

            if not items:
                # Fallback: grab every anchor whose href looks like a book page
                items = [
                    a for a in soup.find_all('a', href=True)
                    if re.search(r'/book/\d+|/novel/\d+', a['href'])
                ]

            if not items:
                # No more novels found on this page — stop
                break

            page_novels = []
            for item in items:
                a_tag = item if item.name == 'a' else item.find('a', href=True)
                if not a_tag:
                    continue
                title = a_tag.get_text(strip=True) or a_tag.get('title', '')
                href = a_tag['href']
                if href.startswith('/'):
                    href = 'https://m.xxsypro.com' + href
                author_tag = item.find(class_=re.compile(r'author', re.I)) if item.name != 'a' else None
                author = author_tag.get_text(strip=True) if author_tag else ''
                if title and href:
                    page_novels.append({'title': title, 'url': href, 'author': author})

            if not page_novels:
                break

            all_novels.extend(page_novels)
            print(f"第{page}页：获取到 {len(page_novels)} 本小说")

            # Detect last page: if fewer items than per_page, we've reached the end
            if len(page_novels) < params['per_page']:
                break

            page += 1
            time.sleep(0.5)  # polite delay between requests

        print(f"共获取到 {len(all_novels)} 本小说（共 {page} 页）")
        return all_novels

    def down_text(self, chapter_id):
        """下载章节内容"""
        max_retries = self.config.get('max_retries', 3)
        retry_count = 0
        content = ""
        
        while retry_count < max_retries:
            try:
                api_url = f"https://api.cengui.cn/api/tomato/content.php?item_id={chapter_id}"
                response = self.session.get(api_url, timeout=self.config["request_timeout"])
                data = response.json()
                
                if data.get("code") == 200:
                    content = data.get("data", {}).get("content", "")
                    
                    # 移除HTML标签
                    content = re.sub(r'<header>.*?</header>', '', content, flags=re.DOTALL)
                    content = re.sub(r'<footer>.*?</footer>', '', content, flags=re.DOTALL)
                    content = re.sub(r'</?article>', '', content)
                    content = re.sub(r'<p idx="\d+">', '\n', content)
                    content = re.sub(r'</p>', '\n', content)
                    content = re.sub(r'<[^>]+>', '', content)
                    content = re.sub(r'\\u003c|\\u003e', '', content)
                    
                    # 处理可能的重复章节标题行
                    title = data.get("data", {}).get("title", "")
                    if title and content.startswith(title):
                        content = content[len(title):].lstrip()
                    
                    content = re.sub(r'\n{2,}', '\n', content).strip()
                    content = '\n'.join(['    ' + line if line.strip() else line for line in content.split('\n')])
                    break
            except Exception as e:
                print(f"请求失败: {str(e)}, 重试第{retry_count + 1}次...")
                retry_count += 1
                time.sleep(1 * retry_count)
        
        if not content: # 如果所有重试后 content 仍然为空
            raise ConnectionError(f"无法下载章节 {chapter_id}，API 可能已失效或网络错误。")
            
        return content
