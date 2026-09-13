"""Gera docs/data/agregado.json com dados FICTÍCIOS (flag demo=true) só para validar a interface.
Uso: python -m tests.demo   — depois a primeira varredura real sobrescreve o arquivo."""
import json, random
from datetime import date, timedelta
from model.agregador import Pesquisa, Dobradinha, agrega_uf, PARAMS
from pipeline.util import RAIZ

random.seed(7)
hoje = date.today()
ufs = json.loads((RAIZ / "config/ufs.json").read_text())
casas = [("Casa Alfa", 1.3, "A"), ("Casa Beta", 1.0, "B"), ("Casa Gama", 0.7, "C"), ("Casa Delta", 0.6, None)]
ratings = {c: dict(mae=m, disputas=12, nota=n, peso=w) for c, w, n in casas for m in [3.1 if n == "A" else 4.2 if n == "B" else 5.5] if n}
estados = {}
for uf, cfg in ufs.items():
    k = random.choice([0, 1, 1, 2, 3, 5])
    nomes = [f"Cand. {uf}-{l}" for l in "ABCDE"]
    base = sorted([random.uniform(15, 45) for _ in nomes], reverse=True)
    pares = [Dobradinha(nomes[0], nomes[2], 0.7)] if random.random() < .6 else []
    ps = []
    for i in range(k):
        casa, w, _ = random.choice(casas)
        d = hoje - timedelta(days=random.randint(2, 60) + i * 5)
        m = {n: max(2, b + random.gauss(0, 3)) for n, b in zip(nomes, base)}
        ps.append(Pesquisa(uf, casa, d, random.choice([800, 1000, 1500, 2000]), "2votos", m, indecisos=random.uniform(8, 25), branco_nulo=random.uniform(4, 10), registro_tse=f"{uf}-0{random.randint(1000, 9999)}/2026", fonte="demo", peso_instituto=w))
    r = agrega_uf(uf, ps, pares, hoje)
    estados[uf] = dict(nome=cfg["nome"], grid=cfg["grid"], n_pesquisas=r.n_pesquisas,
        ultima_pesquisa=r.ultima_pesquisa.isoformat() if r.ultima_pesquisa else None, dias_sem_pesquisa=r.dias_sem_pesquisa, aviso=r.aviso,
        dobradinhas=[dict(a=p.a, b=p.b, tau=p.tau) for p in pares],
        candidatos=[dict(nome=e.candidato, media=round(e.media, 1), sigma=round(e.sigma, 1), p_eleito=round(e.p_eleito, 3), p_primeiro=round(e.p_primeiro, 3), n=e.n_pesquisas, parceiro=e.parceiro) for e in r.candidatos],
        pesquisas=r.pesos, pendentes=([dict(uf=uf, instituto="Casa Beta", instituto_bruto="CASA BETA PESQUISAS LTDA", registro_tse=f"{uf}-08811/2026", data_fim=(hoje - timedelta(days=3)).isoformat(), amostra=1200, dias=3)] if uf in ("RS", "SP") else []))
saida = dict(demo=True, atualizado=hoje.isoformat(), novas_hoje=2, total_pesquisas=sum(e["n_pesquisas"] for e in estados.values()), total_pendentes=2,
             parametros={k: v for k, v in PARAMS.items() if k not in ("seed", "n_sim")}, ratings=ratings, mae_global=4.1, estados=estados)
(RAIZ / "docs/data/agregado.json").write_text(json.dumps(saida, ensure_ascii=False))
print("demo gravado")
