"""Limpeza de sessoes ETW orfas: dizer a verdade sobre o que foi removido."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from dbxstats.sensors import fps  # noqa: E402


class _Saida:
    def __init__(self, texto, returncode=0):
        self.stdout = texto.encode("latin-1")
        self.returncode = returncode


def test_confirma_quando_a_sessao_sumiu(monkeypatch, caplog):
    """Antes o log afirmava a remocao sem conferir nada."""
    monkeypatch.setattr(fps.subprocess, "run",
                        lambda *a, **k: _Saida("Data Collector Set  Type  Status\n"))
    with caplog.at_level("INFO"):
        fps._conferir_remocao(["DBXStats_123"])
    assert any("removidas" in r.message for r in caplog.records)


def test_avisa_quando_a_sessao_resistiu(monkeypatch, caplog):
    """O caso real: o log repetia "removendo" a cada 15 s e nada acontecia, e
    quem lesse concluia que o problema era outro."""
    monkeypatch.setattr(fps.subprocess, "run",
                        lambda *a, **k: _Saida("DBXStats_123  Rastrear  Em execucao\n"))
    with caplog.at_level("WARNING"):
        fps._conferir_remocao(["DBXStats_123"])
    recados = [r.message for r in caplog.records]
    assert any("resistiu" in m for m in recados)


def test_o_aviso_aponta_a_causa_certa(monkeypatch, caplog):
    """`logman` diz "acesso negado" mesmo com privilegio de administrador, o que
    manda o diagnostico para permissao quando a causa e' recurso em uso."""
    monkeypatch.setattr(fps.subprocess, "run",
                        lambda *a, **k: _Saida("DBXStats_123  Rastrear  Em execucao\n"))
    with caplog.at_level("WARNING"):
        fps._conferir_remocao(["DBXStats_123"])
    texto = " ".join(r.message for r in caplog.records).lower()
    assert "outra copia" in texto
    assert "permissao" in texto


def test_consulta_que_falha_nao_derruba_a_limpeza(monkeypatch):
    def explode(*a, **k):
        raise OSError("logman sumiu")

    monkeypatch.setattr(fps.subprocess, "run", explode)
    fps._conferir_remocao(["DBXStats_123"])       # nao pode levantar


def test_so_sessoes_do_app_entram_na_conta():
    """Varrer nome alheio derrubaria rastreamento de outro programa."""
    assert fps._orfa("DBXStats_9999")
    assert not fps._orfa("Circular Kernel Context Logger")
    assert not fps._orfa("DiagLog")


# ── o conselho depende de haver outra copia ──────────────────────────────────
def _sessao_presa(monkeypatch):
    monkeypatch.setattr(fps.subprocess, "run",
                        lambda *a, **k: _Saida("DBXStats_123  Rastrear  Em execucao\n"))


def test_com_outra_copia_aberta_manda_fechar(monkeypatch, caplog):
    _sessao_presa(monkeypatch)
    monkeypatch.setattr(fps, "_outras_copias", lambda: [4242])
    with caplog.at_level("WARNING"):
        fps._conferir_remocao(["DBXStats_123"])
    texto = " ".join(r.message for r in caplog.records)
    assert "4242" in texto
    assert "feche todas" in texto
    assert "reinici" not in texto.lower()


def test_sem_outra_copia_manda_reiniciar(monkeypatch, caplog):
    """O caso que a mensagem anterior errava: culpava "outra copia aberta"
    quando nao havia nenhuma, mandando procurar o que nao existe."""
    _sessao_presa(monkeypatch)
    monkeypatch.setattr(fps, "_outras_copias", lambda: [])
    with caplog.at_level("WARNING"):
        fps._conferir_remocao(["DBXStats_123"])
    texto = " ".join(r.message for r in caplog.records).lower()
    assert "reiniciando o windows" in texto
    assert "feche todas" not in texto


def test_a_propria_instancia_nao_conta_como_outra_copia():
    """Contar a si mesmo daria sempre "ha' outra copia" e nunca o conselho certo."""
    assert os.getpid() not in fps._outras_copias()


# ── a consulta precisa ter dado certo para valer ─────────────────────────────
class _Falhou:
    """logman que retorna erro: stdout vazio e codigo diferente de zero."""
    stdout = b""
    returncode = 1


def test_consulta_que_falha_nao_vira_remocao_confirmada(monkeypatch, caplog):
    """O bug real: logman falhando devolve texto vazio, nenhum nome casa, e o
    log anunciava "removidas" sobre sessoes que continuavam de pe'."""
    monkeypatch.setattr(fps.subprocess, "run", lambda *a, **k: _Falhou())
    with caplog.at_level("INFO"):
        fps._conferir_remocao(["DBXStats_123"])
    texto = " ".join(r.message for r in caplog.records)
    assert "removidas" not in texto
    assert "nao consegui conferir" in texto


def test_saida_vazia_com_codigo_zero_tambem_nao_confirma(monkeypatch, caplog):
    class _Vazio:
        stdout = b"   \n"
        returncode = 0

    monkeypatch.setattr(fps.subprocess, "run", lambda *a, **k: _Vazio())
    with caplog.at_level("INFO"):
        fps._conferir_remocao(["DBXStats_123"])
    assert "removidas" not in " ".join(r.message for r in caplog.records)
