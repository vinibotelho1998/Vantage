"""Fluidez e gargalo contra series de frametime de casos conhecidos.

As duas metricas sao opiniao sobre a experiencia, e opiniao errada e' pior que
metrica ausente: um vsync travado precisa dar nota quase cheia, ruido puro precisa
desabar, e o veredito de gargalo nao pode nascer de duas ou tres amostras nem
piscar entre CPU e GPU a cada tique. Aqui as series sao sinteticas justamente para
que a resposta certa seja conhecida de antemao.
"""
import random

from vantage.core import frames as fr

NAN = float("nan")


def _amostras(fts, cpu=NAN, gpu=NAN):
    """Monta amostras no formato do motor; cpu/gpu aceitam escalar ou lista."""
    out = []
    t = 0.0
    for i, ms in enumerate(fts):
        c = cpu[i] if isinstance(cpu, list) else cpu
        g = gpu[i] if isinstance(gpu, list) else gpu
        t += ms / 1000.0
        out.append((t, ms, c, g, g, 10.0, 1.0, NAN))
    return out


def _vsync(hz, segundos, jitter_ms=0.0, seed=1):
    """Cadencia travada no refresh, com o tremor de decimos que o Windows sempre poe."""
    rng = random.Random(seed)
    passo = 1000.0 / hz
    n = int(hz * segundos)
    return [passo + rng.uniform(-jitter_ms, jitter_ms) for _ in range(n)]


def _limitado(ms, segundos, sigma, seed=2):
    """Jogo preso num motor so' (CPU ou GPU): frametime em torno de um valor."""
    rng = random.Random(seed)
    n = max(2, int(segundos * 1000.0 / ms))
    return [max(0.5, rng.gauss(ms, sigma)) for _ in range(n)]


def _com_engasgos(base_ms, segundos, cada_s, travada_ms, sigma=0.3, seed=3):
    """Serie limpa interrompida por uma travada de tempos em tempos."""
    rng = random.Random(seed)
    fts, decorrido, proximo = [], 0.0, cada_s
    while decorrido < segundos * 1000.0:
        if decorrido >= proximo * 1000.0:
            ms = travada_ms
            proximo += cada_s
        else:
            ms = max(0.5, rng.gauss(base_ms, sigma))
        fts.append(ms)
        decorrido += ms
    return fts


def _ruido(lo, hi, segundos, seed=4):
    """Sem cadencia nenhuma: cada quadro sorteia o proprio tempo."""
    rng = random.Random(seed)
    fts, decorrido = [], 0.0
    while decorrido < segundos * 1000.0:
        ms = rng.uniform(lo, hi)
        fts.append(ms)
        decorrido += ms
    return fts


# ── fluidez ───────────────────────────────────────────────────────────────────
def test_vsync_travado_da_nota_quase_cheia():
    """144 fps preso no refresh e' o teto da experiencia; se isso nao da 100, a escala mente."""
    for hz in (60, 144):
        exato = fr.compute(_amostras(_vsync(hz, 20))).smoothness
        real = fr.compute(_amostras(_vsync(hz, 20, jitter_ms=0.15))).smoothness
        assert exato == 100.0
        assert real >= 97.0


def test_fluidez_cai_de_forma_monotona_com_a_variacao():
    """Mais variacao tem de valer menos nota, sempre; senao o numero nao ordena nada."""
    notas = [fr.compute(_amostras(_limitado(10.0, 30, sigma))).smoothness
             for sigma in (0.0, 0.3, 0.8, 1.5, 3.0, 6.0)]
    assert notas == sorted(notas, reverse=True)
    assert notas[0] >= 99.0
    assert notas[-1] <= 55.0


def test_fluidez_desaba_com_engasgos_periodicos():
    """Travada de 80 ms a cada dois segundos e' o caso que o usuario reclama e sente."""
    limpo = fr.compute(_amostras(_limitado(8.0, 60, 0.3))).smoothness
    engasgado = fr.compute(_amostras(_com_engasgos(8.0, 60, 2.0, 80.0))).smoothness
    assert limpo >= 95.0
    assert engasgado <= 75.0
    assert limpo - engasgado >= 20.0


def test_fluidez_de_ruido_puro_fica_no_chao():
    """Sem cadencia alguma o veredito tem de ser o pior, nao 'media'.

    A afirmacao e' sobre a faixa, nao sobre o numero exato: o que a pessoa le'
    e' a frase. Prender o teste a um valor fechado so' fazia ele quebrar a cada
    recalibracao sem nada ter piorado de verdade.
    """
    m = fr.compute(_amostras(_ruido(5.0, 30.0, 30)))
    assert m.smoothness < 50.0
    assert fr.verdict(m).startswith("Ruim")
    assert fr.verdict(m).startswith("Ruim")


