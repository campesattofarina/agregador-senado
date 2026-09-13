from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from unidecode import unidecode

RAIZ = Path(__file__).resolve().parents[1]
_ALIAS = json.loads((RAIZ / "config/institutos.json").read_text())["alias"]

MESES = {m: i + 1 for i, m in enumerate(
    ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"])}
MESES.update({m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])})
MESES["sept"] = 9

BN_KEYS = ("branco", "nulo", "nenhum", "blank", "null", "none", "outros", "other")
IND_KEYS = ("indeciso", "nao sabe", "não sabe", "ns/nr", "undecided", "don't know", "nao respond")


def chave(s: str) -> str:
    s = unidecode(str(s)).lower()
    s = re.sub(r"\[.*?\]", "", s)          # remove [1] de notas
    s = re.sub(r"\(.*?\)", "", s)          # remove (PT), (datas)
    return re.sub(r"\s+", " ", s).strip(" .-")


def instituto_canonico(bruto: str) -> str:
    k = chave(bruto)
    k = re.sub(r"\d.*$", "", k).strip(" /-")   # tira datas coladas ao nome
    if k in _ALIAS:
        return _ALIAS[k]
    for alias, nome in _ALIAS.items():
        if k.startswith(alias):
            return nome
    return bruto.strip().split("[")[0].strip() or "Desconhecido"


def parse_pct(s) -> float | None:
    if s is None:
        return None
    t = unidecode(str(s)).replace("%", "").replace(",", ".").strip()
    t = re.sub(r"\[.*?\]", "", t)
    m = re.search(r"-?\d+(\.\d+)?", t)
    return float(m.group()) if m else None


def parse_int(s) -> int | None:
    t = re.sub(r"[^\d]", "", str(s or ""))
    return int(t) if t else None


def parse_data_fim(texto: str, ano_default: int = 2026) -> date | None:
    """Extrai a data FINAL de campo de textos como
    '28–31 May 2025', '28 a 31 de maio de 2025', '31/05/2025', '1–3 de setembro', '3 set 2026'."""
    t = unidecode(str(texto)).lower()
    t = re.sub(r"\[.*?\]", "", t)
    # dd/mm/yyyy (pega a última ocorrência)
    ms = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", t)
    if ms:
        d, m, y = ms[-1]
        y = int(y) if len(y) == 4 else 2000 + int(y)
        return _safe(int(y), int(m), int(d))
    ano = re.findall(r"(20\d{2})", t)
    y = int(ano[-1]) if ano else ano_default
    # última ocorrência de "<dia> <mes>" ou "<mes> <dia>"
    dm = re.findall(r"(\d{1,2})\s*(?:de\s*)?([a-z]{3,9})", t)
    md = re.findall(r"([a-z]{3,9})\s*(\d{1,2})(?!\d)", t)
    cands = []
    for d, m in dm:
        if m[:3] in MESES or m[:4] in MESES:
            cands.append((int(d), MESES.get(m[:4], MESES.get(m[:3]))))
    for m, d in md:
        if (m[:3] in MESES or m[:4] in MESES) and int(d) <= 31:
            cands.append((int(d), MESES.get(m[:4], MESES.get(m[:3]))))
    if cands:
        d, m = cands[-1]
        return _safe(y, m, d)
    return None


def _safe(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def eh_bn(nome: str) -> bool:
    k = chave(nome)
    return any(x in k for x in BN_KEYS)


def eh_ind(nome: str) -> bool:
    k = chave(nome)
    return any(x in k for x in IND_KEYS)
