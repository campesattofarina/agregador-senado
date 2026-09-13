"""
Modelo de agregação de pesquisas para o Senado (2 vagas por UF, 2 votos por eleitor).

Lógica, em ordem:
1. Cada pesquisa vira um vetor de "menções" m_i (% dos entrevistados que citam o candidato i).
   Numa pesquisa de 2 votos, soma(m) <= 200. Numa de 1 voto, soma(m) <= 100 e o vetor é
   convertido para 2 votos via kernel de dobradinha (ver `kernel_segundo_voto`).
2. Indecisos são redistribuídos com o mesmo kernel: quem "iria de A" no 1º voto dá o 2º voto
   ao parceiro de A com probabilidade tau (dobradinha), senão proporcional aos demais.
3. Peso da pesquisa = recência × amostra × nota do instituto, com penalidade para o mesmo
   instituto repetido (uma casa não domina o estado).
4. Estimativa por candidato = média ponderada; incerteza = amostral + dispersão entre casas +
   envelhecimento (sem pesquisa nova, o intervalo abre).
5. Monte Carlo: sorteia cenários com choque comum de estado e correlação intra-dobradinha;
   os 2 primeiros de cada cenário levam as vagas -> P(eleito) por candidato.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

import numpy as np

# ---------- parâmetros do modelo (todos aqui, nada espalhado) ----------
PARAMS = dict(
    tau_default=0.65,          # transferência de 2º voto dentro da dobradinha
    meia_vida_dias=15.0,       # peso da pesquisa cai pela metade a cada 15 dias
    peso_1voto=0.6,            # pesquisa de 1 voto vale menos que a de 2 votos
    peso_instituto_desconhecido=0.6,
    peso_repeticao=0.5,        # 2ª pesquisa mais antiga da mesma casa vale 50%, a 3ª 25%...
    sigma_casa=3.0,            # dispersão mínima entre institutos (pp), mesmo com 1 pesquisa
    sigma_envelhecimento_dia=0.12,  # pp de incerteza extra por dia sem pesquisa
    sigma_comum=2.0,           # choque de estado comum a todos (erro sistemático)
    rho_dobradinha=0.5,        # correlação dos erros dentro do par
    n_sim=20000,
    seed=2026,
    # freio prático: com poucas pesquisas ou pesquisa velha, a probabilidade é puxada
    # para o "não sei" (2/k). lambda = min(1, (n+1)/4) * max(0.5, 1 - dias/120)
    pesquisas_para_confianca_plena=3,
    dias_para_meia_confianca=120,
)


@dataclass
class Pesquisa:
    uf: str
    instituto: str
    data_fim: date
    amostra: int
    tipo: str                      # "2votos" | "1voto"
    mencoes: dict[str, float]      # candidato -> % entrevistados
    indecisos: float = 0.0         # % entrevistados sem resposta
    branco_nulo: float = 0.0       # % entrevistados branco/nulo/nenhum
    registro_tse: str = ""
    fonte: str = ""
    peso_instituto: float = 1.0    # vem de ratings.py


@dataclass
class Dobradinha:
    a: str
    b: str
    tau: float


# ---------- kernel de dobradinha ----------
def kernel_segundo_voto(p1: dict[str, float], pares: list[Dobradinha], tau_default: float) -> dict[str, float]:
    """
    Dado um vetor de 1º voto p1 (soma ~ 100), devolve o 2º voto esperado por candidato.
    P(2º = j | 1º = i) = tau_i  se j é parceiro de i
                       = (1 - tau_i) * p1_j / (soma(p1) - p1_i)  caso contrário (tau_i=0 sem parceiro)
    """
    parceiro: dict[str, tuple[str, float]] = {}
    for d in pares:
        parceiro[d.a] = (d.b, d.tau if d.tau else tau_default)
        parceiro[d.b] = (d.a, d.tau if d.tau else tau_default)

    total = sum(p1.values())
    p2 = {c: 0.0 for c in p1}
    if total <= 0:
        return p2
    for i, pi in p1.items():
        if pi <= 0:
            continue
        par = parceiro.get(i)
        tau_i = par[1] if par and par[0] in p1 else 0.0
        if par and par[0] in p1:
            p2[par[0]] += pi * tau_i
        resto = total - pi
        if resto > 0 and (1 - tau_i) > 0:
            for j, pj in p1.items():
                if j == i:
                    continue
                p2[j] += pi * (1 - tau_i) * pj / resto
    return p2


def normaliza_pesquisa(p: Pesquisa, pares: list[Dobradinha], tau_default: float) -> dict[str, float]:
    """
    Converte a pesquisa em "menções projetadas" (% de eleitores que votariam no candidato),
    com indecisos redistribuídos via kernel. Saída comparável entre pesquisas de 1 e 2 votos.
    """
    m = {c: float(v) for c, v in p.mencoes.items() if v is not None}
    if not m:
        return {}
    if p.tipo == "1voto":
        # 1º voto observado -> projeta o 2º voto com o kernel
        p2 = kernel_segundo_voto(m, pares, tau_default)
        m = {c: m[c] + p2.get(c, 0.0) for c in m}

    # indecisos: cada indeciso tem 2 votos; 1º proporcional, 2º via kernel
    if p.indecisos > 0:
        total = sum(m.values())
        if total > 0:
            primeiro = {c: p.indecisos * m[c] / total for c in m}
            segundo = kernel_segundo_voto(primeiro, pares, tau_default)
            m = {c: m[c] + primeiro[c] + segundo.get(c, 0.0) for c in m}
    return m


# ---------- pesos ----------
def peso_pesquisa(p: Pesquisa, hoje: date, ordem_na_casa: int) -> float:
    dias = max(0, (hoje - p.data_fim).days)
    w_rec = 0.5 ** (dias / PARAMS["meia_vida_dias"])
    w_amostra = min(1.5, max(0.5, math.sqrt(max(p.amostra, 100) / 1000.0)))
    w_tipo = PARAMS["peso_1voto"] if p.tipo == "1voto" else 1.0
    w_rep = PARAMS["peso_repeticao"] ** ordem_na_casa   # 0 = mais recente da casa
    return w_rec * w_amostra * w_tipo * w_rep * p.peso_instituto


# ---------- agregação por UF ----------
@dataclass
class Estimativa:
    candidato: str
    media: float
    sigma: float
    p_eleito: float = 0.0
    p_primeiro: float = 0.0
    n_pesquisas: int = 0
    parceiro: str | None = None


@dataclass
class ResultadoUF:
    uf: str
    hoje: date
    candidatos: list[Estimativa]
    n_pesquisas: int
    ultima_pesquisa: date | None
    dias_sem_pesquisa: int | None
    pesos: list[dict] = field(default_factory=list)
    aviso: str = ""


def agrega_uf(uf: str, pesquisas: Iterable[Pesquisa], pares: list[Dobradinha], hoje: date,
              tau_default: float | None = None) -> ResultadoUF:
    tau_default = tau_default if tau_default is not None else PARAMS["tau_default"]
    ps = sorted([p for p in pesquisas if p.uf == uf], key=lambda p: p.data_fim, reverse=True)
    if not ps:
        return ResultadoUF(uf, hoje, [], 0, None, None, aviso="Sem pesquisas estimuladas registradas para o Senado.")

    # ordem dentro de cada casa (0 = mais recente)
    ordem: dict[str, int] = {}
    pesos, vetores = [], []
    for p in ps:
        k = ordem.get(p.instituto, 0)
        ordem[p.instituto] = k + 1
        w = peso_pesquisa(p, hoje, k)
        v = normaliza_pesquisa(p, pares, tau_default)
        pesos.append(w)
        vetores.append(v)

    candidatos = sorted({c for v in vetores for c in v})
    W = np.array(pesos)
    X = np.full((len(ps), len(candidatos)), np.nan)
    for r, v in enumerate(vetores):
        for c, val in v.items():
            X[r, candidatos.index(c)] = val

    ests: list[Estimativa] = []
    ultima = ps[0].data_fim
    dias_sem = max(0, (hoje - ultima).days)
    parceiro_de = {}
    for d in pares:
        parceiro_de[d.a] = d.b
        parceiro_de[d.b] = d.a

    for j, c in enumerate(candidatos):
        mask = ~np.isnan(X[:, j])
        w = W[mask]
        x = X[mask, j]
        if w.sum() <= 0:
            continue
        media = float(np.average(x, weights=w))
        # variância entre pesquisas (ponderada), com piso sigma_casa
        var_entre = float(np.average((x - media) ** 2, weights=w)) if len(x) > 1 else 0.0
        # erro amostral efetivo: n_eff = (sum w)^2 / sum w^2 * n médio
        n_med = float(np.average([ps[i].amostra for i in np.where(mask)[0]], weights=w))
        n_eff = n_med * (w.sum() ** 2) / (np.sum(w ** 2))
        p_frac = min(max(media / 100.0, 0.01), 0.99)
        var_amostral = (100.0 ** 2) * p_frac * (1 - p_frac) / max(n_eff, 100)
        var_env = (PARAMS["sigma_envelhecimento_dia"] * dias_sem) ** 2
        sigma = math.sqrt(var_amostral + max(var_entre, PARAMS["sigma_casa"] ** 2) + var_env)
        ests.append(Estimativa(c, media, sigma, n_pesquisas=int(mask.sum()), parceiro=parceiro_de.get(c)))

    _simula_vagas(ests, pares)
    _freio_pratico(ests, n_pesquisas=len(ps), dias_sem=dias_sem)
    ests.sort(key=lambda e: (-e.p_eleito, -e.media))

    detalhe = [dict(instituto=p.instituto, data_fim=p.data_fim.isoformat(), amostra=p.amostra,
                    tipo=p.tipo, peso=round(float(w), 3), registro_tse=p.registro_tse, fonte=p.fonte,
                    peso_instituto=p.peso_instituto) for p, w in zip(ps, pesos)]
    aviso = ""
    if len(ps) == 1:
        aviso = "Uma única pesquisa: intervalo largo por construção."
    elif dias_sem > 30:
        aviso = f"{dias_sem} dias sem pesquisa nova; incerteza ampliada."
    return ResultadoUF(uf, hoje, ests, len(ps), ultima, dias_sem, detalhe, aviso)


def _freio_pratico(ests: list[Estimativa], n_pesquisas: int, dias_sem: int) -> None:
    """Uma pesquisa de 48 dias atrás não sustenta 96% de certeza, por mais que a conta feche.
    Mistura a simulação com a ignorância (2 vagas / k candidatos) conforme a base é fina/velha."""
    k = len(ests)
    if k < 3:
        return
    lam = min(1.0, (n_pesquisas + 1) / (PARAMS["pesquisas_para_confianca_plena"] + 1)) * \
        max(0.5, 1.0 - dias_sem / PARAMS["dias_para_meia_confianca"])
    for e in ests:
        e.p_eleito = lam * e.p_eleito + (1 - lam) * (2.0 / k)
        e.p_primeiro = lam * e.p_primeiro + (1 - lam) * (1.0 / k)


def _simula_vagas(ests: list[Estimativa], pares: list[Dobradinha]) -> None:
    """Monte Carlo com choque comum e correlação intra-dobradinha; 2 primeiros levam."""
    if len(ests) < 2:
        for e in ests:
            e.p_eleito, e.p_primeiro = 1.0, 1.0
        return
    rng = np.random.default_rng(PARAMS["seed"])
    n, k = PARAMS["n_sim"], len(ests)
    idx = {e.candidato: i for i, e in enumerate(ests)}
    mu = np.array([e.media for e in ests])
    sd = np.array([e.sigma for e in ests])

    # matriz de correlação: identidade + rho nos pares
    C = np.eye(k)
    for d in pares:
        if d.a in idx and d.b in idx:
            C[idx[d.a], idx[d.b]] = C[idx[d.b], idx[d.a]] = PARAMS["rho_dobradinha"]
    L = np.linalg.cholesky(C + 1e-9 * np.eye(k))
    z = rng.standard_normal((n, k)) @ L.T
    comum = rng.standard_normal((n, 1)) * PARAMS["sigma_comum"]
    amostras = mu + z * sd + comum
    ordem = np.argsort(-amostras, axis=1)
    top2 = ordem[:, :2]
    primeiro = ordem[:, 0]
    for i, e in enumerate(ests):
        e.p_eleito = float(np.mean((top2 == i).any(axis=1)))
        e.p_primeiro = float(np.mean(primeiro == i))