def test_fluidez_mede_cadencia_e_nao_velocidade():
    """Queda lenta de 120 para 60 fps nao e' engasgo: aparece no fps, nao na fluidez.

    O calculo antigo saia pelo desvio padrao da janela inteira e punia essa rampa
    como se fosse stutter, quando nao ha um unico solavanco nela.
    """
    n = 6000
    fts = [8.33 + (16.67 - 8.33) * i / (n - 1) for i in range(n)]
    assert fr.compute(_amostras(fts)).smoothness >= 95.0


def test_fluidez_nao_pula_entre_tiques():
    """A interface atualiza 4x por segundo; nota que pula de 40 a 90 e' ruido, nao leitura."""
    fts = _com_engasgos(10.0, 150, 3.0, 70.0)
    todas = _amostras(fts)
    notas = []
    for tique in range(40):
        fim = 60.0 + tique * 0.25
        janela = fr.window([s for s in todas if s[fr.T] <= fim], 60.0)
        notas.append(fr.compute(janela).smoothness)
    saltos = [abs(b - a) for a, b in zip(notas, notas[1:], strict=False)]
    assert max(saltos) <= 3.0
    assert max(notas) - min(notas) <= 8.0


def test_fluidez_espera_amostra_minima():
    """Com meia duzia de quadros a mediana das diferencas e' chute; melhor nao opinar."""
    assert fr.compute(_amostras([16.7] * 10)).smoothness is None
    assert fr.compute(_amostras([16.7] * 200)).smoothness is not None


def test_fluidez_nao_desconta_duas_vezes_a_mesma_travada():
    """Uma unica travada numa captura longa nao pode derrubar a nota inteira.

    Antes o desconto vinha em contagem absoluta de engasgos, entao a mesma captura
    valia notas diferentes conforme o tamanho da janela.
    """
    curta = fr.compute(_amostras(_limitado(10.0, 30, 0.3) + [90.0])).smoothness
    longa = fr.compute(_amostras(_limitado(10.0, 300, 0.3) + [90.0])).smoothness
    assert curta >= 85.0
    assert longa >= curta          # a mesma travada pesa menos numa janela maior
    assert longa - curta <= 10.0


# ── gargalo ───────────────────────────────────────────────────────────────────
def test_gargalo_gpu_por_quadro():
    """Caso de livro: GPU fechando o quadro quase inteiro, CPU folgada."""
    m = fr.compute(_amostras(_limitado(10.0, 20, 0.3), cpu=4.0, gpu=9.6))
    assert m.bottleneck == fr.BOTTLENECK_GPU
    assert m.gpu_bound_pct == 100.0


def test_gargalo_cpu_por_quadro():
    m = fr.compute(_amostras(_limitado(12.0, 20, 0.3), cpu=11.5, gpu=6.0))
    assert m.bottleneck == fr.BOTTLENECK_CPU
    assert m.cpu_bound_pct == 100.0


def test_gargalo_com_os_dois_saturados_fica_com_quem_termina_por_ultimo():
    """CPU 9,9 ms e GPU 8,5 ms num quadro de 10: quem manda e' a CPU."""
    m = fr.compute(_amostras([10.0] * 300, cpu=9.9, gpu=8.5))
    assert m.bottleneck == fr.BOTTLENECK_CPU


def test_gpu_alta_nao_atropela_a_cpu_mais_alta_ainda():
    """GPU em 92,5% do quadro com a CPU em 99%: nao e' gargalo de GPU, e' empate.

    A regra antiga testava primeiro "GPU acima de 92% do frametime" e devolvia GPU
    sem nunca olhar a CPU: o veredito mandava mexer no lado errado.
    """
    m = fr.compute(_amostras([10.0] * 300, cpu=9.9, gpu=9.25))
    assert m.bottleneck == fr.BOTTLENECK_BALANCED


def test_limitador_nao_e_confundido_com_gargalo_de_gpu():
    """Cap de 60 fps com CPU e GPU folgadas: dizer 'GPU' aqui manda o usuario mexer no lugar errado.

    A regra antiga so' reconhecia o limitador quando o desvio padrao ficava abaixo
    de 1,2 ms; um cap real oscila mais que isso e caia na comparacao de medias,
    onde 0,30 contra 0,18 virava veredito de GPU.
    """
    m = fr.compute(_amostras(_vsync(60, 30, jitter_ms=1.6), cpu=3.0, gpu=5.0))
    assert m.bottleneck == fr.BOTTLENECK_CAP
    assert m.capped_pct == 100.0


