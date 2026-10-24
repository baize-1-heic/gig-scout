# -*- coding: utf-8 -*-
"""demand-scout.py —— 「全网找副业」的无人值守侦察工（2026-10-24 建）

干什么（**匿名、零模型花费、不弹任何窗口**）：
  1) RemoteOK `/api`（实测 ✓ 200、匿名 JSON）→ 按 tag/职位关键词筛 AI/Agent/automation
  2) remote-china.com `/jobs`（实测 ✓ 200、匿名 HTML，**国内源**）→ job-item 卡片解析，中英文关键词
  3) HN Algolia「Ask HN: Who is hiring?」当月帖（实测 ✓ 200、匿名）→ 拉评论树、筛 AI＋remote
  4) 新条目追加 `work\\_plan\\scout\\DEMAND-LEDGER.md`（去重靠 state.json，断点续跑）

不干什么：
  - 不登录任何平台（Boss直聘/闲鱼/小红书/Upwork 都要登录或已无 RSS → 不做，见 DEMAND-20261024.md 实测表）
  - 不投模型、不下载文件、不碰收藏夹、不起浏览器（CDP 都不用）

实测边界（2026-10-24 本机直连，别再猜）：
  remoteok.com/api          200  匿名 JSON，约 99 条窗口
  remote-china.com/jobs     200  匿名 HTML，job-item 卡片带标题/薪资/公司/日期；详情页也匿名可读
  hn.algolia.com/api/v1     200  匿名 JSON
  weworkremotely RSS        403  ← 网页端说「公开可用」，**本机实测被拒**（以本机为准）
  v2ex.com/api/v1 & v2      超时 ← 本机出网问题，非源不存在
  eleduck.com/categories/5  200  但它是 SPA：`__NEXT_DATA__` 里 user=null、列表页 post-links=0 → **不做自动源**

用法：
  python -X utf8 bin\\demand-scout.py             # 跑一轮（自动任务入口）
  python -X utf8 bin\\demand-scout.py --dry       # 只打印会新增什么，不写盘
  python -X utf8 bin\\demand-scout.py --self-test # 筛选/解析不变量自检（红了 exit 1）
"""
import json, os, re, sys, datetime, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 🔴 输出目录可用环境变量覆盖，默认仍是 bili-watcher 的结构 → 计划任务行为不变（向后兼容），
#    但同一份文件能直接拿到别处/容器里跑（开源用），不必改代码。2026-10-24 round 10 加。
SCOUT_DIR = os.environ.get("DEMAND_SCOUT_DIR") or os.path.join(ROOT, "work", "_plan", "scout")
LEDGER = os.environ.get("DEMAND_SCOUT_LEDGER") or os.path.join(SCOUT_DIR, "DEMAND-LEDGER.md")
STATE = os.environ.get("DEMAND_SCOUT_STATE") or os.path.join(SCOUT_DIR, "demand-state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; X64) dsh-demand-scout"

AI_KW = re.compile(r"\b(AI|LLM|agent|agents|RAG|prompt|MCP|n8n|automation|automate|DeepSeek|"
                   r"Anthropic|OpenAI|Claude|GPT|LangChain|LangGraph|fine-?tun\w*|embedding\w*|"
                   r"copilot|machine learning|data annotation)\b|"
                   r"(大模型|人工智能|智能体|提示词|数据标注|标注|模型训练|工作流|自动化|批处理|爬虫|"
                   r"脚本助手|Coding|编程助手)", re.I)
REMOTE_KW = re.compile(r"\b(remote|worldwide|anywhere|global|UTC[+-]?\d*)\b|(远程|居家|线上|在家办公)", re.I)
STUDENT_OK = re.compile(r"(intern|internship|junior|entry[- ]level|no experience|student|"
                        r"trainee|apprentice|part[- ]time|contract|freelance)|"
                        r"(兼职|实习|在校|学生|应届|经验不限|无经验|日结|周结)", re.I)
SALARY = re.compile(r"(\$|USD|EUR|£|€)\s?\d[\d,.]*\s?(k|K)?|\d+\s?(元|k|K)\s?/|\d+[–-]\d+\s?(元|k)|"
                    r"\d[\d,]*\s?[-–]\s?\d[\d,]*\s?元", re.I)
# 排除：与「每周 5–8 小时、在校、无 3–5 年经验」直接冲突的岗位（senior/全职/坐班/资历门槛）
# 🔴 2026-10-24 加 `in[- ]person`：真跑时漏进一条 HN「NY, SF, London & Toronto (In-Person)」——
#    它写了 remote 字样但实际要到场，`on-site|hybrid` 没覆盖 "in person" 这个写法。
BLOCK_KW = re.compile(r"\b(staff|principal|senior|lead|head of|VP|Director|full[- ]?time|"
                      r"on-?site|in[- ]person|hybrid|relocation|clearance|citizen|\d{1,2}\+?\s?years)\b|"
                      r"(全职|坐班|驻场|需到岗|线下办公|3-5年|3–5年|5年以上|10年)", re.I)


def http_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def http_html(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_html(t):
    t = re.sub(r"<a[^>]*href=\"([^\"]+)\"[^>]*>[^<]*</a>", r"\1", t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&#x2F;", "/").replace("&amp;", "&").replace("&#x27;", "'")
    return re.sub(r"\s+", " ", t).strip()


def score_job(text):
    """给一段招聘文本打分：AI 味 / 远程 / 学生可投 / 有薪资 / 有排除词。纯函数，可测。"""
    return {
        "ai": bool(AI_KW.search(text)),
        "remote": bool(REMOTE_KW.search(text)),
        "student_ok": bool(STUDENT_OK.search(text)),
        "salary": bool(SALARY.search(text)),
        "blocked": bool(BLOCK_KW.search(text)),
    }


def keep(score):
    """收录判据：有 AI 味 ＋（远程 或 学生可投）＋ 没撞排除词。"""
    return score["ai"] and (score["remote"] or score["student_ok"]) and not score["blocked"]


def parse_job_items(html):
    """remote-china.com 列表页的 job-item 卡片 → dict 列表。纯函数、可测、只用标准库正则。
    结构（2026-10-24 实测抓到的原文）：
      <div class="job-item"> <a href="/jobs/2298" ...>
      <h3 class="job-title">电商客服</h3>
      <time datetime="2026-10-23T20:58:49...">
      <p class="job-description">…</p>
      <span class="job-salary">周薪 1000-1200 元</span>
      <span class="job-team-name">陕西米因电子科技有限公司</span>
    """
    out = []
    for m in re.finditer(r'<div class="job-item">([\s\S]*?)(?=<div class="job-item">|$)', html):
        blk = m.group(1)

        def pick(pat):
            mm = re.search(pat, blk)
            return strip_html(mm.group(1)) if mm else ""

        href = pick(r'<a href="(/jobs/\d+)"')
        if not href:
            continue
        out.append({
            "id": href.rsplit("/", 1)[-1],
            "title": pick(r'<h3 class="job-title">([\s\S]*?)</h3>')[:110],
            "org": pick(r'<span class="job-team-name">([\s\S]*?)</span>')[:40],
            "pay": pick(r'<span class="job-salary">([\s\S]*?)</span>')[:40] or "未披露",
            "desc": pick(r'<p class="job-description">([\s\S]*?)</p>')[:300],
            "date": (re.search(r'datetime="(\d{4}-\d{2}-\d{2})', blk) or [None, ""])[1],
            "url": "https://remote-china.com" + href,
        })
    return out


def fetch_remote_china():
    """国内匿名可读源（2026-10-24 实测 ✓：列表页与详情页都无需登录）。
    电鸭是 SPA（post-links=0、__NEXT_DATA__ 里 user=null）→ 不抓；只抓这个。"""
    html = http_html("https://remote-china.com/jobs")
    out = []
    for it in parse_job_items(html):
        blob = " ".join([it["title"], it["desc"], it["pay"]])
        sc = score_job(blob)
        if not keep(sc):
            continue
        out.append({
            "src": "remote-china", "id": "rc-%s" % it["id"], "title": it["title"],
            "org": it["org"], "pay": it["pay"],
            "flags": "".join(k[0].upper() for k, v in sc.items() if v and k != "blocked"),
            "url": it["url"], "date": it["date"],
        })
    return out


def fetch_remoteok():
    j = http_json("https://remoteok.com/api")
    out = []
    for it in j[1:] if j and isinstance(j, list) else []:
        blob = " ".join(str(it.get(k) or "") for k in ("position", "tags", "description", "location"))
        sc = score_job(blob)
        if not keep(sc):
            continue
        out.append({
            "src": "remoteok", "id": str(it.get("id") or it.get("slug")),
            "title": strip_html(str(it.get("position") or ""))[:110],
            "org": str(it.get("company") or "")[:40],
            "pay": "%s-%s" % (it.get("salary_min") or 0, it.get("salary_max") or 0)
                   if (it.get("salary_min") or it.get("salary_max")) else "未披露",
            "flags": "".join(k[0].upper() for k, v in sc.items() if v and k != "blocked"),
            "url": it.get("url") or ("https://remoteok.com/remote-jobs/" + str(it.get("slug") or "")),
            "date": str(it.get("date") or "")[:10],
        })
    return out


def find_hn_hiring_story():
    q = urllib.parse.quote('"Who is hiring?"')
    j = http_json("https://hn.algolia.com/api/v1/search_by_date?query=%s&tags=story&hitsPerPage=25" % q)
    best = None
    for h in j.get("hits") or []:
        t = h.get("title") or ""
        if re.match(r"^\s*Ask HN:\s*Who is hiring\?", t, re.I) and (h.get("points") or 0) > 50:
            if best is None or (h.get("created_at") or "") > (best.get("created_at") or ""):
                best = h
    return best


def walk(node, out):
    if node.get("text"):
        out.append((node.get("author") or "?", strip_html(node["text"])))
    for c in node.get("children") or []:
        walk(c, out)


def fetch_hn():
    st = find_hn_hiring_story()
    if not st:
        return [], None
    tree = http_json("https://hn.algolia.com/api/v1/items/%s" % st["objectID"])
    flat = []
    for c in tree.get("children") or []:
        walk(c, flat)
    out = []
    for author, txt in flat:
        sc = score_job(txt)
        if not keep(sc):
            continue
        out.append({
            "src": "hn", "id": "%s:%s" % (st["objectID"], author),
            "title": txt[:110], "org": author,
            "pay": "有薪资" if sc["salary"] else "未披露",
            "flags": "".join(k[0].upper() for k, v in sc.items() if v and k != "blocked"),
            "url": "https://news.ycombinator.com/item?id=%s" % st["objectID"],
            "date": str(st.get("created_at") or "")[:10],
        })
    return out, st.get("title")


def load_state():
    if os.path.exists(STATE):
        return json.loads(open(STATE, encoding="utf-8").read())
    return {"seen": {}, "runs": []}


def save_state(st):
    os.makedirs(SCOUT_DIR, exist_ok=True)
    open(STATE, "w", encoding="utf-8").write(json.dumps(st, ensure_ascii=False, indent=1))


def log_line(msg):
    """无人值守跑（pythonw 无 stdout）也要留痕：追加一行到 _demand-scout.log。
    🔴 2026-10-24 加：原来失败只 print 到 stdout → pythonw 下**没人看得见**，源挂了会静默无记录。"""
    os.makedirs(SCOUT_DIR, exist_ok=True)
    with open(os.path.join(SCOUT_DIR, "_demand-scout.log"), "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))


def ledger_ensure():
    os.makedirs(SCOUT_DIR, exist_ok=True)
    if not os.path.exists(LEDGER):
        open(LEDGER, "w", encoding="utf-8").write(
            "# 全网需求台账（demand-scout.py 自动追加，勿手改）\n\n"
            "> 源：RemoteOK /api ＋ remote-china.com/jobs（国内，匿名可读）＋ HN「Who is hiring?」当月帖。"
            "三个源都匿名、零花费、不起浏览器。\n"
            "> flags 字母：A=AI味 R=远程 S=学生/兼职可投 Pay=有薪资数字。人工评估见 DEMAND-20261024.md。\n"
            "> 🔴 收录不等于推荐：条目可能是虚假招聘（remote-china 有用户举报机制）、也可能门槛不符 —— **投之前必须人工点开原文核**。\n\n")


def ledger_append(rows):
    txt = open(LEDGER, encoding="utf-8").read()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    block = ["## %s（新增 %d 条）" % (now, len(rows)), ""]
    for r in rows:
        block.append("- `%s` [%s] **%s** ｜ %s ｜ 薪资 %s ｜ [%s](%s)" % (
            r["src"], r["flags"], r["title"], r["org"], r["pay"], r["date"] or "?", r["url"]))
    block.append("")
    open(LEDGER, "w", encoding="utf-8").write(txt.rstrip() + "\n\n" + "\n".join(block) + "\n")


def run(dry):
    rows = []
    errors = []
    for name, fn in (("remoteok", fetch_remoteok), ("remote-china", fetch_remote_china),
                     ("hn", lambda: fetch_hn()[0])):
        try:
            rows += fn()
        except Exception as e:
            errors.append("%s:%s" % (name, str(e)[:90]))
    st = load_state()
    seen = st.get("seen", {})
    fresh = [r for r in rows if r["id"] not in seen]
    hn_title = None
    try:
        hn_title = (find_hn_hiring_story() or {}).get("title")
    except Exception:
        pass
    print("hits=%d fresh=%d errors=%s hn=%s" % (len(rows), len(fresh), errors or "none", hn_title))
    if dry:
        log_line("DRY hits=%d fresh=%d errors=%s" % (len(rows), len(fresh), errors or "none"))
        for r in fresh[:10]:
            print("  would-add %s [%s] %s | %s" % (r["src"], r["flags"], r["title"][:60], r["pay"]))
        return 0
    if fresh:
        ledger_ensure()
        ledger_append(fresh)
    for r in fresh:
        seen[r["id"]] = datetime.datetime.now().strftime("%Y-%m-%d")
    st["seen"] = seen
    st.setdefault("runs", []).append({"at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                     "hits": len(rows), "fresh": len(fresh), "errors": errors})
    st["runs"] = st["runs"][-60:]
    save_state(st)
    log_line("run ok hits=%d fresh=%d errors=%s hn=%s" % (len(rows), len(fresh), errors or "none", hn_title))
    return 0


# ---------------- 自检（能红） ----------------
def self_test():
    fails = []

    def ck(n, c):
        if not c:
            fails.append(n)

    # AI 味命中
    ck("ai-hit", score_job("We need an LLM agent engineer for RAG pipelines")["ai"])
    ck("ai-miss", not score_job("Looking for a barista in Portland")["ai"])
    # 远程 / 学生可投
    ck("remote", score_job("Fully remote, anywhere in the world")["remote"])
    ck("student", score_job("Part-time contract, no experience required")["student_ok"])
    # 排除词
    ck("block-senior", score_job("Staff Engineer, on-site in Berlin, 10+ years")["blocked"])
    # keep 判据
    ck("keep-good", keep(score_job("AI automation engineer, remote, contract")))
    ck("keep-noremote-noai", not keep(score_job("Barista, on-site")))
    ck("keep-blocked", not keep(score_job("AI engineer but Staff level, on-site")))
    # 薪资识别
    ck("salary-usd", score_job("$120k - $160k base")["salary"])
    ck("salary-cny", score_job("300-500元/天")["salary"])
    ck("salary-none", not score_job("competitive compensation")["salary"])
    # strip_html 实体与标签
    ck("strip", strip_html('<a href="https://x.io">site</a> &#x2F; R&amp;D') == "https://x.io / R&D")
    # 中文关键词（新源是中文站）
    ck("cn-ai", score_job("大模型数据标注，兼职周结")["ai"])
    ck("cn-remote", score_job("远程办公，居家即可")["remote"])
    ck("cn-student", score_job("在校生可投，经验不限，日结")["student_ok"])
    ck("cn-salary", score_job("周薪 1000-1200 元")["salary"])
    ck("cn-block", score_job("全职坐班，3-5年经验")["blocked"])
    ck("block-inperson", score_job("NY, SF, London (In-Person), remote-friendly team")["blocked"])
    # 列表页解析（用 2026-10-24 实抓的结构做固定样本，不联网）
    FIX = ('<div class="job-item"><a href="/jobs/2298" class="job-link"></a>'
           '<div class="job-header"><h3 class="job-title">电商客服</h3>'
           '<time datetime="2026-10-23T20:58:49+08:00">2026-10-23</time></div>'
           '<div class="job-content"><p class="job-description">兼职周结，居家办公</p></div>'
           '<div class="job-footer"><span class="job-salary">周薪 1000-1200 元</span>'
           '<span class="job-team-name">某某电子科技有限公司</span></div></div>'
           '<div class="job-item"><a href="/jobs/2297" class="job-link"></a>'
           '<h3 class="job-title">药品研发大模型训练</h3>'
           '<time datetime="2026-10-22T09:00:00+08:00">2026-10-22</time>'
           '<p class="job-description">远程，标注大模型输出</p>'
           '<span class="job-salary">日薪 300 元</span>'
           '<span class="job-team-name">某医药公司</span></div>')
    parsed = parse_job_items(FIX)
    ck("parse-count", len(parsed) == 2)
    ck("parse-fields", parsed and parsed[0]["title"] == "电商客服" and parsed[0]["pay"] == "周薪 1000-1200 元"
       and parsed[0]["org"] == "某某电子科技有限公司" and parsed[0]["date"] == "2026-10-23"
       and parsed[0]["url"] == "https://remote-china.com/jobs/2298")
    ck("parse-ai-kept", keep(score_job(" ".join([parsed[1]["title"], parsed[1]["desc"], parsed[1]["pay"]]))))
    ck("parse-empty", parse_job_items("<html>nothing</html>") == [])
    # 留痕（无人值守跑 pythonw 无 stdout，失败必须落盘可查）
    # 🔴 探针行写完就撤掉，别污染真日志（2026-10-24 手动清过两次才补上这条）
    # 🔴 局部变量别叫 keep —— 会遮蔽模块级 keep() 函数，实测炸 UnboundLocalError（自检抓到的）
    PROBE = "__selftest_probe__"
    log_line(PROBE)
    logp = os.path.join(SCOUT_DIR, "_demand-scout.log")
    ck("log-written", os.path.exists(logp) and PROBE in open(logp, encoding="utf-8").read())
    if os.path.exists(logp):
        kept_lines = [ln for ln in open(logp, encoding="utf-8").read().splitlines() if PROBE not in ln]
        open(logp, "w", encoding="utf-8").write(("\n".join(kept_lines) + "\n") if kept_lines else "")
    if fails:
        print("SELF-TEST FAIL: %s" % ", ".join(fails))
        return 1
    print("SELF-TEST OK (24 checks)")
    return 0


def main():
    if "--self-test" in sys.argv:
        raise SystemExit(self_test())
    raise SystemExit(run("--dry" in sys.argv))


if __name__ == "__main__":
    main()
