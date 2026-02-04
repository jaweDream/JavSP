# Proposal: curl-cffi 升级替换 cloudscraper

## Context（背景）

### 用户需求
升级项目的 HTTP 请求层，用 `curl_cffi` 替换 `cloudscraper`，以获得更好的反爬虫绕过能力（TLS 指纹伪装）。

### 发现的约束

#### 硬约束（Hard Constraints）

| ID | 约束 | 来源 |
|----|------|------|
| HC-1 | `Request` 类的公共 API 必须保持不变：`get()`, `post()`, `head()`, `get_html()` | `base.py:79-113` |
| HC-2 | 构造函数签名 `Request(use_scraper=False)` 必须保持兼容 | 4 个爬虫使用 `use_scraper=True` |
| HC-3 | Response 对象必须兼容 `requests.Response`（`.status_code`, `.content`, `.text`, `.headers`, `.history`, `.url`） | 所有爬虫依赖这些属性 |
| HC-4 | 必须支持 `proxies` 字典格式 `{'http': url, 'https': url}` | `base.py:36-41` |
| HC-5 | 必须支持 `cookies` 字典参数 | `fanza.py:20`, `mgstage.py:16` |
| HC-6 | 必须支持 `timeout` 秒数参数 | `base.py:54` |
| HC-7 | 必须支持自定义 `headers` 字典 | 所有爬虫 |
| HC-8 | Python 版本范围：3.10 - 3.12 | `pyproject.toml:11` |

#### 软约束（Soft Constraints）

| ID | 约束 | 说明 |
|----|------|------|
| SC-1 | 优先使用 `impersonate="chrome"` 获得最新 Chrome 指纹 | curl_cffi 最佳实践 |
| SC-2 | ~~保留 cloudscraper 作为 fallback~~ **移除 cloudscraper** | 经分析，cloudscraper 的 JS Challenge 能力对现代 CF 无效，curl_cffi TLS 指纹更有效 |
| SC-3 | 最小改动原则，仅修改 `base.py` | 场景 A 要求 |
| SC-4 | curl_cffi 模式使用其默认 UA | 避免 UA 与 TLS 指纹不匹配 |

#### 依赖约束

| 依赖 | 当前版本 | 操作 |
|-----|---------|------|
| `cloudscraper` | 1.2.71 | **移除** |
| `curl_cffi` | - | 新增，版本 >= 0.5.0 |
| `requests` | 2.31.0 | 保留（非 scraper 模式仍需） |

#### 使用 `use_scraper=True` 的爬虫

| 文件 | 位置 | 说明 |
|-----|------|------|
| `javdb.py` | L16, L48 | 需要绕过 CF |
| `javlib.py` | L14 | 需要绕过 CF |
| `airav.py` | L13 | 需要绕过 CF |

#### 使用 `use_scraper=False`（默认）的爬虫

| 文件 | 说明 |
|-----|------|
| `mgstage.py` | 仅需 cookies |
| `fanza.py` | 仅需 cookies |
| `javmenu.py` | 普通请求 |

---

## Requirements（需求）

### REQ-1: 替换 Request 类的 scraper 后端

**场景**：当 `use_scraper=True` 时，使用 `curl_cffi` 代替 `cloudscraper`。

**验收标准**：
- `Request(use_scraper=True)` 创建的实例使用 curl_cffi Session
- `Request(use_scraper=False)` 仍使用 requests 库
- 所有现有爬虫无需修改代码即可正常工作

### REQ-2: 保持 Response 兼容性

**场景**：爬虫代码依赖 `response.status_code`, `.history`, `.url`, `.content`, `.text` 等属性。

**验收标准**：
- curl_cffi Response 对象的这些属性与 requests.Response 行为一致
- `resp2html()` 函数无需修改

### REQ-3: 支持浏览器指纹伪装

**场景**：通过 TLS 指纹绕过 CloudFlare 检测。

**验收标准**：
- 默认使用 `impersonate="chrome"` 参数
- 可通过构造函数参数自定义 impersonate 值

### REQ-4: 保持代理支持

**场景**：用户配置代理服务器访问站点。

**验收标准**：
- `proxies={'http': url, 'https': url}` 格式继续有效
- 或自动转换为 curl_cffi 的 `proxy` 参数

### REQ-5: 更新依赖配置

**场景**：在 pyproject.toml 中更新依赖。

**验收标准**：
- 移除或降级 `cloudscraper` 依赖
- 添加 `curl_cffi>=0.5.0` 依赖
- `uv sync` / `poetry install` 正常工作

---

## Success Criteria（成功判据）

| ID | 判据 | 验证方式 |
|----|------|---------|
| SC-1 | 所有使用 `use_scraper=True` 的爬虫正常工作 | 运行 `pytest unittest/test_crawlers.py --only javdb` |
| SC-2 | 所有使用 `use_scraper=False` 的爬虫正常工作 | 运行 `pytest unittest/test_crawlers.py --only fanza` |
| SC-3 | 代理配置正常生效 | 手动测试带代理请求 |
| SC-4 | 依赖安装无冲突 | `uv sync` 成功 |
| SC-5 | 无爬虫代码修改（仅 base.py） | `git diff --stat` 验证 |

---

## Risks（风险）

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| curl_cffi Response 与 requests 不完全兼容 | 部分爬虫解析失败 | 添加 Response 标准化层 |
| curl_cffi 无法绕过 Turnstile/CAPTCHA | 特定站点失败 | 抛出 SiteBlocked，需用户提供 cookies 或换免代理地址 |
| 代理参数格式差异 | 代理不生效 | 自动转换 proxies dict 为 proxy 字符串 |
| Response.history 缺失 | javdb/javlib 重定向检测失效 | 合成 history：若 redirect_count>0，填充 stub |

---

## Out of Scope（不在范围内）

- 异步化改造（场景 B/C）
- 引入 Engine 抽象层
- 修改各爬虫文件
- 添加新功能

---

## Decisions（已确认决策）

| 问题 | 决策 | 理由 |
|-----|------|------|
| cloudscraper 处理 | **移除** | 经 Codex 实测：cloudscraper 对现代 CF 无效，curl_cffi TLS 指纹更有效。3 层降级是过度设计。 |
| impersonate 参数 | **硬编码 "chrome"** | 简单可靠，使用最新 Chrome 指纹 |
| User-Agent | **curl_cffi 默认** | 让 curl_cffi 根据 impersonate 生成匹配的 UA，避免指纹不一致 |
| Challenge 检测 | **检测后抛出 SiteBlocked** | 403/503 + 'cdn-cgi'/'Just a moment' 时主动报错，避免静默解析失败 |

---

## Implementation Strategy（实施策略）

```
Request(use_scraper=True) 时的请求流程：

1. 使用 curl_cffi.requests.Session + impersonate="chrome"
2. 检测 Challenge 页面（403/503 + CF 标记）→ 抛出 SiteBlocked
3. 标准化 Response（补充 history、转换异常类型）

Request(use_scraper=False) 时：
- 直接使用 requests（保持不变）

无降级链 - curl_cffi 失败时 cloudscraper 也会失败（相同原因）
```
