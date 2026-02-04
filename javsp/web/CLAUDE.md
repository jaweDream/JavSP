[根目录](../../CLAUDE.md) > [javsp](../) > **web**

# Web 爬虫模块

## 变更记录 (Changelog)

| 时间 | 变更内容 |
|-----|---------|
| 2026-02-04T14:40:05 | 初始化模块文档 |

---

## 模块职责

`javsp/web/` 模块负责从各个网站抓取影片元数据，包括：
- 封装统一的 HTTP 请求接口（代理、超时、重试、CloudFlare 绕过）
- 实现 19 个站点的爬虫（解析 HTML/JSON 提取影片信息）
- 提供翻译服务（Google/Bing/Baidu/Claude/OpenAI）
- 定义爬虫相关异常类

---

## 入口与启动

爬虫模块不独立启动，由主程序 `__main__.py` 中的 `import_crawlers()` 动态导入，通过 `parallel_crawler()` 多线程调用。

单独测试爬虫：
```bash
python -m javsp.web.javbus
python -m javsp.web.javdb
```

---

## 对外接口

### 爬虫接口规范

每个爬虫文件必须实现：

```python
def parse_data(movie: MovieInfo) -> None:
    """抓取影片数据并直接更新 movie 对象

    Args:
        movie: MovieInfo 实例，包含 dvdid 或 cid

    Raises:
        MovieNotFoundError: 影片未找到
        SiteBlocked: 站点拦截
        CredentialError: 凭据无效
    """
```

可选实现：

```python
def parse_clean_data(movie: MovieInfo) -> None:
    """抓取数据并进行清洗（genre 映射等）"""
    parse_data(movie)
    movie.genre_norm = genre_map.map(movie.genre_id)
```

### HTTP 请求接口 (`base.py`)

```python
# Request 类 - 支持自定义 headers/cookies
request = Request(use_scraper=True)  # 使用 cloudscraper 绕过 CF
request.headers['Accept-Language'] = 'ja'
request.cookies = {'session': 'xxx'}
html = request.get_html(url)

# 函数式接口
resp = request_get(url, cookies={}, timeout=10)
html = get_html(url, encoding='utf-8')
html = post_html(url, data={})
info = download(url, output_path)

# 工具函数
text = get_resp_text(resp, encoding='utf-8')
html = resp2html(resp)
is_ok = is_connectable(url, timeout=3)
```

### 翻译接口 (`translate.py`)

```python
from javsp.web.translate import translate, translate_movie_info

# 翻译单个文本
result = translate(texts, engine, actress=[])
# 返回: {'trans': '译文', 'orig_break': [...], 'trans_break': [...]}
# 或: {'error': '错误信息'}

# 翻译整个 MovieInfo
success = translate_movie_info(info)  # 根据配置翻译 title/plot
```

---

## 关键依赖与配置

### 依赖包

- `requests`: HTTP 请求
- `cloudscraper`: CloudFlare 绕过
- `lxml`: HTML 解析

### 配置项 (`config.yml`)

```yaml
network:
  proxy_server: 'http://127.0.0.1:7897'  # 代理服务器
  proxy_free:                             # 免代理地址
    javbus: 'https://www.seedmm.help'
    javdb: 'https://javdb368.com'
  retry: 3                                # 重试次数
  timeout: PT10S                          # 超时时间

crawler:
  selection:                              # 各番号类型使用的爬虫
    normal: [airav, avsox, javbus, javdb, javlib, jav321, mgstage, prestige]
    fc2: [fc2, avsox, javdb, javmenu, fc2ppvdb]
    cid: [fanza]
```

---

## 数据模型

### MovieInfo 字段（爬虫需填充）

