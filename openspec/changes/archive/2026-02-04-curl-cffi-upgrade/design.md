# Design: curl-cffi 升级替换 cloudscraper

## 技术决策摘要

| 决策点 | 选择 | 理由 |
|-------|------|------|
| HTTP 后端 | curl_cffi (无 cloudscraper fallback) | cloudscraper 对现代 CF 无效，TLS 指纹更有效 |
| impersonate | 硬编码 "chrome" | 简单可靠，无需配置 |
| Response 处理 | 标准化为 requests.Response 兼容 | 确保爬虫代码无需修改 |
| history 合成 | 最小 stub (status_code=302, url=原始) | 满足现有 truthy 检查 |
| UA 处理 | curl_cffi 模式忽略自定义 UA | 保持 TLS 指纹一致性 |
| 异常处理 | 转换为 requests 异常 + 保留 __cause__ | 兼容重试逻辑 + 便于调试 |

---

## 架构变更

### 变更前

```
Request(use_scraper=True)
    └── cloudscraper.create_scraper()
         └── _scraper_monitor() fallback to requests
```

### 变更后

```
Request(use_scraper=True)
    └── curl_cffi.requests.Session(impersonate="chrome")
         ├── _convert_proxy()      # proxies dict → proxy string
         ├── _filter_headers()     # 移除 User-Agent
         ├── _check_challenge()    # CF 检测 → SiteBlocked
         ├── _normalize_response() # 补充 history, 转换异常
         └── 无 fallback
```

---

## 核心组件设计

### 1. Request 类改造

```python
class Request:
    def __init__(self, use_scraper=False):
        if use_scraper:
            self._session = curl_cffi.requests.Session()
            self._impersonate = "chrome"  # 硬编码
        else:
            self._session = None  # 使用 requests 模块函数

        self.headers = headers.copy()  # 保持不变
        self.cookies = {}
        self.proxies = read_proxy()
        self.timeout = Cfg().network.timeout.total_seconds()
```

### 2. 代理转换 (_convert_proxy)

```python
def _convert_proxy(self) -> str | None:
    """将 proxies dict 转换为 curl_cffi proxy string"""
    if not self.proxies:
        return None

    # 优先 HTTPS
    proxy = self.proxies.get('https') or self.proxies.get('http')

    if self.proxies.get('http') != self.proxies.get('https'):
        # 脱敏日志：隐藏用户名密码
        logger.warning("HTTP/HTTPS 代理不同，使用 HTTPS 代理")

    return str(proxy) if proxy else None
```

### 3. Headers 过滤 (_filter_headers)

```python
def _filter_headers(self) -> dict:
    """过滤 headers，移除 User-Agent（由 curl_cffi 控制）"""
    filtered = self.headers.copy()
    filtered.pop('User-Agent', None)  # 忽略自定义 UA
    return filtered
```

### 4. Challenge 检测 (_check_challenge)

```python
CF_MARKERS = [b'cdn-cgi', b'Just a moment', b'challenge-platform']

def _check_challenge(self, resp) -> None:
    """检测 CloudFlare 挑战页面"""
    if resp.status_code in (403, 503):
        content = resp.content[:4096]  # 只检查前 4KB
        if any(marker in content for marker in CF_MARKERS):
            raise SiteBlocked("CloudFlare challenge detected")
```

### 5. Response 标准化 (_normalize_response)

```python
def _normalize_response(self, resp, original_url: str):
    """将 curl_cffi Response 标准化为 requests.Response 兼容"""
    # 合成 history（最小 stub）
    if resp.redirect_count > 0 or str(resp.url) != original_url:
        stub = type('StubResponse', (), {
            'status_code': 302,
            'url': original_url
        })()
        resp.history = [stub]
    else:
        resp.history = []

    return resp
```

### 6. 异常转换

```python
EXCEPTION_MAP = {
    curl_cffi.requests.exceptions.ConnectionError: requests.exceptions.ConnectionError,
    curl_cffi.requests.exceptions.Timeout: requests.exceptions.Timeout,
    curl_cffi.requests.exceptions.ProxyError: requests.exceptions.ProxyError,
    curl_cffi.requests.exceptions.SSLError: requests.exceptions.SSLError,
}

def _convert_exception(self, exc):
    """转换 curl_cffi 异常为 requests 异常，保留 __cause__"""
    target_cls = EXCEPTION_MAP.get(type(exc), requests.exceptions.RequestException)
    raise target_cls(str(exc)) from exc
```

---

## 请求流程

```
get(url, delay_raise=False)
    │
    ├─ use_scraper=False ──→ requests.get() ──→ raise_for_status() ──→ return
    │
    └─ use_scraper=True
         │
         ├─ _convert_proxy()     → proxy string
         ├─ _filter_headers()    → headers without UA
         │
         ├─ try:
         │      session.get(url, impersonate="chrome", ...)
         │  except curl_cffi 异常:
         │      _convert_exception() → raise requests 异常
         │
         ├─ _check_challenge()   → SiteBlocked if CF page
         ├─ _normalize_response() → 补充 history
         │
         └─ if not delay_raise:
                resp.raise_for_status()  # 转换后的 resp
```

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|-----|---------|------|
| `javsp/web/base.py` | 修改 | Request 类重构，移除 cloudscraper |
| `pyproject.toml` | 修改 | 移除 cloudscraper，添加 curl_cffi |

**不变的文件**：
- 所有爬虫文件 (`javsp/web/*.py`)
- 配置文件 (`config.yml`)
- 测试数据 (`unittest/data/`)

---

## 测试策略

### 单元测试

1. **API 兼容性** - 验证 Request.get/post/head/get_html 签名不变
2. **Response 属性** - 验证 status_code, content, text, headers, url, history
3. **Challenge 检测** - 模拟 403 + CF 标记响应
4. **异常转换** - 验证 curl_cffi 异常转为 requests 异常

### 集成测试

```bash
# 验证 scraper 模式爬虫
pytest unittest/test_crawlers.py --only javdb
pytest unittest/test_crawlers.py --only javlib
pytest unittest/test_crawlers.py --only airav

# 验证非 scraper 模式爬虫
pytest unittest/test_crawlers.py --only fanza
pytest unittest/test_crawlers.py --only mgstage
```

---

## 风险与缓解

| 风险 | 缓解措施 |
|-----|---------|
| curl_cffi 平台兼容性 | 文档说明支持的平台，CI 覆盖主流系统 |
| Turnstile/CAPTCHA | 抛出 SiteBlocked，用户需提供 cookies 或换地址 |
| history 检查失败 | 最小 stub 满足 truthy 检查，如有问题再扩展 |
