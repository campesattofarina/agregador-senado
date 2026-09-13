"""
Baixa o CSV de pesquisas registradas no TSE (Portal de Dados Abertos) e filtra as de SENADOR.
O CSV traz o REGISTRO (instituto, UF, datas, amostra, nº TSE), não os percentuais.
Serve para: (a) saber que uma pesquisa existe antes de qualquer site publicar, (b) validar que o
que veio da Wikipédia é pesquisa registrada, (c) listar pendências (registrada, sem números).
"""
from __future__ import annotations

import io
import logging
import zipfile

import pandas as pd
import requests

from .util import instituto_canonico

log = logging.getLogger("tse")
URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral/pesquisa_eleitoral_{ano}.zip"


def _col(df: pd.DataFrame, *padroes: str) -> str | None:
    for p in padroes:
        for c in df.columns:
            if p in c.upper():
                return c
    return None


def baixa_registro(ano: int = 2026) -> pd.DataFrame:
    r = requests.get(URL.format(ano=ano), timeout=120)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nome = next(n for n in z.namelist() if n.lower().endswith(".csv") and "pesquisa_eleitoral" in n.lower())
    df = pd.read_csv(z.open(nome), sep=";", encoding="latin-1", dtype=str, low_memory=False)
    c_cargo = _col(df, "CARGO")
    c_uf = _col(df, "SG_UF", "UF")
    c_id = _col(df, "IDENTIFICACAO", "NR_PESQUISA", "PROTOCOLO")
    c_emp = _col(df, "EMPRESA", "NM_INSTITUTO")
    c_fim = _col(df, "DT_FIM", "FIM_PESQUISA", "TERMINO")
    c_ini = _col(df, "DT_INICIO", "INICIO_PESQUISA")
    c_n = _col(df, "ENTREVISTADOS", "QT_AMOSTRA")
    c_reg = _col(df, "DT_REGISTRO")
    if not all((c_cargo, c_uf, c_id, c_emp, c_fim)):
        raise RuntimeError(f"Layout inesperado do CSV do TSE: {list(df.columns)}")
    sen = df[df[c_cargo].str.upper().str.contains("SENAD", na=False)].copy()
    out = pd.DataFrame({
        "registro_tse": sen[c_id].str.strip(),
        "uf": sen[c_uf].str.strip().str.upper(),
        "instituto_bruto": sen[c_emp].str.strip(),
        "data_inicio": pd.to_datetime(sen[c_ini], dayfirst=True, errors="coerce").dt.date if c_ini else None,
        "data_fim": pd.to_datetime(sen[c_fim], dayfirst=True, errors="coerce").dt.date,
        "amostra": pd.to_numeric(sen[c_n], errors="coerce").fillna(0).astype(int) if c_n else 0,
        "data_registro": pd.to_datetime(sen[c_reg], dayfirst=True, errors="coerce").dt.date if c_reg else None,
    })
    out["instituto"] = out["instituto_bruto"].map(instituto_canonico)
    out = out[out["uf"].str.len() == 2].drop_duplicates("registro_tse")
    log.info("TSE: %d registros de pesquisa para Senador em %d", len(out), ano)
    return out.sort_values("data_fim", ascending=False)
