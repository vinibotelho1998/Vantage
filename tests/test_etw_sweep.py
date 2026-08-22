"""Limpeza de sessoes ETW orfas: dizer a verdade sobre o que foi removido."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DBXSTATS_NO_FILE_LOG", "1")

from dbxstats.sensors import fps  # noqa: E402


class _Saida:
    def __init__(self, texto):
        self.stdout = texto.encode("latin-1")


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
