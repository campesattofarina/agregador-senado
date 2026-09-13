"""
Coleta o HISTÓRICO para calcular a nota dos institutos: pesquisas finais e resultado oficial
de Senado e Governador, por UF, em 2018 e 2022 (2014 opcional), a partir das páginas
"Eleições estaduais em <UF> em <ano>" (pt) e "<ano> <State> gubernatorial election" (en).

Resultado oficial: a página traz a tabela de resultado com % de votos válidos por candidato.
Se a tabela de resultado não for encontrada, o script grava o que conseguiu e lista as UFs
faltantes; nesse caso preencher data/historico/resultados.csv à mão a partir do TSE
(dadosabertos.tse.jus.br -> resultados -> votação nominal por UF).

Uso:  python -m pipeline.historico 2022 2018
Reutiliza o parser de tabelas do módulo wikipedia (mesmo padrão de tabela).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import date

import pandas as pd
from bs4 import BeautifulSoup

from . import wikipedia as wk
from .util import RAIZ, chave, parse_pct

log = logging.getLogger("historico")
ELEICAO = {2014: date(2014, 10, 5), 2018: date(2018, 10, 7), 2022: date(2022, 10, 2)}
CARGOS = {"SENADOR": r"senad|senate", "GOVERNADOR": r"governad|gubernatorial|governor"}


def tabelas_por_cargo(html: str, padrao: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for h in soup.find_all(re.compile("^h[2-4]$")):
        if not re.search(padrao, h.get_text(" ", strip=True), re.I):
            continue
        nivel = int(h.name[1])
        for sib in h.find_all_next():
            if re.fullmatch(r"h[2-4]", sib.name or "") and int(sib.name[1]) <= nivel:
                break
            if sib.name == "table" and "wikitable" in " ".join(sib.get("class", [])):
                out.append(sib)
    return out


def resultado_da_tabela(tab) -> dict[str, float]:
    """Tabela de resultado: procura colunas 'candidato' e '%'; devolve {candidato: pct}."""
    trs = tab.find_all("tr")
    if not trs:
        return {}
    header = [chave(c.get_text(" ", strip=True)) for c in trs[0].find_all(["th", "td"])]
    i_c = next((i for i, h in enumerate(header) if "candidat" in h or "nome" in h or "name" in h), None)
    i_p = next((i for i, h in enumerate(header) if h in ("%", "% validos", "porcentagem", "percentage", "pct")
                or h.startswith("%")), None)
    if i_c is None or i_p is None:
        return {}
    res = {}
    for tr in trs[1:]:
        cel = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cel) <= max(i_c, i_p):
            continue
        v = parse_pct(cel[i_p])
        nome = re.sub(r"\[.*?\]", "", cel[i_c]).strip()
        if v is not None and nome and not re.search(r"total|valid|branco|nulo|absten", chave(nome)):
            res[nome] = v
    return res if len(res) >= 2 else {}


def coleta_ano(ano: int, ufs: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    pes, res = [], []
    for uf, cfg in ufs.items():
        titulos = {"pt": cfg["wiki_pt"].replace("2026", str(ano)), "en": cfg["wiki_en"].replace("2026", str(ano))}
        for lang, titulo in titulos.items():
            try:
                html = wk.html_da_pagina(titulo, lang)
            except Exception as e:
                log.warning("%s %s %s: %s", ano, uf, lang, e)
                continue
            if not html:
                continue
            fonte = f"{lang}:{titulo}"
            for cargo, padrao in CARGOS.items():
                for tab in tabelas_por_cargo(html, padrao):
                    r = resultado_da_tabela(tab)
                    if r:
                        for c, v in r.items():
                            res.append(dict(ano=ano, uf=uf, cargo=cargo, candidato=c, pct_validos=v, fonte=fonte))
                        continue
                    try:
                        for l in wk.linhas_da_tabela(tab, uf, fonte, ano):
                            pes.append(dict(ano=ano, uf=uf, cargo=cargo, instituto=l["instituto"],
                                            data_fim=l["data_fim"], data_eleicao=ELEICAO[ano].isoformat(),
                                            amostra=l["amostra"], candidato=l["candidato"], pct=l["pct"]))
                    except Exception as e:
                        log.warning("%s %s tabela ignorada: %s", ano, uf, e)
        log.info("%d %s: %d linhas de pesquisa, %d de resultado", ano, uf,
                 sum(1 for p in pes if p["uf"] == uf), sum(1 for r in res if r["uf"] == uf))
    return pd.DataFrame(pes), pd.DataFrame(res)


def main(anos: list[int]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    ufs = json.loads((RAIZ / "config/ufs.json").read_text())
    P, R = [], []
    for ano in anos:
        p, r = coleta_ano(ano, ufs)
        P.append(p)
        R.append(r)
    pes = pd.concat(P, ignore_index=True) if P else pd.DataFrame()
    res = pd.concat(R, ignore_index=True) if R else pd.DataFrame()
    dest = RAIZ / "data/historico"
    dest.mkdir(parents=True, exist_ok=True)
    if not pes.empty:
        pes.drop_duplicates(["ano", "uf", "cargo", "instituto", "data_fim", "candidato"]).to_csv(dest / "pesquisas_finais.csv", index=False)
    if not res.empty:
        res.drop_duplicates(["ano", "uf", "cargo", "candidato"]).to_csv(dest / "resultados.csv", index=False)
    faltam = [(a, uf, c) for a in anos for uf in ufs for c in CARGOS
              if res.empty or res[(res.ano == a) & (res.uf == uf) & (res.cargo == c)].empty]
    if faltam:
        (dest / "resultados_faltantes.txt").write_text("\n".join(f"{a} {uf} {c}" for a, uf, c in faltam))
        log.warning("%d disputas sem resultado oficial capturado -> data/historico/resultados_faltantes.txt", len(faltam))
    return 0


if __name__ == "__main__":
    raise SystemExit(main([int(a) for a in sys.argv[1:]] or [2022, 2018]))
