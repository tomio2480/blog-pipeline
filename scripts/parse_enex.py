"""ENEX (Evernote エクスポート) を Markdown へ変換する CLI スクリプト．

設計方針:

- 標準ライブラリのみで実装する．サードパーティ依存ゼロ．
- `xml.etree.ElementTree.iterparse` で `<note>` 単位にストリーミング処理し，
  処理後に `clear()` を呼んで子要素を解放する．
- `<resource><data>` の base64 本体は出力 Markdown へ含めない．
  ただし iterparse の性質上，end イベント到達時には `<data>` のテキストは
  メモリへ一度乗る．完全な非読込は `xml.sax` への切替が必要となるが，
  実 ENEX は 1 ノート 30MB 程度であり実害軽微として iterparse 方式を採用する．
- 出力ファイル名は NFC 正規化のうえ Windows 予約名・不正文字・末尾空白等を
  サニタイズし，最大 80 文字へ切り詰める．衝突時は `-2`，`-3` を付与する．
- フロントマターは YAML で出力する．本文は 3 セクション構成
  （人間メモ / Evernote AI 構造化情報 / 生の文字起こし）．

使い方:

    python scripts/parse_enex.py <input.enex> --output-dir <materials/raw>
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Iterable, Iterator, Union


SOURCE_NAME = "evernote"
SECTION_HUMAN_MEMO = "## 🗒️ 人間メモ（音声と AI 構造化の間に書かれたもの）"
SECTION_AI_STRUCTURED = "## 🤖 Evernote AI 構造化情報"
SECTION_RAW_TRANSCRIPTION = "## 🗣️ 生の文字起こし（参考）"
EMPTY_AI_PLACEHOLDER = "（構造化情報なし）"
MAX_FILENAME_STEM_LENGTH = 80
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
XML_BUILTIN_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_ENTITY_PATTERN = re.compile(r"&[a-zA-Z][a-zA-Z0-9]*;|&#[0-9]+;|&#[xX][0-9a-fA-F]+;")
# textlint の全角スペースルールに合わせて強調記法と隣接する場合にスペースを除去する記号
# 全角句読点・括弧に加えて，半角の句読点・括弧も対象とする
EMPHASIS_RIGHT_PUNCT = "，．、。）」』〉》】］｝！？.,!?:;)]}"
EMPHASIS_LEFT_PUNCT = "（「『〈《【［｛([{"

Source = Union[str, Path, IO[bytes]]


@dataclass
class Note:
    title: str
    created: str
    updated: str
    author: str | None
    tags: list[str] = field(default_factory=list)
    attachments: list[dict[str, str]] = field(default_factory=list)
    transcription_state: str = "absent"
    languages: list[str] = field(default_factory=list)
    raw_transcription: str = ""
    human_memo_enml: str = ""
    ai_structured_enml: str = ""


# ---------- public API ----------


def parse_enex(source: Source) -> Iterator[Note]:
    """ENEX を 1 ノートずつ Note へ変換して yield する．

    `(start, end)` イベントで iterparse し，ルート要素を取得したうえで note 終端ごとに
    `root.clear()` を呼ぶ．これにより巨大 ENEX でも処理済み note がルート直下に
    蓄積してメモリを圧迫することを防ぐ．タグ比較は namespace を無視して行う．
    """
    src: str | IO[bytes]
    if isinstance(source, Path):
        src = str(source)
    else:
        src = source
    context = iter(ET.iterparse(src, events=("start", "end")))
    try:
        _, root = next(context)
    except StopIteration:
        return
    for event, elem in context:
        if event == "end" and _local_tag(elem.tag).lower() == "note":
            yield _build_note(elem)
            elem.clear()
            root.clear()


def note_to_markdown(note: Note) -> str:
    """Note をフロントマター付き Markdown へ整形する．"""
    parts: list[str] = [_yaml_frontmatter(note), ""]

    parts.append(SECTION_HUMAN_MEMO)
    parts.append("")
    memo_md = enml_to_markdown(note.human_memo_enml)
    if memo_md:
        parts.append(memo_md)
        parts.append("")

    parts.append(SECTION_AI_STRUCTURED)
    parts.append("")
    ai_md = enml_to_markdown(note.ai_structured_enml)
    if ai_md:
        parts.append(ai_md)
    else:
        parts.append(EMPTY_AI_PLACEHOLDER)
    parts.append("")

    parts.append(SECTION_RAW_TRANSCRIPTION)
    parts.append("")
    if note.raw_transcription:
        parts.append(note.raw_transcription)
        parts.append("")

    return "\n".join(parts)


def sanitize_filename(title: str, created_iso: str) -> str:
    """`<YYYY-MM-DD>-<safe_title>.md` を返す．"""
    date_prefix = created_iso[:10] if len(created_iso) >= 10 else "0000-00-00"

    normalized = unicodedata.normalize("NFC", title)
    cleaned = re.sub(r'[\\/:\*\?"<>\|\x00-\x1f]+', "-", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"-+", "-", cleaned)
    cleaned = cleaned.strip(" .-")

    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"

    if not cleaned:
        cleaned = "untitled"

    stem = f"{date_prefix}-{cleaned}"
    if len(stem) > MAX_FILENAME_STEM_LENGTH:
        stem = stem[:MAX_FILENAME_STEM_LENGTH].rstrip(" .-")

    return f"{stem}.md"


def write_notes(notes: Iterable[Note], output_dir: Path) -> list[Path]:
    """Note 群を output_dir 下へ書き出す．衝突は連番サフィックスで回避する．"""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for note in notes:
        base = sanitize_filename(note.title, note.created)
        path = _resolve_collision(output_dir, base)
        path.write_text(note_to_markdown(note), encoding="utf-8")
        written.append(path)
    return written


def extract_transcription(en_media_style: str) -> tuple[str, str, list[str]]:
    """`--en-transcription` JSON から (連結テキスト, 状態, languages) を返す．

    json.JSONDecoder().raw_decode() を使い，先頭から有効な JSON オブジェクトのみを
    切り出す．JSON 文字列値内に `}` が含まれる場合も誤って切断しない．
    """
    if not en_media_style:
        return "", "absent", []
    marker = "--en-transcription:"
    idx = en_media_style.find(marker)
    if idx < 0:
        return "", "absent", []
    rest = en_media_style[idx + len(marker):].lstrip()
    try:
        data, _ = json.JSONDecoder().raw_decode(rest)
    except json.JSONDecodeError:
        return "", "absent", []
    if not isinstance(data, dict):
        return "", "absent", []
    state = str(data.get("transcription_state", "absent"))
    raw_languages = data.get("languages", [])
    languages = (
        [str(lang) for lang in raw_languages if lang is not None]
        if isinstance(raw_languages, list)
        else []
    )
    segments = data.get("segments", []) or []
    text = "\n".join(
        seg.get("text", "") for seg in segments if isinstance(seg, dict) and seg.get("text")
    )
    return text, state, languages


def enml_to_markdown(enml: str) -> str:
    """ENML フラグメントを Markdown 文字列へ変換する．"""
    if not enml or not enml.strip():
        return ""
    prepared = _replace_html_entities(enml)
    wrapped = f"<root>{prepared}</root>"
    try:
        root = ET.fromstring(wrapped)
    except ET.ParseError:
        return ""
    blocks = _render_children_as_blocks(root)
    return blocks


# ---------- internal helpers ----------


def _build_note(note_elem: ET.Element) -> Note:
    title = (note_elem.findtext("{*}title") or "").strip()
    created = _enex_datetime_to_iso(note_elem.findtext("{*}created") or "")
    updated = _enex_datetime_to_iso(note_elem.findtext("{*}updated") or "")
    tags = [(t.text or "").strip() for t in note_elem.findall("{*}tag") if t.text]
    author = note_elem.findtext("{*}note-attributes/{*}author")
    if author is not None:
        author = author.strip() or None

    content_xml = note_elem.findtext("{*}content") or ""
    (
        attachments,
        transcript_text,
        state,
        langs,
        memo_enml,
        ai_enml,
    ) = _parse_enml_content(content_xml)

    return Note(
        title=title,
        created=created,
        updated=updated,
        author=author,
        tags=tags,
        attachments=attachments,
        transcription_state=state,
        languages=langs,
        raw_transcription=transcript_text,
        human_memo_enml=memo_enml,
        ai_structured_enml=ai_enml,
    )


def _enex_datetime_to_iso(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_enml_content(
    content_xml: str,
) -> tuple[list[dict[str, str]], str, str, list[str], str, str]:
    if not content_xml.strip():
        return [], "", "absent", [], "", ""

    cleaned = re.sub(r"<\?xml[^?]*\?>", "", content_xml)
    cleaned = re.sub(r"<!DOCTYPE[^>]*>", "", cleaned).strip()
    cleaned = _replace_html_entities(cleaned)

    try:
        en_note = ET.fromstring(cleaned)
    except ET.ParseError:
        return [], "", "absent", [], "", ""

    attachments: list[dict[str, str]] = []
    transcript_parts: list[str] = []
    state = "absent"
    languages: list[str] = []
    memo_elements: list[ET.Element] = []
    ai_elements: list[ET.Element] = []
    seen_h1 = False

    for child in list(en_note):
        tag = _local_tag(child.tag).lower()
        if tag == "en-media":
            h = child.get("hash")
            t = child.get("type")
            if h and t:
                attachments.append({"hash": h, "type": t})
            text, st, lg = extract_transcription(child.get("style", ""))
            if text:
                transcript_parts.append(text)
            if state == "absent" and st != "absent":
                state = st
                languages = lg or languages
        elif not seen_h1 and tag == "h1":
            seen_h1 = True
            ai_elements.append(child)
        elif seen_h1:
            ai_elements.append(child)
        else:
            memo_elements.append(child)

    transcript_text = "\n".join(transcript_parts)
    memo_enml = "".join(_serialize(e) for e in memo_elements)
    ai_enml = "".join(_serialize(e) for e in ai_elements)
    return attachments, transcript_text, state, languages, memo_enml, ai_enml


def _replace_html_entities(text: str) -> str:
    """XML 基本実体（ &amp; / &lt; / &gt; / &quot; / &apos; ）以外のエンティティを decode する．

    ENML には &nbsp; / &mdash; / &hellip; / &ldquo; / &copy; など多種多様な HTML
    エンティティが含まれる．これらを未処理のままだと ET.fromstring が ParseError を投げ
    本文が空になる．XML 基本実体は ET parser が後段で decode するため温存する．

    数値エンティティ（ &#38; → & など）が XML 文法を壊さないよう，decode 結果に対し
    html.escape で再エスケープし，ET parser が後段で正しく decode できる形にする．
    """

    def _decode(match: re.Match[str]) -> str:
        entity = match.group(0)
        if entity in XML_BUILTIN_ENTITIES:
            return entity
        decoded = html.unescape(entity)
        return html.escape(decoded, quote=False)

    return _ENTITY_PATTERN.sub(_decode, text)


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _serialize(elem: ET.Element) -> str:
    return ET.tostring(elem, encoding="unicode", short_empty_elements=False)


def _render_children_as_blocks(parent: ET.Element) -> str:
    blocks: list[str] = []
    leading_text = (parent.text or "").strip()
    if leading_text:
        blocks.append(leading_text)
    for child in parent:
        rendered = _render_block(child)
        if rendered:
            blocks.append(rendered)
        tail = (child.tail or "").strip()
        if tail:
            blocks.append(tail)
    return "\n\n".join(blocks)


def _render_block(elem: ET.Element) -> str:
    tag = _local_tag(elem.tag).lower()
    if tag in ("h1", "h2", "h3"):
        prefix = "#" * int(tag[1])
        return f"{prefix} {_render_inline(elem)}".strip()
    if tag == "ul":
        items = [f"- {_render_inline(li)}" for li in elem.findall("{*}li")]
        return "\n".join(items)
    if tag == "ol":
        items = [
            f"{i + 1}. {_render_inline(li)}"
            for i, li in enumerate(elem.findall("{*}li"))
        ]
        return "\n".join(items)
    if tag == "blockquote":
        return f"> {_render_inline(elem)}"
    if tag == "div":
        if any(_local_tag(c.tag).lower() in {"h1", "h2", "h3", "ul", "ol", "blockquote", "div", "p", "hr"} for c in elem):
            return _render_children_as_blocks(elem)
        return _render_inline(elem)
    if tag == "hr":
        return "---"
    if tag in ("br", "en-media"):
        return ""
    return _render_inline(elem)


def _render_inline(elem: ET.Element) -> str:
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        ctag = _local_tag(child.tag).lower()
        if ctag in ("b", "strong"):
            content = _render_inline(child).strip()
            if content:
                parts.append(f" **{content}** ")
        elif ctag in ("i", "em"):
            content = _render_inline(child).strip()
            if content:
                parts.append(f" *{content}* ")
        elif ctag == "a":
            href = child.get("href", "")
            parts.append(f"[{_render_inline(child).strip()}]({href})")
        elif ctag == "code":
            content = _render_inline(child).strip()
            if content:
                parts.append(f"`{content}`")
        elif ctag == "br":
            parts.append("\n")
        elif ctag == "en-media":
            pass
        else:
            parts.append(_render_inline(child))
        if child.tail:
            parts.append(child.tail)
    return _normalize_emphasis_spacing("".join(parts))


def _normalize_emphasis_spacing(s: str) -> str:
    """強調記法 `**` ／ `*` の前後のスペースを正規化する．

    1. 連続スペースを 1 つへ折りたたむ（元 ENML に既にスペースがあった場合の二重スペース
       副作用を抑える）．
    2. 全角句読点・括弧および全角文字（非 ASCII）と隣接するスペースは除去する．
       textlint の `ja-no-space-around-parentheses` 等との衝突を避けるとともに，
       日本語文書としての見栄えを優先する．多くの Markdown レンダラーは全角文字隣接でも
       強調記法を正しく解釈する．
    3. 半角句読点・括弧と隣接するスペースも除去する（`!` ／ `,` ／ `)` 等）．
    """
    s = re.sub(r" {2,}(\*\*|\*)", r" \1", s)
    s = re.sub(r"(\*\*|\*) {2,}", r"\1 ", s)
    s = re.sub(
        rf"(\*\*|\*) ([{re.escape(EMPHASIS_RIGHT_PUNCT)}]|[^\x00-\x7f])",
        r"\1\2",
        s,
    )
    s = re.sub(
        rf"([{re.escape(EMPHASIS_LEFT_PUNCT)}]|[^\x00-\x7f]) (\*\*|\*)",
        r"\1\2",
        s,
    )
    return s


def _yaml_frontmatter(note: Note) -> str:
    lines: list[str] = ["---", f"source: {SOURCE_NAME}"]
    lines.append(f'note_title: "{_yaml_escape(note.title)}"')
    lines.append(f'created: "{note.created}"')
    lines.append(f'updated: "{note.updated}"')
    if note.author:
        lines.append(f'author: "{_yaml_escape(note.author)}"')
    else:
        lines.append("author: null")
    if note.tags:
        tags_str = ", ".join(f'"{_yaml_escape(t)}"' for t in note.tags)
        lines.append(f"tags: [{tags_str}]")
    else:
        lines.append("tags: []")
    if note.attachments:
        lines.append("attachments:")
        for att in note.attachments:
            lines.append(f'  - hash: "{att["hash"]}"')
            lines.append(f'    type: "{att["type"]}"')
    else:
        lines.append("attachments: []")
    lines.append(f'transcription_state: "{note.transcription_state}"')
    if note.languages:
        langs_str = ", ".join(f'"{_yaml_escape(lang)}"' for lang in note.languages)
        lines.append(f"languages: [{langs_str}]")
    else:
        lines.append("languages: []")
    lines.append("---")
    return "\n".join(lines)


def _yaml_escape(s: str) -> str:
    """YAML double-quoted scalar として安全な形へエスケープする．

    json.dumps の double-quoted 文字列リテラルは YAML double-quoted scalar と
    互換のため，改行・タブ等の制御文字を含むタイトルでもフロントマターが壊れない．
    """
    return json.dumps(s, ensure_ascii=False)[1:-1]


def _resolve_collision(output_dir: Path, base_name: str) -> Path:
    path = output_dir / base_name
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = output_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ENEX (Evernote エクスポート) を Markdown へ変換する"
    )
    parser.add_argument("enex_path", type=Path, help="入力 ENEX ファイルのパス")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="出力先ディレクトリ（無ければ作成する）",
    )
    args = parser.parse_args(argv)

    if not args.enex_path.exists():
        print(f"ENEX ファイルが見つかりません: {args.enex_path}", file=sys.stderr)
        return 2

    written = write_notes(parse_enex(args.enex_path), args.output_dir)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
