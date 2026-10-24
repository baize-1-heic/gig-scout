# gig-scout

> 一个**零依赖、匿名、不弹窗**的远程 AI 岗位侦察脚本：从公开源（RemoteOK API、remote-china.com、Hacker News「Who is hiring?」当月帖）拉岗位，按「AI 相关 + 远程 + 学生/兼职可投」筛选，排除 senior/全职/坐班/资历门槛，新条目追加进一个 Markdown 台账。
>
> 设计给「无人值守」跑：`pythonw` 下无 stdout 也能靠日志查账；断网时优雅降级、如实记 `errors`，不静默失败。

## 为什么它值得看：判据是「能红」的

这个脚本的核心不是"能跑"，是**跑错了会红给你看**。它自带一套 `--self-test`，把归类逻辑的不变量写成 24 条断言：

```bash
python demand-scout.py --self-test
# SELF-TEST OK (24 checks)   ← 绿；任何一条断言不成立就 FAIL 并 exit 1
```

24 条覆盖了：AI 关键词命中/不命中、远程判定、学生可投判定、薪资识别（USD 与人民币两种写法）、排除词（含 `senior`/`full-time`/`on-site`/`in-person`/`N+ years`）、收录判据 `keep()` 的三种边界、列表页 HTML 卡片解析（固定样本，不联网）、日志留痕。

**这套判据真的红过一次**：开发时一个局部变量名 `keep` 遮蔽了模块级函数 `keep()`，`--self-test` 当场 `UnboundLocalError` exit 1 抓到 —— 没有它，这个 bug 会在夜里无人值守时静默炸掉。

## 用法

```bash
# 常规跑一轮（拉三个源、筛、追加台账）
python demand-scout.py

# 只看会新增什么，不写盘
python demand-scout.py --dry

# 归类逻辑自检（红了 exit 1）
python demand-scout.py --self-test
```

输出目录默认在脚本所在项目的 `work/_plan/scout/`，可用环境变量覆盖（便于容器化/换机器）：

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `DEMAND_SCOUT_DIR` | `<repo>/work/_plan/scout` | 台账与状态目录 |
| `DEMAND_SCOUT_LEDGER` | `$DEMAND_SCOUT_DIR/DEMAND-LEDGER.md` | 台账文件 |
| `DEMAND_SCOUT_STATE` | `$DEMAND_SCOUT_DIR/demand-state.json` | 去重状态（断点续跑靠它） |

## 用 Docker 跑（可复现）

```bash
docker build -t gig-scout .
docker run --rm -e DEMAND_SCOUT_DIR=/out -v "$PWD/out:/out" gig-scout
```

镜像基于 `python:3.12-slim`，**无任何第三方依赖**（纯标准库 `urllib`/`re`/`json`）。

## CI：双轮复现验证

`.github/workflows/selftest.yml` 对**同一个 commit** 跑两次 `--self-test`（外加一次 `--dry` 联网冒烟），对应"构造可复现环境 + 双轮复现验证"的要求。Actions 的 run 记录公开、带时间戳、不可事后篡改 —— 这是"我本机跑过"给不了的凭证。

## 边界与诚实声明

- **只读公开源、匿名、不登录任何平台**。Boss直聘/闲鱼/小红书/Upwork 需要登录或已无 RSS → 不抓。
- **收录 ≠ 推荐**：源里可能混虚假招聘（remote-china 有用户举报机制），投之前必须人工点开原文核。
- **平台会变**：remote-china.com 的 HTML 结构若改版，`parse_job_items()` 会解析不到 → 台账新增数会掉到 0，届时看 `_demand-scout.log` 的 `errors`。
- HN 那条抓的是「Ask HN: Who is hiring?」当月帖，靠标题正则 + 分数阈值定位，月份切换后自动跟到最新一期。

## License

MIT
