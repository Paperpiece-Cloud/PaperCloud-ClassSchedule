"""AI 批改作文。

流程：
    图片 --(Windows 内置 OCR)--> 文字 --(DeepSeek API)--> 批改意见 + 评语

为什么中间要 OCR：
    DeepSeek 的 API 是纯文本的（deepseek-chat / deepseek-reasoner 都没有视觉），
    所以图片必须先在本地转成文字再发过去。
    好处是：不上传图片、不花额外的钱、隐私更稳。
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_PS1 = os.path.join(ROOT, "tools", "ocr.ps1")
PS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                  "System32", "WindowsPowerShell", "v1.0", "powershell.exe")

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

# 年级选项：小学 6 + 初中 3 + 高中 3
GRADES = [
    "小学1年级", "小学2年级", "小学3年级",
    "小学4年级", "小学5年级", "小学6年级",
    "初一", "初二", "初三",
    "高一", "高二", "高三",
]

# 各学段的批改侧重不一样
STAGE_HINT = {
    "小学": "重点看：字词是否正确、句子是否通顺、有没有把想说的说清楚。"
           "批改语气要温和鼓励，多肯定，问题用小学生能听懂的话讲。",
    "初中": "重点看：结构是否完整、中心是否明确、有没有细节描写、语言是否通顺。"
           "要指出具体问题并给修改方向。",
    "高中": "重点看：立意深度、论证逻辑、语言表达、材料的运用。"
           "要求可以严一些，指出提升空间。",
}

SYSTEM = """你是一位有二十年经验的语文老师，正在批改学生的作文。
你的批改要具体、可操作，不要说空话套话。
直接给结果，不要复述作文内容，不要加"好的""以下是"这类开场白。"""

PROMPT = """这是一篇{grade}学生的作文（图片 OCR 出来的，可能有识别错字，遇到明显是识别问题的地方请忽略，不要当成学生的错别字）。

请按下面四个部分批改，用 markdown 格式：

## 整体评价
两三句话，说清这篇作文的优点和主要问题。

## 具体问题
分条列出，每条格式：`原文片段` → 问题是什么 → 怎么改。
重点看{stage_hint}

## 修改建议
给 2–4 条这个学生下次写作能直接用上的建议。

## 简洁评语
**只写一两句**，是那种老师写在作文本最后的话。要有温度，别太生硬。

---

