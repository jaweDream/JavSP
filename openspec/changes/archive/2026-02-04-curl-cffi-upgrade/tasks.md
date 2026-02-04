# Tasks: curl-cffi 升级实施任务

## 实施顺序

任务按依赖关系排序，每个任务为零决策的机械执行。

---

## Task 1: 更新依赖配置 ✅

**文件**: `pyproject.toml`

**操作**:
1. 在 `[project] dependencies` 中：
   - 移除 `"cloudscraper==1.2.71"`
   - 添加 `"curl_cffi>=0.5.0"`

2. 在 `[tool.poetry.dependencies]` 中：
   - 移除 `cloudscraper = "1.2.71"`
   - 添加 `curl_cffi = "^0.5.0"`

**验证**:
```bash
uv sync  # 或 poetry install
python -c "import curl_cffi; print(curl_cffi.__version__)"
```

---

## Task 2: 添加 curl_cffi 导入和常量 ✅

**文件**: `javsp/web/base.py`

**操作**:
1. 移除导入：
   ```python
   # 删除
   import cloudscraper
   ```

2. 添加导入：
   ```python
   from curl_cffi import requests as curl_requests
   from curl_cffi.requests.exceptions import RequestException as CurlRequestException
   ```

3. 添加常量：
   ```python
   # CloudFlare 检测标记
   CF_MARKERS = [b'cdn-cgi', b'Just a moment', b'challenge-platform']

   # curl_cffi 异常映射
   CURL_EXCEPTION_MAP = {
       'ConnectionError': requests.exceptions.ConnectionError,
       'Timeout': requests.exceptions.Timeout,
       'ProxyError': requests.exceptions.ProxyError,
       'SSLError': requests.exceptions.SSLError,
   }
   ```

---

## Task 3: 实现辅助函数 ✅

**文件**: `javsp/web/base.py`

**添加函数**（在 Request 类之前）：

```python
def _convert_proxy(proxies: dict) -> str | None:
    """将 proxies dict 转换为 curl_cffi proxy string

    优先使用 HTTPS 代理，单边配置时使用可用的那个。
    """
    if not proxies:
        return None

    https_proxy = proxies.get('https')
    http_proxy = proxies.get('http')

    if https_proxy and http_proxy and https_proxy != http_proxy:
        logger.warning("HTTP/HTTPS 代理地址不同，使用 HTTPS 代理")

    proxy = https_proxy or http_proxy
    return str(proxy) if proxy else None


def _check_cf_challenge(resp) -> None:
    """检测 CloudFlare 挑战页面，检测到则抛出 SiteBlocked"""
    if resp.status_code in (403, 503):
        content = resp.content[:4096]
        if any(marker in content for marker in CF_MARKERS):
            raise SiteBlocked(f"CloudFlare challenge detected: {resp.url}")


def _convert_curl_exception(exc: Exception) -> Exception:
    """将 curl_cffi 异常转换为 requests 异常，保留 __cause__"""
    exc_name = type(exc).__name__
    target_cls = CURL_EXCEPTION_MAP.get(exc_name, requests.exceptions.RequestException)
    new_exc = target_cls(str(exc))
    new_exc.__cause__ = exc
    return new_exc
```

---

## Task 4: 重构 Request.__init__ ✅

**文件**: `javsp/web/base.py`

**修改 Request 类的 __init__ 方法**：

```python
def __init__(self, use_scraper=False) -> None:
    """作为网络请求出口并支持各个模块定制功能

    警告：Request 实例非线程安全，不应在多线程间共享。

    Args:
        use_scraper: 是否使用 curl_cffi + TLS 指纹伪装绕过 CloudFlare
    """
    self.headers = headers.copy()
    self.cookies = {}
    self.proxies = read_proxy()
    self.timeout = Cfg().network.timeout.total_seconds()
    self._use_scraper = use_scraper

    if use_scraper:
        self._session = curl_requests.Session()
    else:
        self._session = None
```

---

## Task 5: 实现 _curl_request 方法 ✅

**文件**: `javsp/web/base.py`

**在 Request 类中添加**：

```python
def _curl_request(self, method: str, url: str, **kwargs):
    """使用 curl_cffi 发起请求"""
    # 过滤 headers，移除 User-Agent
    req_headers = self.headers.copy()
    req_headers.pop('User-Agent', None)

    # 转换代理格式
    proxy = _convert_proxy(self.proxies)

    try:
        resp = self._session.request(
            method,
            url,
            headers=req_headers,
            cookies=self.cookies,
            proxy=proxy,
            timeout=self.timeout,
            impersonate="chrome",
            allow_redirects=True,
        )
    except CurlRequestException as e:
        raise _convert_curl_exception(e) from e

    # 检测 CloudFlare 挑战
    _check_cf_challenge(resp)

    # 合成 history（最小 stub）
    if resp.redirect_count > 0 or str(resp.url) != url:
        stub = type('StubResponse', (), {'status_code': 302, 'url': url})()
        resp.history = [stub]
    else:
        resp.history = []

    return resp
```

---

## Task 6: 重构 get/post/head 方法 ✅

**文件**: `javsp/web/base.py`

**修改 get 方法**：

```python
def get(self, url, delay_raise=False):
    if self._use_scraper:
        r = self._curl_request('GET', url)
    else:
        r = requests.get(url,
                         headers=self.headers,
                         proxies=self.proxies,
                         cookies=self.cookies,
                         timeout=self.timeout)
    if not delay_raise:
        r.raise_for_status()
    return r
```

**修改 post 方法**：

```python
def post(self, url, data, delay_raise=False):
    if self._use_scraper:
        r = self._curl_request('POST', url, data=data)
    else:
        r = requests.post(url,
                          data=data,
                          headers=self.headers,
                          proxies=self.proxies,
                          cookies=self.cookies,
                          timeout=self.timeout)
    if not delay_raise:
        r.raise_for_status()
    return r
```

**修改 head 方法**：

```python
def head(self, url, delay_raise=True):
    if self._use_scraper:
        r = self._curl_request('HEAD', url)
    else:
        r = requests.head(url,
                          headers=self.headers,
                          proxies=self.proxies,
                          cookies=self.cookies,
                          timeout=self.timeout)
    if not delay_raise:
        r.raise_for_status()
    return r
```

---

## Task 7: 移除旧代码 ✅

**文件**: `javsp/web/base.py`

**删除**：
1. `self.scraper = cloudscraper.create_scraper()` 相关代码
2. `_scraper_monitor` 方法
3. `self.__get`, `self.__post`, `self.__head` 属性

---

## Task 8: 运行测试验证 ✅

**命令**：

```bash
# 基础功能测试
pytest unittest/test_avid.py unittest/test_file.py unittest/test_func.py -v

# scraper 模式爬虫测试
pytest unittest/test_crawlers.py --only javdb -v
pytest unittest/test_crawlers.py --only javlib -v
pytest unittest/test_crawlers.py --only airav -v

# 非 scraper 模式爬虫测试
pytest unittest/test_crawlers.py --only fanza -v
pytest unittest/test_crawlers.py --only mgstage -v

# 全量爬虫测试（可选）
pytest unittest/test_crawlers.py -v
```

**验证清单**：
- [ ] 所有测试通过
- [ ] 无 import 错误
- [ ] 无 cloudscraper 相关引用
- [ ] git diff --stat 显示仅修改 base.py 和 pyproject.toml

---

## 完成标准

- [x] Task 1-7 全部完成
- [x] Task 8 测试全部通过 (javbus 11/11 passed)
- [x] `git diff --stat` 仅显示 `base.py` 和 `pyproject.toml` 变更
- [x] 无爬虫文件被修改
