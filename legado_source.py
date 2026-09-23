"""
Legado (阅读) 书源解析引擎
支持导入 Legado 书源 JSON，解析搜索、目录、正文规则
"""

import json
import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlencode, quote
from config import CONFIG


SOURCES_FILE = "legado_sources.json"


def load_sources():
    if os.path.exists(SOURCES_FILE):
        try:
            with open(SOURCES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_sources(sources):
    with open(SOURCES_FILE, 'w', encoding='utf-8') as f:
        json.dump(sources, f, ensure_ascii=False, indent=2)


def import_sources_from_json(json_text):
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    valid = []
    for src in data:
        if not isinstance(src, dict):
            continue
        if "bookSourceUrl" not in src:
            continue
        valid.append(src)
    return valid


def import_sources_from_url(url, timeout=30):
    session = requests.Session()
    ua = random.choice(CONFIG["request"]["user_agents"])
    resp = session.get(url, headers={"User-Agent": ua}, timeout=timeout)
    resp.raise_for_status()
    return import_sources_from_json(resp.text)


class RuleParser:
    """解析 Legado 书源规则并提取数据"""

    def __init__(self, base_url=""):
        self.base_url = base_url
        self.session = requests.Session()
        self.ua = random.choice(CONFIG["request"]["user_agents"])

    def _get(self, url, timeout=15):
        headers = {"User-Agent": self.ua}
        resp = self.session.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or 'utf-8'
        return resp.text

    def _resolve_url(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http"):
            return url
        return urljoin(self.base_url, url)

    def _apply_rule(self, element, rule_str):
        if not rule_str or not element:
            return ""
        rule_str = rule_str.strip()

        if "##" in rule_str:
            parts = rule_str.split("##", 1)
            raw = self._apply_rule(element, parts[0])
            try:
                regex_parts = parts[1].split("##")
                pattern = regex_parts[0]
                replacement = regex_parts[1] if len(regex_parts) > 1 else r"\1"
                match = re.search(pattern, raw)
                if match:
                    return match.expand(replacement)
            except Exception:
                pass
            return raw

        if rule_str.startswith("@css:"):
            css_rule = rule_str[5:]
            if "@" in css_rule:
                selector, attr = css_rule.rsplit("@", 1)
            else:
                selector, attr = css_rule, "text"
            selector = selector.strip()
            attr = attr.strip()
            found = element.select_one(selector) if selector else element
            if not found:
                return ""
            if attr == "text":
                return found.get_text(strip=True)
            elif attr == "textNodes":
                return found.get_text(strip=True)
            elif attr == "html":
                return str(found)
            elif attr == "src" or attr == "href":
                return found.get(attr, "")
            else:
                return found.get(attr, "")

        if "class." in rule_str or "id." in rule_str or "tag." in rule_str:
            return self._apply_legacy_rule(element, rule_str)

        if "@" in rule_str:
            parts = rule_str.split("@")
            current = element
            for part in parts[:-1]:
                part = part.strip()
                if not part:
                    continue
                if current is None:
                    return ""
                found = current.select_one(part)
                if found:
                    current = found
            attr = parts[-1].strip()
            if current is None:
                return ""
            if attr == "text":
                return current.get_text(strip=True)
            elif attr == "textNodes":
                return current.get_text(strip=True)
            elif attr == "html":
                return str(current)
            else:
                return current.get(attr, "") or ""

        if rule_str.startswith(".") or rule_str.startswith("#") or ">" in rule_str:
            found = element.select_one(rule_str)
            if found:
                return found.get_text(strip=True)
            return ""

        found = element.select_one(rule_str)
        if found:
            return found.get_text(strip=True)
        return ""

    def _apply_legacy_rule(self, element, rule_str):
        parts = rule_str.split("@")
        current = element
        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            if current is None:
                return ""
            if part in ("text", "textNodes", "html", "href", "src", "content"):
                if part in ("text", "textNodes"):
                    return current.get_text(strip=True)
                elif part == "html":
                    return str(current)
                else:
                    return current.get(part, "")
            if part.startswith("class."):
                cls = part[6:]
                found = current.find(class_=cls)
                if found:
                    current = found
                    continue
            elif part.startswith("id."):
                id_val = part[3:]
                found = current.find(id=id_val)
                if found:
                    current = found
                    continue
            elif part.startswith("tag."):
                tag = part[4:]
                found = current.find(tag)
                if found:
                    current = found
                    continue
            else:
                found = current.find(part)
                if found:
                    current = found
                    continue
        if current and current != element:
            return current.get_text(strip=True)
        return ""

    def _apply_rule_all(self, element, rule_str):
        if not rule_str or not element:
            return []
        rule_str = rule_str.strip()

        if rule_str.startswith("@css:"):
            css_part = rule_str[5:]
            selector = css_part
            if "@" in css_part:
                selector = css_part.rsplit("@", 1)[0].strip()
            return element.select(selector)

        if "class." in rule_str:
            parts = rule_str.split("@")
            for part in parts:
                part = part.strip()
                if part.startswith("class."):
                    cls = part[6:]
                    return element.find_all(class_=cls)
            return []

        if "tag." in rule_str:
            parts = rule_str.split("@")
            for part in parts:
                part = part.strip()
                if part.startswith("tag."):
                    tag = part[4:]
                    return element.find_all(tag)
            return []

        return element.select(rule_str) if rule_str else []


class LegadoSource:
    """单个 Legado 书源"""

    def __init__(self, source_data):
        self.data = source_data
        self.name = source_data.get("bookSourceName", "未知书源")
        self.url = source_data.get("bookSourceUrl", "")
        self.source_type = source_data.get("bookSourceType", 0)
        self.enabled = source_data.get("enabled", True)
        self.search_url = source_data.get("searchUrl", "")
        self.rule_search = source_data.get("ruleSearch", {})
        self.rule_book_info = source_data.get("ruleBookInfo", {})
        self.rule_toc = source_data.get("ruleToc", {})
        self.rule_content = source_data.get("ruleContent", {})
        self.parser = RuleParser(self.url)

    def _build_search_url(self, keyword):
        search_tpl = self.search_url
        if not search_tpl:
            return ""
        search_tpl = search_tpl.replace("{{key}}", quote(keyword))
        search_tpl = search_tpl.replace("{{page}}", "1")
        search_tpl = search_tpl.replace("searchKey", quote(keyword))
        search_tpl = search_tpl.replace("searchPage", "1")

        if search_tpl.startswith("http"):
            return search_tpl.split(",")[0].strip()

        return urljoin(self.url + "/", search_tpl.split(",")[0].strip())

    def search(self, keyword, timeout=15):
        url = self._build_search_url(keyword)
        if not url:
            return []

        try:
            html = self.parser._get(url, timeout=timeout)
        except Exception:
            return []

        soup = BeautifulSoup(html, 'html.parser')
        results = []

        rule_list = self.rule_search.get("bookList", "")
        rule_name = self.rule_search.get("name", "")
        rule_author = self.rule_search.get("author", "")
        rule_book_url = self.rule_search.get("bookUrl", "")
        rule_intro = self.rule_search.get("intro", "")
        rule_cover = self.rule_search.get("coverUrl", "")

        items = self.parser._apply_rule_all(soup, rule_list) if rule_list else []

        for item in items[:20]:
            try:
                name = self.parser._apply_rule(item, rule_name) if rule_name else ""
                if not name:
                    continue
                author = self.parser._apply_rule(item, rule_author) if rule_author else "未知"
                book_url = self.parser._apply_rule(item, rule_book_url) if rule_book_url else ""
                book_url = self.parser._resolve_url(book_url)
                intro = self.parser._apply_rule(item, rule_intro) if rule_intro else ""
                cover = self.parser._apply_rule(item, rule_cover) if rule_cover else ""
                cover = self.parser._resolve_url(cover)

                results.append({
                    "name": name.strip(),
                    "author": author.strip(),
                    "url": book_url,
                    "intro": intro.strip(),
                    "cover": cover,
                    "source": self.name,
                    "source_url": self.url
                })
            except Exception:
                continue

        return results

    def get_chapters(self, book_url, timeout=15):
        if not book_url:
            return []

        try:
            html = self.parser._get(book_url, timeout=timeout)
        except Exception:
            return []

        soup = BeautifulSoup(html, 'html.parser')

        rule_list = self.rule_toc.get("chapterList", "")
        rule_name = self.rule_toc.get("chapterName", "")
        rule_url = self.rule_toc.get("chapterUrl", "")

        items = self.parser._apply_rule_all(soup, rule_list) if rule_list else []
        if not items:
            items = soup.select("a")

        chapters = []
        for idx, item in enumerate(items):
            try:
                name = self.parser._apply_rule(item, rule_name) if rule_name else item.get_text(strip=True)
                if not name:
                    name = item.get_text(strip=True)
                ch_url = self.parser._apply_rule(item, rule_url) if rule_url else ""
                if not ch_url:
                    ch_url = item.get("href", "")
                ch_url = self.parser._resolve_url(ch_url)

                if not name or not ch_url:
                    continue

                chapters.append({
                    "title": name.strip(),
                    "url": ch_url,
                    "index": idx
                })
            except Exception:
                continue

        return chapters

    def get_content(self, chapter_url, timeout=15):
        if not chapter_url:
            return ""

        try:
            html = self.parser._get(chapter_url, timeout=timeout)
        except Exception:
            return ""

        soup = BeautifulSoup(html, 'html.parser')
        rule = self.rule_content.get("content", "")

        if rule:
            content_el = None
            if rule.startswith("@css:"):
                css = rule[5:]
                if "@" in css:
                    css = css.rsplit("@", 1)[0].strip()
                content_el = soup.select_one(css)
            elif "class." in rule:
                parts = rule.split("@")
                for part in parts:
                    part = part.strip()
                    if part.startswith("class."):
                        cls = part[6:]
                        content_el = soup.find(class_=cls)
                        break
            elif "id." in rule:
                parts = rule.split("@")
                for part in parts:
                    part = part.strip()
                    if part.startswith("id."):
                        id_val = part[3:]
                        content_el = soup.find(id=id_val)
                        break
            else:
                content_el = soup.select_one(rule)

            if content_el:
                for br in content_el.find_all("br"):
                    br.replace_with("\n")
                for p in content_el.find_all("p"):
                    p.insert_before("\n")
                    p.insert_after("\n")
                text = content_el.get_text()
            else:
                text = ""
        else:
            article = soup.find("article") or soup.find("div", id="content") or soup.find("div", class_="content")
            if article:
                for br in article.find_all("br"):
                    br.replace_with("\n")
                text = article.get_text()
            else:
                text = ""

        lines = text.split("\n")
        cleaned = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned.append("    " + line)
        return "\n".join(cleaned)


class LegadoEngine:
    """Legado 书源搜索引擎 - 管理多个书源并发搜索"""

    def __init__(self):
        self.sources = []
        self.load()

    def load(self):
        raw = load_sources()
        self.sources = [LegadoSource(s) for s in raw]

    def save(self):
        save_sources([s.data for s in self.sources])

    def add_sources(self, source_list):
        existing_urls = {s.url for s in self.sources}
        added = 0
        for src_data in source_list:
            url = src_data.get("bookSourceUrl", "")
            if url and url not in existing_urls:
                self.sources.append(LegadoSource(src_data))
                existing_urls.add(url)
                added += 1
        if added > 0:
            self.save()
        return added

    def remove_source(self, source_url):
        self.sources = [s for s in self.sources if s.url != source_url]
        self.save()

    def clear_sources(self):
        self.sources = []
        self.save()

    def get_enabled_sources(self):
        return [s for s in self.sources if s.enabled]

    def search(self, keyword, max_sources=10, timeout=15, callback=None):
        all_results = []
        enabled = self.get_enabled_sources()[:max_sources]
        for i, source in enumerate(enabled):
            if callback:
                callback(f"正在搜索: {source.name} ({i+1}/{len(enabled)})")
            try:
                results = source.search(keyword, timeout=timeout)
                all_results.extend(results)
            except Exception:
                pass
            time.sleep(0.3)
        return all_results

    def search_parallel(self, keyword, max_sources=20, timeout=15, callback=None):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        all_results = []
        enabled = self.get_enabled_sources()[:max_sources]

        def _search_one(source):
            try:
                return source.search(keyword, timeout=timeout)
            except Exception:
                return []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_search_one, s): s for s in enabled}
            done_count = 0
            for future in as_completed(futures):
                source = futures[future]
                done_count += 1
                if callback:
                    callback(f"搜索进度: {done_count}/{len(enabled)} ({source.name})")
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception:
                    pass

        return all_results

    def download_novel(self, source_url, book_url, save_path, progress_callback=None, log_callback=None):
        source = None
        for s in self.sources:
            if s.url == source_url:
                source = s
                break
        if not source:
            raise ValueError(f"未找到书源: {source_url}")

        if log_callback:
            log_callback(f"正在从 {source.name} 获取章节列表...")

        chapters = source.get_chapters(book_url)
        if not chapters:
            raise ValueError("未找到任何章节")

        if log_callback:
            log_callback(f"共找到 {len(chapters)} 章")

        os.makedirs(save_path, exist_ok=True)

        total = len(chapters)
        contents = {}

        for i, chapter in enumerate(chapters):
            try:
                content = source.get_content(chapter["url"])
                if content:
                    contents[chapter["index"]] = (chapter, content)
                    if log_callback:
                        log_callback(f"已下载: {chapter['title']}")
                else:
                    if log_callback:
                        log_callback(f"内容为空: {chapter['title']}")
            except Exception as e:
                if log_callback:
                    log_callback(f"下载失败: {chapter['title']} - {str(e)}")

            if progress_callback:
                progress_callback((i + 1) / total * 100, f"下载中: {i+1}/{total}")

            time.sleep(0.5)

        return contents, chapters