| 字段 | 类型 | 说明 |
|-----|------|------|
| `dvdid` | str | DVD 番号 (如 IPX-177) |
| `cid` | str | Content ID (如 sqte00300) |
| `url` | str | 影片页面 URL |
| `title` | str | 影片标题 |
| `cover` | str | 封面图 URL |
| `big_cover` | str | 高清封面 URL (可选) |
| `actress` | list[str] | 女优列表 |
| `actress_pics` | dict[str, str] | 女优头像 {name: url} |
| `genre` | list[str] | 分类标签 |
| `genre_id` | list[str] | 分类 ID (用于映射) |
| `genre_norm` | list[str] | 标准化后的分类 |
| `publish_date` | str | 发布日期 (YYYY-MM-DD) |
| `duration` | str | 时长 (分钟数字符串) |
| `producer` | str | 制作商 |
| `publisher` | str | 发行商 |
| `director` | str | 导演 |
| `serial` | str | 系列 |
| `score` | str | 评分 |
| `plot` | str | 剧情简介 |
| `preview_pics` | list[str] | 预览图 URL 列表 |
| `preview_video` | str | 预告片 URL |
| `uncensored` | bool | 是否无码 |

---

## 异常处理 (`exceptions.py`)

```python
class CrawlerError(Exception):
    """爬虫异常基类"""

class MovieNotFoundError(CrawlerError):
    """影片未找到"""
    def __init__(self, mod, avid): ...

class MovieDuplicateError(CrawlerError):
    """搜索结果重复"""
    def __init__(self, mod, avid, dup_count): ...

class SiteBlocked(CrawlerError):
    """站点封锁/CF 拦截"""

class SitePermissionError(CrawlerError):
    """权限不足"""

class CredentialError(CrawlerError):
    """凭据无效"""

class WebsiteError(CrawlerError):
    """网站故障"""
```

---

## 爬虫列表

| 文件 | 站点 | 番号类型 | 特点 |
|-----|------|---------|------|
| `airav.py` | AIRav | normal | 有预告片、简体中文标题 |
| `arzon.py` | Arzon | normal | 需要 Cookies |
| `arzon_iv.py` | Arzon IV | normal | IV 作品 |
| `avsox.py` | AVSOX | normal, fc2 | |
| `avwiki.py` | AVWiki | normal | 素人系列数据丰富 |
| `dl_getchu.py` | DL.Getchu | getchu | 同人作品 |
| `fanza.py` | DMM/FANZA | cid | 主要 CID 数据源 |
| `fc2.py` | FC2 官方 | fc2 | |
| `fc2fan.py` | FC2Fan | fc2 | 已关站，支持本地镜像 |
| `fc2ppvdb.py` | FC2PPVDB | fc2 | |
| `gyutto.py` | Gyutto | gyutto | 同人作品 |
| `jav321.py` | JAV321 | normal | |
| `javbus.py` | JavBus | normal | 有女优头像 |
| `javdb.py` | JavDB | normal, fc2 | 有评分，封面有水印 |
| `javlib.py` | JavLibrary | normal | 有评分 |
| `javmenu.py` | JavMenu | fc2 | |
| `mgstage.py` | MGStage | normal | |
| `njav.py` | NJav | normal | |
| `prestige.py` | Prestige | normal | 蚊香社官网 |

---

## 常见问题 (FAQ)

### Q: 如何添加新爬虫？

1. 创建 `javsp/web/newsite.py`
2. 实现 `parse_data(movie: MovieInfo)` 函数
3. 在 `javsp/config.py` 的 `CrawlerID` 枚举添加站点
4. 在 `config.yml` 的 `crawler.selection` 添加爬虫
5. 创建 `data/genre_newsite.csv` (可选)
6. 添加测试数据到 `unittest/data/`

### Q: 如何处理 CloudFlare 拦截？

```python
# 使用 cloudscraper
request = Request(use_scraper=True)
html = request.get_html(url)

# 或配置免代理地址
# config.yml: network.proxy_free.sitename: 'https://...'
```

### Q: 如何调试爬虫？

```python
# 设置调试模式（自动打开浏览器显示抓取的页面）
import sys
sys.javsp_debug_mode = True

# 保存抓取结果
movie.dump(crawler='sitename')  # 保存到 unittest/data/
```

---

## 相关文件清单

| 文件 | 说明 |
|-----|------|
| `base.py` | HTTP 请求封装、下载功能 |
| `exceptions.py` | 异常类定义 |
| `translate.py` | 翻译服务 |
| `proxyfree.py` | 免代理地址管理 |
| `[site].py` | 各站点爬虫实现 |

---

*文档生成时间: 2026-02-04T14:40:05*
