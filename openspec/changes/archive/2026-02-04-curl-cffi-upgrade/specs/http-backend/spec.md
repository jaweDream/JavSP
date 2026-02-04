# HTTP Backend Upgrade Specification

本规格定义了将 `curl_cffi` 集成为主 HTTP 后端，并保持与现有代码完全兼容的行为要求。

---

## ADDED Requirements

### Requirement: curl_cffi 作为主 scraper 后端

当 `Request(use_scraper=True)` 时，系统 SHALL 使用 `curl_cffi` 作为主要 HTTP 客户端，并通过 `impersonate="chrome"` 参数伪装 TLS 指纹。

**约束**：
- `impersonate` 参数硬编码为 `"chrome"`，不支持自定义
- 构造函数签名保持 `Request(use_scraper=False)` 不变

#### Scenario: scraper 模式初始化
- **WHEN** 创建 `Request(use_scraper=True)` 实例
- **THEN** 内部创建 `curl_cffi.requests.Session` 对象
- **THEN** Session 配置为 `impersonate="chrome"`（硬编码，不可更改）

#### Scenario: 非 scraper 模式保持不变
- **WHEN** 创建 `Request(use_scraper=False)` 实例（默认）
- **THEN** 继续使用 `requests` 库
- **THEN** 行为与升级前完全一致

---

### Requirement: CloudFlare Challenge 检测

当 `use_scraper=True` 时，系统 SHALL 检测 CloudFlare 挑战页面并抛出明确异常，而非静默返回挑战页内容。

#### Scenario: 检测到 Challenge 页面
- **WHEN** curl_cffi 返回 HTTP 403 或 503
- **AND** 响应内容包含 CloudFlare 标记（`cdn-cgi`、`Just a moment`、`challenge-platform`）
- **THEN** 抛出 `SiteBlocked` 异常
- **THEN** 异常消息包含 "CloudFlare challenge detected"

#### Scenario: 正常 403/503 响应
- **WHEN** curl_cffi 返回 HTTP 403 或 503
- **AND** 响应内容不包含 CloudFlare 标记
- **THEN** 正常返回响应（或根据 `delay_raise` 抛出 HTTPError）

#### Scenario: 无降级链
- **WHEN** curl_cffi 请求失败（异常或 Challenge）
- **THEN** 不尝试 cloudscraper 或 requests 降级
- **THEN** 直接抛出异常（cloudscraper 对现代 CF 无效，降级无意义）

---

### Requirement: Response 对象兼容性

系统 SHALL 确保所有后端返回的响应对象与 `requests.Response` 行为兼容，无需修改任何爬虫代码。

#### Scenario: 属性兼容性
- **WHEN** 从任意后端获取响应
- **THEN** 响应对象 MUST 具有以下属性：
  - `.status_code` (int)
  - `.content` (bytes)
  - `.text` (str)
  - `.headers` (CaseInsensitiveDict)
  - `.url` (str, 最终 URL)
  - `.history` (list[Response], 重定向链)
  - `.encoding` (str)

#### Scenario: 方法兼容性
- **WHEN** 调用响应对象的方法
- **THEN** `.json()` 返回解析后的 JSON 对象
- **THEN** `.raise_for_status()` 在 4xx/5xx 时抛出 `requests.exceptions.HTTPError`

#### Scenario: resp2html 函数兼容
- **WHEN** 将响应传递给 `resp2html()` 函数
- **THEN** 函数正常工作无需任何修改

#### Scenario: history 合成（最小 stub）
- **WHEN** curl_cffi 返回的 `redirect_count > 0` 或 `final_url != requested_url`
- **THEN** 合成 `history = [stub_response]`
- **THEN** stub_response 仅包含 `status_code=302` 和 `url=requested_url`
- **THEN** 满足现有代码的 `if resp.history:` truthy 检查

---

### Requirement: delay_raise 行为一致性

系统 SHALL 保持 `delay_raise` 参数与升级前完全一致的默认值和行为。

#### Scenario: get/post 方法默认值
- **WHEN** 调用 `get(url)` 或 `post(url, data)` 不传 delay_raise
- **THEN** 默认 `delay_raise=False`
- **THEN** 4xx/5xx 状态码立即抛出 `HTTPError`

#### Scenario: head 方法默认值
- **WHEN** 调用 `head(url)` 不传 delay_raise
- **THEN** 默认 `delay_raise=True`
- **THEN** 不自动抛出异常，返回响应对象

---

### Requirement: 异常类型一致性

系统 SHALL 将所有后端的网络异常统一转换为 `requests.exceptions.RequestException` 子类，确保现有重试逻辑正常工作。

#### Scenario: curl_cffi 异常转换
- **WHEN** curl_cffi 抛出连接错误
- **THEN** 转换为 `requests.exceptions.ConnectionError`
- **THEN** 原始异常保留为 `__cause__`（`raise ... from original_exc`）

#### Scenario: SSL 异常转换
- **WHEN** 任意后端抛出 SSL/TLS 错误
- **THEN** 转换为 `requests.exceptions.SSLError`

#### Scenario: 超时异常转换
- **WHEN** 任意后端请求超时
- **THEN** 转换为 `requests.exceptions.Timeout`

#### Scenario: 代理异常转换
- **WHEN** 代理连接失败
- **THEN** 转换为 `requests.exceptions.ProxyError`

---

### Requirement: 代理参数自动转换

系统 SHALL 自动将现有的 `proxies` 字典格式转换为 `curl_cffi` 期望的格式。

#### Scenario: 标准代理转换
- **WHEN** 配置 `proxies={'http': 'http://proxy:8080', 'https': 'http://proxy:8080'}`
- **THEN** 转换为 curl_cffi 的 `proxy='http://proxy:8080'`
- **THEN** 在日志中记录转换结果

