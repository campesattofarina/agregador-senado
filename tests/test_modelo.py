from datetime import date
from model.agregador import Pesquisa, Dobradinha, agrega_uf, kernel_segundo_voto, normaliza_pesquisa

hoje = date(2026, 9, 9)
pares = [Dobradinha("Ana", "Bruno", 0.7)]

def test_kernel_transfere_para_parceiro():
    p1 = {"Ana": 40, "Bruno": 10, "Carla": 30, "Dario": 20}
    p2 = kernel_segundo_voto(p1, pares, 0.65)
    # quem vota Ana no 1º (40) dá 70% do 2º a Bruno = 28, mais o proporcional dos outros
    assert p2["Bruno"] > 28
    assert abs(sum(p2.values()) - 100) < 1e-6

def test_1voto_vira_2votos_com_dobradinha():
    p = Pesquisa("RS", "X", hoje, 1000, "1voto", {"Ana": 40, "Bruno": 10, "Carla": 30, "Dario": 20})
    m = normaliza_pesquisa(p, pares, 0.65)
    assert m["Bruno"] > m["Dario"]          # dobradinha puxa Bruno acima de Dario no 2º voto
    assert 199 < sum(m.values()) <= 200.01

def test_agregacao_e_vagas():
    ps = [
        Pesquisa("RS", "Casa1", date(2026, 9, 5), 1500, "2votos", {"Ana": 42, "Bruno": 33, "Carla": 35, "Dario": 22}, indecisos=12, branco_nulo=8, peso_instituto=1.2),
        Pesquisa("RS", "Casa2", date(2026, 8, 28), 1000, "2votos", {"Ana": 38, "Bruno": 30, "Carla": 37, "Dario": 25}, indecisos=15, branco_nulo=6, peso_instituto=0.9),
        Pesquisa("RS", "Casa1", date(2026, 8, 10), 1500, "2votos", {"Ana": 36, "Bruno": 26, "Carla": 36, "Dario": 28}, indecisos=20, branco_nulo=7, peso_instituto=1.2),
        Pesquisa("RS", "Casa3", date(2026, 9, 1), 800, "1voto", {"Ana": 33, "Bruno": 12, "Carla": 28, "Dario": 15}, indecisos=12, peso_instituto=0.6),
    ]
    r = agrega_uf("RS", ps, pares, hoje)
    nomes = [e.candidato for e in r.candidatos]
    assert nomes[0] == "Ana"
    total_p = sum(e.p_eleito for e in r.candidatos)
    assert abs(total_p - 2.0) < 0.02        # exatamente 2 vagas
    # peso: pesquisa mais recente da Casa1 > pesquisa antiga da Casa1
    w = {(d["instituto"], d["data_fim"]): d["peso"] for d in r.pesos}
    assert w[("Casa1", "2026-09-05")] > 2 * w[("Casa1", "2026-08-10")]
    for e in r.candidatos:
        print(f"{e.candidato:6s} média {e.media:5.1f} ±{e.sigma:4.1f}  P(eleito) {e.p_eleito:.2f}  P(1º) {e.p_primeiro:.2f}")
    print("pesos:", w)

def test_uma_pesquisa_intervalo_largo():
    ps = [Pesquisa("AC", "Casa1", date(2026, 7, 1), 600, "2votos", {"E": 30, "F": 28, "G": 27}, indecisos=30)]
    r = agrega_uf("AC", ps, [], hoje)
    assert all(e.sigma > 8 for e in r.candidatos)
    assert "única" in r.aviso
