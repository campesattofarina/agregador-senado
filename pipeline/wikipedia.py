"""
Lê as páginas de eleição estadual na Wikipédia (pt e en) e extrai as tabelas de pesquisas
para o SENADO. Cada linha vira um dicionário compatível com data/pesquisas.csv.

Heurística: procura títulos (h2/h3/h4) contendo "senad"/"senate"; pega as tabelas até o
próximo título de mesmo nível; 1ª coluna = instituto (+ datas), colunas com "amostra/sample"
= amostra, colunas branco/nulo/indeciso = BN/IND, o resto = candidatos.
"""
from __future__ import annotations

import logging
import re
import sys
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .util import (chave, eh_bn, eh_ind, instituto_canonico, parse_data_fim, parse_int, parse_pct)

log = logging.getLogger("wikipedia")
UA = {"User-Agent": "agregador-senado/1.0 (projeto aberto; github pages)"}


def html_da_pagina(titulo: str, lang: str) -> str | None:
    url = f"https://{lang}.wikipedia.org/w/index.php?title={quote(titulo.replace(' ', '_'))}&action=render"
    r = requests.get(url, headers=UA, timeout=40)
    if r.status_code != 200:
        log.info("%s: %s -> %s", lang, titulo, r.status_code)
        return None
    return r.text


def tabelas_de_senado(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for h in soup.find_all(re.compile("^h[2-4]$")):
        if not re.search(r"senad|senate", h.get_text(" ", strip=True), re.I):
            continue
        nivel = int(h.name[1])
        for sib in h.find_all_next():
            if re.fullmatch(r"h[2-4]", sib.name or "") and int(sib.name[1]) <= nivel:
                break
            if sib.name == "table" and "wikitable" in " ".join(sib.get("class", [])):
                out.append(sib)
    return out


def linhas_da_tabela(tab, uf: str, fonte: str, ano: int = 2026) -> list[dict]:
    trs = tab.find_all("tr")
    if len(trs) < 2:
        return []
    # cabeçalho: pode ter 2 linhas (nome / partido). Usa a 1ª linha com >= 3 th.
    header = None
    for tr in trs[:3]:
        ths = tr.find_all(["th", "td"])
        if len(ths) >= 3:
            header = [chave(th.get_text(" ", strip=True)) for th in ths]
            break
    if not header:
        return []
    # espelha rowspan simples: se 2ª linha do cabeçalho tem menos células, ignora
    idx_amostra = next((i for i, h in enumerate(header) if "amostra" in h or "sample" in h), None)
    idx_margem = next((i for i, h in enumerate(header) if "margem" in h or "margin" in h), None)
    idx_data = next((i for i, h in enumerate(header) if h in ("data", "date", "datas", "periodo", "fieldwork")), None)
    nomes_raw = [th.get_text(" ", strip=True) for th in trs[0].find_all(["th", "td"])]

    out = []
    for tr in trs[1:]:
        tds = tr.find_all(["td", "th"])
        if len(tds) < 3:
            continue
        cel = [td.get_text(" ", strip=True) for td in tds]
        if len(cel) != len(header):
            continue  # linhas com colspan (eventos, notas) são puladas
        inst_txt = cel[0]
        if not inst_txt or parse_pct(inst_txt) is not None and idx_data is None:
            continue
        data_txt = cel[idx_data] if idx_data is not None else inst_txt
        data_fim = parse_data_fim(data_txt, ano)
        if not data_fim:
            continue
        amostra = parse_int(cel[idx_amostra]) if idx_amostra is not None else None
        inst = instituto_canonico(inst_txt)
        registro = ""
        m = re.search(r"([A-Z]{2}-\d{5}/\d{4})", tr.get_text(" "))
        if m:
            registro = m.group(1)
        ind = bn = 0.0
        mencoes = {}
        for i, (h, nome) in enumerate(zip(header, nomes_raw)):
            if i in (0, idx_amostra, idx_margem, idx_data):
                continue
            v = parse_pct(cel[i])
            if v is None:
                continue
            if eh_ind(h):
                ind += v
            elif eh_bn(h):
                bn += v
            else:
                mencoes[re.sub(r"\[.*?\]", "", nome).strip()] = v
        if len(mencoes) < 2:
            continue
        soma = sum(mencoes.values())
        tipo = "2votos" if soma + bn + ind > 115 else "1voto"
        for cand, v in mencoes.items():
            out.append(dict(uf=uf, instituto=inst, registro_tse=registro, data_fim=data_fim.isoformat(),
                            amostra=amostra or 0, tipo=tipo, candidato=cand, pct=v, fonte=fonte))
        out.append(dict(uf=uf, instituto=inst, registro_tse=registro, data_fim=data_fim.isoformat(),
                        amostra=amostra or 0, tipo=tipo, candidato="__IND__", pct=ind, fonte=fonte))
        out.append(dict(uf=uf, instituto=inst, registro_tse=registro, data_fim=data_fim.isoformat(),
                        amostra=amostra or 0, tipo=tipo, candidato="__BN__", pct=bn, fonte=fonte))
    return out


def coleta_uf(uf: str, cfg: dict, ano: int = 2026) -> list[dict]:
    linhas = []
    for lang, key in (("pt", "wiki_pt"), ("en", "wiki_en")):
        titulo = cfg.get(key)
        if not titulo:
            continue
        try:
            html = html_da_pagina(titulo, lang)
        except requests.RequestException as e:
            log.warning("%s %s: %s", uf, lang, e)
            continue
        if not html:
            continue
        fonte = f"https://{lang}.wikipedia.org/wiki/{quote(titulo.replace(' ', '_'))}"
        for tab in tabelas_de_senado(html):
            try:
                linhas += linhas_da_tabela(tab, uf, fonte, ano)
            except Exception as e:  # tabela fora do padrão não derruba a coleta
                log.warning("%s tabela ignorada: %s", uf, e)
    return linhas


if __name__ == "__main__":
    import json
    from .util import RAIZ
    logging.basicConfig(level=logging.INFO)
    ufs = json.loads((RAIZ / "config/ufs.json").read_text())
    alvo = sys.argv[1:] or list(ufs)
    for uf in alvo:
        ls = coleta_uf(uf, ufs[uf])
        print(uf, len(ls), "linhas")
