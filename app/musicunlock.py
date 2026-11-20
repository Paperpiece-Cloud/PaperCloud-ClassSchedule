"""音乐解锁 —— 去掉各平台下载文件的加密外壳，还原成原始音频。

原理参考 unlock-music（IXarea）的公开算法，纯 Python 实现，不联网。

支持：
    网易云      .ncm                       AES-128-ECB + RC4 keybox
    QQ音乐      .qmc0 .qmc3 .qmcflac .qmcogg   静态掩码
    QQ音乐      .qmc2 .mflac .mgg .mgg1 .mflac0  映射表（密钥藏在文件尾）
    酷狗        .kgm .kgma .kgg            头部派生密钥 + XOR
    酷我        .kwm                      头部密钥
    虾米        .xm                        静态掩码

解锁后按文件头自动判断真实格式（mp3 / flac / ogg / m4a / wav）。
"""

import os
import struct

try:
    from Crypto.Cipher import AES as _AES
except Exception:
    try:
        from Cryptodome.Cipher import AES as _AES
    except Exception:
        _AES = None


# ---------------------------------------------------------------- 纯 Python AES
# 为什么要有这个：
#   云电脑上的 Python 版本和开发机不一样，pycryptodome 的 .pyd 是编译好的，
#   版本对不上就 import 失败，用户只会看到「缺少 AES 库」。
#   NCM 只需要解 48 个字节的密钥，纯 Python 慢一点完全无所谓，
#   但能保证任何机器、任何 Python 版本都能用。

_SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16]

_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i

_RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a = (a ^ 0x11b) & 0xff
    return a


def _mul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r


