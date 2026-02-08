from __future__ import annotations

import html as html_lib
import re
from typing import Optional

from ..utils.strings import slugify_label


# Math blocks: $$...$$ or \[...\]
_MATH_BLOCK_RE = re.compile(r"(?s)(\$\$.*?\$\$|\\\[.*?\\\])")
# Bracketed inline math: \( ... \)
_MATH_BRACKET_RE = re.compile(r"(?s)(\\\(.*?\\\))")
_MERMAID_CODE_BLOCK_RE = re.compile(r'(?is)<pre><code(?: class="([^"]*)")?>(.*?)</code></pre>')
_HEADING_RE = re.compile(r"(?is)<h([23])([^>]*)>(.*?)</h\1>")
_HEADING_ID_RE = re.compile(r'(?i)\bid\s*=\s*"([^"]+)"')


def _mask_math_segments(text: str) -> tuple[str, list[str]]:
    placeholders: list[str] = []

    def replace(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"@@MATH{len(placeholders) - 1}@@"

    def looks_like_math(payload: str) -> bool:
        return bool(re.search(r"\\[A-Za-z]+|[_^{}]", payload))

    masked = _MATH_BLOCK_RE.sub(replace, text)
    masked = _MATH_BRACKET_RE.sub(replace, masked)

    out: list[str] = []
    i = 0
    length = len(masked)
    while i < length:
        ch = masked[i]
        if ch == "$":
            if i > 0 and masked[i - 1] == "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 < length and masked[i + 1] == "$":
                j = i + 2
                while j + 1 < length:
                    if masked[j] == "$" and masked[j + 1] == "$":
                        segment = masked[i : j + 2]
                        placeholders.append(segment)
                        out.append(f"@@MATH{len(placeholders) - 1}@@")
                        i = j + 2
                        break
                    j += 1
                else:
                    out.append(ch)
                    i += 1
                continue
            j = i + 1
            while j < length:
                if masked[j] == "$":
                    if masked[j - 1] == "\\":
                        j += 1
                        continue
                    segment = masked[i : j + 1]
                    payload = segment[1:-1].strip()
                    if payload and (not segment[1].isspace() or looks_like_math(payload)):
                        placeholders.append(segment)
                        out.append(f"@@MATH{len(placeholders) - 1}@@")
                        i = j + 1
                        break
                    out.append(ch)
                    i += 1
                    break
                j += 1
            else:
                out.append(ch)
                i += 1
            continue
        out.append(ch)
        i += 1

    return "".join(out), placeholders


def _unmask_math_segments(html_text: str, placeholders: list[str]) -> str:
    if not placeholders:
        return html_text
    restored = html_text
    for idx, segment in enumerate(placeholders):
        safe_segment = re.sub(r"(?<!\\\\)#", r"\\#", segment)
        safe = html_lib.escape(safe_segment)
        restored = restored.replace(f"@@MATH{idx}@@", safe)
    return restored


def markdown_to_html(markdown_text: str) -> str:
    try:
        import markdown  # type: ignore
    except Exception:
        escaped = html_lib.escape(markdown_text)
        return f"<pre>{escaped}</pre>"
    masked, placeholders = _mask_math_segments(markdown_text)
    html_text = markdown.markdown(masked, extensions=["extra", "tables", "fenced_code"])
    return _unmask_math_segments(html_text, placeholders)


def transform_mermaid_code_blocks(body_html: str) -> tuple[str, bool]:
    has_mermaid = False

    def replace(match: re.Match[str]) -> str:
        nonlocal has_mermaid
        class_attr = (match.group(1) or "").lower()
        if "mermaid" not in class_attr:
            return match.group(0)
        raw = html_lib.unescape(match.group(2) or "").strip()
        if not raw:
            return ""
        has_mermaid = True
        safe = html_lib.escape(raw)
        return (
            "<figure class=\"report-figure report-diagram\">"
            f"<div class=\"mermaid\">{safe}</div>"
            "</figure>"
        )

    transformed = _MERMAID_CODE_BLOCK_RE.sub(replace, body_html or "")
    return transformed, has_mermaid


def _strip_html_tags(text: str) -> str:
    no_tags = re.sub(r"(?is)<[^>]+>", "", text or "")
    return html_lib.unescape(no_tags).strip()


def prepare_sidebar_toc(body_html: str) -> tuple[str, str]:
    entries: list[tuple[int, str, str]] = []
    used_ids: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        level = int(match.group(1))
        attrs = match.group(2) or ""
        inner = match.group(3) or ""
        label = _strip_html_tags(inner)
        if not label:
            return match.group(0)
        existing = _HEADING_ID_RE.search(attrs)
        if existing:
            section_id = existing.group(1).strip()
        else:
            base = slugify_label(label) or f"section-{len(entries) + 1}"
            section_id = base
            seq = 2
            while section_id in used_ids:
                section_id = f"{base}-{seq}"
                seq += 1
            attrs = f'{attrs} id="{section_id}"'
        used_ids.add(section_id)
        entries.append((level, section_id, label))
        return f"<h{level}{attrs}>{inner}</h{level}>"

    updated_html = _HEADING_RE.sub(replace, body_html or "")
    if not entries:
        return updated_html, ""

    toc_items = []
    for level, section_id, label in entries:
        item_class = "toc-item toc-sub" if level >= 3 else "toc-item"
        toc_items.append(
            f'<a class="{item_class}" href="#{html_lib.escape(section_id, quote=True)}">'
            f"{html_lib.escape(label)}</a>"
        )
    toc_html = (
        "<aside class=\"toc-sidebar\" id=\"toc-sidebar\">"
        "<div class=\"toc-title\">Contents</div>"
        f"<nav class=\"toc-nav\">{''.join(toc_items)}</nav>"
        "</aside>"
    )
    return updated_html, toc_html


def html_to_text(html_text: str) -> str:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        BeautifulSoup = None

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    cleaned = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\\1>", "", html_text)
    cleaned = re.sub(r"(?is)<br\\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?is)</p>", "\n\n", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", "", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def render_viewer_html(title: str, body_html: str) -> str:
    safe_title = html_lib.escape(title)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{safe_title}</title>\n"
        "  <script>\n"
        "    window.MathJax = {\n"
        "      tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] },\n"
        "      svg: { fontCache: 'global' }\n"
        "    };\n"
        "  </script>\n"
        "  <script src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js\"></script>\n"
        "  <style>\n"
        "    body { font-family: \"Iowan Old Style\", Georgia, serif; margin: 0; color: #1d1c1a; }\n"
        "    header { padding: 16px 20px; border-bottom: 1px solid #e7dfd2; background: #f7f4ee; }\n"
        "    header h1 { margin: 0; font-size: 1.1rem; }\n"
        "    main { padding: 20px; }\n"
        "    .meta-block { background: #fdf7ea; border: 1px solid #e7dfd2; padding: 12px 14px; margin-bottom: 16px; }\n"
        "    .meta-block p { margin: 0 0 6px 0; }\n"
        "    .meta-block p:last-child { margin-bottom: 0; }\n"
        "    pre { white-space: pre-wrap; font-family: \"SFMono-Regular\", Consolas, monospace; font-size: 0.95rem; }\n"
        "    code { font-family: \"SFMono-Regular\", Consolas, monospace; }\n"
        "    table { border-collapse: collapse; width: 100%; }\n"
        "    th, td { border: 1px solid #e7dfd2; padding: 8px 10px; text-align: left; }\n"
        "    th { background: #f6f1e8; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        f"  <header><h1>{safe_title}</h1></header>\n"
        f"  <main>{body_html}</main>\n"
        "  <script>\n"
        "    document.querySelectorAll('a').forEach((link) => {\n"
        "      link.setAttribute('target', '_blank');\n"
        "      link.setAttribute('rel', 'noopener');\n"
        "    });\n"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
    )


def wrap_html(
    title: str,
    body_html: str,
    template_name: Optional[str] = None,
    theme_css: Optional[str] = None,
    theme_href: Optional[str] = None,
    extra_body_class: Optional[str] = None,
    with_mermaid: bool = False,
    layout: Optional[str] = None,
) -> str:
    safe_title = html_lib.escape(title)
    template_class = ""
    if template_name:
        template_class = f" template-{slugify_label(template_name)}"
    extra_class = f" {extra_body_class}" if extra_body_class else ""
    theme_link = ""
    if theme_href:
        safe_href = html_lib.escape(theme_href, quote=True)
        theme_link = f"  <link rel=\"stylesheet\" href=\"{safe_href}\" />\n"
    layout_mode = (layout or "").strip().lower()
    toc_html = ""
    if layout_mode == "sidebar_toc":
        body_html, toc_html = prepare_sidebar_toc(body_html)
    mermaid_head = ""
    mermaid_tail = ""
    if with_mermaid:
        mermaid_head = (
            "  <script src=\"https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js\"></script>\n"
        )
        mermaid_tail = (
            "  <script>\n"
            "    if (window.mermaid) {\n"
            "      mermaid.initialize({\n"
            "        startOnLoad: true,\n"
            "        securityLevel: 'strict',\n"
            "        theme: 'neutral',\n"
            "      });\n"
            "    }\n"
            "  </script>\n"
        )
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{safe_title}</title>\n"
        "  <script>\n"
        "    window.MathJax = {\n"
        "      tex: { inlineMath: [['$', '$'], ['\\\\(', '\\\\)']], displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']] },\n"
        "      svg: { fontCache: 'global' }\n"
        "    };\n"
        "  </script>\n"
        "  <script src=\"https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js\"></script>\n"
        f"{mermaid_head}"
        "  <style>\n"
        "    @import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@300;500;700&family=Space+Grotesk:wght@400;600;700&family=JetBrains+Mono:wght@400;600&display=swap');\n"
        "    :root {\n"
        "      --bg: #0b0f14;\n"
        "      --bg-2: #121821;\n"
        "      --card: rgba(255, 255, 255, 0.06);\n"
        "      --site-ink: #f5f7fb;\n"
        "      --site-muted: rgba(245, 247, 251, 0.65);\n"
        "      --accent: #4ee0b5;\n"
        "      --accent-2: #6bd3ff;\n"
        "      --edge: rgba(255, 255, 255, 0.15);\n"
        "      --glow: rgba(78, 224, 181, 0.25);\n"
        "      --ink: #0b1220;\n"
        "      --muted: #425066;\n"
        "      --accent-strong: #2fb892;\n"
        "      --paper: rgba(255, 255, 255, 0.94);\n"
        "      --paper-strong: #ffffff;\n"
        "      --paper-alt: rgba(240, 245, 255, 0.6);\n"
        "      --rule: rgba(15, 23, 42, 0.12);\n"
        "      --shadow: 0 28px 70px rgba(15, 23, 42, 0.22);\n"
        "      --chrome-ink: #f5f7fb;\n"
        "      --chrome-muted: rgba(245, 247, 251, 0.66);\n"
        "      --chrome-surface: rgba(11, 17, 29, 0.62);\n"
        "      --chrome-border: rgba(255, 255, 255, 0.16);\n"
        "      --chrome-hover-soft: rgba(255, 255, 255, 0.06);\n"
        "      --chrome-hover: rgba(255, 255, 255, 0.08);\n"
        "      --link: var(--accent-2);\n"
        "      --link-hover: var(--accent);\n"
        "      --page-bg: radial-gradient(1200px 600px at 12% -10%, var(--glow), transparent 60%),\n"
        "        radial-gradient(900px 540px at 92% 8%, rgba(107, 211, 255, 0.18), transparent 55%),\n"
        "        linear-gradient(180deg, #0b111d 0%, var(--bg-2) 45%, var(--bg) 100%);\n"
        "      --body-font: \"Fraunces\", \"Charter\", Georgia, serif;\n"
        "      --heading-font: \"Space Grotesk\", \"Segoe UI\", sans-serif;\n"
        "      --ui-font: \"Space Grotesk\", \"Segoe UI\", sans-serif;\n"
        "      --mono-font: \"JetBrains Mono\", \"Consolas\", monospace;\n"
        "    }\n"
        "    :root[data-theme=\"sky\"] {\n"
        "      --bg: #0b1220;\n"
        "      --bg-2: #0f1b2e;\n"
        "      --card: rgba(255, 255, 255, 0.06);\n"
        "      --site-ink: #f4f7ff;\n"
        "      --site-muted: rgba(244, 247, 255, 0.62);\n"
        "      --accent: #64b5ff;\n"
        "      --accent-2: #8fd1ff;\n"
        "      --edge: rgba(255, 255, 255, 0.18);\n"
        "      --glow: rgba(100, 181, 255, 0.28);\n"
        "      --accent-strong: #3f8ed1;\n"
        "    }\n"
        "    :root[data-theme=\"crimson\"] {\n"
        "      --bg: #120a0d;\n"
        "      --bg-2: #1c0f16;\n"
        "      --card: rgba(255, 255, 255, 0.06);\n"
        "      --site-ink: #fff5f7;\n"
        "      --site-muted: rgba(255, 245, 247, 0.62);\n"
        "      --accent: #ff6b81;\n"
        "      --accent-2: #ff9aa9;\n"
        "      --edge: rgba(255, 255, 255, 0.15);\n"
        "      --glow: rgba(255, 107, 129, 0.25);\n"
        "      --accent-strong: #e3546d;\n"
        "    }\n"
        "    * { box-sizing: border-box; }\n"
        "    html { scroll-behavior: smooth; }\n"
        "    body {\n"
        "      margin: 0;\n"
        "      min-height: 100vh;\n"
        "      color: var(--site-ink);\n"
        "      background: var(--page-bg);\n"
        "      font-family: var(--body-font);\n"
        "      line-height: 1.7;\n"
        "      letter-spacing: -0.01em;\n"
        "      overflow-x: hidden;\n"
        "    }\n"
        "    .backdrop {\n"
        "      position: fixed;\n"
        "      inset: 0;\n"
        "      pointer-events: none;\n"
        "      z-index: 0;\n"
        "      overflow: hidden;\n"
        "    }\n"
        "    .orb {\n"
        "      position: absolute;\n"
        "      border-radius: 999px;\n"
        "      opacity: 0.6;\n"
        "      mix-blend-mode: screen;\n"
        "      filter: blur(0px);\n"
        "      animation: float 16s ease-in-out infinite;\n"
        "    }\n"
        "    .orb-1 {\n"
        "      width: 520px;\n"
        "      height: 520px;\n"
        "      background: radial-gradient(circle at 30% 30%, rgba(255, 122, 89, 0.55), transparent 60%);\n"
        "      top: -220px;\n"
        "      left: -160px;\n"
        "    }\n"
        "    .orb-2 {\n"
        "      width: 440px;\n"
        "      height: 440px;\n"
        "      background: radial-gradient(circle at 60% 40%, rgba(14, 165, 164, 0.5), transparent 62%);\n"
        "      top: 80px;\n"
        "      right: -120px;\n"
        "      animation-delay: -4s;\n"
        "    }\n"
        "    .orb-3 {\n"
        "      width: 340px;\n"
        "      height: 340px;\n"
        "      background: radial-gradient(circle at 50% 50%, rgba(148, 163, 184, 0.35), transparent 70%);\n"
        "      bottom: -180px;\n"
        "      left: 22%;\n"
        "      animation-delay: -8s;\n"
        "    }\n"
        "    .page {\n"
        "      position: relative;\n"
        "      z-index: 1;\n"
        "      max-width: 1040px;\n"
        "      margin: 56px auto 96px;\n"
        "      padding: 0 28px;\n"
        "    }\n"
        "    .toc-sidebar {\n"
        "      display: none;\n"
        "      position: fixed;\n"
        "      left: max(18px, calc(50% - 700px));\n"
        "      top: 64px;\n"
        "      width: 250px;\n"
        "      max-height: calc(100vh - 96px);\n"
        "      overflow-y: auto;\n"
        "      padding: 16px 12px;\n"
        "      border-radius: 14px;\n"
        "      border: 1px solid var(--chrome-border);\n"
        "      background: var(--chrome-surface);\n"
        "      backdrop-filter: blur(8px);\n"
        "      z-index: 2;\n"
        "    }\n"
        "    .toc-title {\n"
        "      font-family: var(--ui-font);\n"
        "      font-size: 0.78rem;\n"
        "      letter-spacing: 0.2em;\n"
        "      text-transform: uppercase;\n"
        "      color: var(--chrome-muted);\n"
        "      margin-bottom: 10px;\n"
        "    }\n"
        "    .toc-nav {\n"
        "      display: flex;\n"
        "      flex-direction: column;\n"
        "      gap: 4px;\n"
        "    }\n"
        "    .toc-item {\n"
        "      display: block;\n"
        "      color: var(--chrome-ink);\n"
        "      text-decoration: none;\n"
        "      font-family: var(--ui-font);\n"
        "      font-size: 0.88rem;\n"
        "      line-height: 1.35;\n"
        "      opacity: 0.82;\n"
        "      border-left: 2px solid transparent;\n"
        "      padding: 6px 8px;\n"
        "      border-radius: 8px;\n"
        "      transition: all 0.18s ease;\n"
        "    }\n"
        "    .toc-item:hover {\n"
        "      opacity: 1;\n"
        "      border-left-color: var(--accent);\n"
        "      background: var(--chrome-hover-soft);\n"
        "    }\n"
        "    .toc-item.active {\n"
        "      opacity: 1;\n"
        "      border-left-color: var(--accent);\n"
        "      background: var(--chrome-hover);\n"
        "    }\n"
        "    .toc-sub {\n"
        "      margin-left: 12px;\n"
        "      font-size: 0.82rem;\n"
        "      opacity: 0.75;\n"
        "    }\n"
        "    body.layout-sidebar_toc .page {\n"
        "      max-width: 980px;\n"
        "    }\n"
        "    @media (min-width: 1300px) {\n"
        "      body.layout-sidebar_toc .toc-sidebar {\n"
        "        display: block;\n"
        "      }\n"
        "      body.layout-sidebar_toc .page {\n"
        "        margin-left: max(300px, calc(50% - 370px));\n"
        "        margin-right: 56px;\n"
        "      }\n"
        "    }\n"
        "    .masthead {\n"
        "      display: flex;\n"
        "      flex-direction: column;\n"
        "      gap: 12px;\n"
        "      padding: 18px 22px 22px;\n"
        "      border: 1px solid var(--masthead-border, rgba(226, 232, 240, 0.18));\n"
        "      border-radius: 18px;\n"
        "      background: var(--masthead-bg, rgba(10, 14, 20, 0.55));\n"
        "      backdrop-filter: blur(8px);\n"
        "      margin-bottom: 36px;\n"
        "      color: var(--masthead-text, #f8fafc);\n"
        "      animation: fadeIn 0.7s ease-out both;\n"
        "    }\n"
        "    .masthead-top {\n"
        "      display: flex;\n"
        "      align-items: center;\n"
        "      justify-content: space-between;\n"
        "      gap: 16px;\n"
        "    }\n"
        "    .kicker {\n"
        "      font-family: var(--ui-font);\n"
        "      font-size: 0.82rem;\n"
        "      letter-spacing: 0.28em;\n"
        "      text-transform: uppercase;\n"
        "      color: var(--masthead-kicker, rgba(255, 255, 255, 0.68));\n"
        "    }\n"
        "    .back-link {\n"
        "      display: none;\n"
        "      align-items: center;\n"
        "      gap: 8px;\n"
        "      font-family: var(--ui-font);\n"
        "      font-size: 0.78rem;\n"
        "      text-decoration: none;\n"
        "      padding: 6px 12px;\n"
        "      border-radius: 999px;\n"
        "      border: 1px solid var(--masthead-link-border, rgba(255, 255, 255, 0.2));\n"
        "      color: var(--masthead-link, rgba(255, 255, 255, 0.78));\n"
        "      background: var(--masthead-link-bg, rgba(15, 23, 42, 0.35));\n"
        "      transition: all 0.2s ease;\n"
        "    }\n"
        "    .back-link:hover {\n"
        "      color: #fff;\n"
        "      border-color: rgba(255, 255, 255, 0.45);\n"
        "      transform: translateY(-1px);\n"
        "    }\n"
        "    .report-title {\n"
        "      font-family: var(--heading-font);\n"
        "      font-size: clamp(2.2rem, 3.6vw, 3.6rem);\n"
        "      margin: 0;\n"
        "      line-height: 1.08;\n"
        "      letter-spacing: -0.03em;\n"
        "      color: var(--masthead-title, #f8fafc);\n"
        "    }\n"
        "    .report-deck {\n"
        "      color: var(--masthead-deck, rgba(226, 232, 240, 0.8));\n"
        "      font-size: 1.05rem;\n"
        "      max-width: 720px;\n"
        "    }\n"
        "    .article {\n"
        "      background: var(--paper);\n"
        "      color: var(--ink);\n"
        "      border: 1px solid rgba(255, 255, 255, 0.6);\n"
        "      border-radius: 22px;\n"
        "      padding: 40px 44px;\n"
        "      box-shadow: var(--shadow);\n"
        "      backdrop-filter: blur(8px);\n"
        "      animation: rise 0.8s ease-out both;\n"
        "    }\n"
        "    .article > * { animation: rise 0.6s ease-out both; }\n"
        "    .article > *:nth-child(1) { animation-delay: 0.05s; }\n"
        "    .article > *:nth-child(2) { animation-delay: 0.1s; }\n"
        "    .article > *:nth-child(3) { animation-delay: 0.15s; }\n"
        "    .article > *:nth-child(4) { animation-delay: 0.2s; }\n"
        "    .article > *:nth-child(5) { animation-delay: 0.25s; }\n"
        "    .article h1, .article h2, .article h3, .article h4 {\n"
        "      font-family: var(--heading-font);\n"
        "      color: var(--ink);\n"
        "    }\n"
        "    .article h1 { font-size: 2rem; margin-top: 0; }\n"
        "    .article h2 {\n"
        "      font-size: 1.55rem;\n"
        "      margin-top: 2.6rem;\n"
        "      padding-top: 1rem;\n"
        "      border-top: 1px solid var(--rule);\n"
        "      position: relative;\n"
        "      padding-left: 18px;\n"
        "    }\n"
        "    .article h2::before {\n"
        "      content: '';\n"
        "      position: absolute;\n"
        "      left: 0;\n"
        "      top: 1.45rem;\n"
        "      width: 8px;\n"
        "      height: 8px;\n"
        "      border-radius: 999px;\n"
        "      background: var(--accent-strong);\n"
        "    }\n"
        "    .article h3 { font-size: 1.2rem; margin-top: 1.7rem; color: #1f2937; }\n"
        "    .article h2, .article h3 { scroll-margin-top: 92px; }\n"
        "    .article p { font-size: 1.05rem; }\n"
        "    .article ul, .article ol { padding-left: 1.4rem; }\n"
        "    .article blockquote {\n"
        "      margin: 1.4rem 0;\n"
        "      padding: 1rem 1.2rem;\n"
        "      border-left: 3px solid var(--accent);\n"
        "      background: rgba(15, 23, 42, 0.04);\n"
        "    }\n"
        "    .article .misc-block {\n"
        "      margin: 1.2rem 0 1.4rem;\n"
        "      padding: 1rem 1.1rem;\n"
        "      border-radius: 12px;\n"
        "      border: 1px solid rgba(15, 23, 42, 0.14);\n"
        "      background: rgba(148, 163, 184, 0.1);\n"
        "    }\n"
        "    .article .misc-block ul {\n"
        "      margin: 0;\n"
        "      padding-left: 1.2rem;\n"
        "    }\n"
        "    .article .misc-block li {\n"
        "      margin: 0.35rem 0;\n"
        "      color: var(--muted);\n"
        "      font-size: 0.98rem;\n"
        "    }\n"
        "    .article .misc-block.ai-disclosure {\n"
        "      border-color: var(--accent);\n"
        "      background: rgba(78, 224, 181, 0.08);\n"
        "    }\n"
        "    .article .misc-block.ai-disclosure p {\n"
        "      margin: 0 0 0.55rem;\n"
        "      color: var(--ink);\n"
        "      font-family: var(--ui-font);\n"
        "      letter-spacing: 0.01em;\n"
        "    }\n"
        "    .article a {\n"
        "      color: var(--link);\n"
        "      text-decoration: none;\n"
        "      border-bottom: 1px solid transparent;\n"
        "      transition: all 0.2s ease;\n"
        "    }\n"
        "    .article a:hover { color: var(--link-hover); border-bottom-color: var(--link-hover); }\n"
        "    .article code {\n"
        "      font-family: var(--mono-font);\n"
        "      font-size: 0.94rem;\n"
        "      background: rgba(148, 163, 184, 0.14);\n"
        "      padding: 2px 6px;\n"
        "      border-radius: 6px;\n"
        "    }\n"
        "    .article pre {\n"
        "      background: rgba(148, 163, 184, 0.18);\n"
        "      padding: 1rem 1.1rem;\n"
        "      border-radius: 12px;\n"
        "      overflow-x: auto;\n"
        "    }\n"
        "    .article figure.report-figure {\n"
        "      margin: 1.8rem 0;\n"
        "      padding: 0;\n"
        "      width: 100%;\n"
        "      max-width: 100%;\n"
        "      overflow: hidden;\n"
        "    }\n"
        "    .article figure.report-figure img {\n"
        "      display: block;\n"
        "      width: 100%;\n"
        "      max-width: 100%;\n"
        "      height: auto;\n"
        "      max-height: 70vh;\n"
        "      object-fit: contain;\n"
        "      border-radius: 14px;\n"
        "      background: rgba(15, 23, 42, 0.04);\n"
        "      box-shadow: 0 18px 50px rgba(15, 23, 42, 0.18);\n"
        "    }\n"
        "    .article figure.report-figure figcaption {\n"
        "      margin-top: 0.65rem;\n"
        "      font-size: 0.95rem;\n"
        "      color: var(--muted);\n"
        "    }\n"
        "    .article figure.report-diagram {\n"
        "      background: rgba(15, 23, 42, 0.04);\n"
        "      border: 1px solid rgba(15, 23, 42, 0.1);\n"
        "      border-radius: 14px;\n"
        "      padding: 0.9rem;\n"
        "    }\n"
        "    .article .mermaid {\n"
        "      display: flex;\n"
        "      justify-content: center;\n"
        "      overflow-x: auto;\n"
        "      min-height: 40px;\n"
        "    }\n"
        "    .article .mermaid svg {\n"
        "      max-width: 100% !important;\n"
        "      height: auto;\n"
        "    }\n"
        "    .article table { border-collapse: collapse; width: 100%; margin: 1.4rem 0; }\n"
        "    .article th, .article td { border: 1px solid var(--rule); padding: 10px 12px; }\n"
        "    .article th { background: rgba(148, 163, 184, 0.15); text-align: left; }\n"
        "    .article tr:nth-child(even) td { background: rgba(148, 163, 184, 0.08); }\n"
        "    .article hr { border: none; border-top: 1px solid var(--rule); margin: 2rem 0; }\n"
        "    .viewer-overlay {\n"
        "      position: fixed;\n"
        "      inset: 0;\n"
        "      background: rgba(15, 23, 42, 0.6);\n"
        "      opacity: 0;\n"
        "      pointer-events: none;\n"
        "      transition: opacity 0.2s ease;\n"
        "      z-index: 20;\n"
        "    }\n"
        "    .viewer-overlay.open { opacity: 1; pointer-events: auto; }\n"
        "    .viewer-panel {\n"
        "      position: fixed;\n"
        "      top: 0;\n"
        "      right: 0;\n"
        "      height: 100vh;\n"
        "      width: min(480px, 92vw);\n"
        "      background: #fff;\n"
        "      box-shadow: -20px 0 60px rgba(15, 23, 42, 0.25);\n"
        "      transform: translateX(105%);\n"
        "      transition: transform 0.25s ease;\n"
        "      z-index: 30;\n"
        "      display: flex;\n"
        "      flex-direction: column;\n"
        "    }\n"
        "    .viewer-panel.open { transform: translateX(0); }\n"
        "    .viewer-header {\n"
        "      display: flex;\n"
        "      align-items: center;\n"
        "      justify-content: space-between;\n"
        "      gap: 8px;\n"
        "      padding: 14px 16px;\n"
        "      border-bottom: 1px solid #e2e8f0;\n"
        "      background: #f8fafc;\n"
        "    }\n"
        "    .viewer-title { font-size: 0.95rem; color: var(--ink); flex: 1; }\n"
        "    .viewer-actions { display: flex; gap: 8px; align-items: center; }\n"
        "    .viewer-actions a {\n"
        "      font-size: 0.78rem;\n"
        "      text-decoration: none;\n"
        "      color: var(--link);\n"
        "    }\n"
        "    .viewer-close {\n"
        "      border: none;\n"
        "      background: #1f2937;\n"
        "      color: #fff;\n"
        "      width: 26px;\n"
        "      height: 26px;\n"
        "      border-radius: 999px;\n"
        "      cursor: pointer;\n"
        "    }\n"
        "    .viewer-frame { flex: 1; border: none; width: 100%; border-radius: 0 0 16px 16px; }\n"
        "    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }\n"
        "    @keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }\n"
        "    @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(18px); } }\n"
        f"    {'' if theme_href else (theme_css or '')}\n"
        "  </style>\n"
        f"{theme_link}"
        "</head>\n"
        f"<body class=\"theme-coral{template_class}{extra_class}{(' layout-' + layout_mode) if layout_mode else ''}\">\n"
        "  <div class=\"backdrop\">\n"
        "    <div class=\"orb orb-1\"></div>\n"
        "    <div class=\"orb orb-2\"></div>\n"
        "    <div class=\"orb orb-3\"></div>\n"
        "  </div>\n"
        f"  {toc_html}\n"
        "  <div class=\"page\">\n"
        "    <header class=\"masthead\">\n"
        "      <div class=\"masthead-top\">\n"
        "        <div class=\"kicker\">FEDERLICHT</div>\n"
        "        <a class=\"back-link\" id=\"back-link\" href=\"#\">목록으로</a>\n"
        "      </div>\n"
        f"      <div class=\"report-title\">{safe_title}</div>\n"
        "      <div class=\"report-deck\">Research review and tech survey</div>\n"
        "    </header>\n"
        "    <main class=\"article\">\n"
        f"{body_html}\n"
        "    </main>\n"
        "  </div>\n"
        "  <div id=\"viewer-overlay\" class=\"viewer-overlay\"></div>\n"
        "  <aside id=\"viewer-panel\" class=\"viewer-panel\" aria-hidden=\"true\">\n"
        "    <div class=\"viewer-header\">\n"
        "      <div class=\"viewer-title\" id=\"viewer-title\">Source preview</div>\n"
        "      <div class=\"viewer-actions\">\n"
        "        <a id=\"viewer-raw\" href=\"#\" target=\"_blank\" rel=\"noopener\">Open raw</a>\n"
        "        <button class=\"viewer-close\" id=\"viewer-close\" aria-label=\"Close\">x</button>\n"
        "      </div>\n"
        "    </div>\n"
        "    <iframe id=\"viewer-frame\" class=\"viewer-frame\" title=\"Source preview\"></iframe>\n"
        "  </aside>\n"
        "  <script>\n"
        "    (function() {\n"
        "      const params = new URLSearchParams(window.location.search);\n"
        "      const themeParam = params.get('theme');\n"
        "      const storedTheme = localStorage.getItem('federlicht.theme');\n"
        "      const theme = themeParam || storedTheme;\n"
        "      if (theme) {\n"
        "        document.documentElement.dataset.theme = theme;\n"
        "        localStorage.setItem('federlicht.theme', theme);\n"
        "      }\n"
        "      const backLink = document.getElementById('back-link');\n"
        "      if (backLink) {\n"
        "        const path = window.location.pathname.replace(/\\\\/g, '/');\n"
        "        const idx = path.lastIndexOf('/runs/');\n"
        "        if (idx !== -1) {\n"
        "          backLink.href = `${path.slice(0, idx)}/index.html`;\n"
        "          backLink.style.display = 'inline-flex';\n"
        "        }\n"
        "      }\n"
        "      const panel = document.getElementById('viewer-panel');\n"
        "      const overlay = document.getElementById('viewer-overlay');\n"
        "      const frame = document.getElementById('viewer-frame');\n"
        "      const rawLink = document.getElementById('viewer-raw');\n"
        "      const title = document.getElementById('viewer-title');\n"
        "      const closeBtn = document.getElementById('viewer-close');\n"
        "      function closeViewer() {\n"
        "        panel.classList.remove('open');\n"
        "        overlay.classList.remove('open');\n"
        "        panel.setAttribute('aria-hidden', 'true');\n"
        "        frame.src = 'about:blank';\n"
        "      }\n"
        "      function openViewer(viewer, raw, label) {\n"
        "        frame.src = viewer;\n"
        "        rawLink.href = raw || viewer;\n"
        "        title.textContent = label || 'Source preview';\n"
        "        panel.classList.add('open');\n"
        "        overlay.classList.add('open');\n"
        "        panel.setAttribute('aria-hidden', 'false');\n"
        "      }\n"
        "      document.querySelectorAll('.viewer-link').forEach((link) => {\n"
        "        link.addEventListener('click', (ev) => {\n"
        "          ev.preventDefault();\n"
        "          const viewer = link.getAttribute('data-viewer') || link.href;\n"
        "          const raw = link.getAttribute('data-raw');\n"
        "          const label = link.textContent || 'Source preview';\n"
        "          if (viewer) openViewer(viewer, raw, label);\n"
        "        });\n"
        "      });\n"
        "      overlay.addEventListener('click', closeViewer);\n"
        "      closeBtn.addEventListener('click', closeViewer);\n"
        "      const tocLinks = Array.from(document.querySelectorAll('.toc-item'));\n"
        "      const tocSections = tocLinks\n"
        "        .map((link) => {\n"
        "          const id = (link.getAttribute('href') || '').replace('#', '');\n"
        "          if (!id) return null;\n"
        "          const section = document.getElementById(id);\n"
        "          if (!section) return null;\n"
        "          return { link, section };\n"
        "        })\n"
        "        .filter(Boolean);\n"
        "      if (tocSections.length) {\n"
        "        tocLinks.forEach((link) => {\n"
        "          link.addEventListener('click', (ev) => {\n"
        "            const href = link.getAttribute('href') || '';\n"
        "            if (!href.startsWith('#')) return;\n"
        "            const target = document.getElementById(href.slice(1));\n"
        "            if (!target) return;\n"
        "            ev.preventDefault();\n"
        "            target.scrollIntoView({ behavior: 'smooth', block: 'start' });\n"
        "            if (history && history.replaceState) {\n"
        "              history.replaceState(null, '', href);\n"
        "            }\n"
        "          });\n"
        "        });\n"
        "        \n"
        "        const updateToc = () => {\n"
        "          const threshold = window.scrollY + 180;\n"
        "          let active = null;\n"
        "          for (const item of tocSections) {\n"
        "            if (item.section.offsetTop <= threshold) active = item;\n"
        "          }\n"
        "          tocLinks.forEach((node) => node.classList.remove('active'));\n"
        "          if (active) active.link.classList.add('active');\n"
        "        };\n"
        "        updateToc();\n"
        "        window.addEventListener('scroll', updateToc, { passive: true });\n"
        "      }\n"
        "    })();\n"
        "  </script>\n"
        f"{mermaid_tail}"
        "</body>\n"
        "</html>\n"
    )