作文内容：
{text}
"""


# ================================================================ OCR

def _clean_ocr(text):
    """Windows OCR 会在汉字之间插空格，这里去掉。
    英文单词之间的空格保留。"""
    if not text:
        return ""
    lines = []
    for ln in text.split("\n"):
        s = ln.strip()
        if not s:
            lines.append("")
            continue
        # 只在两个 CJK 字符之间的空格才删
        s = re.sub(r"(?<=[\u4e00-\u9fa5\u3000-\u303f])\s+(?=[\u4e00-\u9fa5\u3000-\u303f])", "", s)
        s = re.sub(r"(?<=[\u4e00-\u9fa5]) (?=[，。！？；：、）】」』])", "", s)
        s = re.sub(r"(?<=[（【「『]) (?=[\u4e00-\u9fa5])", "", s)
        lines.append(s)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def ocr_image(path):
    """调 Windows 内置 OCR 把图片转文字。失败返回空串。"""
    if not os.path.isfile(OCR_PS1):
        return ""
    try:
        p = subprocess.run(
            [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", OCR_PS1, "-Path", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        txt = (p.stdout or b"").decode("utf-8", "replace")
        return _clean_ocr(txt)
    except Exception:
        return ""


# ================================================================ DeepSeek

def _api_key(cfg):
    """拿 DeepSeek Key。

    优先用内存里的 cfg；如果它是空的，就直接读一遍 config/secrets.json ——
    这样改完配置不用重启服务也能立刻生效，省得「明明填了却说没配」。
    """
    k = str((cfg or {}).get("deepseek_key") or "").strip()
    if k:
        return k
    try:
        import json as _json
        for fn in ("secrets.json", "config.json"):
            p = os.path.join(ROOT, "config", fn)
            if os.path.isfile(p):
                with open(p, encoding="utf-8-sig") as f:
                    v = str(_json.load(f).get("deepseek_key") or "").strip()
                if v:
                    return v
    except Exception:
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def grade_essay(cfg, images, grade, extra=""):
    """images: 图片路径列表。返回 (成功, 结果文本 或 错误信息, 调试信息)。"""
    key = _api_key(cfg)
    if not key:
        return False, "还没配置 DeepSeek API Key。在 config\\secrets.json 里加一行 " \
                      "\"deepseek_key\": \"sk-...\"，然后重启服务。", ""

    # 1. OCR
    texts = []
    failed = 0
    for p in images[:10]:
        t = ocr_image(p)
        if t:
            texts.append(t)
        else:
            failed += 1
    if not texts:
        return False, ("10 张图里一张也没识别出文字。"
                       "可能是照片太模糊、光线太暗，或者不是横着拍的。"), ""

    body_text = "\n\n---- 第 %d 张 ----\n\n".join([]) or ""
    parts = []
    for i, t in enumerate(texts, 1):
        parts.append("（第 %d 张）\n%s" % (i, t))
    body_text = "\n\n".join(parts)

    if len(body_text) > 12000:
        body_text = body_text[:12000] + "\n\n（后面太长省略了）"

    stage = "小学" if grade.startswith("小学") else ("初中" if grade.startswith("初") else "高中")

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT.format(
                grade=grade, stage_hint=STAGE_HINT.get(stage, ""), text=body_text)},
        ],
        "temperature": 1.0,
        "max_tokens": 2000,
        "stream": False,
    }

    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key,
                 "Accept": "application/json"},
        method="POST")

    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read().decode("utf-8"))
            m = (j.get("error") or {}).get("message") or str(j)[:200]
        except Exception:
            m = "HTTP %d" % e.code
        if e.code == 401:
            m = "API Key 不对（401）。检查一下 secrets.json 里的 deepseek_key。"
        elif e.code == 402:
            m = "账户余额不足（402），去 platform.deepseek.com 充点钱。"
        elif e.code == 429:
            m = "请求太频繁了（429），等一会儿再试。"
        return False, m, ""
    except Exception as e:
        return False, "调用失败：%s: %s" % (type(e).__name__, e), ""

    try:
        txt = d["choices"][0]["message"]["content"].strip()
    except Exception:
        return False, "返回格式看不懂：%s" % str(d)[:200], ""

    if not txt:
        return False, "模型返回了空内容，再试一次", ""

    used = d.get("usage") or {}
    info = "识别 %d 张图，共 %d 字；消耗 tokens：%s" % (
        len(texts), len(body_text), used.get("total_tokens", "?"))
    if failed:
        info += "；%d 张没识别出字" % failed
    return True, txt, info


def ocr_only(cfg, images):
    """只 OCR 不出批改，用来让用户先看看识别对不对。"""
    out = []
    for p in images[:10]:
        t = ocr_image(p)
        out.append(t)
    return out

def grade_text(cfg, text, grade):
    """已经拿到文字了，直接交给 DeepSeek 批改。"""
    key = _api_key(cfg)
    if not key:
        return False, "还没配置 DeepSeek API Key", ""
    text = (text or "").strip()
    if not text:
        return False, "没有可批改的文字", ""
    if len(text) > 12000:
        text = text[:12000] + "\n\n（后面太长省略了）"

    stage = "小学" if grade.startswith("小学") else ("初中" if grade.startswith("初") else "高中")
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": PROMPT.format(
                grade=grade, stage_hint=STAGE_HINT.get(stage, ""), text=text)},
        ],
        "temperature": 1.0,
        "max_tokens": 2000,
        "stream": False,
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key,
                 "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        try:
            j = json.loads(ex.read().decode("utf-8"))
            m = (j.get("error") or {}).get("message") or str(j)[:200]
        except Exception:
            m = "HTTP %d" % ex.code
        if ex.code == 401:
            m = "API Key 不对（401）"
        elif ex.code == 402:
            m = "账户余额不足（402）"
        elif ex.code == 429:
            m = "请求太频繁（429），等一会儿"
        return False, m, ""
    except Exception as ex:
        return False, "调用失败：%s" % ex, ""
    try:
        txt = d["choices"][0]["message"]["content"].strip()
    except Exception:
        return False, "返回格式看不懂", ""
    if not txt:
        return False, "模型返回空内容", ""
    used = d.get("usage") or {}
    return True, txt, "tokens：%s" % used.get("total_tokens", "?")