#### Scenario: 空代理处理
- **WHEN** 配置 `proxies={}` 或 `proxies=None`
- **THEN** curl_cffi 不使用代理
- **THEN** 不产生错误

#### Scenario: 不同协议代理
- **WHEN** `http` 和 `https` 代理地址不同
- **THEN** 使用 `https` 代理（优先 HTTPS）
- **THEN** 记录警告日志（脱敏：隐藏代理 URL 中的用户名密码）

#### Scenario: 单边代理配置
- **WHEN** 仅配置 `http` 或仅配置 `https`
- **THEN** 使用已配置的那个代理

#### Scenario: SOCKS 代理支持
- **WHEN** 配置 `proxies={'http': 'socks5://proxy:1080', 'https': 'socks5://proxy:1080'}`
- **THEN** 正确传递给 curl_cffi

---

### Requirement: curl_cffi 模式使用默认 User-Agent

当使用 curl_cffi 后端时，系统 SHALL 使用 curl_cffi 根据 `impersonate` 参数生成的默认 User-Agent，而非项目硬编码的 UA。

#### Scenario: curl_cffi 默认 headers
- **WHEN** 使用 curl_cffi 发起请求
- **THEN** User-Agent 由 curl_cffi 根据 `impersonate="chrome"` 自动设置
- **THEN** 仅覆盖非指纹相关 headers（如 Accept-Language、Referer）
- **THEN** 忽略调用方设置的 `headers['User-Agent']`（保持指纹一致性）

#### Scenario: 非 scraper 模式保持硬编码 UA
- **WHEN** 使用 `use_scraper=False`
- **THEN** 继续使用项目定义的硬编码 User-Agent

---

### Requirement: Cookie 传递兼容性

系统 SHALL 确保传入的 `cookies` 字典在所有后端中被正确发送。

#### Scenario: 字典格式 cookies
- **WHEN** 请求时传入 `cookies={'key': 'value'}`
- **THEN** Cookie 被正确包含在请求头中
- **THEN** 服务端能正确接收该 Cookie

#### Scenario: 多 cookie 传递
- **WHEN** 传入多个 cookie `cookies={'a': '1', 'b': '2'}`
- **THEN** 所有 cookie 均被正确发送

#### Scenario: 无会话级 cookie 累积
- **WHEN** 同一 Request 实例发起多次请求
- **THEN** 每次请求仅发送 `self.cookies` 中的显式 cookies
- **THEN** 不累积服务端 Set-Cookie 返回的 cookies

---

### Requirement: 线程安全文档化

系统 SHALL 在代码文档中明确说明 `Request` 实例的线程安全约束。

#### Scenario: 文档说明
- **WHEN** 查看 `Request` 类的 docstring
- **THEN** 包含线程安全警告："Request 实例非线程安全，不应在多线程间共享"

---

## ADDED Requirements (Dependencies)

### Requirement: 依赖更新

系统 SHALL 在 `pyproject.toml` 中正确配置 `curl_cffi` 依赖。

#### Scenario: 添加 curl_cffi 依赖
- **WHEN** 执行 `uv sync` 或 `poetry install`
- **THEN** `curl_cffi>=0.5.0` 被正确安装
- **THEN** 支持 Python 3.10-3.12

#### Scenario: 移除 cloudscraper 依赖
- **WHEN** 查看 pyproject.toml
- **THEN** `cloudscraper` 依赖已移除
- **THEN** `curl_cffi>=0.5.0` 已添加

---

## Property-Based Testing (PBT) Properties

| ID | 属性 | 不变式 | 伪造策略 |
|----|------|--------|---------|
| PBT-1 | API 兼容性 | `Request.get/post/head/get_html` 签名不变 | 旧版签名比对 |
| PBT-2 | Response 等价性 | 响应具有所有必需属性和方法 | 属性存在性 + 类型断言 |
| PBT-3 | Challenge 检测 | 403/503 + CF 标记触发 SiteBlocked | 模拟 403 + 'cdn-cgi' 响应 |
| PBT-4 | 异常类型一致性 | 网络错误均为 `RequestException` 子类 + `__cause__` 保留 | 异常类型断言 + cause 检查 |
| PBT-5 | Proxy 转换正确性 | HTTPS 优先、单边可用、日志脱敏 | 格式验证 + 日志内容检查 |
| PBT-6 | Cookie 传递性 | 仅显式 cookies 发送，无累积 | 多次请求后 cookies 不变 |
| PBT-7 | History 合成 | 重定向时 history 非空且 history[0].url == 原始 URL | redirect 场景断言 |
| PBT-8 | delay_raise 一致性 | get/post 默认 False，head 默认 True | 各方法默认行为验证 |
| PBT-9 | UA 忽略 | scraper 模式忽略自定义 UA | 设置 UA 后验证实际发送的 UA |
| PBT-10 | impersonate 不可变 | 始终为 "chrome" | 无参数可改变 impersonate |

---

## Resolved Constraints（已解决的约束）

| 约束 | 决策 | 理由 |
|-----|------|------|
| impersonate 自定义 | 硬编码 "chrome" | 简单可靠，避免配置复杂度 |
| delay_raise 默认值 | 保持原有（get/post=False, head=True） | 向后兼容 |
| history 合成 | 最小 stub（status_code=302, url=原始） | 满足现有 truthy 检查即可 |
| CF 检测范围 | 仅 403/503 + 固定标记 | 简单有效，避免过度检测 |
| UA 冲突处理 | 忽略自定义 UA | 保持 TLS 指纹一致性 |
| 代理合并 | 优先 HTTPS + 警告 | 兼容单边配置 |
| cookies 累积 | 不累积，仅显式 | 与现有行为一致 |
| 异常链 | 保留 __cause__ | 便于调试 |
