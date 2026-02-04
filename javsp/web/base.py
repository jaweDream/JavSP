"""网络请求的统一接口"""
import os
import sys
import time
import shutil
import logging
import requests
import contextlib
import lxml.html
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import RequestException as CurlRequestException
from tqdm import tqdm
from lxml import etree
from lxml.html.clean import Cleaner
from requests.models import Response


from javsp.config import Cfg
from javsp.web.exceptions import *


__all__ = ['Request', 'get_html', 'post_html', 'request_get', 'resp2html', 'is_connectable', 'download', 'get_resp_text', 'read_proxy']


headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }

logger = logging.getLogger(__name__)
# 删除js脚本相关的tag，避免网页检测到没有js运行环境时强行跳转，影响调试
cleaner = Cleaner(kill_tags=['script', 'noscript'])

# CloudFlare 检测标记
CF_MARKERS = [b'cdn-cgi', b'Just a moment', b'challenge-platform']

# curl_cffi 异常映射
CURL_EXCEPTION_MAP = {
    'ConnectionError': requests.exceptions.ConnectionError,
    'Timeout': requests.exceptions.Timeout,
    'ProxyError': requests.exceptions.ProxyError,
    'SSLError': requests.exceptions.SSLError,
}

def read_proxy():
    if Cfg().network.proxy_server is None:
        return {}
    else:
        proxy = str(Cfg().network.proxy_server)
        return {'http': proxy, 'https': proxy}


def _convert_proxy(proxies: dict) -> str | None:
    """将 proxies dict 转换为 curl_cffi proxy string"""
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

# 与网络请求相关的功能汇总到一个模块中以方便处理，但是不同站点的抓取器又有自己的需求（针对不同网站
# 需要使用不同的UA、语言等）。每次都传递参数很麻烦，而且会面临函数参数越加越多的问题。因此添加这个
# 处理网络请求的类，它带有默认的属性，但是也可以在各个抓取器模块里进行进行定制
class Request():
    """作为网络请求出口并支持各个模块定制功能

    警告：Request 实例非线程安全，不应在多线程间共享。
    """
    def __init__(self, use_scraper=False) -> None:
        self.headers = headers.copy()
        self.cookies = {}
        self.proxies = read_proxy()
        self.timeout = Cfg().network.timeout.total_seconds()
        self._use_scraper = use_scraper
        if use_scraper:
            self._session = curl_requests.Session()
        else:
            self._session = None

    def _curl_request(self, method: str, url: str, **kwargs):
        """使用 curl_cffi 发起请求"""
        req_headers = self.headers.copy()
        req_headers.pop('User-Agent', None)
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
                **kwargs,
            )
        except CurlRequestException as e:
            raise _convert_curl_exception(e) from e
        _check_cf_challenge(resp)
        if resp.redirect_count > 0:
            stub = type('StubResponse', (), {'status_code': 302, 'url': url})()
            resp.history = [stub]
        else:
            resp.history = []
        return resp

    def _raise_for_status(self, r):
        """调用 raise_for_status，转换 curl_cffi 异常为 requests 异常"""
        try:
            r.raise_for_status()
        except CurlRequestException as e:
            raise _convert_curl_exception(e) from e

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
            self._raise_for_status(r)
        return r

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
            self._raise_for_status(r)
        return r

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
            self._raise_for_status(r)
        return r

    def get_html(self, url):
        r = self.get(url)
        html = resp2html(r)
        return html


class DownloadProgressBar(tqdm):
    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        self.update(b * bsize - self.n)


def request_get(url, cookies={}, timeout=None, delay_raise=False):
    """获取指定url的原始请求"""
    if timeout is None:
        timeout = Cfg().network.timeout.seconds
    
    r = requests.get(url, headers=headers, proxies=read_proxy(), cookies=cookies, timeout=timeout)
    if not delay_raise:
        if r.status_code == 403 and b'>Just a moment...<' in r.content:
            raise SiteBlocked(f"403 Forbidden: 无法通过CloudFlare检测: {url}")
        else:
            r.raise_for_status()
    return r


def request_post(url, data, cookies={}, timeout=None, delay_raise=False):
    """向指定url发送post请求"""
    if timeout is None:
        timeout = Cfg().network.timeout.seconds
    r = requests.post(url, data=data, headers=headers, proxies=read_proxy(), cookies=cookies, timeout=timeout)
    if not delay_raise:
        r.raise_for_status()
    return r


def get_resp_text(resp: Response, encoding=None):
    """提取Response的文本"""
    if encoding:
        resp.encoding = encoding
    elif hasattr(resp, 'apparent_encoding') and resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding
    return resp.text