def _expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        tmp = list(w[i - 1])
        if i % nk == 0:
            tmp = tmp[1:] + tmp[:1]
            tmp = [_SBOX[b] for b in tmp]
            tmp[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            tmp = [_SBOX[b] for b in tmp]
        w.append([w[i - nk][j] ^ tmp[j] for j in range(4)])
    return w, nr


def _add_round_key(s, w, rnd):
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[rnd * 4 + c][r]


def _inv_shift_rows(s):
    for r in range(1, 4):
        s[r] = s[r][-r:] + s[r][:-r]


def _inv_sub_bytes(s):
    for r in range(4):
        for c in range(4):
            s[r][c] = _INV_SBOX[s[r][c]]


def _inv_mix_columns(s):
    for c in range(4):
        a = [s[r][c] for r in range(4)]
        s[0][c] = _mul(a[0],14) ^ _mul(a[1],11) ^ _mul(a[2],13) ^ _mul(a[3],9)
        s[1][c] = _mul(a[0],9)  ^ _mul(a[1],14) ^ _mul(a[2],11) ^ _mul(a[3],13)
        s[2][c] = _mul(a[0],13) ^ _mul(a[1],9)  ^ _mul(a[2],14) ^ _mul(a[3],11)
        s[3][c] = _mul(a[0],11) ^ _mul(a[1],13) ^ _mul(a[2],9)  ^ _mul(a[3],14)


def _pure_aes128_decrypt(key, data):
    """AES-128-ECB 解密。data 长度必须是 16 的倍数。"""
    if len(key) != 16:
        raise ValueError("key 必须是 16 字节")
    if len(data) % 16:
        raise ValueError("data 长度必须是 16 的倍数")
    w, nr = _expand_key(key)
    out = bytearray()
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        s = [[blk[r + 4 * c] for c in range(4)] for r in range(4)]
        _add_round_key(s, w, nr)
        for rnd in range(nr - 1, -1, -1):
            _inv_shift_rows(s)
            _inv_sub_bytes(s)
            _add_round_key(s, w, rnd)
            if rnd != 0:
                _inv_mix_columns(s)
        for c in range(4):
            for r in range(4):
                out.append(s[r][c])
    return bytes(out)


def aes_ecb_decrypt(key, data):
    """能进口 C 库就用 C 库，否则用纯 Python。两条路结果完全一样。"""
    if _AES is not None:
        try:
            return _AES.new(key, _AES.MODE_ECB).decrypt(data)
        except Exception:
            pass
    return _pure_aes128_decrypt(key, data)



# ================================================================
#                            工具
# ================================================================

def sniff(blob):
    """按文件头判断真实格式。"""
    if not blob or len(blob) < 4:
        return None
    if blob[:3] == b"ID3" or blob[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if blob[:4] == b"fLaC":
        return "flac"
    if blob[:4] == b"OggS":
        return "ogg"
    if blob[4:8] == b"ftyp":
        return "m4a"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        return "wav"
    if blob[:4] == b"\x30\x26\xb2\x75":
        return "wma"
    return None


def _looks_plain(blob):
    """文件头已经能认出来就是没加密，直接放过。"""
    return sniff(blob[:64]) is not None


# ================================================================
#                       网易云 .ncm
# ================================================================

NCM_AES_KEY = bytes([
    0x68, 0x7A, 0x48, 0x52, 0x41, 0x6D, 0x73, 0x6F,
    0x35, 0x6B, 0x49, 0x6E, 0x62, 0x61, 0x78, 0x57])


def _ncm_keybox(key):
    """NCM 的 RC4 变种：先建 256 字节盒子，再按密钥打乱。"""
    box = list(range(256))
    j = 0
    klen = len(key)
    for i in range(256):
        j = (j + box[i] + key[i % klen]) & 0xFF
        box[i], box[j] = box[j], box[i]
    return box


def unlock_ncm(blob):
    """解 .ncm，返回 (音频字节, 提示)。"""
    if blob[:8] != b"CTENFDAM":
        return None, "不是网易云 ncm 文件"

    p = 8
    # --- 1. RC4 密钥 ---
    p += 2                                    # 跳过 2 字节
    klen = struct.unpack("<I", blob[p:p + 4])[0]
    p += 4
    keydata = bytes(b ^ 0x64 for b in blob[p:p + klen])
    p += klen
    dec = aes_ecb_decrypt(NCM_AES_KEY, keydata)[17:]        # 去掉 "neteasecloudmusic" 前缀
    rc4key = dec

    # --- 2. 元数据 ---
    mlen = struct.unpack("<I", blob[p:p + 4])[0]
    p += 4 + mlen

    # --- 3. CRC ---
    p += 5

    # --- 4. 封面 ---
    ilen = struct.unpack("<I", blob[p:p + 4])[0]
    p += 4 + ilen

    # --- 5. 音频：逐字节 XOR keybox ---
    audio = bytearray(blob[p:])
    box = _ncm_keybox(rc4key)
    for i in range(len(audio)):
        j = (i + 1) & 0xFF
        audio[i] ^= box[(box[j] + box[(box[j] + j) & 0xFF]) & 0xFF]
    return bytes(audio), "网易云 ncm"


# ================================================================
#                        QQ音乐 .qmc*
# ================================================================

_QMC_SEED = bytes([0x77, 0x48, 0x32, 0x73, 0xDE, 0xF2, 0xC0, 0xC8])


def _qmc_static_mask(off):
    if off > 0x7FFF:
        off %= 0x7FFF
    return _QMC_SEED[(off * off + 80923) % 8]


def unlock_qmc_static(blob):
    """QQ音乐的静态掩码版（qmc0/qmc3/qmcflac/qmcogg）。"""
    out = bytearray(blob)
    for i in range(len(out)):
        out[i] ^= _qmc_static_mask(i)
    return bytes(out), "QQ音乐 qmc（静态）"


class _QmcMap:
    """映射表加密：密钥藏在文件末尾，先解出来再逐字节查表。"""

    def __init__(self, key):
        idx = list(range(256))
        j = 0
        for i in range(256):
            j = (j + idx[i] + key[i % len(key)]) & 0xFF
            idx[i], idx[j] = idx[j], idx[i]
        self.idx = idx

    def mask(self, off):
        i = off & 0xFF
        return self.idx[(self.idx[i] + self.idx[(i + self.idx[i]) & 0xFF]) & 0xFF]


def _qmc_read_key(blob):
    """从文件尾读映射表密钥。返回 (密钥, 去掉尾部的数据长度)。"""
    if len(blob) < 8:
        return None, len(blob)
    # 布局：...[数据][密钥][4字节密钥长度]
    klen = struct.unpack(">I", blob[-4:])[0]
    if not (1 <= klen <= 512) or klen + 4 > len(blob):
        return None, len(blob)
    raw = blob[-4 - klen:-4]
    key = bytes(b ^ 0xFF for b in raw)
    return key, len(blob) - 4 - klen


def unlock_qmc_map(blob):
    """QQ音乐的映射表版（qmc2/mflac/mgg…）。"""
    key, real_len = _qmc_read_key(blob)
    if not key:
        return None, "读不到映射表密钥"
    data = bytearray(blob[:real_len])
    m = _QmcMap(key)
    for i in range(len(data)):
        data[i] ^= m.mask(i)
    return bytes(data), "QQ音乐 qmc（映射表）"


# ================================================================
#                          酷狗 .kgm
# ================================================================

_KGM_MASK = bytes([
    0x7C, 0xD5, 0x32, 0xEB, 0x86, 0x02, 0x7F, 0x4B,
    0xA8, 0xAF, 0xA6, 0x8E, 0x0F, 0xFF, 0x99, 0x14,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


def unlock_kgm(blob):
    """酷狗 .kgm/.kgma/.kgg。"""
    if blob[:4] not in (b"kgm ", b"kgma", b"kgg ") and blob[:16] != b"7\x00\x00\x00\x00\x00\x00\x00":
        # 酷狗的头部标识有好几种，宽松判断
        if len(blob) < 0x2C:
            return None, "文件太小"
    data = bytearray(blob)
    # 头部按固定表 XOR 解出密钥区
    for i in range(min(0x2C, len(data))):
        data[i] ^= _KGM_MASK[i % len(_KGM_MASK)]
    key = bytes(data[0x1C:0x2C])
    if not any(key):
        key = bytes(blob[0x1C:0x2C])
    # 从 0x2C 起逐字节 XOR
    body = bytearray(blob[0x2C:])
    for i in range(len(body)):
        body[i] ^= key[i % 16]
    return bytes(body), "酷狗 kgm"


# ================================================================
#                          酷我 .kwm
# ================================================================

def unlock_kwm(blob):
    """酷我 .kwm。"""
    if blob[:4] != b"yeel":
        return None, "不是酷我 kwm 文件"
    if len(blob) < 0x400:
        return None, "文件太小"
    key = bytes(blob[0x18:0x28])
    body = bytearray(blob[0x400:])
    for i in range(len(body)):
        body[i] ^= key[i % len(key)]
    return bytes(body), "酷我 kwm"


# ================================================================
#                          虾米 .xm
# ================================================================

_XM_SEED = bytes([0x5C, 0x61, 0x6E, 0x64, 0x79, 0x2C, 0x20, 0x25])


def unlock_xm(blob):
    if blob[:2] not in (b"if", b"af"):
        return None, "不是虾米 xm 文件"
    body = bytearray(blob[0x10:])
    for i in range(len(body)):
        body[i] ^= _XM_SEED[(i * i + 27) % 8]
    return bytes(body), "虾米 xm"


# ================================================================
#                          总入口
# ================================================================

LOCKED_EXT = {
    ".ncm": "网易云音乐",
    ".qmc0": "QQ音乐", ".qmc3": "QQ音乐", ".qmcflac": "QQ音乐", ".qmcogg": "QQ音乐",
    ".qmc2": "QQ音乐", ".mflac": "QQ音乐", ".mflac0": "QQ音乐",
    ".mgg": "QQ音乐", ".mgg1": "QQ音乐", ".mggl": "QQ音乐",
    ".kgm": "酷狗", ".kgma": "酷狗", ".kgg": "酷狗", ".vpr": "酷狗",
    ".kwm": "酷我",
    ".xm": "虾米",
}


def is_locked(name):
    return os.path.splitext(name or "")[1].lower() in LOCKED_EXT


def platform_of(name):
    return LOCKED_EXT.get(os.path.splitext(name or "")[1].lower(), "")


def unlock(name, blob):
    """解锁一个加密音乐文件。

    返回 (音频字节 | None, 真实扩展名 | '', 说明)。
    """
    ext = os.path.splitext(name or "")[1].lower()

    # 已经是普通音频就直接放过
    if _looks_plain(blob):
        return blob, (sniff(blob) or ""), "本来就是普通音频，没加密"

    if ext == ".ncm":
        out, msg = unlock_ncm(blob)
    elif ext in (".qmc0", ".qmc3", ".qmcflac", ".qmcogg"):
        out, msg = unlock_qmc_static(blob)
    elif ext in (".qmc2", ".mflac", ".mflac0", ".mgg", ".mgg1", ".mggl"):
        out, msg = unlock_qmc_map(blob)
    elif ext in (".kgm", ".kgma", ".kgg", ".vpr"):
        out, msg = unlock_kgm(blob)
    elif ext == ".kwm":
        out, msg = unlock_kwm(blob)
    elif ext == ".xm":
        out, msg = unlock_xm(blob)
    else:
        # 扩名不认识，但文件开头也不像普通音频 —— 挨个试
        out, msg = None, ""
        for fn, nm in ((unlock_ncm, "ncm"), (unlock_qmc_map, "qmc映射表"),
                       (unlock_qmc_static, "qmc静态"), (unlock_kgm, "kgm"),
                       (unlock_kwm, "kwm"), (unlock_xm, "xm")):
            try:
                o, m = fn(blob)
            except Exception:
                continue
            if o and sniff(o[:64]):
                return o, sniff(o[:64]), "自动识别为 " + nm
        return None, "", "认不出这个格式（只支持网易云/QQ音乐/酷狗/酷我/虾米）"

    if not out:
        return None, "", msg

    real = sniff(out[:64])
    if not real:
        return None, "", (msg or "解锁了，但解出来的不是已知音频格式")
    return out, real, msg
