"""工具箱 · 转换引擎。

分工：
    ffmpeg  音频 / 视频   转码、裁剪、调音量、抽音轨、抽帧
    Pillow  图片          格式互转、缩放、压缩、水印、拼 PDF
    纯 Python 文档         Word/Excel/PPT -> PDF（文字版）；
                           图片 -> PDF；PDF 合并/拆分/转图片

设计要点：
    · 文件落在 data/toolbox/<提取码>/，3 天后自动清理
    · 每个任务记 IP 和 cookie，同一来源 3 天内能反复下载
    · 单文件上限 100MB（云电脑 CPU 弱，视频转码很吃资源）
    · 转换全部走子进程调 ffmpeg，超时和并发都要卡住，别把机器搞死
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
BOX_DIR = os.path.join(DATA_DIR, "toolbox")
JOBS_FILE = os.path.join(DATA_DIR, "toolbox.json")
BIN_DIR = os.path.join(ROOT, "bin")

FFMPEG = os.path.join(BIN_DIR, "ffmpeg.exe")
FFPROBE = os.path.join(BIN_DIR, "ffprobe.exe")

KEEP_SECONDS = 3 * 24 * 3600      # 保留 3 天
MAX_BYTES = 100 * 1024 * 1024     # 单文件 100MB
MAX_JOBS = 200                    # 最多同时留多少个任务
CONVERT_TIMEOUT = 900             # 单次转换最长 15 分钟
MAX_CONCURRENT = 1                # 云电脑 CPU 弱，一次只转一个

_lock = threading.RLock()
_running = [0]

# ---------------------------------------------------------------- 能力表

AUDIO_FMT = {
    "mp3":  [".mp3"],
    "wav":  [".wav"],
    "flac": [".flac"],
    "aac":  [".aac", ".m4a"],
    "ogg":  [".ogg", ".oga"],
    "wma":  [".wma"],
    "opus": [".opus"],
}
VIDEO_FMT = {
    "mp4":  [".mp4"],
    "mkv":  [".mkv"],
    "avi":  [".avi"],
    "mov":  [".mov"],
    "webm": [".webm"],
    "gif":  [".gif"],
}
IMAGE_FMT = {
    "jpg":  [".jpg", ".jpeg"],
    "png":  [".png"],
    "webp": [".webp"],
    "bmp":  [".bmp"],
    "gif":  [".gif"],
    "tiff": [".tiff", ".tif"],
}
DOC_IN = [".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".csv", ".md"]


def ffmpeg_ready():
    return os.path.isfile(FFMPEG)


LOCKED_EXT = {".ncm", ".qmc0", ".qmc3", ".qmcflac", ".qmcogg", ".qmc2",
              ".mflac", ".mflac0", ".mgg", ".mgg1", ".mggl",
              ".kgm", ".kgma", ".kgg", ".vpr", ".kwm", ".xm"}


def kind_of(name):
    e = os.path.splitext(name or "")[1].lower()
    if e in LOCKED_EXT:
        return "locked"
    for k, exts in (("audio", AUDIO_FMT), ("video", VIDEO_FMT),
                    ("image", IMAGE_FMT)):
        for lst in exts.values():
            if e in lst:
                return k
    if e == ".pdf":
        return "pdf"
    if e in DOC_IN:
        return "doc"
    return "other"


# ---------------------------------------------------------------- 任务存储

def _load():
    try:
        with open(JOBS_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = JOBS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, JOBS_FILE)


def _new_code():
    return hashlib.md5((str(time.time()) + os.urandom(8).hex()).encode()).hexdigest()[:6].upper()


def job_dir(code):
    return os.path.join(BOX_DIR, code)


def save_upload(filename, blob, ip="", cookie=""):
    """存一个上传的文件，返回 (提取码, 任务信息)。超限则抛 ValueError。"""
    if len(blob) > MAX_BYTES:
        raise ValueError("文件超过 100MB，不给转")
    if not blob:
        raise ValueError("空文件")

    with _lock:
        d = _load()
        _sweep(d)
        code = _new_code()
        while code in d:
            code = _new_code()
        dd = job_dir(code)
        os.makedirs(dd, exist_ok=True)
        safe = re.sub(r"[^\w\u4e00-\u9fa5.\-]", "_", os.path.basename(filename or "file"))
        path = os.path.join(dd, safe)
        with open(path, "wb") as f:
            f.write(blob)
        d[code] = {
            "code": code,
            "created": time.time(),
            "expire": time.time() + KEEP_SECONDS,
            "ip": ip,
            "cookie": cookie,
            "files": [{"name": safe, "size": len(blob), "kind": kind_of(safe)}],
            "ops": [],
        }
        _save(d)
        return code, d[code]


def _sweep(d=None):
    """删掉过期的任务（文件和记录一起）。"""
    own = d is None
    if own:
        d = _load()
    now = time.time()
    dead = [k for k, v in d.items() if (v.get("expire") or 0) < now]
    for k in dead:
        try:
            shutil.rmtree(job_dir(k), ignore_errors=True)
        except Exception:
            pass
        d.pop(k, None)
    if dead or own:
        _save(d)
    return len(dead)


def list_jobs(ip="", cookie=""):
    with _lock:
        d = _load()
        _sweep(d)
        out = []
        for v in d.values():
            if (ip and v.get("ip") == ip) or (cookie and v.get("cookie") == cookie):
                out.append(v)
        return sorted(out, key=lambda x: x.get("created") or 0, reverse=True)


def get_job(code, ip="", cookie=""):
    with _lock:
        d = _load()
        _sweep(d)
        v = d.get((code or "").upper())
        if not v:
            return None
        return v


def add_file(code, filename, blob):
    if len(blob) > MAX_BYTES:
        raise ValueError("文件超过 100MB")
    with _lock:
        d = _load()
        v = d.get(code)
        if not v:
            raise ValueError("提取码不存在")
        dd = job_dir(code)
        os.makedirs(dd, exist_ok=True)
        safe = re.sub(r"[^\w\u4e00-\u9fa5.\-]", "_", os.path.basename(filename or "file"))
        with open(os.path.join(dd, safe), "wb") as f:
            f.write(blob)
        v.setdefault("files", []).append({"name": safe, "size": len(blob), "kind": kind_of(safe)})
        _save(d)
        return v


# ---------------------------------------------------------------- 转换调度

def _slot():
    """并发闸门：云电脑只允许一个转换在跑。"""
    while True:
        with _lock:
            if _running[0] < MAX_CONCURRENT:
                _running[0] += 1
                return True
        time.sleep(1.5)


def _release():
    with _lock:
        _running[0] = max(0, _running[0] - 1)


def _run(cmd, timeout=CONVERT_TIMEOUT):
    """跑一条外部命令，返回 (成功, 输出尾部)。"""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        tail = (p.stdout or b"").decode("utf-8", "replace")[-1200:]
        return p.returncode == 0, tail
    except subprocess.TimeoutExpired:
        return False, "转换超时（超过 %d 分钟）" % (timeout // 60)
    except FileNotFoundError:
        return False, "找不到 ffmpeg，请确认 bin/ffmpeg.exe 存在"
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)


def _probe(path):
    """用 ffprobe 读时长等信息。"""
    try:
        p = subprocess.run([FFPROBE, "-v", "quiet", "-print_format", "json",
                            "-show_format", "-show_streams", path],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        return json.loads((p.stdout or b"{}").decode("utf-8", "replace"))
    except Exception:
        return {}


# ---------------------------------------------------------------- 音频 / 视频

def audio_convert(src, dst, fmt="mp3", bitrate="192k", sample_rate=None, volume=None):
    cmd = [FFMPEG, "-y", "-i", src]
    if volume is not None:
        cmd += ["-af", "volume=%.2f" % volume]
    if fmt == "wav":
        cmd += ["-c:a", "pcm_s16le"]
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
    elif fmt == "flac":
        cmd += ["-c:a", "flac"]
    elif fmt == "aac":
        cmd += ["-c:a", "aac", "-b:a", bitrate]
    elif fmt == "ogg":
        cmd += ["-c:a", "libvorbis", "-b:a", bitrate]
    elif fmt == "opus":
        cmd += ["-c:a", "libopus", "-b:a", bitrate]
    elif fmt == "wma":
        cmd += ["-c:a", "wmav2", "-b:a", bitrate]
    else:
        cmd += ["-c:a", "libmp3lame", "-b:a", bitrate]
    cmd += ["-vn", dst]
    return _run(cmd)


def video_convert(src, dst, fmt="mp4", scale=None, crf=23, volume=None, mute=False):
    vf = []
    if scale:
        vf.append("scale=%s:-2" % scale)
    cmd = [FFMPEG, "-y", "-i", src]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    if mute:
        cmd += ["-an"]
    elif volume is not None:
        cmd += ["-af", "volume=%.2f" % volume]
    if fmt == "webm":
        cmd += ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0"]
        if not mute:
            cmd += ["-c:a", "libopus"]
    elif fmt == "gif":
        cmd += ["-vf", "fps=10,scale=480:-1", "-loop", "0"]
    else:
        cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast",
                "-pix_fmt", "yuv420p"]
        if not mute:
            cmd += ["-c:a", "aac", "-b:a", "160k"]
    cmd += [dst]
    return _run(cmd)


def cut(src, dst, start=None, duration=None, reencode=True):
    """按时间切一段。start/duration 是秒。"""
    cmd = [FFMPEG, "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", src]
    if duration:
        cmd += ["-t", str(duration)]
    if reencode:
        cmd += ["-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-c", "copy"]
    cmd += [dst]
    return _run(cmd)


def extract_audio(src, dst, fmt="mp3"):
    return audio_convert(src, dst, fmt=fmt)


def extract_frames(src, outdir, fps=1, max_frames=30, pattern="f_%03d.jpg"):
    os.makedirs(outdir, exist_ok=True)
    cmd = [FFMPEG, "-y", "-i", src, "-vf", "fps=%s" % fps,
           "-frames:v", str(max_frames), os.path.join(outdir, pattern)]
    return _run(cmd)


# ---------------------------------------------------------------- 图片

def image_convert(src, dst, fmt="jpg", quality=88, max_side=None, watermark=None):
    from PIL import Image, ImageDraw
    im = Image.open(src)
    im = im.convert("RGB") if fmt in ("jpg", "bmp") else im
    if max_side:
        w, h = im.size
        m = max(w, h)
        if m > int(max_side):
            r = int(max_side) / float(m)
            im = im.resize((max(1, int(w * r)), max(1, int(h * r))), Image.LANCZOS)
    if watermark:
        try:
            d = ImageDraw.Draw(im)
            d.text((12, im.size[1] - 30), watermark, fill=(255, 255, 255))
        except Exception:
            pass
    save_kw = {}
    if fmt in ("jpg", "webp"):
        save_kw["quality"] = int(quality)
    if fmt == "jpg":
        save_kw["optimize"] = True
    im.save(dst, fmt.upper() if fmt != "jpg" else "JPEG", **save_kw)
    return True, "ok"


def images_to_pdf(paths, dst):
    from PIL import Image
    ims = []
    for p in paths:
        im = Image.open(p)
        ims.append(im.convert("RGB") if im.mode != "RGB" else im)
    if not ims:
        return False, "没有图片"
    ims[0].save(dst, "PDF", save_all=True, append_images=ims[1:])
    return True, "ok"


def pdf_to_images(src, outdir, dpi=120, max_pages=50):
    """PDF -> 图片。优先用 pypdfium2，没有就退化成 Pillow（只能读部分 PDF）。"""
    os.makedirs(outdir, exist_ok=True)
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(src)
        n = min(len(pdf), max_pages)
        out = []
        for i in range(n):
            page = pdf[i]
            img = page.render(scale=dpi / 72.0).to_pil()
            p = os.path.join(outdir, "p%03d.jpg" % (i + 1))
            img.convert("RGB").save(p, "JPEG", quality=88)
            out.append(p)
        return True, out
    except Exception as e:
        return False, "PDF 转图片需要 pypdfium2（%s）" % e


def pdf_merge(paths, dst):
    try:
        from pypdf import PdfWriter
    except Exception:
        try:
            from PyPDF2 import PdfWriter
        except Exception as e:
            return False, "PDF 合并需要 pypdf（%s）" % e
    w = PdfWriter()
    for p in paths:
        w.append(p)
    with open(dst, "wb") as f:
        w.write(f)
    return True, "ok"


def pdf_split(src, outdir, pages=None, each=True):
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        try:
            from PyPDF2 import PdfReader, PdfWriter
        except Exception as e:
            return False, "PDF 拆分需要 pypdf（%s）" % e
    os.makedirs(outdir, exist_ok=True)
    r = PdfReader(src)
    out = []
    if each:
        for i, page in enumerate(r.pages):
            w = PdfWriter()
            w.add_page(page)
            p = os.path.join(outdir, "page_%03d.pdf" % (i + 1))
            with open(p, "wb") as f:
                w.write(f)
            out.append(p)
    else:
        w = PdfWriter()
        for n in (pages or []):
            if 1 <= int(n) <= len(r.pages):
                w.add_page(r.pages[int(n) - 1])
        p = os.path.join(outdir, "extract.pdf")
        with open(p, "wb") as f:
            w.write(f)
        out.append(p)
    return True, out


# ---------------------------------------------------------------- 文档 -> PDF

# ---------------------------------------------------------------- 文档 -> PDF

# 系统里的中文字体，按优先级找
_CJK_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",     # 黑体
    r"C:\Windows\Fonts\simsun.ttc",     # 宋体
    r"C:\Windows\Fonts\Deng.ttf",       # 等线
    r"C:\Windows\Fonts\simkai.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def find_cjk_font():
    for p in _CJK_CANDIDATES:
        if os.path.isfile(p):
            return p
    # 退而求其次：Windows Fonts 目录里扫一个
    d = r"C:\Windows\Fonts"
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.lower() in ("msyh.ttc", "simhei.ttf", "simsun.ttc", "deng.ttf"):
                return os.path.join(d, f)
    return None


def _wrap_cjk(draw, text, font, max_w):
    """按像素宽度折行。中文逐字量，英文按词。"""
    if not text:
        return [""]
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur); cur = ""
            continue
        test = cur + ch
        try:
            w = draw.textlength(test, font=font)
        except Exception:
            w = len(test) * 12
        if w > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    lines.append(cur)
    return lines


def _pdf_write(path, blocks):
    """把文字块渲染成 A4 页面，直接存成 PDF。

    走的是「渲染成图再存 PDF」—— 纯 Python 里要嵌入中文字体做真正的矢量 PDF
    太复杂，而图片方式中文和表格都能正确显示。
    """
    from PIL import Image, ImageDraw, ImageFont
    import io as _io

    DPI = 150
    W, H = int(8.27 * DPI), int(11.69 * DPI)      # A4
    M = int(0.7 * DPI)                             # 页边距
    FS = 22
    LH = 34

    fp = find_cjk_font()
    try:
        font = ImageFont.truetype(fp, FS) if fp else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    pages = []
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)
    y = M

    def newpage():
        nonlocal img, dr, y
        pages.append(img)
        img = Image.new("RGB", (W, H), "white")
        dr = ImageDraw.Draw(img)
        y = M

    max_w = W - 2 * M
    for b in blocks:
        for ln in _wrap_cjk(dr, str(b), font, max_w):
            if y + LH > H - M:
                newpage()
            dr.text((M, y), ln, fill=(20, 20, 20), font=font)
            y += LH
        y += 6                                  # 块间距

    pages.append(img)
    if not pages:
        return False, "没有内容"
    pages[0].save(path, "PDF", resolution=DPI, save_all=True,
                  append_images=pages[1:])
    return True, "ok"


def doc_to_pdf(src, dst):
    """Word / Excel / PPT / txt / csv / md -> PDF。

    中文字体走系统字体渲染，表格按列展开成文本。
    云电脑上没有 LibreOffice，所以不是像素级还原原版式，
    但内容和表格都在，中文正常。
    """
    ext = os.path.splitext(src)[1].lower()
    blocks = []
    try:
        if ext == ".docx":
            import docx
            doc = docx.Document(src)
            for p in doc.paragraphs:
                if p.text.strip():
                    blocks.append(p.text)
            for t in doc.tables:
                blocks.append("")
                for row in t.rows:
                    blocks.append(" | ".join(c.text.strip() for c in row.cells))

        elif ext in (".xlsx", ".xlsm"):
            import openpyxl
            wb = openpyxl.load_workbook(src, data_only=True)
            for ws in wb.worksheets:
                blocks.append("=== %s ===" % ws.title)
                for row in ws.iter_rows(values_only=True):
                    cells = [("" if c is None else str(c)) for c in row]
                    if any(cells):
                        blocks.append(" | ".join(cells))
                blocks.append("")

        elif ext == ".pptx":
            from pptx import Presentation
            prs = Presentation(src)
            for i2, slide in enumerate(prs.slides, 1):
                blocks.append("--- 第 %d 页 ---" % i2)
                for sh in slide.shapes:
                    if sh.has_text_frame and sh.text_frame.text.strip():
                        blocks.append(sh.text_frame.text)
                blocks.append("")

        elif ext in (".txt", ".md", ".csv"):
            txt = open(src, "rb").read()
            for enc in ("utf-8", "gbk", "utf-16", "latin-1"):
                try:
                    blocks = txt.decode(enc).split("\n")
                    break
                except Exception:
                    continue
        else:
            return False, "%s 暂不支持转 PDF" % ext
    except Exception as e:
        return False, "读取失败：%s" % e

    if not blocks:
        return False, "文件里没读到内容"
    return _pdf_write(dst, blocks)




# ---------------------------------------------------------------- 新增工具

def audio_merge(paths, dst):
    """多个音频按顺序拼成一个。

    用 concat 滤镜（而不是 concat demuxer）—— demuxer 在 Windows 上对
    反斜杠路径和中文名很挑，滤镜方式直接把每段当输入，稳得多。
    """
    import tempfile
    import shutil as _sh
    tmpd = tempfile.mkdtemp()
    try:
        parts = []
        for i, p in enumerate(paths):
            w = os.path.join(tmpd, "p%03d.wav" % i)
            ok, msg = audio_convert(p, w, fmt="wav")
            if not ok:
                return False, "第 %d 个转换失败：%s" % (i + 1, msg)
            parts.append(w)
        if not parts:
            return False, "没有音频"

        cmd = [FFMPEG, "-y"]
        for p in parts:
            cmd += ["-i", p]
        if len(parts) == 1:
            # 单个就没什么好拼的，直接转一下
            cmd += ["-c:a", "libmp3lame", "-b:a", "192k", dst]
        else:
            chains = "".join("[%d:a]" % k for k in range(len(parts)))
            cmd += ["-filter_complex",
                    "%sconcat=n=%d:v=0:a=1[out]" % (chains, len(parts)),
                    "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", dst]
        return _run(cmd)
    finally:
        _sh.rmtree(tmpd, ignore_errors=True)


def change_speed(src, dst, speed=1.5, video=False):
    """变速。音频用 atempo 链（单段限制 0.5~2.0，超出就串联）。"""
    s = float(speed)
    if s <= 0.05:
        return False, "倍速太小"
    chain, rest = [], s
    while rest > 2.0:
        chain.append("atempo=2.0")
        rest /= 2.0
    while rest < 0.5:
        chain.append("atempo=0.5")
        rest /= 0.5
    chain.append("atempo=%.4f" % rest)
    af = ",".join(chain)

    if not video:
        return _run([FFMPEG, "-y", "-i", src, "-filter:a", af, dst])

    vf = "setpts=%.6f*PTS" % (1.0 / s)
    return _run([FFMPEG, "-y", "-i", src, "-filter:v", vf, "-filter:a", af,
                 "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", dst])


def snapshot(src, dst, at=1.0):
    """在指定秒数截一张图。"""
    return _run([FFMPEG, "-y", "-ss", str(at), "-i", src,
                 "-frames:v", "1", "-q:v", "2", dst])


def image_rot(src, dst, angle=90, flip=False):
    """旋转 / 翻转。angle 只接受 90 的倍数，非 90 倍数按 90 处理。"""
    from PIL import Image
    im = Image.open(src)
    a = int(angle) % 360
    if a == 90:
        im = im.rotate(-90, expand=True)
    elif a == 180:
        im = im.rotate(180, expand=True)
    elif a == 270:
        im = im.rotate(90, expand=True)
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    fmt = (os.path.splitext(dst)[1].lstrip(".") or "jpg").lower()
    im = im.convert("RGB") if fmt in ("jpg", "jpeg", "bmp") else im
    im.save(dst, "JPEG" if fmt in ("jpg", "jpeg") else fmt.upper(),
            quality=90) if fmt in ("jpg", "jpeg", "webp") else im.save(dst)
    return True, "ok"


def image_gray(src, dst):
    from PIL import Image
    im = Image.open(src).convert("L")
    im.save(dst, "PNG" if dst.lower().endswith(".png") else "JPEG", quality=92)
    return True, "ok"


def image_square(src, dst, size=1080):
    """居中裁剪成正方形，再缩放到指定边长。"""
    from PIL import Image
    im = Image.open(src)
    w, h = im.size
    m = min(w, h)
    im = im.crop(((w - m) // 2, (h - m) // 2, (w - m) // 2 + m, (h - m) // 2 + m))
    s = int(size)
    if s > 0 and im.size[0] != s:
        im = im.resize((s, s), Image.LANCZOS)
    im = im.convert("RGB") if dst.lower().endswith((".jpg", ".jpeg")) else im
    im.save(dst, quality=92) if dst.lower().endswith((".jpg", ".jpeg", ".webp")) \
        else im.save(dst)
    return True, "ok"


def image_long(srcs, dst, gap=0):
    """多张图竖着拼成一张长图，宽度按最宽的对齐。"""
    from PIL import Image
    ims = []
    for p in srcs:
        try:
            ims.append(Image.open(p).convert("RGB"))
        except Exception:
            pass
    if not ims:
        return False, "没有可用图片"
    W = max(i.size[0] for i in ims)
    g = int(gap)
    H = sum(i.size[1] for i in ims) + g * (len(ims) - 1)
    out = Image.new("RGB", (W, H), "white")
    y = 0
    for im in ims:
        if im.size[0] != W:
            r = W / float(im.size[0])
            im = im.resize((W, max(1, int(im.size[1] * r))), Image.LANCZOS)
        out.paste(im, (0, y))
        y += im.size[1] + g
    out.save(dst, "JPEG", quality=90)
    return True, "ok"


def pdf_text(src, dst):
    """PDF 提取文字到 txt。"""
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader
        except Exception as e:
            return False, "需要 pypdf（%s）" % e
    r = PdfReader(src)
    out = []
    for i, p in enumerate(r.pages, 1):
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        out.append("===== 第 %d 页 =====" % i)
        out.append(t.strip())
        out.append("")
    txt = "\n".join(out)
    if not txt.strip():
        return False, "这份 PDF 没有可提取的文字（可能是扫描件）"
    with open(dst, "w", encoding="utf-8") as f:
        f.write(txt)
    return True, "ok"


def pdf_encrypt(src, dst, pwd="1234"):
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        try:
            from PyPDF2 import PdfReader, PdfWriter
        except Exception as e:
            return False, "需要 pypdf（%s）" % e
    r = PdfReader(src)
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    try:
        w.encrypt(str(pwd))
    except Exception as e:
        return False, "加密失败：%s" % e
    with open(dst, "wb") as f:
        w.write(f)
    return True, "ok"


def pdf_decrypt(src, dst, pwd=""):
    try:
        from pypdf import PdfReader, PdfWriter
    except Exception:
        try:
            from PyPDF2 import PdfReader, PdfWriter
        except Exception as e:
            return False, "需要 pypdf（%s）" % e
    try:
        r = PdfReader(src)
        if getattr(r, "is_encrypted", False):
            ok = r.decrypt(str(pwd or ""))
            if not ok:
                return False, "密码不对"
        w = PdfWriter()
        for p in r.pages:
            w.add_page(p)
        with open(dst, "wb") as f:
            w.write(f)
        return True, "ok"
    except Exception as e:
        return False, "解密失败：%s" % e


# ---------------------------------------------------------------- 后台清理线程

class Cleaner(threading.Thread):
    def __init__(self, interval=1800):
        super().__init__(daemon=True, name="toolbox-cleaner")
        self.interval = interval
        self.running = True

    def run(self):
        while self.running:
            try:
                n = _sweep()
                if n:
                    print("[工具箱] 清理过期文件 %d 个" % n)
            except Exception:
                pass
            for _ in range(int(self.interval)):
                if not self.running:
                    return
                time.sleep(1)

    def stop(self):
        self.running = False


cleaner = Cleaner()

def capabilities():
    """这台机器上哪些工具真能用。网页据此把用不了的标出来。"""
    def has(mod):
        try:
            __import__(mod)
            return True
        except Exception:
            return False

    pil = has("PIL")
    # AES 不再依赖 pycryptodome：musicunlock 里有纯 Python 实现
    aes_c = has("Crypto.Cipher.AES")
    aes = True          # 永远可用
    try:
        aes_backend = "C 库" if aes_c else "纯 Python"
    except Exception:
        aes_backend = "纯 Python"
    pypdf = has("pypdf") or has("PyPDF2")
    pdfium = has("pypdfium2")
    docx = has("docx")
    pptx = has("pptx")
    xlsx = has("openpyxl")
    ff = ffmpeg_ready()

    return {
        "ffmpeg": ff,
        "pillow": pil,
        "aes": aes,
        "aes_backend": aes_backend,
        "pypdf": pypdf,
        "pypdfium2": pdfium,
        "docx": docx,
        "pptx": pptx,
        "openpyxl": xlsx,
        # 按功能汇总：key 是前端用的「缺什么」
        "missing": {
            "audio": [] if ff else ["ffmpeg"],
            "video": [] if ff else ["ffmpeg"],
            "image": [] if pil else ["pillow"],
            "unlock_ncm": [] if aes else ["pycryptodome"],
            "pdf": ([] if (pypdf and pil) else
                    (["pypdf"] if not pypdf else []) + (["pillow"] if not pil else [])),
            "pdf2img": [] if (pdfium and pil) else ["pypdfium2"],
            "doc": ([] if (pil and (docx or xlsx or pptx))
                    else (["pillow"] if not pil else []) +
                         ([] if (docx or xlsx or pptx) else ["python-docx/pptx/openpyxl"])),
        },
    }
