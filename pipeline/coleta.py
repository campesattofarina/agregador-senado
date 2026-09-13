"""
Varredura diária. Roda no GitHub Actions (cron) e também localmente:  python -m pipeline.coleta

1. Baixa o registro do TSE (pesquisas de Senador registradas em 2026).
2. Lê as 27 páginas estaduais na Wikipédia (pt + en) e extrai tabelas de Senado.
3. Funde com data/pesquisas.csv (append + dedupe por uf|instituto|data_fim|candidato).
   Linhas em data/correcoes.csv sobrescrevem qualquer fonte automática (correção manual vence).
4. Cruza registro TSE x pesquisas capturadas -> data/pendentes.json
   (registradas no TSE sem números capturados; publicado no site, não escondido).
5. Chama publica.py para gerar docs/data/agregado.json.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pandas as pd

from . import publica, tse_registro, wikipedia
from .util import RAIZ

log = logging.getLogger("coleta")
COLS = ["uf", "instituto", "registro_tse", "data_fim", "amostra", "tipo", "candidato", "pct", "fonte"]
CHAVE = ["uf", "instituto", "data_fim", "candidato"]


def carrega_base() -> pd.DataFrame:
    p = RAIZ / "data/pesquisas.csv"
    if p.exists():
        return pd.read_csv(p, dtype={"registro_tse": str})
    return pd.DataFrame(columns=COLS)


def funde(base: pd.DataFrame, novas: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if novas.empty:
        return base, 0
    antes = len(base.drop_duplicates(CHAVE)) if not base.empty else 0
    tudo = pd.concat([base, novas[COLS]], ignore_index=True)
    # correções manuais têm prioridade absoluta
    pc = RAIZ / "data/correcoes.csv"
    if pc.exists():
        corr = pd.read_csv(pc, dtype={"registro_tse": str})
        tudo = pd.concat([tudo, corr[COLS]], ignore_index=True)
    tudo = tudo.drop_duplicates(CHAVE, keep="last").sort_values(["uf", "data_fim", "instituto"])
    n_novas = tudo.groupby(["uf", "instituto", "data_fim"]).ngroups - (
        base.groupby(["uf", "instituto", "data_fim"]).ngroups if not base.empty else 0)
    return tudo, max(0, n_novas)


def pendencias(registro: pd.DataFrame, base: pd.DataFrame, hoje: date) -> list[dict]:
    """Registrada no TSE, campo já encerrado, e sem números na base (casando instituto+UF+data ±3d)."""
    if registro.empty:
        return []
    capt = base.drop_duplicates(["uf", "instituto", "data_fim"])[["uf", "instituto", "data_fim", "registro_tse"]].copy()
    capt["data_fim"] = pd.to_datetime(capt["data_fim"]).dt.date
    out = []
    for _, r in registro.iterrows():
        if pd.isna(r["data_fim"]) or r["data_fim"] > hoje:
            continue
        if (capt["registro_tse"] == r["registro_tse"]).any():
            continue
        m = capt[(capt["uf"] == r["uf"]) & (capt["instituto"] == r["instituto"])]
        m = m[[abs((d - r["data_fim"]).days) <= 3 for d in m["data_fim"]]]
        if m.empty:
            out.append(dict(uf=r["uf"], instituto=r["instituto"], instituto_bruto=r["instituto_bruto"],
                            registro_tse=r["registro_tse"], data_fim=r["data_fim"].isoformat(),
                            amostra=int(r["amostra"]),
                            dias=(hoje - r["data_fim"]).days))
    return sorted(out, key=lambda x: x["data_fim"], reverse=True)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    hoje = date.today()
    ufs = json.loads((RAIZ / "config/ufs.json").read_text())

    try:
        registro = tse_registro.baixa_registro(2026)
    except Exception as e:
        log.error("TSE indisponível hoje: %s", e)
        registro = pd.DataFrame()

    linhas = []
    for uf, cfg in ufs.items():
        ls = wikipedia.coleta_uf(uf, cfg)
        log.info("%s: %d linhas", uf, len(ls))
        linhas += ls
    novas = pd.DataFrame(linhas, columns=COLS)

    base = carrega_base()
    base, n_novas = funde(base, novas)
    # se o registro TSE trouxe o nº da pesquisa e a Wikipédia não, propaga por instituto+uf+data
    if not registro.empty:
        base = _propaga_registro(base, registro)
    base.to_csv(RAIZ / "data/pesquisas.csv", index=False)

    pend = pendencias(registro, base, hoje)
    (RAIZ / "data/pendentes.json").write_text(json.dumps(
        dict(atualizado=hoje.isoformat(), total=len(pend), itens=pend), ensure_ascii=False, indent=2))
    if not registro.empty:
        registro.to_csv(RAIZ / "data/registro_tse.csv", index=False)

    log.info("novas pesquisas hoje: %d | pendências TSE: %d", n_novas, len(pend))
    publica.main(n_novas_hoje=n_novas)
    return 0


def _propaga_registro(base: pd.DataFrame, registro: pd.DataFrame) -> pd.DataFrame:
    base = base.copy()
    base["registro_tse"] = base["registro_tse"].fillna("").astype(str)
    reg = registro.dropna(subset=["data_fim"])
    for i, row in base[base["registro_tse"] == ""].iterrows():
        d = pd.to_datetime(row["data_fim"]).date()
        m = reg[(reg["uf"] == row["uf"]) & (reg["instituto"] == row["instituto"])]
        m = m[[abs((x - d).days) <= 3 for x in m["data_fim"]]]
        if len(m) == 1:
            base.at[i, "registro_tse"] = m.iloc[0]["registro_tse"]
    return base


if __name__ == "__main__":
    raise SystemExit(main())
