"""Pure-python phoneme utilities: ARPAbet->IPA, normalization, alignment (no heavy deps, unit-tested)."""
from __future__ import annotations

ARPA_IPA = {
    "AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɚ",
    "EY": "eɪ", "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "ɡ", "HH": "h", "JH": "dʒ",
    "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ",
    "T": "t", "TH": "θ", "V": "v", "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ",
}


def arpa_to_ipa(token: str) -> str | None:
    base = token.rstrip("012")
    stress = token[len(base):]
    if base == "AH" and stress == "0":
        return "ə"
    if base == "ER" and stress == "0":
        return "ɚ"
    return ARPA_IPA.get(base)


# Map recognizer output variants onto the reference inventory.
_NORMALIZE = {
    "ɐ": "ʌ", "ᵻ": "ɪ", "ɜ": "ɚ", "ɝ": "ɚ", "r": "ɹ", "ɾ": "t", "g": "ɡ", "ɒ": "ɑ",
    "o": "oʊ", "e": "eɪ", "ʔ": "t", "ɫ": "l", "ɬ": "l", "i:": "i", "u:": "u",
}

# Pairs that differ only by dialect/reduction - not counted as accent errors.
_LENIENT = [{"ə", "ʌ"}, {"ɪ", "ə"}, {"ɑ", "ɔ"}, {"ɚ", "ə"}]

MULTI = ["tʃ", "dʒ", "aɪ", "aʊ", "eɪ", "oʊ", "ɔɪ", "əʊ"]


def normalize(p: str) -> str:
    p = p.replace("ː", "").replace("ˈ", "").replace("ˌ", "").strip()
    return _NORMALIZE.get(p, p)


def split_ipa(s: str) -> list[str]:
    """Split an IPA string (space separated or not) into phonemes."""
    out = []
    for chunk in s.split():
        chunk = chunk.replace("ˈ", "").replace("ˌ", "")
        i = 0
        while i < len(chunk):
            two = chunk[i:i + 2]
            if two in MULTI:
                out.append(two)
                i += 2
                continue
            ch = chunk[i]
            if ch == "ː" and out:
                i += 1
                continue
            out.append(ch)
            i += 1
    return [normalize(p) for p in out if normalize(p)]


def same(a: str, b: str) -> bool:
    a, b = normalize(a), normalize(b)
    return a == b or any(a in s and b in s for s in _LENIENT)


def align(ref: list[str], hyp: list[str]) -> list[tuple[str | None, str | None]]:
    """Levenshtein alignment. Returns pairs (ref_phone|None, hyp_phone|None)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = 0 if same(ref[i - 1], hyp[j - 1]) else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + sub)
    i, j, out = n, m, []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if same(ref[i - 1], hyp[j - 1]) else 1):
            out.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            out.append((ref[i - 1], None))
            i -= 1
        else:
            out.append((None, hyp[j - 1]))
            j -= 1
    return out[::-1]


def score_words(ref_words: list[tuple[str, list[str]]], hyp: list[str]) -> list[dict]:
    """ref_words: [(word, [ipa phonemes])]. Returns per-word results in the shared schema."""
    flat, owner = [], []
    for wi, (_, phones) in enumerate(ref_words):
        for p in phones:
            flat.append(p)
            owner.append(wi)
    words = [{"word": w, "score": 0.0, "error_type": "None", "phonemes": []} for w, _ in ref_words]
    k = 0
    for r, h in align(flat, hyp):
        if r is None:
            continue  # inserted sound: ignored for per-phoneme scoring
        w = words[owner[k]]
        if h is None:
            w["phonemes"].append({"ipa": r, "score": 0, "heard": "—"})
        elif same(r, h):
            w["phonemes"].append({"ipa": r, "score": 100, "heard": None})
        else:
            w["phonemes"].append({"ipa": r, "score": 20, "heard": normalize(h)})
        k += 1
    for w in words:
        ph = w["phonemes"]
        w["score"] = sum(p["score"] for p in ph) / len(ph) if ph else 0
        if ph and all(p["heard"] == "—" for p in ph):
            w["error_type"] = "Omission"
        elif w["score"] < 60:
            w["error_type"] = "Mispronunciation"
    return words
