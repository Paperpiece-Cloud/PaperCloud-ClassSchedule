"""
CAS 登录加密算法 —— des.js 的忠实 Python 移植（纯标准库，零依赖）。

原实现来自 /sso/comm/js/des.js (Guapo, 2006)，是标准 DES，
但密钥/数据都是按 UTF-16 码元切成 4 字符 = 64bit 块处理。

登录页实际调用:
    rsa = strEnc(username + password + lt, '1', '2', '3')
"""

# ---------------------------------------------------------------- 表

_S1 = [[14,4,13,1,2,15,11,8,3,10,6,12,5,9,0,7],
       [0,15,7,4,14,2,13,1,10,6,12,11,9,5,3,8],
       [4,1,14,8,13,6,2,11,15,12,9,7,3,10,5,0],
       [15,12,8,2,4,9,1,7,5,11,3,14,10,0,6,13]]
_S2 = [[15,1,8,14,6,11,3,4,9,7,2,13,12,0,5,10],
       [3,13,4,7,15,2,8,14,12,0,1,10,6,9,11,5],
       [0,14,7,11,10,4,13,1,5,8,12,6,9,3,2,15],
       [13,8,10,1,3,15,4,2,11,6,7,12,0,5,14,9]]
_S3 = [[10,0,9,14,6,3,15,5,1,13,12,7,11,4,2,8],
       [13,7,0,9,3,4,6,10,2,8,5,14,12,11,15,1],
       [13,6,4,9,8,15,3,0,11,1,2,12,5,10,14,7],
       [1,10,13,0,6,9,8,7,4,15,14,3,11,5,2,12]]
_S4 = [[7,13,14,3,0,6,9,10,1,2,8,5,11,12,4,15],
       [13,8,11,5,6,15,0,3,4,7,2,12,1,10,14,9],
       [10,6,9,0,12,11,7,13,15,1,3,14,5,2,8,4],
       [3,15,0,6,10,1,13,8,9,4,5,11,12,7,2,14]]
_S5 = [[2,12,4,1,7,10,11,6,8,5,3,15,13,0,14,9],
       [14,11,2,12,4,7,13,1,5,0,15,10,3,9,8,6],
       [4,2,1,11,10,13,7,8,15,9,12,5,6,3,0,14],
       [11,8,12,7,1,14,2,13,6,15,0,9,10,4,5,3]]
_S6 = [[12,1,10,15,9,2,6,8,0,13,3,4,14,7,5,11],
       [10,15,4,2,7,12,9,5,6,1,13,14,0,11,3,8],
       [9,14,15,5,2,8,12,3,7,0,4,10,1,13,11,6],
       [4,3,2,12,9,5,15,10,11,14,1,7,6,0,8,13]]
_S7 = [[4,11,2,14,15,0,8,13,3,12,9,7,5,10,6,1],
       [13,0,11,7,4,9,1,10,14,3,5,12,2,15,8,6],
       [1,4,11,13,12,3,7,14,10,15,6,8,0,5,9,2],
       [6,11,13,8,1,4,10,7,9,5,0,15,14,2,3,12]]
_S8 = [[13,2,8,4,6,15,11,1,10,9,3,14,5,0,12,7],
       [1,15,13,8,10,3,7,4,12,5,6,11,0,14,9,2],
       [7,11,4,1,9,12,14,2,0,6,10,13,15,3,5,8],
       [2,1,14,7,4,10,8,13,15,12,9,0,3,5,6,11]]
_SBOXES = [_S1, _S2, _S3, _S4, _S5, _S6, _S7, _S8]

_P_BOX = [15, 6, 19, 20, 28, 11, 27, 16, 0, 14, 22, 25, 4, 17, 30, 9,
          1, 7, 23, 13, 31, 26, 2, 8, 18, 12, 29, 5, 21, 10, 3, 24]

_FP = [39, 7, 47, 15, 55, 23, 63, 31, 38, 6, 46, 14, 54, 22, 62, 30,
       37, 5, 45, 13, 53, 21, 61, 29, 36, 4, 44, 12, 52, 20, 60, 28,
       35, 3, 43, 11, 51, 19, 59, 27, 34, 2, 42, 10, 50, 18, 58, 26,
       33, 1, 41, 9, 49, 17, 57, 25, 32, 0, 40, 8, 48, 16, 56, 24]

_PC2 = [13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9, 22, 18, 11, 3,
        25, 7, 15, 6, 26, 19, 12, 1, 40, 51, 30, 36, 46, 54, 29, 39,
        50, 44, 32, 47, 43, 48, 38, 55, 33, 52, 45, 41, 49, 35, 28, 31]

_LOOP = [1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1]


# ---------------------------------------------------------------- 位转换

