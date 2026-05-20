# -*- coding: utf-8 -*-
"""
抖音无水印视频下载工具 - 后端服务器 (浏览器版 + 代理下载)
"""
import os
import re
import sys
import json
import time
import atexit
import io
import logging
import subprocess
import tempfile
import zipfile
import shutil
import threading
import webbrowser
import urllib.request
from urllib.parse import quote
from pathlib import Path
from datetime import datetime


def get_base_path():
    """资源路径：开发模式用 __file__ 目录，PyInstaller 打包后用 sys._MEIPASS"""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def get_data_path():
    """运行时数据目录：打包后放 EXE 同级目录，开发模式用项目目录"""
    if getattr(sys, 'frozen', False):
        data_dir = Path(sys.executable).parent
    else:
        data_dir = get_base_path()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

if getattr(sys, 'frozen', False):
    # 打包模式下依赖已内置
    from flask import Flask, request, jsonify, send_from_directory, Response
    from flask_cors import CORS
    from DrissionPage import ChromiumPage, ChromiumOptions
    DRISSION_AVAILABLE = True
else:
    try:
        from flask import Flask, request, jsonify, send_from_directory, Response
        from flask_cors import CORS
    except ImportError:
        print("正在安装 flask...")
        os.system(f'"{sys.executable}" -m pip install flask flask-cors')
        from flask import Flask, request, jsonify, send_from_directory, Response
        from flask_cors import CORS

    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
        DRISSION_AVAILABLE = True
    except ImportError:
        print("正在安装 DrissionPage...")
        os.system(f'"{sys.executable}" -m pip install DrissionPage')
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
            DRISSION_AVAILABLE = True
        except ImportError:
            DRISSION_AVAILABLE = False

# ==================== 配置 ====================

