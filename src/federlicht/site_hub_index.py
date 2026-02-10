from __future__ import annotations

import json


def build_site_index_html(manifest: dict, refresh_minutes: int = 10) -> str:
    manifest_json = json.dumps(manifest, ensure_ascii=False)
    manifest_json = manifest_json.replace("</", "<\\/")
    refresh_ms = max(refresh_minutes, 1) * 60 * 1000
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Federlicht Report Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@300;600;700&family=Space+Grotesk:wght@400;500;700&family=Noto+Sans+KR:wght@300;400;500;700&display=swap" rel="stylesheet">
    <style>
      :root {{
        --bg: #0b0f14;
        --bg-2: #121821;
        --card: rgba(255, 255, 255, 0.06);
        --ink: #f5f7fb;
        --muted: rgba(245, 247, 251, 0.65);
        --accent: #4ee0b5;
        --accent-2: #6bd3ff;
        --edge: rgba(255, 255, 255, 0.15);
        --glow: rgba(78, 224, 181, 0.25);
      }}
      :root[data-theme="sky"] {{
        --bg: #0b1220;
        --bg-2: #0f1b2e;
        --card: rgba(255, 255, 255, 0.06);
        --ink: #f4f7ff;
        --muted: rgba(244, 247, 255, 0.62);
        --accent: #64b5ff;
        --accent-2: #8fd1ff;
        --edge: rgba(255, 255, 255, 0.18);
        --glow: rgba(100, 181, 255, 0.28);
      }}
      :root[data-theme="crimson"] {{
        --bg: #120a0d;
        --bg-2: #1c0f16;
        --card: rgba(255, 255, 255, 0.06);
        --ink: #fff5f7;
        --muted: rgba(255, 245, 247, 0.62);
        --accent: #ff6b81;
        --accent-2: #ff9aa9;
        --edge: rgba(255, 255, 255, 0.15);
        --glow: rgba(255, 107, 129, 0.25);
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Noto Sans KR", "Space Grotesk", sans-serif;
        color: var(--ink);
        background: radial-gradient(circle at 20% 20%, var(--glow), transparent 42%),
                    radial-gradient(circle at 80% 0%, rgba(107, 211, 255, 0.2), transparent 36%),
                    linear-gradient(160deg, #0a0d12 10%, #0f1622 60%, #0b0f14 100%);
        min-height: 100vh;
      }}
      .wrap {{
        max-width: 1200px;
        margin: 0 auto;
        padding: 48px 28px 120px;
      }}
      header.hero {{
        position: relative;
        border: 1px solid var(--edge);
        border-radius: 28px;
        padding: 48px;
        background: linear-gradient(140deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02));
        box-shadow: 0 40px 120px rgba(0,0,0,0.4);
        overflow: hidden;
      }}
      header.hero::after {{
        content: "";
        position: absolute;
        inset: -40% -20%;
        background: radial-gradient(circle, rgba(78, 224, 181, 0.12), transparent 60%);
        opacity: 0.8;
        pointer-events: none;
      }}
      .nav {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-size: 12px;
        color: var(--muted);
      }}
      .nav-actions {{
        display: inline-flex;
        align-items: center;
        gap: 12px;
      }}
      #theme-select {{
        background: transparent;
        color: var(--muted);
        border: 1px solid var(--edge);
        border-radius: 999px;
        padding: 6px 12px;
        font-size: 11px;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        cursor: pointer;
      }}
      #theme-select option {{
        color: #0b0f14;
      }}
      .nav .brand {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
      }}
      .pulse {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--accent);
        box-shadow: 0 0 12px var(--glow);
      }}
      .hero-grid {{
        display: grid;
        gap: 32px;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        margin-top: 36px;
      }}
      .hero h1 {{
        font-family: "Fraunces", serif;
        font-weight: 700;
        font-size: clamp(32px, 4.8vw, 56px);
        margin: 0 0 14px;
      }}
      .hero p {{
        margin: 0;
        font-size: 16px;
        color: var(--muted);
        line-height: 1.6;
      }}
      .cta {{
        display: flex;
        gap: 12px;
        margin-top: 24px;
        flex-wrap: wrap;
      }}
      .btn {{
        background: var(--accent);
        color: #071016;
        font-weight: 600;
        padding: 12px 18px;
        border-radius: 999px;
        text-decoration: none;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
      }}
      .btn.secondary {{
        background: transparent;
        color: var(--ink);
        border: 1px solid var(--edge);
      }}
      .btn:hover {{
        transform: translateY(-2px);
        box-shadow: 0 16px 32px rgba(78, 224, 181, 0.25);
      }}
      .stats {{
        display: flex;
        gap: 20px;
        flex-wrap: wrap;
        margin-top: 22px;
      }}
      .stat {{
        padding: 14px 18px;
        border-radius: 14px;
        border: 1px solid var(--edge);
        background: rgba(0, 0, 0, 0.25);
        min-width: 140px;
      }}
      .stat span {{
        display: block;
        font-family: "Space Grotesk", sans-serif;
        font-weight: 600;
        font-size: 20px;
      }}
      .section {{
        margin-top: 52px;
      }}
      .section h2 {{
        font-family: "Space Grotesk", sans-serif;
        font-weight: 600;
        font-size: 22px;
        margin: 0 0 10px;
      }}
      .section p {{
        margin: 0 0 24px;
        color: var(--muted);
      }}
      .filter-bar {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 18px;
      }}
      .filter-bar input,
      .filter-bar select {{
        background: rgba(0, 0, 0, 0.28);
        color: var(--ink);
        border: 1px solid var(--edge);
        border-radius: 12px;
        padding: 8px 12px;
        font-size: 12px;
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
      }}
      .filter-bar select option {{
        color: #0b0f14;
      }}
      .tabs {{
        margin-top: 18px;
        border: 1px solid var(--edge);
        border-radius: 18px;
        padding: 18px;
        background: rgba(0, 0, 0, 0.2);
      }}
      .tab-buttons {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 12px;
      }}
      .tab-button {{
        border: 1px solid var(--edge);
        background: transparent;
        color: var(--muted);
        padding: 6px 12px;
        border-radius: 999px;
        font-size: 12px;
        cursor: pointer;
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
      }}
      .tab-button.active {{
        background: var(--accent);
        color: #071016;
        border-color: transparent;
      }}
      .tab-panel {{
        display: none;
      }}
      .tab-panel.active {{
        display: block;
      }}
      .chip-list {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}
      .chip {{
        border: 1px solid var(--edge);
        background: transparent;
        color: var(--muted);
        border-radius: 999px;
        padding: 6px 12px;
        font-size: 12px;
        cursor: pointer;
      }}
      .chip strong {{
        color: var(--ink);
        font-weight: 600;
        margin-left: 6px;
      }}
      .insights {{
        display: grid;
        gap: 12px;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        margin-top: 14px;
      }}
      .insight-card {{
        border: 1px solid var(--edge);
        border-radius: 14px;
        padding: 14px;
        background: rgba(0, 0, 0, 0.22);
      }}
      .insight-card h4 {{
        margin: 0 0 8px;
        font-size: 12px;
        font-family: "Space Grotesk", sans-serif;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .insight-item {{
        font-size: 13px;
        color: var(--ink);
        display: flex;
        justify-content: space-between;
        margin-bottom: 6px;
      }}
      .word-cloud {{
        margin-top: 18px;
        padding: 18px;
        border-radius: 18px;
        border: 1px solid var(--edge);
        background: rgba(0, 0, 0, 0.24);
        position: relative;
        min-height: 220px;
        overflow: hidden;
      }}
      .word-cloud .word {{
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
        font-weight: 600;
        letter-spacing: 0.02em;
        position: absolute;
        white-space: nowrap;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.15);
        background: linear-gradient(120deg, rgba(255,255,255,0.12), rgba(255,255,255,0.04));
        transition: transform 0.25s ease, color 0.25s ease, border-color 0.25s ease, filter 0.25s ease;
        font-size: calc(12px + var(--weight, 0.4) * 20px);
        background-image: var(--cloud-gradient, linear-gradient(120deg, #6bd3ff, #4ee0b5));
        color: transparent;
        -webkit-background-clip: text;
        background-clip: text;
        text-shadow: 0 8px 18px rgba(0, 0, 0, 0.35);
        opacity: var(--cloud-opacity, 0.75);
        animation: cloudFloat var(--cloud-duration, 6s) ease-in-out infinite;
        animation-delay: var(--cloud-delay, 0s);
        transform: translate3d(0, 0, 0) rotate(var(--cloud-tilt, 0deg));
      }}
      .word-cloud .word:hover {{
        transform: translate3d(0, -6px, 0) rotate(var(--cloud-tilt, 0deg));
        filter: drop-shadow(0 12px 18px rgba(78, 224, 181, 0.3));
        border-color: var(--accent);
      }}
      @keyframes cloudFloat {{
        0% {{ transform: translate3d(0, 0, 0) rotate(var(--cloud-tilt, 0deg)); }}
        50% {{ transform: translate3d(0, -10px, 0) rotate(var(--cloud-tilt, 0deg)); }}
        100% {{ transform: translate3d(0, 0, 0) rotate(var(--cloud-tilt, 0deg)); }}
      }}
      .grid {{
        display: grid;
        gap: 18px;
        grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      }}
      .card {{
        padding: 20px;
        border-radius: 18px;
        border: 1px solid var(--edge);
        background: var(--card);
        backdrop-filter: blur(6px);
        display: flex;
        flex-direction: column;
        gap: 14px;
        animation: floatIn 0.6s ease both;
      }}
      .card h3 {{
        margin: 0;
        font-size: 18px;
        font-weight: 600;
      }}
      .card h3 a {{
        color: var(--accent-2);
        text-decoration: none;
      }}
      .card h3 a:visited {{
        color: var(--accent-2);
      }}
      .card h3 a:hover {{
        color: var(--accent);
      }}
      .card h3 a:focus-visible {{
        outline: 2px solid var(--accent-2);
        outline-offset: 2px;
        border-radius: 6px;
      }}
      .tags {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}
      .tag {{
        font-size: 11px;
        padding: 4px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255, 255, 255, 0.18);
        color: var(--muted);
      }}
      .card .summary {{
        color: var(--muted);
        line-height: 1.5;
        font-size: 14px;
        min-height: 60px;
      }}
      .card .meta {{
        display: flex;
        justify-content: space-between;
        font-size: 12px;
        color: var(--muted);
      }}
      .links {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }}
      .links a {{
        font-size: 12px;
        color: var(--accent-2);
        text-decoration: none;
      }}
      .load-more {{
        margin-top: 18px;
        display: flex;
        justify-content: center;
      }}
      .load-more button {{
        border: 1px solid var(--edge);
        background: transparent;
        color: var(--ink);
        font-weight: 600;
        padding: 10px 18px;
        border-radius: 999px;
        cursor: pointer;
      }}
      .load-more button:hover {{
        color: var(--accent);
        border-color: var(--accent);
      }}
      .banner {{
        position: fixed;
        left: 50%;
        bottom: 24px;
        transform: translateX(-50%);
        background: #0d131c;
        border: 1px solid var(--edge);
        border-radius: 16px;
        padding: 14px 20px;
        display: flex;
        align-items: center;
        gap: 16px;
        box-shadow: 0 18px 40px rgba(0,0,0,0.35);
        z-index: 50;
      }}
      .banner strong {{
        font-family: "Space Grotesk", sans-serif;
      }}
      .banner button {{
        border: none;
        background: var(--accent);
        color: #071016;
        font-weight: 600;
        padding: 8px 14px;
        border-radius: 999px;
        cursor: pointer;
      }}
      .empty {{
        border: 1px dashed var(--edge);
        border-radius: 18px;
        padding: 26px;
        color: var(--muted);
      }}
      .disclosure-footer {{
        margin-top: 40px;
        padding: 20px 22px;
        border: 1px solid var(--edge);
        border-radius: 16px;
        background: rgba(0, 0, 0, 0.24);
        color: var(--muted);
        font-size: 13px;
        line-height: 1.6;
      }}
      .disclosure-footer strong {{
        color: var(--ink);
        display: block;
        margin-bottom: 8px;
        font-family: "Space Grotesk", "Noto Sans KR", sans-serif;
        letter-spacing: 0.04em;
      }}
      .disclosure-footer ul {{
        margin: 0;
        padding-left: 18px;
      }}
      .disclosure-footer li {{
        margin-bottom: 6px;
      }}
      @keyframes floatIn {{
        from {{
          opacity: 0;
          transform: translateY(14px);
        }}
        to {{
          opacity: 1;
          transform: translateY(0);
        }}
      }}
      @media (max-width: 720px) {{
        header.hero {{ padding: 32px; }}
        .wrap {{ padding: 32px 20px 90px; }}
      }}
    </style>
  </head>
  <body>
    <script id="manifest-data" type="application/json">{manifest_json}</script>
    <div class="wrap">
      <header class="hero">
        <div class="nav">
          <div class="brand"><span class="pulse"></span> Federlicht Report Hub</div>
          <div class="nav-actions">
            <div id="last-updated"></div>
            <select id="theme-select" aria-label="Theme">
              <option value="">Default</option>
              <option value="sky">Sky</option>
              <option value="crimson">Crimson</option>
            </select>
          </div>
        </div>
        <div class="hero-grid">
          <div>
            <h1>Enlighten your Technology Insight.</h1>
            <p>Federlicht가 생성한 기술 리포트를 모아둔 허브입니다. 최신 실행 결과를 자동으로 받아오며, 공유 가능한 HTML 리포트를 바로 열람할 수 있습니다.</p>
            <div class="cta">
              <a class="btn" href="#latest">최신 리포트 보기</a>
              <a class="btn secondary" href="#archive">전체 목록</a>
            </div>
            <div class="stats">
              <div class="stat"><small>Reports</small><span id="stat-reports">0</span></div>
              <div class="stat"><small>Languages</small><span id="stat-langs">0</span></div>
              <div class="stat"><small>Templates</small><span id="stat-templates">0</span></div>
            </div>
          </div>
          <div class="card" id="latest-card">
            <div class="tags" id="latest-tags"></div>
            <h3><a id="latest-title-link" href="#">보고서를 기다리는 중</a></h3>
            <p class="summary" id="latest-summary">manifest.json에서 최신 리포트를 불러옵니다.</p>
            <div class="meta" id="latest-meta"></div>
            <div class="links" id="latest-links"></div>
          </div>
        </div>
      </header>

      <section class="section" id="latest">
        <h2>Latest Reports</h2>
        <p>최근 생성된 리포트부터 순서대로 정렬됩니다. 새 리포트가 감지되면 배너로 알려드립니다.</p>
        <div class="grid" id="report-grid"></div>
        <div class="load-more"><button id="report-more">더 보기</button></div>
      </section>

      <section class="section" id="explore">
        <h2>Explore</h2>
        <p>태그/템플릿/작성자 기준으로 빠르게 탐색합니다.</p>
        <div class="tabs">
          <div class="tab-buttons">
            <button class="tab-button active" data-tab="topics">Topics</button>
            <button class="tab-button" data-tab="templates">Templates</button>
            <button class="tab-button" data-tab="authors">Authors</button>
          </div>
          <div class="tab-panel active" id="tab-topics"></div>
          <div class="tab-panel" id="tab-templates"></div>
          <div class="tab-panel" id="tab-authors"></div>
        </div>
        <div class="insights" id="trend-insights"></div>
        <div class="word-cloud" id="word-cloud"></div>
      </section>

      <section class="section" id="archive">
        <h2>Archive</h2>
        <p>모든 리포트를 한 번에 탐색하거나, 템플릿/언어/형식을 기준으로 비교할 수 있습니다.</p>
        <div class="filter-bar">
          <input id="search-input" type="search" placeholder="Search title, summary, author" />
          <select id="filter-template">
            <option value="">All templates</option>
          </select>
          <select id="filter-lang">
            <option value="">All languages</option>
          </select>
          <select id="filter-tag">
            <option value="">All tags</option>
          </select>
          <select id="filter-author">
            <option value="">All authors</option>
          </select>
        </div>
        <div class="grid" id="archive-grid"></div>
        <div class="load-more"><button id="archive-more">더 보기</button></div>
      </section>
      <footer class="disclosure-footer">
        <strong>AI Transparency and Source Notice</strong>
        <ul>
          <li>이 허브의 게시물은 Federlicht 기반 AI 보조 생성물이며, 최종 책임은 사용자/조직에 있습니다.</li>
          <li>외부 출처의 저작권/라이선스는 원 저작권자에게 있으며, 재배포 전 원문 정책 확인이 필요합니다.</li>
          <li>고위험 의사결정(법률·의료·재무·규제)에는 원문 대조와 추가 검증 절차를 수행하세요.</li>
          <li>EU AI Act 투명성 취지에 따라 AI 생성/보조 작성 콘텐츠임을 명시합니다.</li>
        </ul>
      </footer>
    </div>

    <div class="banner" id="update-banner" style="display:none;">
      <div>
        <strong>새 보고서 있음</strong>
        <div id="update-detail" style="font-size:12px;color:var(--muted);"></div>
      </div>
      <button id="apply-update">새로고침</button>
    </div>

    <script>
      const bootstrap = document.getElementById('manifest-data');
      let currentManifest = bootstrap ? JSON.parse(bootstrap.textContent || '{{}}') : {{ items: [] }};
      let pendingManifest = null;
      const REFRESH_MS = {refresh_ms};

      const escapeHtml = (value) => String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');

      const countBy = (items, getter) => {{
        const counts = new Map();
        items.forEach((item) => {{
          const value = getter(item);
          const values = Array.isArray(value) ? value : [value];
          values.forEach((raw) => {{
            const key = (raw || '').toString().trim();
            if (!key || key === 'unknown') return;
            counts.set(key, (counts.get(key) || 0) + 1);
          }});
        }});
        return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
      }};

      const sortItems = (items) => items.slice().sort((a, b) => {{
        const ta = Date.parse(a.timestamp || a.date || 0) || 0;
        const tb = Date.parse(b.timestamp || b.date || 0) || 0;
        return tb - ta;
      }});

      const buildLinks = (paths = {{}}) => {{
        const entries = [];
        if (paths.report) entries.push(['Report', paths.report]);
        if (paths.overview) entries.push(['Overview', paths.overview]);
        if (paths.workflow) entries.push(['Workflow', paths.workflow]);
        return entries.map(([label, href]) => `<a href="${{escapeHtml(href)}}">${{label}}</a>`).join('');
      }};

        const renderLatest = (item) => {{
        if (!item) return;
        const latestLink = document.getElementById('latest-title-link');
        if (latestLink) {{
          latestLink.textContent = item.title || 'Untitled report';
          latestLink.href = (item.paths && item.paths.report) ? item.paths.report : '#';
        }}
        document.getElementById('latest-summary').textContent = item.summary || '요약 정보가 없습니다.';
        document.getElementById('latest-meta').textContent = `${{item.date || ''}} · ${{item.author || 'Unknown'}}`;
        const tags = [item.lang, item.template, item.model, item.format]
          .filter(tag => tag && tag !== 'unknown')
          .map(tag => `<span class="tag">${{escapeHtml(tag)}}</span>`).join('');
        document.getElementById('latest-tags').innerHTML = tags;
        document.getElementById('latest-links').innerHTML = buildLinks(item.paths);
      }};

      const buildCardHtml = (item, idx) => {{
        const delay = (idx % 6) * 0.05;
        const tags = [item.lang, item.template, item.model, item.format]
          .filter(tag => tag && tag !== 'unknown')
          .map(tag => `<span class="tag">${{escapeHtml(tag)}}</span>`).join('');
        const summary = escapeHtml(item.summary || '');
        const meta = `${{escapeHtml(item.date || '')}} · ${{escapeHtml(item.author || 'Unknown')}}`;
        const reportHref = (item.paths && item.paths.report) ? item.paths.report : '#';
        return `
          <article class="card" style="animation-delay:${{delay}}s">
            <div class="tags">${{tags}}</div>
            <h3><a href="${{escapeHtml(reportHref)}}">${{escapeHtml(item.title || 'Untitled')}}</a></h3>
            <p class="summary">${{summary || '요약 정보가 없습니다.'}}</p>
            <div class="meta">${{meta}}</div>
            <div class="links">${{buildLinks(item.paths)}}</div>
          </article>
        `;
      }};

      const createPager = (targetId, buttonId, pageSize) => {{
        let items = [];
        let index = 0;
        const target = document.getElementById(targetId);
        const button = document.getElementById(buttonId);
        const renderNext = () => {{
          if (!target) return;
          if (!items.length) {{
            target.innerHTML = '<div class="empty">아직 등록된 리포트가 없습니다.</div>';
            if (button) button.style.display = 'none';
            return;
          }}
          const slice = items.slice(index, index + pageSize);
          slice.forEach((item, idx) => {{
            target.insertAdjacentHTML('beforeend', buildCardHtml(item, index + idx));
          }});
          index += slice.length;
          if (button) {{
            button.style.display = index >= items.length ? 'none' : 'inline-flex';
          }}
        }};
        if (button) {{
          button.addEventListener('click', renderNext);
        }}
        const reset = (nextItems) => {{
          items = nextItems || [];
          index = 0;
          if (target) target.innerHTML = '';
          renderNext();
        }};
        return {{ reset }};
      }};

      const renderStats = (items) => {{
        const langCount = new Set(items.map(item => item.lang).filter(Boolean)).size;
        const templateCount = new Set(items.map(item => item.template).filter(Boolean)).size;
        document.getElementById('stat-reports').textContent = items.length;
        document.getElementById('stat-langs').textContent = langCount;
        document.getElementById('stat-templates').textContent = templateCount;
      }};

      const withinDays = (items, days) => {{
        const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
        return items.filter(item => {{
          const stamp = item.timestamp || item.date;
          if (!stamp) return false;
          const time = Date.parse(stamp);
          return !Number.isNaN(time) && time >= cutoff;
        }});
      }};

      const buildKeywordStats = (items) => {{
        const counts = new Map();
        items.forEach(item => {{
          (item.keywords || []).forEach((entry) => {{
            if (!entry) return;
            let term = '';
            let count = 1;
            if (Array.isArray(entry)) {{
              term = String(entry[0] || '').trim();
              count = Number(entry[1] || 1);
            }} else {{
              term = String(entry || '').trim();
            }}
            if (!term) return;
            counts.set(term, (counts.get(term) || 0) + (Number.isFinite(count) ? count : 1));
          }});
        }});
        return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
      }};

      const layoutWordCloud = (container) => {{
        if (!container) return;
        const words = Array.from(container.querySelectorAll('.word'));
        if (!words.length) return;
        const width = container.clientWidth;
        const height = container.clientHeight;
        const placed = [];
        const center = {{ x: width / 2, y: height / 2 }};
        const overlaps = (rect) => {{
          return placed.some((p) =>
            rect.x < p.x + p.w && rect.x + rect.w > p.x &&
            rect.y < p.y + p.h && rect.y + rect.h > p.y
          );
        }};
        words.forEach((word) => {{
          const w = word.offsetWidth;
          const h = word.offsetHeight;
          let angle = Math.random() * Math.PI * 2;
          let radius = 0;
          let found = null;
          for (let i = 0; i < 220; i++) {{
            const x = center.x + Math.cos(angle) * radius - w / 2;
            const y = center.y + Math.sin(angle) * radius - h / 2;
            const rect = {{ x, y, w, h }};
            if (x >= 0 && y >= 0 && x + w <= width && y + h <= height && !overlaps(rect)) {{
              found = rect;
              break;
            }}
            angle += 0.35;
            radius += 2.2;
          }}
          if (!found) {{
            const x = Math.max(0, Math.random() * Math.max(1, width - w));
            const y = Math.max(0, Math.random() * Math.max(1, height - h));
            found = {{ x, y, w, h }};
          }}
          placed.push(found);
          word.style.left = `${{found.x.toFixed(1)}}px`;
          word.style.top = `${{found.y.toFixed(1)}}px`;
        }});
      }};

      const latestPager = createPager('report-grid', 'report-more', 6);
      const archivePager = createPager('archive-grid', 'archive-more', 12);

      const populateFilters = (items) => {{
        const templateSelect = document.getElementById('filter-template');
        const langSelect = document.getElementById('filter-lang');
        const tagSelect = document.getElementById('filter-tag');
        const authorSelect = document.getElementById('filter-author');
        if (!templateSelect || !langSelect || !tagSelect || !authorSelect) return;
        const templates = Array.from(new Set(items.map(item => item.template).filter(Boolean))).sort();
        const langs = Array.from(new Set(items.map(item => item.lang).filter(Boolean))).sort();
        const tags = Array.from(new Set(items.flatMap(item => item.tags || []))).sort();
        const authors = Array.from(new Set(items.map(item => item.author).filter(Boolean))).sort();
        const fill = (select, values, label) => {{
          const current = select.value;
          select.innerHTML = `<option value="">${{label}}</option>` +
            values.map(value => `<option value="${{escapeHtml(value)}}">${{escapeHtml(value)}}</option>`).join('');
          select.value = current;
        }};
        fill(templateSelect, templates, 'All templates');
        fill(langSelect, langs, 'All languages');
        fill(tagSelect, tags, 'All tags');
        fill(authorSelect, authors, 'All authors');
      }};

      const applyFilters = (items) => {{
        const query = (document.getElementById('search-input')?.value || '').toLowerCase().trim();
        const template = document.getElementById('filter-template')?.value || '';
        const lang = document.getElementById('filter-lang')?.value || '';
        const tag = document.getElementById('filter-tag')?.value || '';
        const author = document.getElementById('filter-author')?.value || '';
        return items.filter(item => {{
          if (template && item.template !== template) return false;
          if (lang && item.lang !== lang) return false;
          if (tag && !(item.tags || []).includes(tag)) return false;
          if (author && item.author !== author) return false;
          if (!query) return true;
          const haystack = `${{item.title || ''}} ${{item.summary || ''}} ${{item.author || ''}}`.toLowerCase();
          return haystack.includes(query);
        }});
      }};

      const renderTabs = (items) => {{
        const tabTopics = document.getElementById('tab-topics');
        const tabTemplates = document.getElementById('tab-templates');
        const tabAuthors = document.getElementById('tab-authors');
        if (!tabTopics || !tabTemplates || !tabAuthors) return;
        const topTags = countBy(items, item => item.tags || []).slice(0, 20);
        const topTemplates = countBy(items, item => item.template).slice(0, 20);
        const topAuthors = countBy(items, item => item.author).slice(0, 20);
        const chipHtml = (list, type) => {{
          if (!list.length) return '<div class="empty">데이터가 없습니다.</div>';
          return `<div class="chip-list">` + list.map(([value, count]) =>
            `<button class="chip" data-type="${{type}}" data-value="${{escapeHtml(value)}}">${{escapeHtml(value)}} <strong>${{count}}</strong></button>`
          ).join('') + `</div>`;
        }};
        tabTopics.innerHTML = chipHtml(topTags, 'tag');
        tabTemplates.innerHTML = chipHtml(topTemplates, 'template');
        tabAuthors.innerHTML = chipHtml(topAuthors, 'author');
      }};

      const renderTrends = (items) => {{
        const target = document.getElementById('trend-insights');
        if (!target) return;
        const scoped = withinDays(items, 30);
        const pool = scoped.length ? scoped : items;
        const topTags = countBy(pool, item => item.tags || []).slice(0, 3);
        const topTemplates = countBy(pool, item => item.template).slice(0, 3);
        const topAuthors = countBy(pool, item => item.author).slice(0, 3);
        const block = (title, list) => {{
          const rows = list.length
            ? list.map(([value, count]) => `<div class="insight-item"><span>${{escapeHtml(value)}}</span><strong>${{count}}</strong></div>`).join('')
            : '<div class="insight-item"><span>데이터 없음</span><strong>-</strong></div>';
          return `<div class="insight-card"><h4>${{title}}</h4>${{rows}}</div>`;
        }};
        target.innerHTML = block('Top Tags', topTags) + block('Top Templates', topTemplates) + block('Top Authors', topAuthors);
      }};

      const renderWordCloud = (items) => {{
        const target = document.getElementById('word-cloud');
        if (!target) return;
        const scoped = withinDays(items, 30);
        const pool = scoped.length ? scoped : items;
        const stats = buildKeywordStats(pool).slice(0, 40);
        if (!stats.length) {{
          target.innerHTML = '<div class="empty">최근 30일 키워드가 없습니다.</div>';
          return;
        }}
        const max = stats[0][1] || 1;
        const gradients = [
          'linear-gradient(120deg, #6bd3ff, #4ee0b5)',
          'linear-gradient(120deg, #ff8c96, #ffd36b)',
          'linear-gradient(120deg, #c6b7ff, #7df0ff)',
          'linear-gradient(120deg, #4ee0b5, #8fd1ff)',
          'linear-gradient(120deg, #ff9aa9, #ff6b81)',
        ];
        target.innerHTML = stats.map(([term, count], idx) => {{
          const ratio = count / max;
          const weight = Math.max(0.25, Math.min(1, Math.pow(ratio, 0.6)));
          const opacity = Math.max(0.45, Math.min(1, 0.35 + Math.pow(ratio, 0.5) * 0.65));
          const gradient = gradients[idx % gradients.length];
          const delay = (Math.random() * 2).toFixed(2);
          const duration = (5 + Math.random() * 4).toFixed(2);
          const tilt = ((Math.random() * 6) - 3).toFixed(2);
          return `<span class="word" style="--weight:${{weight.toFixed(2)}};--cloud-opacity:${{opacity.toFixed(2)}};--cloud-gradient:${{gradient}};--cloud-delay:${{delay}}s;--cloud-duration:${{duration}}s;--cloud-tilt:${{tilt}}deg;">${{escapeHtml(term)}}</span>`;
        }}).join('');
        requestAnimationFrame(() => layoutWordCloud(target));
      }};

      const setFilterValue = (type, value) => {{
        if (!value) return;
        if (type === 'tag') {{
          const tagSelect = document.getElementById('filter-tag');
          if (tagSelect) tagSelect.value = value;
        }} else if (type === 'template') {{
          const templateSelect = document.getElementById('filter-template');
          if (templateSelect) templateSelect.value = value;
        }} else if (type === 'author') {{
          const authorSelect = document.getElementById('filter-author');
          if (authorSelect) authorSelect.value = value;
        }}
        const items = sortItems(currentManifest.items || []);
        const filtered = applyFilters(items);
        archivePager.reset(filtered);
        renderTrends(filtered);
        renderWordCloud(filtered);
      }};

      const renderAll = (manifest) => {{
        const items = sortItems(manifest.items || []);
        renderLatest(items[0]);
        latestPager.reset(items);
        populateFilters(items);
        renderTabs(items);
        renderTrends(items);
        renderWordCloud(items);
        const filtered = applyFilters(items);
        archivePager.reset(filtered);
        renderStats(items);
        const updated = manifest.generated_at ? new Date(manifest.generated_at).toLocaleString() : '';
        document.getElementById('last-updated').textContent = updated ? `Updated ${{updated}}` : '';
      }};

      const showUpdateBanner = (manifest) => {{
        const banner = document.getElementById('update-banner');
        const detail = document.getElementById('update-detail');
        const items = sortItems(manifest.items || []);
        const latest = items[0];
        if (!latest) return;
        detail.textContent = `${{latest.title || 'Untitled'}} · ${{latest.author || 'Unknown'}}`;
        banner.style.display = 'flex';
      }};

      const applyUpdate = () => {{
        if (!pendingManifest) return;
        currentManifest = pendingManifest;
        pendingManifest = null;
        renderAll(currentManifest);
        document.getElementById('update-banner').style.display = 'none';
        try {{
          localStorage.setItem('federlicht.manifest.revision', currentManifest.revision || '');
        }} catch (err) {{}}
      }};

      document.getElementById('apply-update').addEventListener('click', applyUpdate);

      const pollManifest = () => {{
        fetch(`manifest.json?ts=${{Date.now()}}`, {{ cache: 'no-store' }})
          .then((resp) => resp.json())
          .then((data) => {{
            if (!data || !data.revision) return;
            if (currentManifest.revision && data.revision === currentManifest.revision) return;
            pendingManifest = data;
            showUpdateBanner(data);
          }})
          .catch(() => {{}});
      }};

      const filterInputs = ['search-input', 'filter-template', 'filter-lang', 'filter-tag', 'filter-author'];
      filterInputs.forEach((id) => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('input', () => {{
          const items = sortItems(currentManifest.items || []);
          const filtered = applyFilters(items);
          archivePager.reset(filtered);
          renderTrends(filtered);
          renderWordCloud(filtered);
        }});
        el.addEventListener('change', () => {{
          const items = sortItems(currentManifest.items || []);
          const filtered = applyFilters(items);
          archivePager.reset(filtered);
          renderTrends(filtered);
          renderWordCloud(filtered);
        }});
      }});

      window.addEventListener('resize', () => {{
        const items = sortItems(currentManifest.items || []);
        const filtered = applyFilters(items);
        renderWordCloud(filtered);
      }});

      document.querySelectorAll('.tab-button').forEach((button) => {{
        button.addEventListener('click', () => {{
          document.querySelectorAll('.tab-button').forEach((btn) => btn.classList.remove('active'));
          document.querySelectorAll('.tab-panel').forEach((panel) => panel.classList.remove('active'));
          button.classList.add('active');
          const tabId = button.dataset.tab;
          const panel = document.getElementById(`tab-${{tabId}}`);
          if (panel) panel.classList.add('active');
        }});
      }});

      document.addEventListener('click', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (!target.classList.contains('chip')) return;
        const type = target.dataset.type;
        const value = target.dataset.value;
        if (!type || !value) return;
        setFilterValue(type, value);
        document.getElementById('archive')?.scrollIntoView({{ behavior: 'smooth' }});
      }});

      document.addEventListener('click', (event) => {{
        const target = event.target;
        if (!(target instanceof HTMLElement)) return;
        if (!target.classList.contains('word')) return;
        const term = target.textContent || '';
        if (!term) return;
        const tagSelect = document.getElementById('filter-tag');
        if (tagSelect) {{
          tagSelect.value = '';
        }}
        const searchInput = document.getElementById('search-input');
        if (searchInput) {{
          searchInput.value = term;
        }}
        const items = sortItems(currentManifest.items || []);
        const filtered = applyFilters(items);
        archivePager.reset(filtered);
        renderTrends(filtered);
        renderWordCloud(filtered);
        document.getElementById('archive')?.scrollIntoView({{ behavior: 'smooth' }});
      }});

      renderAll(currentManifest);
      try {{
        localStorage.setItem('federlicht.manifest.revision', currentManifest.revision || '');
      }} catch (err) {{}}
      const params = new URLSearchParams(window.location.search);
      const themeParam = params.get('theme');
      const storedTheme = localStorage.getItem('federlicht.theme');
      const theme = themeParam || storedTheme;
      if (theme) {{
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('federlicht.theme', theme);
      }}
      const themeSelect = document.getElementById('theme-select');
      if (themeSelect) {{
        themeSelect.value = theme || '';
        themeSelect.addEventListener('change', (event) => {{
          const selected = event.target.value;
          if (selected) {{
            document.documentElement.dataset.theme = selected;
            localStorage.setItem('federlicht.theme', selected);
          }} else {{
            document.documentElement.removeAttribute('data-theme');
            localStorage.removeItem('federlicht.theme');
          }}
        }});
      }}
      setInterval(pollManifest, REFRESH_MS);
    </script>
  </body>
</html>
"""



