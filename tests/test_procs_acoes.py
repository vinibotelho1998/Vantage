"""Acoes da aba Processos: encerrar, prioridade e afinidade.

Aqui o app deixa de so' olhar e passa a mexer em processo alheio, rodando
elevado; o Windows nao vai segurar nada. Os testes cobrem justamente o que
nao tem desfazer: matar o processo errado, matar um processo essencial, e
mandar uma selecao de nucleos diferente da que a pessoa escolheu. Tudo com
dubles: nenhum processo de verdade e' tocado.
"""
import psutil
import pytest

from dbxstats.sensors import procs as P


class _Processo:
    """Duble de psutil.Process: anota o que foi pedido em vez de fazer."""

    def __init__(self, pid=1234, nome="jogo.exe", nega=(), sumiu=False, teimoso=False):
        self.pid = pid
        self._nome = nome
        self._nega = set(nega)      # metodos que o Windows recusaria
        self._sumiu = sumiu
        self._teimoso = teimoso     # ignora o terminate e so' morre no kill
        self.chamadas: list[tuple] = []
        self.prioridade = psutil.NORMAL_PRIORITY_CLASS
        self.nucleos = [0, 1, 2, 3]

    def _checar(self, metodo):
        if self._sumiu:
            raise psutil.NoSuchProcess(self.pid)
        if metodo in self._nega:
            raise psutil.AccessDenied(self.pid)

    def name(self):
        self._checar("name")
        return self._nome

    def terminate(self):
        self._checar("terminate")
        self.chamadas.append(("terminate",))

    def kill(self):
        self._checar("kill")
        self.chamadas.append(("kill",))
        self._teimoso = False

    def wait(self, timeout=None):
        self.chamadas.append(("wait", timeout))
        if self._teimoso:
            raise psutil.TimeoutExpired(timeout, pid=self.pid)
        return 0

    def nice(self, valor=None):
        self._checar("nice")
        if valor is None:
            return self.prioridade
        self.prioridade = valor
        self.chamadas.append(("nice", valor))

    def cpu_affinity(self, nucleos=None):
        self._checar("cpu_affinity")
        if nucleos is None:
            return list(self.nucleos)
        self.nucleos = list(nucleos)
        self.chamadas.append(("cpu_affinity", tuple(nucleos)))


@pytest.fixture
def falso(monkeypatch):
    """Instala o duble no lugar de psutil.Process e fixa a CPU em 8 nucleos."""
    def instalar(**kwargs):
        proc = _Processo(**kwargs)
        monkeypatch.setattr(P.psutil, "Process", lambda pid: proc)
        return proc
    monkeypatch.setattr(P, "nucleos_totais", lambda: 8)
    return instalar


# ── o que nao se mata ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("nome", ["lsass.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                                  "services.exe", "smss.exe", "dwm.exe", "Registry", "System"])
def test_processo_essencial_do_windows_e_bloqueado(nome):
    """Rodando elevado, o Windows aceitaria matar qualquer um destes e a sessao cai."""
    assert P.bloqueio_encerrar(nome, 900)


def test_bloqueio_ignora_caixa_alta_do_nome():
    """A lista da tela vem do proprio Windows, que escreve 'LsaSs.exe' quando quer."""
    assert P.bloqueio_encerrar("LSASS.EXE", 700)


def test_pids_do_nucleo_do_windows_sao_bloqueados():
    """PID 0 e 4 nao sao programas: sao o kernel e o processo System."""
    assert P.bloqueio_encerrar("qualquer.exe", 0)
    assert P.bloqueio_encerrar("qualquer.exe", 4)


def test_jogo_comum_nao_e_bloqueado():
    assert P.bloqueio_encerrar("jogo.exe", 4242) == ""


def test_explorer_pode_ser_encerrado_mas_avisa():
    """Matar o Explorer e' legitimo; sumir a barra de tarefas sem avisar, nao."""
    assert P.bloqueio_encerrar("explorer.exe", 5000) == ""
    assert "barra de tarefas" in P.aviso_encerrar("explorer.exe")
    assert P.aviso_encerrar("jogo.exe") == ""


def test_encerrar_recusa_essencial_sem_encostar_no_processo(falso):
    """A recusa tem de vir antes do terminate, nao depois de tentar."""
    proc = falso(nome="lsass.exe")
    ok, msg = P.encerrar(900, "lsass.exe")
    assert not ok
    assert proc.chamadas == []
    assert "essencial" in msg


# ── encerrar ──────────────────────────────────────────────────────────────────
def test_encerrar_processo_normal(falso):
    proc = falso(nome="jogo.exe")
    ok, msg = P.encerrar(1234, "jogo.exe")
    assert ok
    assert ("terminate",) in proc.chamadas
    assert "1234" in msg


