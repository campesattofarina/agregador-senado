"""
Nota dos institutos = erro médio absoluto (em pontos percentuais dos votos válidos) das
pesquisas finais (últimos N dias antes do 1º turno) contra o resultado oficial do TSE,
nas eleições de 2018 e 2022 (e 2014 se houver dado), para Senado e Governador por UF.

Por que Governador também: em muitos estados um instituto fez 1 pesquisa de Senado e 3 de
Governador. Senado pesa mais (peso 1.0), Governador entra como evidência complementar (0.7).

Encolhimento bayesiano: instituto com poucas disputas é puxado para a média geral
(k = 4 disputas equivalentes). Instituto que só apareceu em 2026 recebe a nota "sem histórico"
e peso 0.6 no agregador — quem nunca foi testado não ganha o benefício da dúvida.

Entrada:
  data/historico/pesquisas_finais.csv  ano,uf,cargo,instituto,data_fim,data_eleicao,amostra,candidato,pct
      (linhas especiais: candidato = __BN__ ou __IND__ para branco/nulo e indecisos)
  data/historico/resultados.csv        ano,uf,cargo,candidato,pct_validos
Saída:
  data/ratings.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from unidecode import unidecode

RAIZ = Path(__file__).resolve().parents[1]
JANELA_DIAS = 12          # pesquisa "final" = campo encerrado até 12 dias antes da eleição
CORTE_CANDIDATO = 5.0     # só avalia candidatos com >= 5% dos válidos
K_ENCOLHIMENTO = 4.0
PESO_CARGO = {"SENADOR": 1.0, "GOVERNADOR": 0.7}


def chave(s: str) -> str:
    return unidecode(str(s)).lower().strip()


def notas_de_erro(pf: pd.DataFrame, res: pd.DataFrame) -> pd.DataFrame:
    pf = pf.copy()
    pf["data_fim"] = pd.to_datetime(pf["data_fim"])
    pf["data_eleicao"] = pd.to_datetime(pf["data_eleicao"])
    pf = pf[(pf["data_eleicao"] - pf["data_fim"]).dt.days.between(0, JANELA_DIAS)]
    pf["k"] = pf["candidato"].map(chave)
    res = res.copy()
    res["k"] = res["candidato"].map(chave)

    linhas = []
    grupos = pf.groupby(["ano", "uf", "cargo", "instituto", "data_fim"])
    for (ano, uf, cargo, inst, dfim), g in grupos:
        cand = g[~g["k"].isin(["__bn__", "__ind__"])]
        total = cand["pct"].sum()
        if total <= 0:
            continue
        r = res[(res["ano"] == ano) & (res["uf"] == uf) & (res["cargo"] == cargo)]
        if r.empty:
            continue
        r = r.set_index("k")["pct_validos"]
        erros = []
        for _, row in cand.iterrows():
            if row["k"] not in r.index or r[row["k"]] < CORTE_CANDIDATO:
                continue
            proj = row["pct"] / total * r.sum()   # normaliza para a mesma base dos válidos
            erros.append(abs(proj - r[row["k"]]))
        if len(erros) >= 2:
            linhas.append(dict(ano=ano, uf=uf, cargo=cargo, instituto=inst, data_fim=dfim,
                               mae=float(np.mean(erros)), n_cand=len(erros)))
    return pd.DataFrame(linhas)


def consolida(erros: pd.DataFrame) -> dict:
    if erros.empty:
        return {"_global": None, "institutos": {}}
    erros["w"] = erros["cargo"].map(PESO_CARGO).fillna(0.5)
    # uma nota por disputa (instituto x ano x uf x cargo): média das pesquisas finais daquela disputa
    disp = erros.groupby(["instituto", "ano", "uf", "cargo"]).agg(mae=("mae", "mean"), w=("w", "first")).reset_index()
    global_mae = float(np.average(disp["mae"], weights=disp["w"]))
    out = {}
    for inst, g in disp.groupby("instituto"):
        n_eq = float(g["w"].sum())
        mae_bruto = float(np.average(g["mae"], weights=g["w"]))
        mae = (n_eq * mae_bruto + K_ENCOLHIMENTO * global_mae) / (n_eq + K_ENCOLHIMENTO)
        peso = float(np.clip((global_mae / mae) ** 1.5, 0.3, 1.6))
        out[inst] = dict(
            mae=round(mae, 2), mae_bruto=round(mae_bruto, 2), disputas=int(len(g)),
            disputas_senado=int((g["cargo"] == "SENADOR").sum()),
            anos=sorted(int(a) for a in g["ano"].unique()),
            nota=_letra(mae), peso=round(peso, 3),
        )
    return {"_global": round(global_mae, 2), "_metodo": __doc__.strip().split("\n")[0], "institutos": out}


def _letra(mae: float) -> str:
    for lim, letra in ((3.0, "A"), (4.5, "B"), (6.0, "C"), (8.0, "D")):
        if mae <= lim:
            return letra
    return "E"


def peso_instituto(nome: str, ratings: dict, default: float = 0.6) -> float:
    r = ratings.get("institutos", {}).get(nome)
    return r["peso"] if r else default


def main() -> int:
    pfp = RAIZ / "data/historico/pesquisas_finais.csv"
    rsp = RAIZ / "data/historico/resultados.csv"
    if not pfp.exists() or not rsp.exists():
        print("Sem histórico ainda; gravando ratings vazio.", file=sys.stderr)
        (RAIZ / "data/ratings.json").write_text(json.dumps({"_global": None, "institutos": {}}, ensure_ascii=False, indent=2))
        return 0
    erros = notas_de_erro(pd.read_csv(pfp), pd.read_csv(rsp))
    ratings = consolida(erros)
    (RAIZ / "data/ratings.json").write_text(json.dumps(ratings, ensure_ascii=False, indent=2))
    print(f"{len(ratings['institutos'])} institutos avaliados; MAE global {ratings['_global']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