def test_gargalo_empatado_quando_os_dois_se_revezam():
    """Metade dos quadros de cada lado e' empate, e nao 'sem gargalo nenhum'.

    Com media por coluna os dois lados davam 6,75 ms num quadro de 10 e a conta
    antiga concluia que ninguem estava saturado, quando na verdade os dois estavam,
    em quadros alternados.
    """
    n = 400
    cpu = [9.5 if i % 2 else 4.0 for i in range(n)]
    gpu = [4.0 if i % 2 else 9.5 for i in range(n)]
    m = fr.compute(_amostras([10.0] * n, cpu=cpu, gpu=gpu))
    assert m.bottleneck == fr.BOTTLENECK_BALANCED
    assert 45.0 <= m.cpu_bound_pct <= 55.0


def test_gargalo_indisponivel_sem_as_colunas():
    """PresentMon v1 nao traz CPUBusy/GPUBusy: o certo e' admitir, nao deduzir."""
    m = fr.compute(_amostras([10.0] * 300))
    assert m.bottleneck == fr.BOTTLENECK_NA
    assert "v1" in m.bottleneck_detail
    assert m.cpu_bound_pct is None


def test_gargalo_espera_amostra_minima():
    """Veredito tirado de tres quadros e' chute com cara de certeza."""
    m = fr.compute(_amostras([10.0] * 20, cpu=9.5, gpu=3.0))
    assert m.bottleneck == fr.BOTTLENECK_NONE
    assert "coletando" in m.bottleneck_detail


def test_gargalo_ignora_quadro_com_lado_faltando():
    """Nem todo modo de captura preenche as duas colunas em todo quadro.

    Media por coluna cruzava numeros de quadros diferentes; a votacao so' conta
    quadro em que os dois lados existem.
    """
    n = 400
    cpu = [9.6 if i % 2 else NAN for i in range(n)]
    gpu = [4.0 if i % 2 else 9.9 for i in range(n)]
    m = fr.compute(_amostras([10.0] * n, cpu=cpu, gpu=gpu))
    assert m.bottleneck == fr.BOTTLENECK_CPU
    assert m.cpu_bound_pct == 100.0


def test_gargalo_nao_pisca_entre_tiques():
    """Disputa apertada nao pode fazer o rotulo alternar CPU/GPU a cada 250 ms."""
    rng = random.Random(7)
    n = 8000
    fts = [max(0.5, rng.gauss(10.0, 0.4)) for _ in range(n)]
    cpu = [max(0.5, rng.gauss(9.0, 0.5)) for _ in range(n)]
    gpu = [max(0.5, rng.gauss(8.6, 0.5)) for _ in range(n)]
    todas = _amostras(fts, cpu=cpu, gpu=gpu)
    vereditos = set()
    for tique in range(40):
        fim = 40.0 + tique * 0.25
        janela = fr.window([s for s in todas if s[fr.T] <= fim], 30.0)
        vereditos.add(fr.compute(janela).bottleneck)
    assert len(vereditos) == 1


def test_fluidez_nao_tem_penhasco_no_limiar_de_travada():
    """A punicao contava quadros acima de 50 ms absolutos.

    Um pico de 49 ms valia 96 e um de 51 ms valia 19: 77 pontos por 2 ms de
    diferenca. E depois do degrau a nota voltava a SUBIR com picos maiores,
    porque so' a contagem importava e o pico grande nao pesava mais que o
    pequeno.
    """
    def com_pico(pico_ms: float) -> float:
        fts = [1000 / 144 if i % 144 else pico_ms for i in range(4000)]
        return fr.compute(_amostras(fts)).smoothness

    assert abs(com_pico(49.0) - com_pico(51.0)) < 5.0

    notas = [com_pico(p) for p in (20, 30, 45, 60, 80, 120, 200)]
    assert notas == sorted(notas, reverse=True), notas


def test_fluidez_piora_com_a_frequencia_do_solavanco():
    """Mesmo pico, mais vezes por segundo, tem de doer mais."""
    def a_cada(segundos: float) -> float:
        n = int(144 * segundos)
        fts = [1000 / 144 if i % n else 80.0 for i in range(6000)]
        return fr.compute(_amostras(fts)).smoothness

    notas = [a_cada(s) for s in (1, 2, 5, 10, 30)]
    assert notas == sorted(notas), notas
