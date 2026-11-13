"""
清理小说 TXT 中的段评（读者评论）与作者杂谈。

适用于导出格式中含有以下内容的文件：
  - 正文段落末尾的标记：〔段评12〕
  - 章末的评论区块：【本章段评（选摘）】、【段评导出说明】、〔段评1〕（原始段索引：3）……
  - 作者在正文里插入的杂谈，例如 “（……宝子们稍等！）”

用法：
  python comment_cleaner.py 小说1.txt 小说2.txt            # 输出到原文件同目录
  python comment_cleaner.py *.txt -o cleaned               # 输出到 cleaned 文件夹
  python comment_cleaner.py 小说.txt --no-rename           # 不改名，文件名加 _clean
  python comment_cleaner.py 小说.txt --keep-author-notes   # 只删段评，保留作者杂谈

默认输出文件名为 “章节数_原名.txt”（没有“原名”时使用“书名”）。
"""

import argparse
import os
import re
import sys

# 章节标题：第12章 / 第 12 章 / 番外
CHAPTER_RE = re.compile(r"^(第\s*\d+\s*章|番外)")
# 段落末尾的段评标记
INLINE_MARK_RE = re.compile(r"〔段评\d+〕")
# 评论区块开始
BLOCK_START_RE = re.compile(r"^(【本章段评|【段评导出|【段评不完整|〔段评\d+〕（)")
# 评论区里每条评论下一行的点赞信息，用于识别“长得像章节标题”的评论
LIKE_LINE_RE = re.compile(r"·\s*点赞\s*\d+")
# 作者杂谈：整行都是括号里的话，并且带有作者常用语
AUTHOR_NOTE_PAREN_RE = re.compile(
    r"^\S{0,12}[（(][^）)]*(宝子们|宝宝们|求书架|加书架|书架|催更|月票|推荐票|好评|作者有话|加更|更新|见谅|稍等)[^）)]*[）)]?$"
)
# 作者杂谈：不带括号，但以“宝子们”称呼读者并提到更新/作者/插图等
AUTHOR_NOTE_PLAIN_RE = re.compile(r"宝子们.*(作者|下本书|更新|插图|见谅|稍等|书架|催更)|(作者|下本书|更新|插图).*宝子们")
# 图片占位
IMAGE_RE = re.compile(r"^［(插图|图片)］")

INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _next_nonempty(lines, i, lookahead=3):
    for line in lines[i + 1:i + 1 + lookahead]:
        if line.strip():
            return line.strip()
    return ""


def strip_comments(text, remove_author_notes=True):
    """删除段评与作者杂谈，返回 (清理后的文本, 统计信息字典)。"""
    lines = text.split("\n")
    out = []
    skipping = False
    stats = {"comment_lines": 0, "inline_marks": 0, "author_notes": 0, "chapters": 0}

    for i, line in enumerate(lines):
        s = line.strip()

        if CHAPTER_RE.match(s):
            # 评论区中以“第15章……”开头的评论：下一行是点赞信息，不是新章节
            if skipping and LIKE_LINE_RE.search(_next_nonempty(lines, i)):
                stats["comment_lines"] += 1
                continue
            skipping = False
            stats["chapters"] += 1
        elif BLOCK_START_RE.match(s):
            skipping = True

        if skipping:
            stats["comment_lines"] += 1
            continue

        if remove_author_notes and s and (
            IMAGE_RE.match(s) or AUTHOR_NOTE_PAREN_RE.match(s) or AUTHOR_NOTE_PLAIN_RE.search(s)
        ):
            stats["author_notes"] += 1
            continue

        new_line, n = INLINE_MARK_RE.subn("", line)
        stats["inline_marks"] += n
        out.append(new_line)

    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip() + "\n"
    return cleaned, stats


def clean_chapter_content(content):
    """下载时逐章调用：只删段评，正文其余部分不动。"""
    if not content or not has_comments(content):
        return content
    return strip_comments(content, remove_author_notes=False)[0].strip()


def has_comments(text):
    return "〔段评" in text or "【本章段评" in text


def _book_title(text):
    """从文件头部的“书籍信息”取原名，没有则取书名。"""
    head = text[:3000]
    for key in ("原名", "书名"):
        m = re.search(rf"^{key}[：:]\s*(.+)$", head, flags=re.M)
        if m:
            return m.group(1).strip().strip("《》")
    return None


def safe_filename(name):
    name = INVALID_FILENAME_RE.sub("_", name).strip(" .")
    return name[:150] or "novel"


def clean_file(path, out_dir=None, rename=True, remove_author_notes=True):
    """清理一个文件，返回 (输出路径, 统计信息)。不会覆盖原文件。"""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()

    cleaned, stats = strip_comments(text, remove_author_notes=remove_author_notes)

    out_dir = out_dir or os.path.dirname(os.path.abspath(path))
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    title = _book_title(text) if rename else None
    if title:
        out_name = f"{stats['chapters']}_{safe_filename(title)}.txt"
    else:
        out_name = f"{safe_filename(base)}_clean.txt"

    out_path = os.path.join(out_dir, out_name)
    if os.path.abspath(out_path) == os.path.abspath(path):
        out_path = os.path.join(out_dir, f"{safe_filename(base)}_clean.txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(cleaned)
    return out_path, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="删除小说 TXT 中的段评（读者评论）和作者杂谈")
    parser.add_argument("files", nargs="+", help="要清理的 TXT 文件")
    parser.add_argument("-o", "--out-dir", help="输出文件夹（默认与原文件相同）")
    parser.add_argument("--no-rename", action="store_true", help="不按“章节数_原名”改名，只在文件名后加 _clean")
    parser.add_argument("--keep-author-notes", action="store_true", help="保留作者杂谈，只删除段评")
    args = parser.parse_args(argv)

    failed = 0
    for path in args.files:
        try:
            out_path, st = clean_file(
                path,
                out_dir=args.out_dir,
                rename=not args.no_rename,
                remove_author_notes=not args.keep_author_notes,
            )
            print(
                f"✔ {os.path.basename(path)} → {os.path.basename(out_path)}  "
                f"章节 {st['chapters']} | 删除段评行 {st['comment_lines']} | "
                f"段评标记 {st['inline_marks']} | 作者杂谈 {st['author_notes']}"
            )
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"✘ {path}: {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
