"""Générateur QR Code SVG local (versions 1 à 4, correction L, zéro dépendance)."""

from __future__ import annotations

from urllib.parse import urlsplit

ALLOWED_QR_HOSTS = frozenset({"ik-demos.pages.dev", "ik-demo-artisan.pages.dev"})
_SPECS = (
    (1, 21, 19, 7, ()),
    (2, 25, 34, 10, (6, 18)),
    (3, 29, 55, 15, (6, 22)),
    (4, 33, 80, 20, (6, 26)),
)


def _gf_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        root = _EXP[i]
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= coef
            nxt[j + 1] ^= _gf_mul(coef, root)
        poly = nxt
    return poly


def _rs_remainder(data: list[int], ec_len: int) -> list[int]:
    gen = _rs_generator(ec_len)
    res = list(data) + [0] * ec_len
    for i in range(len(data)):
        factor = res[i]
        if factor == 0:
            continue
        for j, g in enumerate(gen):
            res[i + j] ^= _gf_mul(factor, g)
    return res[len(data):]


def allowed_qr_url(url: str) -> str:
    """Valide une URL publique de démo I&K autorisée pour QR Code."""
    raw = (url or "").strip()
    if not raw or len(raw) > 78 or any(ord(c) < 32 or ord(c) > 126 for c in raw):
        raise ValueError("URL QR invalide")
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_QR_HOSTS
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Domaine QR non autorisé")
    return raw


