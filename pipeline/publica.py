"""Gera docs/data/agregado.json a partir de data/pesquisas.csv + ratings + dobradinhas."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from model.agregador import PARAMS, Dobradinha, Pesquisa, agrega_uf
from model.ratings import peso_instituto

from .util import RAIZ


def carrega_pesquisas(ratings: dict) -> list[Pesquisa]:
    p = RAIZ / "data/pesquisas.csv"
    if not p.exists():
        return []
    df = pd.read_csv(p, dtype={"registro_tse": str}).fillna({"registro_tse": "", "fonte": ""})
    out = []
    for (uf, inst, dfim), g in df.groupby(["uf", "instituto", "data_fim"]):
        menc = {r.candidato: float(r.pct) for r in g.itertuples() if not str(r.candidato).startswith("__")}
        ind = float(g.loc[g.candidato == "__IND__", "pct"].sum())
        bn = float(g.loc[g.candidato == "__BN__", "pct"].sum())
        r0 = g.iloc[0]
        out.append(Pesquisa(uf=uf, instituto=inst, data_fim=date.fromisoformat(str(dfim)[:10]),
                            amostra=int(r0.amostra or 0), tipo=str(r0.tipo), mencoes=menc, indecisos=ind,
                            branco_nulo=bn, registro_tse=str(r0.registro_tse), fonte=str(r0.fonte),
                            peso_instituto=peso_instituto(inst, ratings, PARAMS["peso_instituto_desconhecido"])))
    return out


def carrega_dobradinhas() -> tuple[dict[str, list[Dobradinha]], float]:
    cfg = json.loads((RAIZ / "config/dobradinhas.json").read_text())
    tau_def = float(cfg.get("_default_tau", PARAMS["tau_default"]))
    por_uf: dict[str, list[Dobradinha]] = {}
    for par in cfg.get("pares", []):
        por_uf.setdefault(par["uf"], []).append(Dobradinha(par["a"], par["b"], float(par.get("tau") or 0)))
    return por_uf, tau_def


def main(n_novas_hoje: int = 0) -> None:
    hoje = date.today()
    ufs = json.loads((RAIZ / "config/ufs.json").read_text())
    ratings = json.loads((RAIZ / "data/ratings.json").read_text()) if (RAIZ / "data/ratings.json").exists() else {"institutos": {}}
    pend = json.loads((RAIZ / "data/pendentes.json").read_text()) if (RAIZ / "data/pendentes.json").exists() else {"itens": []}
    pesquisas = carrega_pesquisas(ratings)
    dob, tau_def = carrega_dobradinhas()

    estados = {}
    for uf, cfg in ufs.items():
        r = agrega_uf(uf, pesquisas, dob.get(uf, []), hoje, tau_def)
        estados[uf] = dict(
            nome=cfg["nome"], grid=cfg["grid"], n_pesquisas=r.n_pesquisas,
            ultima_pesquisa=r.ultima_pesquisa.isoformat() if r.ultima_pesquisa else None,
            dias_sem_pesquisa=r.dias_sem_pesquisa, aviso=r.aviso,
            dobradinhas=[dict(a=d.a, b=d.b, tau=d.tau or tau_def) for d in dob.get(uf, [])],
            candidatos=[dict(nome=e.candidato, media=round(e.media, 1), sigma=round(e.sigma, 1),
                             p_eleito=round(e.p_eleito, 3), p_primeiro=round(e.p_primeiro, 3),
                             n=e.n_pesquisas, parceiro=e.parceiro) for e in r.candidatos],
            pesquisas=r.pesos,
            pendentes=[p for p in pend.get("itens", []) if p["uf"] == uf],
        )

    saida = dict(
        atualizado=hoje.isoformat(), novas_hoje=n_novas_hoje,
        total_pesquisas=len(pesquisas), total_pendentes=len(pend.get("itens", [])),
        parametros={k: v for k, v in PARAMS.items() if k not in ("seed", "n_sim")},
        ratings=ratings.get("institutos", {}), mae_global=ratings.get("_global"),
        estados=estados,
    )
    (RAIZ / "docs/data/agregado.json").write_text(json.dumps(saida, ensure_ascii=False))
    print(f"publicado: {len(pesquisas)} pesquisas, {sum(1 for e in estados.values() if e['n_pesquisas'])} UFs com dado")


if __name__ == "__main__":
    main()