def test_processo_teimoso_leva_kill_depois_da_espera(falso):
    """Sem o kill, o app anunciaria 'encerrado' para algo que continua vivo."""
    proc = falso(nome="jogo.exe", teimoso=True)
    ok, _ = P.encerrar(1234, "jogo.exe")
    assert ok
    assert ("kill",) in proc.chamadas


def test_pid_reaproveitado_nao_e_encerrado(falso):
    """O Windows recicla PID e a linha clicada tem ate' 2,5 s de atraso.

    Sem conferir o nome, o clique em Finalizar mataria o processo novo que
    herdou o numero: o programa errado morre e ninguem entende por que.
    """
    proc = falso(nome="outro.exe")
    ok, msg = P.encerrar(1234, "jogo.exe")
    assert not ok
    assert proc.chamadas == []
    assert "não está em execução" in msg


def test_acesso_negado_vira_frase_em_portugues(falso):
    """Excecao do psutil vazando na tela nao diz nada a quem esta' jogando."""
    falso(nome="protegido.exe", nega=["terminate"])
    ok, msg = P.encerrar(1234, "protegido.exe")
    assert not ok
    assert "negou permissão" in msg
    assert "AccessDenied" not in msg


def test_processo_que_ja_morreu_nao_estoura(falso):
    falso(nome="jogo.exe", sumiu=True)
    ok, msg = P.encerrar(1234, "jogo.exe")
    assert not ok
    assert "não está em execução" in msg


# ── prioridade ────────────────────────────────────────────────────────────────
def test_as_seis_faixas_da_tela_existem():
    assert [p.chave for p in P.PRIORIDADES] == [
        "realtime", "high", "above", "normal", "below", "idle"]


def test_so_tempo_real_e_marcada_como_perigosa():
    """A confirmacao extra da tela sai daqui: marcar outra faixa por engano cria atrito."""
    perigosas = [p.chave for p in P.PRIORIDADES if p.perigosa]
    assert perigosas == ["realtime"]


@pytest.mark.parametrize("chave, valor, rotulo", [
    ("realtime", psutil.REALTIME_PRIORITY_CLASS, "Tempo real"),
    ("high", psutil.HIGH_PRIORITY_CLASS, "Alta"),
    ("above", psutil.ABOVE_NORMAL_PRIORITY_CLASS, "Acima do normal"),
    ("normal", psutil.NORMAL_PRIORITY_CLASS, "Normal"),
    ("below", psutil.BELOW_NORMAL_PRIORITY_CLASS, "Abaixo do normal"),
    ("idle", psutil.IDLE_PRIORITY_CLASS, "Baixa"),
])
def test_cada_faixa_casa_com_a_classe_do_windows(chave, valor, rotulo):
    """Trocar um valor por outro poria o processo numa faixa que ninguem pediu."""
    prio = P.prioridade_por_chave(chave)
    assert prio.valor == valor
    assert prio.rotulo == rotulo
    assert P.rotulo_prioridade(valor) == rotulo


def test_prioridade_ilegivel_nao_vira_rotulo_inventado():
    """O dialogo mostra 'agora: ...'; chutar 'Normal' faria a pessoa nao mudar nada."""
    assert P.rotulo_prioridade(None) == ""
    assert P.rotulo_prioridade(999) == ""


def test_mudar_prioridade_manda_a_classe_certa(falso):
    proc = falso(nome="jogo.exe")
    ok, _ = P.mudar_prioridade(1234, "jogo.exe", "high")
    assert ok
    assert ("nice", psutil.HIGH_PRIORITY_CLASS) in proc.chamadas


def test_chave_de_prioridade_desconhecida_nao_toca_no_processo(falso):
    proc = falso(nome="jogo.exe")
    ok, _ = P.mudar_prioridade(1234, "jogo.exe", "turbo")
    assert not ok
    assert proc.chamadas == []


def test_prioridade_negada_pelo_windows_nao_estoura(falso):
    falso(nome="protegido.exe", nega=["nice"])
    ok, msg = P.mudar_prioridade(1234, "protegido.exe", "high")
    assert not ok
    assert "negou permissão" in msg


# ── afinidade: leitura do que foi digitado ────────────────────────────────────
@pytest.mark.parametrize("texto, esperado", [
    ("0-3", [0, 1, 2, 3]),
    ("0,2,4", [0, 2, 4]),
    ("0-1, 6 7", [0, 1, 6, 7]),
    ("3;1;2", [1, 2, 3]),
    ("  5  ", [5]),
    ("3-0", [0, 1, 2, 3]),          # faixa invertida: intencao obvia
    ("0-2, 1-3", [0, 1, 2, 3]),     # sobreposicao nao duplica
    ("", []),
])
def test_leitura_de_nucleos_digitados(texto, esperado):
    assert P.parse_nucleos(texto, 8) == esperado