def _encode_bytes(data: bytes) -> tuple[int, int, tuple[int, ...], list[int]]:
    need_bits = 4 + 8 + len(data) * 8
    chosen = None
    for ver, size, data_cw, ec_cw, align in _SPECS:
        if need_bits <= data_cw * 8:
            chosen = (ver, size, data_cw, ec_cw, align)
            break
    if chosen is None:
        raise ValueError("URL trop longue pour QR V1-V4")
    ver, size, data_cw, ec_cw, align = chosen
    bits: list[int] = []

    def push(val: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((val >> shift) & 1)

    push(0b0100, 4)
    push(len(data), 8)
    for b in data:
        push(b, 8)
    term = min(4, data_cw * 8 - len(bits))
    push(0, term)
    while len(bits) % 8 != 0:
        bits.append(0)
    pad_bytes = (0xEC, 0x11)
    idx = 0
    while len(bits) < data_cw * 8:
        push(pad_bytes[idx & 1], 8)
        idx += 1
    codewords = [
        int("".join(str(b) for b in bits[i : i + 8]), 2)
        for i in range(0, len(bits), 8)
    ]
    ec = _rs_remainder(codewords, ec_cw)
    return ver, size, align, codewords + ec


def _finder_and_setup(size: int, ver: int, align: tuple[int, ...]) -> tuple[list[list[int]], list[list[bool]]]:
    grid = [[0] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def set_mod(r: int, c: int, val: int) -> None:
        if 0 <= r < size and 0 <= c < size:
            grid[r][c] = val
            fixed[r][c] = True

    def draw_finder(tr: int, tc: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = tr + dr, tc + dc
                if not (0 <= r < size and 0 <= c < size):
                    continue
                if dr in (-1, 7) or dc in (-1, 7):
                    set_mod(r, c, 0)
                elif dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4):
                    set_mod(r, c, 1)
                else:
                    set_mod(r, c, 0)

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    for r in align:
        for c in align:
            if (r <= 8 and c <= 8) or (r <= 8 and c >= size - 8) or (r >= size - 8 and c <= 8):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                    set_mod(r + dr, c + dc, val)

    for i in range(8, size - 8):
        val = 1 if i % 2 == 0 else 0
        if not fixed[6][i]:
            set_mod(6, i, val)
        if not fixed[i][6]:
            set_mod(i, 6, val)

    set_mod(4 * ver + 9, 8, 1)

    for i in range(9):
        if i != 6:
            fixed[8][i] = True
            fixed[i][8] = True
    for i in range(size - 8, size):
        fixed[8][i] = True
    for i in range(size - 7, size):
        fixed[i][8] = True

    return grid, fixed


def _format_bits(mask: int) -> int:
    data = (0b01 << 3) | mask  # ECC L = 01
    rem = data << 10
    for shift in range(4, -1, -1):
        if rem & (1 << (shift + 10)):
            rem ^= 0x537 << shift
    return ((data << 10) | rem) ^ 0x5412


def _apply_format(grid: list[list[int]], mask: int) -> None:
    size = len(grid)
    fmt = _format_bits(mask)
    tl_positions = (
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    )
    mirror_positions = (
        (size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8),
        (size - 5, 8), (size - 6, 8), (size - 7, 8), (8, size - 8),
        (8, size - 7), (8, size - 6), (8, size - 5), (8, size - 4),
        (8, size - 3), (8, size - 2), (8, size - 1),
    )
    for idx in range(15):
        bit = (fmt >> (14 - idx)) & 1
        r1, c1 = tl_positions[idx]
        r2, c2 = mirror_positions[idx]
        grid[r1][c1] = bit
        grid[r2][c2] = bit


def _place_codewords(grid: list[list[int]], fixed: list[list[bool]], codewords: list[int]) -> None:
    size = len(grid)
    bits = [(cw >> s) & 1 for cw in codewords for s in range(7, -1, -1)]
    bi = 0
    up = True
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if up else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if not fixed[r][c]:
                    grid[r][c] = bits[bi] if bi < len(bits) else 0
                    bi += 1
        up = not up
        col -= 2


def _mask_cond(mask: int, r: int, c: int) -> bool:
    if mask == 0:
        return (r + c) % 2 == 0
    if mask == 1:
        return r % 2 == 0
    if mask == 2:
        return c % 3 == 0
    if mask == 3:
        return (r + c) % 3 == 0
    if mask == 4:
        return (r // 2 + c // 3) % 2 == 0
    if mask == 5:
        return ((r * c) % 2 + (r * c) % 3) == 0
    if mask == 6:
        return (((r * c) % 2 + (r * c) % 3) % 2) == 0
    return (((r + c) % 2 + (r * c) % 3) % 2) == 0


def _penalty(grid: list[list[int]]) -> int:
    size = len(grid)
    score = 0
    for r in range(size):
        run_r, run_c = 1, 1
        for i in range(1, size):
            run_r = run_r + 1 if grid[r][i] == grid[r][i - 1] else 1
            if run_r == 5:
                score += 3
            elif run_r > 5:
                score += 1
            run_c = run_c + 1 if grid[i][r] == grid[i - 1][r] else 1
            if run_c == 5:
                score += 3
            elif run_c > 5:
                score += 1
    for r in range(size - 1):
        for c in range(size - 1):
            v = grid[r][c]
            if v == grid[r][c + 1] == grid[r + 1][c] == grid[r + 1][c + 1]:
                score += 3
    pat1 = (1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0)
    pat2 = (0, 0, 0, 0, 1, 0, 1, 1, 1, 0, 1)
    for r in range(size):
        row = tuple(grid[r])
        col_vals = tuple(grid[i][r] for i in range(size))
        for i in range(size - 10):
            if row[i : i + 11] in (pat1, pat2):
                score += 40
            if col_vals[i : i + 11] in (pat1, pat2):
                score += 40
    total_dark = sum(sum(row) for row in grid)
    pct = (total_dark * 100) / (size * size)
    score += int(abs(pct - 50) // 5) * 10
    return score


def encode_qr_matrix(url: str) -> list[list[int]]:
    """Construit la matrice QR binaire (0/1) pour une URL autorisée."""
    clean_url = allowed_qr_url(url)
    ver, size, align, codewords = _encode_bytes(clean_url.encode("ascii"))
    base_grid, fixed = _finder_and_setup(size, ver, align)
    _place_codewords(base_grid, fixed, codewords)

    best_grid: list[list[int]] | None = None
    best_score = 10**9
    for mask in range(8):
        cand = [
            [
                (base_grid[r][c] ^ (1 if not fixed[r][c] and _mask_cond(mask, r, c) else 0))
                for c in range(size)
            ]
            for r in range(size)
        ]
        _apply_format(cand, mask)
        sc = _penalty(cand)
        if sc < best_score:
            best_score = sc
            best_grid = cand
    assert best_grid is not None
    return best_grid


def render_qr_svg(url: str, *, module_px: int = 6, quiet: int = 4) -> str:
    """Retourne un SVG local compact représentant le QR Code de l'URL."""
    grid = encode_qr_matrix(url)
    size = len(grid)
    total = (size + 2 * quiet) * module_px
    paths: list[str] = []
    for r, row in enumerate(grid):
        y = (r + quiet) * module_px
        for c, bit in enumerate(row):
            if bit:
                x = (c + quiet) * module_px
                paths.append(f"M{x} {y}h{module_px}v{module_px}h-{module_px}z")
    d = "".join(paths)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="180" height="180" role="img" aria-label="QR Code démo">'
        f'<rect width="{total}" height="{total}" fill="#ffffff"/>'
        f'<path d="{d}" fill="#111111"/></svg>'
    )