def get_html(url, encoding='utf-8'):
    """使用get方法访问指定网页并返回经lxml解析后的document"""
    resp = request_get(url)
    text = get_resp_text(resp, encoding=encoding)
    html = lxml.html.fromstring(text)
    html.make_links_absolute(url, resolve_base_href=True)
    # 清理功能仅应在需要的时候用来调试网页（如prestige），否则可能反过来影响调试（如JavBus）
    # html = cleaner.clean_html(html)
    if hasattr(sys, 'javsp_debug_mode'):
        lxml.html.open_in_browser(html, encoding=encoding)  # for develop and debug
    return html


def resp2html(resp, encoding='utf-8') -> lxml.html.HtmlComment:
    """将request返回的response转换为经lxml解析后的document"""
    text = get_resp_text(resp, encoding=encoding)
    html = lxml.html.fromstring(text)
    html.make_links_absolute(resp.url, resolve_base_href=True)
    # html = cleaner.clean_html(html)
    if hasattr(sys, 'javsp_debug_mode'):
        lxml.html.open_in_browser(html, encoding=encoding)  # for develop and debug
    return html


def post_html(url, data, encoding='utf-8', cookies={}):
    """使用post方法访问指定网页并返回经lxml解析后的document"""
    resp = request_post(url, data, cookies=cookies)
    text = get_resp_text(resp, encoding=encoding)
    html = lxml.html.fromstring(text)
    # jav321提供ed2k形式的资源链接，其中的非ASCII字符可能导致转换失败，因此要先进行处理
    ed2k_tags = html.xpath("//a[starts-with(@href,'ed2k://')]")
    for tag in ed2k_tags:
        tag.attrib['ed2k'], tag.attrib['href'] = tag.attrib['href'], ''
    html.make_links_absolute(url, resolve_base_href=True)
    for tag in ed2k_tags:
        tag.attrib['href'] = tag.attrib['ed2k']
        tag.attrib.pop('ed2k')
    # html = cleaner.clean_html(html)
    # lxml.html.open_in_browser(html, encoding=encoding)  # for develop and debug
    return html


def dump_xpath_node(node, filename=None):
    """将xpath节点dump到文件"""
    if not filename:
        filename = node.tag + '.html'
    with open(filename, 'wt', encoding='utf-8') as f:
        content = etree.tostring(node, pretty_print=True).decode('utf-8')
        f.write(content)


def is_connectable(url, timeout=3):
    """测试与指定url的连接"""
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        return True
    except requests.exceptions.RequestException as e:
        logger.debug(f"Not connectable: {url}\n" + repr(e))
        return False


def urlretrieve(url, filename=None, reporthook=None, headers=None):
    if "arzon" in url:
        headers["Referer"] = "https://www.arzon.jp/"
    """使用requests实现urlretrieve"""
    # https://blog.csdn.net/qq_38282706/article/details/80253447
    with contextlib.closing(requests.get(url, headers=headers,
                                         proxies=read_proxy(), stream=True)) as r:
        header = r.headers
        with open(filename, 'wb+') as fp:
            bs = 1024
            size = -1
            blocknum = 0
            if "content-length" in header:
                size = int(header["Content-Length"])    # 文件总大小（理论值）
            if reporthook:                              # 写入前运行一次回调函数
                reporthook(blocknum, bs, size)
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    fp.write(chunk)
                    fp.flush()
                    blocknum += 1
                    if reporthook:
                        reporthook(blocknum, bs, size)  # 每写入一次运行一次回调函数


def download(url, output_path, desc=None):
    """下载指定url的资源"""
    # 支持“下载”本地资源，以供fc2fan的本地镜像所使用
    if not url.startswith('http'):
        start_time = time.time()
        shutil.copyfile(url, output_path)
        filesize = os.path.getsize(url)
        elapsed = time.time() - start_time
        info = {'total': filesize, 'elapsed': elapsed, 'rate': filesize/elapsed}
        return info
    if not desc:
        desc = url.split('/')[-1]
    referrer = headers.copy()
    referrer['referer'] = url[:url.find('/', 8)+1]  # 提取base_url部分
    with DownloadProgressBar(unit='B', unit_scale=True,
                             miniters=1, desc=desc, leave=False) as t:
        urlretrieve(url, filename=output_path, reporthook=t.update_to, headers=referrer)
        info = {k: t.format_dict[k] for k in ('total', 'elapsed', 'rate')}
        return info


def open_in_chrome(url, new=0, autoraise=True):
    """使用指定的Chrome Profile打开url，便于调试"""
    import subprocess
    chrome = R'C:\Program Files\Google\Chrome\Application\chrome.exe'
    subprocess.run(f'"{chrome}" --profile-directory="Profile 2" {url}', shell=True)

import webbrowser
webbrowser.open = open_in_chrome


if __name__ == "__main__":
    import pretty_errors
    pretty_errors.configure(display_link=True)
    download('https://www.javbus.com/pics/cover/6n54_b.jpg', 'cover.jpg')