@pytest.mark.parametrize("texto", ["8", "0-8", "0-99", "-1", "abc", "1--2", "0-2-4"])
def test_texto_impossivel_e_recusado_em_vez_de_adivinhado(texto):
    """Aceitar 'quase' seria pior: a afinidade aplicada nao seria a que se leu."""
    with pytest.raises(ValueError):
        P.parse_nucleos(texto, 8)


@pytest.mark.parametrize("nucleos, esperado", [
    ([0, 1, 2, 3, 8], "0-3, 8"),
    ([5], "5"),
    ([7, 1, 0], "0-1, 7"),
    ([], "nenhum"),
    ([2, 2, 3], "2-3"),
])
def test_resumo_de_nucleos_em_faixas(nucleos, esperado):
    """Dezesseis numeros soltos ninguem confere antes de clicar em Aplicar."""
    assert P.formatar_nucleos(nucleos) == esperado


# ── afinidade: aplicacao ──────────────────────────────────────────────────────
def test_afinidade_sem_nucleo_nenhum_e_recusada(falso):
    """Zero nucleo nao e' 'liberar geral': e' um processo que nao roda mais."""
    proc = falso(nome="jogo.exe")
    ok, msg = P.mudar_afinidade(1234, "jogo.exe", [])
    assert not ok
    assert proc.chamadas == []
    assert "pelo menos um núcleo" in msg


def test_afinidade_fora_da_cpu_e_recusada(falso):
    proc = falso(nome="jogo.exe")
    ok, msg = P.mudar_afinidade(1234, "jogo.exe", [0, 12])
    assert not ok
    assert proc.chamadas == []
    assert "0 a 7" in msg


def test_afinidade_aplicada_sai_limpa_e_ordenada(falso):
    """psutil recusa lista com repetido; a tela pode mandar dos dois jeitos."""
    proc = falso(nome="jogo.exe")
    ok, msg = P.mudar_afinidade(1234, "jogo.exe", [3, 0, 3, 1])
    assert ok
    assert ("cpu_affinity", (0, 1, 3)) in proc.chamadas
    assert "0-1, 3" in msg


def test_afinidade_completa_e_anunciada_como_sem_restricao(falso):
    proc = falso(nome="jogo.exe")
    ok, msg = P.mudar_afinidade(1234, "jogo.exe", range(8))
    assert ok
    assert proc.nucleos == [0, 1, 2, 3, 4, 5, 6, 7]
    assert "todos os núcleos" in msg


def test_afinidade_negada_pelo_windows_nao_estoura(falso):
    falso(nome="protegido.exe", nega=["cpu_affinity"])
    ok, msg = P.mudar_afinidade(1234, "protegido.exe", [0, 1])
    assert not ok
    assert "negou permissão" in msg


# ── leitura para preencher os dialogos ────────────────────────────────────────
def test_detalhes_traz_prioridade_e_nucleos(falso):
    proc = falso(nome="jogo.exe")
    proc.prioridade = psutil.HIGH_PRIORITY_CLASS
    proc.nucleos = [0, 1]
    assert P.detalhes(1234, "jogo.exe") == {
        "prioridade": psutil.HIGH_PRIORITY_CLASS, "nucleos": [0, 1]}


def test_leitura_negada_de_um_campo_nao_leva_o_outro_junto(falso):
    """Processo que deixa ler a prioridade e recusa a afinidade e' comum."""
    falso(nome="protegido.exe", nega=["cpu_affinity"])
    dados = P.detalhes(1234, "protegido.exe")
    assert dados["prioridade"] == psutil.NORMAL_PRIORITY_CLASS
    assert dados["nucleos"] is None


def test_detalhes_de_processo_sumido_vem_vazio_sem_estourar(falso):
    falso(nome="jogo.exe", sumiu=True)
    assert P.detalhes(1234, "jogo.exe") == {"prioridade": None, "nucleos": None}


def test_consulta_sem_pid_nao_bloqueia_tudo():
    """0 e' o PID do kernel, entao nao pode ser o padrao do parametro.

    Com zero como padrao, perguntar so' pelo nome devolvia "PID 0 e 4 sao o
    nucleo do Windows" para qualquer processo: nada poderia ser encerrado.
    """
    assert P.bloqueio_encerrar("jogo.exe") == ""
    assert P.bloqueio_encerrar("notepad.exe") == ""
    assert P.bloqueio_encerrar("lsass.exe")          # critico continua barrado
    assert P.bloqueio_encerrar("qualquer.exe", 0)    # kernel explicito, barrado