def _str_to_bt(s):
    """字符串 -> 64 位列表（超过 4 字符只取前 4 个，与原 JS 一致）。"""
    leng = len(s)
    bt = [0] * 64
    n = min(leng, 4)
    for i in range(n):
        k = ord(s[i])
        for j in range(16):
            bt[16 * i + j] = (k // (2 ** (15 - j))) % 2
    # 不足 4 字符补 0
    for p in range(leng, 4):
        for q in range(16):
            bt[16 * p + q] = 0
    return bt


def _bt64_to_hex(bits):
    hexstr = []
    for i in range(16):
        v = 0
        for j in range(4):
            v = v * 2 + bits[i * 4 + j]
        hexstr.append("0123456789ABCDEF"[v])
    return "".join(hexstr)


def _hex_to_bt64(h):
    bits = []
    for ch in h[:16]:
        v = int(ch, 16)
        bits.extend([(v >> 3) & 1, (v >> 2) & 1, (v >> 1) & 1, v & 1])
    return bits


def _bits_to_str(bits):
    out = []
    for i in range(4):
        count = 0
        for j in range(16):
            count += bits[16 * i + j] * (2 ** (15 - j))
        if count != 0:
            out.append(chr(count))
    return "".join(out)


def _get_key_bytes(key):
    out = []
    leng = len(key)
    iterator = leng // 4
    for i in range(iterator):
        out.append(_str_to_bt(key[i * 4:i * 4 + 4]))
    remainder = leng % 4
    if remainder > 0:
        out.append(_str_to_bt(key[iterator * 4:iterator * 4 + remainder]))
    return out


# ---------------------------------------------------------------- 置换

def _init_permute(d):
    out = [0] * 64
    m, n = 1, 0
    for i in range(4):
        k = 0
        for j in range(7, -1, -1):
            out[i * 8 + k] = d[j * 8 + m]
            out[i * 8 + k + 32] = d[j * 8 + n]
            k += 1
        m += 2
        n += 2
    return out


def _expand_permute(r):
    e = [0] * 48
    for i in range(8):
        e[i * 6 + 0] = r[31] if i == 0 else r[i * 4 - 1]
        e[i * 6 + 1] = r[i * 4 + 0]
        e[i * 6 + 2] = r[i * 4 + 1]
        e[i * 6 + 3] = r[i * 4 + 2]
        e[i * 6 + 4] = r[i * 4 + 3]
        e[i * 6 + 5] = r[0] if i == 7 else r[i * 4 + 4]
    return e


def _s_box_permute(e):
    out = [0] * 32
    for m in range(8):
        row = e[m * 6 + 0] * 2 + e[m * 6 + 5]
        col = (e[m * 6 + 1] * 8 + e[m * 6 + 2] * 4
               + e[m * 6 + 3] * 2 + e[m * 6 + 4])
        v = _SBOXES[m][row][col]
        for b in range(4):
            out[m * 4 + b] = (v >> (3 - b)) & 1
    return out


def _p_permute(sb):
    return [sb[_P_BOX[i]] for i in range(32)]


def _finally_permute(d):
    return [d[_FP[i]] for i in range(64)]


def _generate_keys(key_byte):
    key = [0] * 56
    for i in range(7):
        for j in range(8):
            k = 7 - j
            key[i * 8 + j] = key_byte[8 * k + i]

    keys = []
    for i in range(16):
        for _ in range(_LOOP[i]):
            temp_left = key[0]
            temp_right = key[28]
            for k in range(27):
                key[k] = key[k + 1]
                key[28 + k] = key[29 + k]
            key[27] = temp_left
            key[55] = temp_right
        keys.append([key[p] for p in _PC2])
    return keys


# ---------------------------------------------------------------- 核心

def _crypt(data_byte, key_byte, decrypt=False):
    keys = _generate_keys(key_byte)
    ip = _init_permute(data_byte)
    left = ip[:32]
    right = ip[32:64]

    rng = range(15, -1, -1) if decrypt else range(16)
    for i in rng:
        temp_left = left
        left = right
        x = [a ^ b for a, b in zip(_expand_permute(right), keys[i])]
        f = _p_permute(_s_box_permute(x))
        right = [a ^ b for a, b in zip(f, temp_left)]

    return _finally_permute(right + left)


# ---------------------------------------------------------------- 对外 API

def str_enc(data, first_key, second_key, third_key):
    """等价于 des.js 的 strEnc(data, firstKey, secondKey, thirdKey)。"""
    leng = len(data)
    key_chain = []
    if first_key:
        key_chain += _get_key_bytes(first_key)
    if second_key:
        key_chain += _get_key_bytes(second_key)
    if third_key:
        key_chain += _get_key_bytes(third_key)

    out = []
    # 每 4 个字符一组
    iterator = leng // 4
    remainder = leng % 4
    for i in range(iterator):
        bt = _str_to_bt(data[i * 4:i * 4 + 4])
        for k in key_chain:
            bt = _crypt(bt, k, decrypt=False)
        out.append(_bt64_to_hex(bt))
    if remainder > 0:
        bt = _str_to_bt(data[iterator * 4:leng])
        for k in key_chain:
            bt = _crypt(bt, k, decrypt=False)
        out.append(_bt64_to_hex(bt))
    return "".join(out)


def str_dec(data, first_key, second_key, third_key):
    """等价于 des.js 的 strDec。"""
    key_chain = []
    if first_key:
        key_chain += _get_key_bytes(first_key)
    if second_key:
        key_chain += _get_key_bytes(second_key)
    if third_key:
        key_chain += _get_key_bytes(third_key)

    out = []
    iterator = len(data) // 16
    for i in range(iterator):
        chunk = data[i * 16:i * 16 + 16]
        bits = _hex_to_bt64(chunk)
        for k in reversed(key_chain):
            bits = _crypt(bits, k, decrypt=True)
        out.append(_bits_to_str(bits))
    return "".join(out)


def login_rsa_token(username, password, lt):
    """登录表单里 rsa 字段的值。"""
    return str_enc(username + password + lt, "1", "2", "3")