VERSION = "3.8.3"
PORT = 8888
HOST = '127.0.0.1'
DOWNLOAD_DIR = get_data_path() / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 自动查找可用浏览器（便携版 Edge → Chrome → 系统 Edge）
def _find_browser():
    candidates = [
        ("便携版 Edge", str(get_data_path() / "edge" / "msedge.exe")),
        ("Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        ("Chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ("Edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        ("Edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for name, path in candidates:
        if os.path.exists(path):
            return name, path
    return None, None

BROWSER_NAME, BROWSER_PATH = _find_browser()

BASE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})


# ==================== 浏览器管理 ====================

class BrowserManager:
    _page = None
    _lock = threading.Lock()

    @classmethod
    def get_page(cls):
        with cls._lock:
            if cls._page is not None:
                try:
                    cls._page.url
                    return cls._page
                except Exception:
                    cls._page = None

            if not DRISSION_AVAILABLE:
                raise RuntimeError("DrissionPage 未安装")

            if not os.path.exists(BROWSER_PATH):
                raise RuntimeError(f"找不到浏览器: {BROWSER_PATH}")

            import random
            debug_port = random.randint(9223, 9999)

            logger.info(f"启动 {BROWSER_NAME} (调试端口: {debug_port})...")
            opts = ChromiumOptions()
            opts.set_browser_path(BROWSER_PATH)
            opts.set_argument("--remote-debugging-port=" + str(debug_port))
            opts.headless(True)
            opts.set_argument("--no-sandbox")
            opts.set_argument("--disable-dev-shm-usage")
            opts.set_argument("--disable-blink-features=AutomationControlled")
            opts.set_argument("--disable-gpu")
            opts.set_argument(f"--user-agent={BASE_UA}")
            opts.set_argument("--user-data-dir=" + str(get_data_path() / "edge_profile"))

            try:
                cls._page = ChromiumPage(addr_or_opts=opts)
                time.sleep(1.5)
                logger.info("独立 Edge 启动成功")
                return cls._page
            except Exception as e:
                cls._page = None
                raise e

    @classmethod
    def close(cls):
        with cls._lock:
            if cls._page is not None:
                try:
                    cls._page.quit()
                except Exception:
                    pass
                cls._page = None

    @classmethod
    def cleanup_profile(cls):
        """删除 Edge 用户数据目录，防止缓存膨胀和分发泄露"""
        profile_dir = get_data_path() / "edge_profile"
        if profile_dir.exists():
            import shutil
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
                logger.info("[Edge] 用户数据已清理")
            except Exception as e:
                logger.warning(f"[Edge] 清理用户数据失败: {e}")


# 注册退出清理（防止 finally 因进程强杀未执行）
atexit.register(lambda: (BrowserManager.close(), BrowserManager.cleanup_profile()))


# ==================== 解析逻辑 ====================

def parse_douyin_link(link):
    link = link.strip()
    patterns = [
        r"/video/(\d+)",
        r"/note/(\d+)",
        r"modal_id=(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            vid = match.group(1)
            if vid.isdigit() and len(vid) >= 10:
                return vid

    if "v.douyin.com" in link:
        logger.info(f"Short link redirect: {link}")
        try:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(link, method='HEAD', headers={
                "User-Agent": BASE_UA,
                "Referer": "https://www.douyin.com/",
            })
            resp = urllib.request.urlopen(req, context=ctx, timeout=15)
            final_url = resp.geturl()
            logger.info(f"Redirected to: {final_url}")
            return parse_douyin_link(final_url)
        except Exception as e:
            logger.warning(f"HTTP redirect failed: {e}, trying browser...")
            page = BrowserManager.get_page()
            page.get(link)
            page.wait(2)
            final_url = page.url
            logger.info(f"Browser redirect: {final_url}")
            return parse_douyin_link(final_url)

    raise ValueError("无法从链接中提取视频ID")


def get_video_info(video_id):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    url = f"https://www.douyin.com/video/{video_id}"
    logger.info(f"Fetching: {url}")

    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    # Method 1: Try extracting SSR data from HTML via HTTP
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, context=ctx, timeout=30)
        html = resp.read().decode('utf-8', errors='ignore')
        result = _extract_ssr_data(html, video_id)
        if result:
            logger.info("[SUCCESS] SSR extraction successful")
            return result
        logger.info("SSR data not found in HTML")
    except Exception as e:
        logger.warning(f"HTTP fetch failed: {e}")

    # Method 2: Try browser-based approach
    try:
        page = BrowserManager.get_page()
        url = f"https://www.douyin.com/video/{video_id}"
        logger.info(f"Trying browser: {url}")

        page.listen.start("aweme/v1/web/aweme/detail")
        page.get(url)
        page.wait(3)

        # 先尝试 SSR（页面加载后立即可得，无需等待监听）
        result = _extract_ssr_data(page.html, video_id)
        if result:
            page.listen.stop()
            logger.info("[SUCCESS] Browser SSR extraction successful")
            return result

        response_data = None
        for _ in range(5):
            packet = page.listen.wait(timeout=2)
            if packet:
                try:
                    body = packet.response.body
                    if body:
                        data = json.loads(body) if isinstance(body, str) else body
                        if data.get("status_code") == 0 and data.get("aweme_detail"):
                            response_data = data
                            break
                except Exception:
                    continue
            page.scroll.down(200)
            page.wait(1)

        page.listen.stop()

        if response_data:
            return extract_video_data(response_data["aweme_detail"], video_id)
    except Exception as e:
        logger.warning(f"Browser method also failed: {e}")

    raise ValueError("Unable to get video data")


def _extract_ssr_data(html, video_id):
    """从 HTML 中解析 SSR 数据，成功返回 video info，否则返回 None"""
    match = re.search(
        r'__UNIVERSAL_DATA_FOR_HYDRATION__\s*=\s*({.*?});?\s*</script>',
        html, re.DOTALL
    )
    if not match:
        return None
    ssr = json.loads(match.group(1))
    for path in [["default", "aweme"], ["aweme"], ["detail", "aweme"]]:
        d = ssr
        for key in path:
            d = d.get(key, {}) if isinstance(d, dict) else {}
        if isinstance(d, dict) and d.get("video"):
            return extract_video_data(d, video_id)
    return None


def extract_video_data(aweme, video_id):
    video = aweme.get("video", {})

    # 无水印 URL
    video_url = ""
    for addr_name in ["play_addr_h264", "play_addr", "play_addr_265"]:
        addr = video.get(addr_name, {})
        url_list = addr.get("url_list", [])
        if url_list:
            video_url = url_list[0].replace("watermark=1", "watermark=0").replace("watermark=2", "watermark=0")
            break

    if not video_url:
        download = video.get("download_addr", {})
        url_list = download.get("url_list", [])
        if url_list:
            video_url = url_list[0]

    if not video_url:
        raise ValueError("无法获取视频 URL")

    # 元数据
    title = aweme.get("desc", "").strip() or "Douyin Video"
    author = aweme.get("author", {}).get("nickname", "").strip() or "Unknown"
    duration = video.get("duration", 0) // 1000

    # 封面
    cover_url = ""
    for ct in ["cover", "origin_cover"]:
        cd = video.get(ct, {})
        cl = cd.get("url_list", [])
        if cl:
            cover_url = cl[0]
            break

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[\\/*?:"<>|]', '', title)[:50] or "douyin_video"
    filename = f"{safe}_{video_id}_{ts}.mp4"

    logger.info(f"[SUCCESS] Parsed: {title[:30]}...")

    return {
        "video_id": video_id,
        "title": title,
        "author": author,
        "video_url": video_url,
        "cover_url": cover_url,
        "duration": duration,
        "filename": filename,
    }


# ==================== Bilibili 解析逻辑 ====================

BILIBILI_QUALITY = {
    127: "8K 超高清", 126: "4K 120fps HDR", 125: "4K HDR",
    120: "4K", 116: "1080P 60fps", 112: "1080P 高码率",
    80: "1080P", 74: "720P 60fps", 64: "720P",
    32: "480P", 16: "360P", 6: "240P",
}

FFMPEG_PATH = None

# ==================== B站 Cookie 管理 ====================

BILIBILI_COOKIE_FILE = get_data_path() / "bilibili_cookies.json"
_bilibili_cookies = {}


def _load_bilibili_cookies():
    global _bilibili_cookies
    if BILIBILI_COOKIE_FILE.exists():
        try:
            with open(BILIBILI_COOKIE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("SESSDATA"):
                _bilibili_cookies = data
                preview = data['SESSDATA'][-4:]
                logger.info(f"[Bilibili] Cookie 已加载 (SESSDATA: ...{preview})")
            else:
                logger.warning("[Bilibili] Cookie 文件缺少 SESSDATA，已忽略")
        except Exception as e:
            logger.warning(f"[Bilibili] 加载 Cookie 失败: {e}")


def _save_bilibili_cookies(cookies_dict):
    global _bilibili_cookies
    _bilibili_cookies = dict(cookies_dict)
    safe_data = {
        "SESSDATA": cookies_dict.get("SESSDATA", ""),
        "bili_jct": cookies_dict.get("bili_jct", ""),
        "DedeUserID": cookies_dict.get("DedeUserID", ""),
        "DedeUserID__ckMd5": cookies_dict.get("DedeUserID__ckMd5", ""),
    }
    with open(BILIBILI_COOKIE_FILE, 'w', encoding='utf-8') as f:
        json.dump(safe_data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(BILIBILI_COOKIE_FILE, 0o600)
    except OSError:
        pass
    logger.info("[Bilibili] Cookie 已保存")


def _make_bilibili_headers():
    headers = {"User-Agent": BASE_UA, "Referer": "https://www.bilibili.com/"}
    if _bilibili_cookies and _bilibili_cookies.get("SESSDATA"):
        cookie_parts = []
        for key in ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"]:
            if _bilibili_cookies.get(key):
                cookie_parts.append(f"{key}={_bilibili_cookies[key]}")
        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)
    return headers


def _api_get(url, headers, timeout=15):
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
    return json.loads(resp.read().decode('utf-8'))


def _try_parse_pgc_link(link):
    """尝试解析 PGC 链接（电影/番剧），成功返回 dict，否则返回 None"""
    link = link.strip()
    m = re.search(r'/bangumi/play/ep(\d+)', link)
    if m:
        return {"type": "pgc", "pgc_id": f"ep{m.group(1)}"}
    m = re.search(r'/bangumi/play/ss(\d+)', link)
    if m:
        return {"type": "pgc", "pgc_id": f"ss{m.group(1)}"}
    m = re.search(r'/movie/(\d+)', link)
    if m:
        return {"type": "pgc", "pgc_id": f"ss{m.group(1)}"}
    return None


def parse_bilibili_link(link):
    link = link.strip()

    # 纯 BV 号
    m = re.match(r'^BV[a-zA-Z0-9]{10}$', link)
    if m:
        return m.group(0)

    headers = _make_bilibili_headers()

    # av 号 → 调 API 转 BV
    m = re.search(r'av(\d+)', link, re.IGNORECASE)
    if m:
        data = _api_get(f"https://api.bilibili.com/x/web-interface/view?aid={m.group(1)}", headers)
        return data["data"]["bvid"]

    # BV 链接
    m = re.search(r'/video/(BV[a-zA-Z0-9]+)', link)
    if m:
        return m.group(1)

    # b23.tv 短链接
    if "b23.tv" in link:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(link, method='HEAD', headers=headers)
        resp = urllib.request.urlopen(req, context=ctx, timeout=15)
        final_url = resp.geturl()
        if "bilibili.com" not in final_url:
            raise ValueError("短链接重定向到非B站地址，已终止")
        return parse_bilibili_link(final_url)

    raise ValueError("无法从链接中提取B站视频ID")


def _get_pgc_playurl_data(ep_id, cid, headers):
    """使用 PGC API 获取播放地址，返回与普通 API 兼容的 dict"""
    pgc_headers = dict(headers)
    pgc_headers["Referer"] = f"https://www.bilibili.com/bangumi/play/ep{ep_id}"

    # 尝试 v2 API，失败则降级到 v1
    urls = [
        f"https://api.bilibili.com/pgc/player/web/v2/playurl?ep_id={ep_id}&cid={cid}&fnval=4048&fnver=0&fourk=1",
        f"https://api.bilibili.com/pgc/player/web/playurl?ep_id={ep_id}&cid={cid}&fnval=4048&fnver=0&fourk=1",
    ]

    for url in urls:
        try:
            data = _api_get(url, pgc_headers)
            code = data.get("code", -1)
            if code != 0:
                logger.warning(f"[Bilibili] PGC playurl 返回 code={code}: {data.get('message', '')}")
                continue  # 试下一个 API

            # 兼容 v2 (result.video_info.dash) 和 v1 (data.dash)
            result = data.get("result", data.get("data", {}))
            if isinstance(result, dict):
                video_info = result.get("video_info", result)
                dash = video_info.get("dash")
                if dash:
                    return {
                        "dash": dash,
                        "accept_quality": result.get("accept_quality", []),
                        "durl": result.get("durl"),
                    }
        except Exception as e:
            logger.warning(f"[Bilibili] PGC playurl 请求失败: {e}")
            continue

    logger.warning(f"[Bilibili] PGC playurl 全部失败 (ep_id={ep_id})")
    return None


def get_bilibili_pgc_info(pgc_info):
    """解析 PGC 内容（电影/番剧）"""
    pgc_id = pgc_info["pgc_id"]
    headers = _make_bilibili_headers()

    # 判断是 ep_id 还是 season_id
    if pgc_id.startswith("ep"):
        param = f"ep_id={pgc_id[2:]}"
    else:
        param = f"season_id={pgc_id[2:]}"

    # 获取 season 元数据
    season_url = f"https://api.bilibili.com/pgc/view/web/season?{param}"
    pgc_headers = dict(headers)
    pgc_headers["Referer"] = "https://www.bilibili.com/bangumi/play/"
    season = _api_get(season_url, pgc_headers)

    if season.get("code") != 0:
        raise ValueError(f"B站电影API错误: {season.get('message', '无法获取电影信息')}")

    sr = season["result"]
    title = sr.get("title", sr.get("season_title", "B站电影"))
    cover = sr.get("cover", "")
    episodes = sr.get("episodes", [])
    if not episodes:
        raise ValueError("该内容没有可播放的剧集")

    # 取第一个 episode 的 aid 作为参考（电影通常只有一集）
    first_ep = episodes[0]
    video_id = f"ep{first_ep['ep_id']}"
    author = sr.get("up_name", sr.get("publisher", sr.get("type_name", "B站")))

    # 构建页（剧集）列表
    pages = []
    for i, ep in enumerate(episodes):
        ep_id_str = str(ep["ep_id"])
        cid = ep["cid"]
        ep_title = ep.get("title", ep.get("long_title", f"第{i+1}集"))

        # 获取播放地址
        play = _get_pgc_playurl_data(ep_id_str, cid, headers)
        dash = play.get("dash") if play else None
        video_streams = []
        audio_streams = []

        if dash:
            for v in dash.get("video", []):
                url = v.get("baseUrl") or (v.get("backup_url") or [None])[0]
                if url:
                    video_streams.append({
                        "quality": BILIBILI_QUALITY.get(v.get("id"), f"未知({v.get('id')})"),
                        "id": v["id"],
                        "url": url,
                        "bandwidth": v.get("bandwidth", 0),
                    })
            # 去重
            seen = {}
            for vs in video_streams:
                vid = vs["id"]
                if vid not in seen or vs["bandwidth"] > seen[vid]["bandwidth"]:
                    seen[vid] = vs
            video_streams = list(seen.values())
            for a in dash.get("audio", []):
                url = a.get("baseUrl") or (a.get("backup_url") or [None])[0]
                if url:
                    audio_streams.append({
                        "quality": f"{a.get('bandwidth', 0)//1000}k",
                        "id": a["id"],
                        "url": url,
                    })

        if not video_streams and play and play.get("durl"):
            for d in play["durl"]:
                if d.get("url"):
                    video_streams.append({"quality": "自动", "id": 0, "url": d["url"]})

        pages.append({
            "page": i + 1,
            "part": ep_title,
            "cid": cid,
            "ep_id": ep_id_str,
            "duration": ep.get("duration", 0),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[\\/*?:"<>|]', '', title)[:50] or "bilibili_video"
    filename = f"{safe}_{video_id}_{ts}.mp4"

    # 检查是否有至少一集有可用画质，否则说明 Cookie 权限不足或内容受 DRM 保护
    has_any_stream = any(p.get("video_streams") for p in pages)
    if not has_any_stream:
        raise ValueError(
            "无法获取视频流地址，可能原因：① Cookie 已过期 ② 该内容需额外付费 ③ 受 DRM 加密保护"
        )

    return {
        "video_id": video_id,
        "bvid": video_id,
        "aid": first_ep.get("aid", 0),
        "title": title,
        "author": author,
        "cover_url": cover,
        "duration": sr.get("total_duration", 0),
        "filename": filename,
        "total_pages": len(pages),
        "pages": pages,
        "is_pgc": True,
    }


def get_bilibili_info(bvid):
    headers = _make_bilibili_headers()

    # 视频元数据
    view = _api_get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", headers)
    if view.get("code") != 0:
        raise ValueError(f"B站API错误: {view.get('message', '未知错误')}")
    vd = view["data"]

    pages_data = vd.get("pages", [])
    pages = []
    for i, p in enumerate(pages_data):
        cid = p["cid"]
        play = _api_get(
            f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=4048&fnver=0&fourk=1",
            headers,
        )
        ps = play.get("data", {})
        video_streams = []
        audio_streams = []

        # DASH 格式
        dash = ps.get("dash")
        if dash:
            for v in dash.get("video", []):
                url = v.get("baseUrl") or (v.get("backup_url") or [None])[0]
                if url:
                    video_streams.append({
                        "quality": BILIBILI_QUALITY.get(v.get("id"), f"未知({v.get('id')})"),
                        "id": v["id"],
                        "url": url,
                        "bandwidth": v.get("bandwidth", 0),
                    })
            # 去重：同一清晰度保留最高码率
            seen = {}
            for vs in video_streams:
                vid = vs["id"]
                if vid not in seen or vs["bandwidth"] > seen[vid]["bandwidth"]:
                    seen[vid] = vs
            video_streams = list(seen.values())
            for a in dash.get("audio", []):
                url = a.get("baseUrl") or (a.get("backup_url") or [None])[0]
                if url:
                    audio_streams.append({
                        "quality": f"{a.get('bandwidth', 0)//1000}k",
                        "id": a["id"],
                        "url": url,
                    })

        # 非 DASH 旧视频
        if not video_streams and ps.get("durl"):
            for d in ps["durl"]:
                if d.get("url"):
                    video_streams.append({"quality": "自动", "id": 0, "url": d["url"]})

        pages.append({
            "page": i + 1,
            "part": p.get("part", f"P{i+1}"),
            "cid": cid,
            "duration": p.get("duration", 0),
            "video_streams": video_streams,
            "audio_streams": audio_streams,
        })

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[\\/*?:"<>|]', '', vd.get("title", ""))[:50] or "bilibili_video"
    filename = f"{safe}_{bvid}_{ts}.mp4"

    return {
        "video_id": bvid,
        "bvid": bvid,
        "aid": vd.get("aid"),
        "title": vd.get("title", ""),
        "author": vd.get("owner", {}).get("name", "Unknown"),
        "cover_url": vd.get("pic", ""),
        "duration": vd.get("duration", 0),
        "filename": filename,
        "total_pages": len(pages),
        "pages": pages,
    }


# ==================== 路由 ====================

@app.route('/')
def index():
    html_path = get_base_path() / "index.html"
    if html_path.exists():
        return send_from_directory(get_base_path(), "index.html")
    return jsonify({"error": "index.html not found"}), 404


@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"success": True, "status": "running"})


@app.route('/api/parse', methods=['POST'])
def parse():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "error": {"code": "INVALID_REQUEST", "message": "请求数据格式错误"}}), 400
        link = data.get("link", "").strip()
        if not link:
            return jsonify({"success": False, "error": {"code": "INVALID_LINK", "message": "请提供视频链接"}}), 400

        if not DRISSION_AVAILABLE:
            return jsonify({"success": False, "error": {"code": "SERVICE_UNAVAILABLE", "message": "DrissionPage 未安装"}}), 500

        logger.info(f"解析: {link}")
        video_id = parse_douyin_link(link)
        info = get_video_info(video_id)
        return jsonify({"success": True, "data": info}), 200

    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "PARSE_ERROR", "message": str(e)}}), 400
    except Exception as e:
        logger.error(f"未知错误: {e}", exc_info=True)
        return jsonify({"success": False, "error": {"code": "SERVICE_UNAVAILABLE", "message": str(e)}}), 500


# 🔑 下载代理（绕过防盗链）
@app.route('/api/download', methods=['GET'])
def download_video():
    video_id = request.args.get('video_id', '')
    video_url = request.args.get('url', '')

    if not video_url:
        return jsonify({"success": False, "error": {"message": "缺少视频URL"}}), 400

    try:
        logger.info(f"代理下载: {video_id}")
        req = urllib.request.Request(video_url, headers={
            "User-Agent": BASE_UA,
            "Referer": "https://www.douyin.com/",
        })
        resp = urllib.request.urlopen(req, timeout=60)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"douyin_{video_id}_{ts}.mp4"

        return Response(
            resp.read(),
            headers={
                "Content-Type": "video/mp4",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )
    except Exception as e:
        logger.error(f"下载失败: {e}")
        return jsonify({"success": False, "error": {"message": f"下载失败: {str(e)}"}}), 500


@app.route('/api/close', methods=['POST'])
def close():
    BrowserManager.close()
    return jsonify({"success": True})


# ==================== Bilibili 路由 ====================

@app.route('/api/bilibili/parse', methods=['POST'])
def bilibili_parse():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"success": False, "error": {"code": "INVALID_REQUEST", "message": "请求数据格式错误"}}), 400
        link = data.get("link", "").strip()
        if not link:
            return jsonify({"success": False, "error": {"code": "INVALID_LINK", "message": "请提供B站视频链接"}}), 400

        logger.info(f"[Bilibili] 解析: {link}")

        # 先尝试 PGC（电影/番剧），再尝试普通视频
        pgc_info = _try_parse_pgc_link(link)
        if pgc_info:
            info = get_bilibili_pgc_info(pgc_info)
        else:
            bvid = parse_bilibili_link(link)
            info = get_bilibili_info(bvid)

        return jsonify({"success": True, "data": info}), 200

    except ValueError as e:
        return jsonify({"success": False, "error": {"code": "PARSE_ERROR", "message": str(e)}}), 400
    except Exception as e:
        logger.error(f"[Bilibili] 未知错误: {e}", exc_info=True)
        return jsonify({"success": False, "error": {"code": "SERVICE_UNAVAILABLE", "message": str(e)}}), 500


def _download_and_merge(bvid, cid, quality_id, filename, headers, ep_id=None):
    """下载视频+音频流并用 FFmpeg 合并，返回 (file_size, generator) 或 None"""
    logger.info(f"[Bilibili] 刷新播放地址(合并模式): {bvid}/{cid}")
    if ep_id:
        play_data = _get_pgc_playurl_data(ep_id, cid, headers)
    else:
        play = _api_get(
            f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=4048&fnver=0&fourk=1",
            headers,
        )
        play_data = play.get("data", {})
    dash = play_data.get("dash") if play_data else None
    if not dash:
        return None  # 没有 DASH 流，回退

    # 选视频流
    video_url = None
    v_streams = dash.get("video", [])
    if quality_id:
        for v in v_streams:
            if str(v.get("id")) == str(quality_id):
                video_url = v.get("baseUrl") or (v.get("backup_url") or [None])[0]
                break
    if not video_url and v_streams:
        best = max(v_streams, key=lambda x: x.get("bandwidth", 0))
        video_url = best.get("baseUrl") or (best.get("backup_url") or [None])[0]
    if not video_url:
        return None

    # 选最佳音频流（最高带宽）
    audio_url = None
    a_streams = dash.get("audio", [])
    if a_streams:
        best_a = max(a_streams, key=lambda x: x.get("bandwidth", 0))
        audio_url = best_a.get("baseUrl") or (best_a.get("backup_url") or [None])[0]

    if not audio_url:
        logger.info("[Bilibili] 无音频流，回退到视频仅画面模式")
        return None

    # 创建临时文件
    video_tmp = tempfile.NamedTemporaryFile(suffix='.m4s', delete=False)
    audio_tmp = tempfile.NamedTemporaryFile(suffix='.m4s', delete=False)
    output_tmp = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
    video_path, audio_path, output_path = video_tmp.name, audio_tmp.name, output_tmp.name
    video_tmp.close()
    audio_tmp.close()
    output_tmp.close()

    # 下载视频流
    logger.info("[Bilibili] 下载视频流...")
    v_req = urllib.request.Request(video_url, headers=headers)
    v_resp = urllib.request.urlopen(v_req, timeout=120)
    with open(video_path, 'wb') as f:
        shutil.copyfileobj(v_resp, f)

    # 下载音频流
    logger.info("[Bilibili] 下载音频流...")
    a_req = urllib.request.Request(audio_url, headers=headers)
    a_resp = urllib.request.urlopen(a_req, timeout=120)
    with open(audio_path, 'wb') as f:
        shutil.copyfileobj(a_resp, f)

    # FFmpeg 合并
    logger.info("[Bilibili] FFmpeg 合并音视频...")
    cmd = [FFMPEG_PATH, '-y',
           '-i', video_path, '-i', audio_path,
           '-c', 'copy', '-map', '0:v', '-map', '1:a',
           output_path]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    file_size = os.path.getsize(output_path)
    logger.info(f"[Bilibili] 合并完成: {file_size} bytes")

    # 返回文件大小 + 生成器（流式传输，不加载到内存）
    def _stream_and_cleanup():
        try:
            with open(output_path, 'rb') as sf:
                while True:
                    chunk = sf.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            for p in [video_path, audio_path, output_path]:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    return (file_size, _stream_and_cleanup())


@app.route('/api/bilibili/download', methods=['GET'])
def bilibili_download():
    bvid = request.args.get('bvid', '')
    cid = request.args.get('cid', '')
    quality_id = request.args.get('quality_id', '')
    filename = request.args.get('filename', 'bilibili_video.mp4')
    ep_id = request.args.get('ep_id', '')

    if not bvid or not cid:
        return jsonify({"success": False, "error": {"message": "缺少视频参数(BVID/CID)"}}), 400

    try:
        headers = _make_bilibili_headers()

        # 有 FFmpeg 时尝试合并模式
        if FFMPEG_PATH:
            result = _download_and_merge(bvid, cid, quality_id, filename, headers, ep_id or None)
            if result:
                file_size, stream_gen = result
                safe_name = quote(filename, safe='')
                return Response(
                    stream_gen,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Disposition": f"attachment; filename=\"{safe_name}\"; filename*=UTF-8''{safe_name}",
                        "Content-Length": str(file_size),
                    },
                )

        # 回退：仅下载视频轨
        logger.info(f"[Bilibili] 刷新播放地址(仅画面): {bvid}/{cid}")
        if ep_id:
            play_data = _get_pgc_playurl_data(ep_id, cid, headers)
        else:
            play = _api_get(
                f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=4048&fnver=0&fourk=1",
                headers,
            )
            play_data = play.get("data", {})
        video_url = None

        dash = play_data.get("dash") if play_data else None
        if dash:
            streams = dash.get("video", [])
            if quality_id:
                for v in streams:
                    if str(v.get("id")) == str(quality_id):
                        video_url = v.get("baseUrl") or (v.get("backup_url") or [None])[0]
                        break
            if not video_url and streams:
                best = max(streams, key=lambda x: x.get("bandwidth", 0))
                video_url = best.get("baseUrl") or (best.get("backup_url") or [None])[0]

        if not video_url and play_data and play_data.get("durl"):
            video_url = play_data["durl"][0].get("url")

        if not video_url:
            return jsonify({"success": False, "error": {"message": "无法获取视频流地址"}}), 500

        logger.info(f"[Bilibili] 代理下载(仅画面): {filename}")
        req = urllib.request.Request(video_url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=120)
        safe_name = quote(filename, safe='')

        # 流式传输，不加载到内存
        def _stream_video():
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                yield chunk

        return Response(
            _stream_video(),
            headers={
                "Content-Type": "video/mp4",
                "Content-Disposition": f"attachment; filename=\"{safe_name}\"; filename*=UTF-8''{safe_name}",
            },
        )
    except Exception as e:
        logger.error(f"[Bilibili] 下载失败: {e}")
        return jsonify({"success": False, "error": {"message": f"下载失败: {str(e)}"}}), 500


@app.route('/api/bilibili/download-audio', methods=['GET'])
def bilibili_download_audio():
    bvid = request.args.get('bvid', '')
    cid = request.args.get('cid', '')
    filename = request.args.get('filename', 'bilibili_audio')
    ep_id = request.args.get('ep_id', '')

    if not bvid or not cid:
        return jsonify({"success": False, "error": {"message": "缺少视频参数(BVID/CID)"}}), 400

    try:
        headers = _make_bilibili_headers()

        # 刷新播放地址
        logger.info(f"[Bilibili] 刷新音频地址: {bvid}/{cid}")
        if ep_id:
            play_data = _get_pgc_playurl_data(ep_id, cid, headers)
        else:
            play = _api_get(
                f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={cid}&fnval=4048&fnver=0&fourk=1",
                headers,
            )
            play_data = play.get("data", {})
        dash = play_data.get("dash", {}) if play_data else {}
        a_streams = dash.get("audio", [])
        if not a_streams:
            return jsonify({"success": False, "error": {"message": "该视频无独立音频流"}}), 400

        # 取最高码率音频流
        best = max(a_streams, key=lambda x: x.get("bandwidth", 0))
        audio_url = best.get("baseUrl") or (best.get("backup_url") or [None])[0]
        if not audio_url:
            return jsonify({"success": False, "error": {"message": "无法获取音频流地址"}}), 500

        kbps = best.get("bandwidth", 0) // 1000
        logger.info(f"[Bilibili] 下载音频流 ({kbps}kbps)...")
        a_req = urllib.request.Request(audio_url, headers=headers)
        a_resp = urllib.request.urlopen(a_req, timeout=120)
        raw_audio = a_resp.read()

        # FFmpeg 可用时：流复制 → .m4a
        if FFMPEG_PATH:
            audio_tmp = tempfile.NamedTemporaryFile(suffix='.m4s', delete=False)
            output_tmp = tempfile.NamedTemporaryFile(suffix='.m4a', delete=False)
            audio_path, output_path = audio_tmp.name, output_tmp.name
            audio_tmp.close()
            output_tmp.close()
            try:
                with open(audio_path, 'wb') as f:
                    f.write(raw_audio)
                subprocess.run(
                    [FFMPEG_PATH, '-y', '-i', audio_path, '-c', 'copy', output_path],
                    check=True, capture_output=True, timeout=60,
                )
                with open(output_path, 'rb') as f:
                    raw_audio = f.read()
            finally:
                for p in [audio_path, output_path]:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        safe_name = quote(filename + '.m4a', safe='')
        return Response(
            raw_audio,
            headers={
                "Content-Type": "audio/mp4",
                "Content-Disposition": f"attachment; filename=\"{safe_name}\"; filename*=UTF-8''{safe_name}",
            },
        )
    except Exception as e:
        logger.error(f"[Bilibili] 音频下载失败: {e}")
        return jsonify({"success": False, "error": {"message": f"音频下载失败: {str(e)}"}}), 500


@app.route('/api/bilibili/ffmpeg-status', methods=['GET'])
def bilibili_ffmpeg_status():
    return jsonify({"available": FFMPEG_PATH is not None, "path": FFMPEG_PATH})


@app.route('/api/bilibili/cookie-status', methods=['GET'])
def bilibili_cookie_status():
    has = bool(_bilibili_cookies and _bilibili_cookies.get("SESSDATA"))
    return jsonify({"success": True, "data": {"has_cookies": has}})


@app.route('/api/bilibili/set-cookies', methods=['POST'])
def bilibili_set_cookies():
    try:
        data = request.get_json(silent=True)
        if not data or not data.get("cookies"):
            return jsonify({"success": False, "error": "请提供 Cookie 数据"}), 400
        cookies = data["cookies"]
        if not cookies.get("SESSDATA"):
            return jsonify({"success": False, "error": "缺少 SESSDATA"}), 400
        _save_bilibili_cookies(cookies)
        return jsonify({"success": True, "message": "Cookie 已保存"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/bilibili/clear-cookies', methods=['POST'])
def bilibili_clear_cookies():
    try:
        _save_bilibili_cookies({})
        if BILIBILI_COOKIE_FILE.exists():
            BILIBILI_COOKIE_FILE.unlink()
        return jsonify({"success": True, "message": "Cookie 已清除"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/bilibili/validate-cookies', methods=['POST'])
def bilibili_validate_cookies():
    try:
        data = request.get_json(silent=True)
        test_bvid = (data or {}).get("test_bvid", "")
        test_cookies = (data or {}).get("cookies") if data else None

        if test_cookies and test_cookies.get("SESSDATA"):
            check_headers = _make_bilibili_headers()
        else:
            check_headers = _make_bilibili_headers()

        # 检查用户身份
        nav = _api_get("https://api.bilibili.com/x/web-interface/nav", check_headers)
        nd = nav.get("data", {})
        is_login = nd.get("isLogin", False)
        uname = nd.get("uname", "")
        vip = nd.get("vipStatus", 0) == 1
        vip_type = nd.get("vipType", 0)

        # 检查可用画质
        available_qualities = []
        if test_bvid and is_login:
            try:
                view = _api_get(
                    f"https://api.bilibili.com/x/web-interface/view?bvid={test_bvid}",
                    check_headers,
                )
                first_cid = view.get("data", {}).get("cid") or view["data"]["pages"][0]["cid"]
                play = _api_get(
                    f"https://api.bilibili.com/x/player/playurl?bvid={test_bvid}&cid={first_cid}&fnval=4048&fnver=0&fourk=1",
                    check_headers,
                )
                for q in play.get("data", {}).get("accept_quality", []):
                    available_qualities.append({
                        "id": q,
                        "label": BILIBILI_QUALITY.get(q, f"未知({q})"),
                    })
            except Exception as e:
                logger.warning(f"[Bilibili] Cookie 验证 - playurl 测试失败: {e}")

        return jsonify({
            "success": True,
            "data": {
                "is_login": is_login,
                "user_name": uname,
                "is_vip": vip,
                "vip_type": vip_type,
                "available_qualities": available_qualities,
            },
        })
    except Exception as e:
        logger.error(f"[Bilibili] Cookie 验证失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== FFmpeg 检测与自动下载 ====================

def find_ffmpeg():
    """查找系统 FFmpeg，返回路径或 None"""
    global FFMPEG_PATH
    exe = shutil.which('ffmpeg')
    if exe:
        FFMPEG_PATH = exe
        return exe
    for p in [get_data_path() / 'bin' / 'ffmpeg.exe', get_data_path() / 'ffmpeg.exe']:
        if p.exists():
            FFMPEG_PATH = str(p)
            return FFMPEG_PATH
    FFMPEG_PATH = None
    return None


def ensure_ffmpeg(logger_fn=print):
    """确保 FFmpeg 可用，若缺失则自动下载（GitHub + 国内镜像）"""
    if find_ffmpeg():
        logger_fn(f"[FFmpeg] [OK] {FFMPEG_PATH}")
        return True

    logger_fn("[FFmpeg] 未找到，正在自动下载便携版...")
    bin_dir = get_data_path() / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)

    urls = [
        ("GitHub", "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
        ("GHProxy", "https://mirror.ghproxy.com/https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
    ]

    for label, url in urls:
        logger_fn(f"[FFmpeg] 尝试 {label} ...")
        try:
            _download_and_extract_ffmpeg(url, bin_dir, logger_fn)
            zip_path = bin_dir / "ffmpeg.zip"
            if zip_path.exists():
                zip_path.unlink()
            if find_ffmpeg():
                logger_fn(f"[FFmpeg] 下载完成 ({label}): {FFMPEG_PATH}")
                return True
        except Exception as e:
            logger_fn(f"[FFmpeg] {label} 下载失败: {e}")
            zip_path = bin_dir / "ffmpeg.zip"
            if zip_path.exists():
                zip_path.unlink()

    logger_fn("[FFmpeg] 所有源均失败，将回退到仅画面下载模式")
    return False


def _download_and_extract_ffmpeg(url, bin_dir, logger_fn):
    zip_path = bin_dir / "ffmpeg.zip"
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": BASE_UA})
    resp = urllib.request.urlopen(req, context=ctx, timeout=30)
    total = int(resp.headers.get('Content-Length', 0))
    downloaded = 0
    logger_fn(f"[FFmpeg] 下载中 (约 {total//1024//1024}MB)...")
    with open(zip_path, 'wb') as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if total and downloaded % (5 * 1024 * 1024) < 65536:
                pct = downloaded * 100 // total
                logger_fn(f"[FFmpeg] 进度: {pct}%")

    logger_fn("[FFmpeg] 解压中...")
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith('/bin/ffmpeg.exe') or name.endswith('\\bin\\ffmpeg.exe') or 'bin' in name and 'ffmpeg.exe' in name:
                source = zf.open(name)
                target = bin_dir / 'ffmpeg.exe'
                with open(target, 'wb') as out:
                    shutil.copyfileobj(source, out)
                break
        else:
            raise RuntimeError("在压缩包中未找到 ffmpeg.exe")


# ==================== 静态文件托管 ====================

@app.route('/<path:filename>')
def serve_static(filename):
    file_path = get_base_path() / filename
    if file_path.exists() and file_path.is_file():
        return send_from_directory(get_base_path(), filename)
    return jsonify({"error": "Not found"}), 404


# ==================== 启动 ====================

def main():
    # 确保 FFmpeg 可用
    ffmpeg_ok = ensure_ffmpeg(lambda msg: print(msg))

    # 加载 B站 Cookie
    _load_bilibili_cookies()

    print("=" * 60)
    print(f"  Yapotato Tool v{VERSION}（多浏览器版本）(抖音 + Bilibili)")
    print("=" * 60)
    print(f"  URL: http://{HOST}:{PORT}")
    if BROWSER_PATH:
        print(f"  浏览器: {BROWSER_NAME} [OK]")
    else:
        print(f"  浏览器: [ERROR] 未找到 Chrome 或 Edge")
    cookie_ok = bool(_bilibili_cookies and _bilibili_cookies.get("SESSDATA"))
    print(f"  Bilibili API: [OK] {'[COOKIE: OK]' if cookie_ok else '[COOKIE: NONE (仅480P)]'}")
    print(f"  FFmpeg: {'[OK]' if ffmpeg_ok else '[NOT_FOUND] 仅画面模式'}")
    print(f"  Press Ctrl+C to stop")
    print("=" * 60)

    if not BROWSER_PATH:
        print(f"\n[ERROR] 未找到 Chrome 或 Edge，抖音解析不可用")
        print(f"   如需抖音功能，请安装 Chrome 或将 Edge 便携版放到 edge/ 目录")
        return

    try:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://{HOST}:{PORT}")), daemon=True).start()
        app.run(host=HOST, port=PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nShutting down...")
        BrowserManager.close()
        BrowserManager.cleanup_profile()
        print("Stopped")

if __name__ == "__main__":
    main()