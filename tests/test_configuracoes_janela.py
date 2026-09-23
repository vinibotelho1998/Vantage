"""Janela de Configuracoes: o que ela grava e o que o "Restaurar padroes" desfaz.

Dois defeitos moravam aqui. O trilho de tensao da memoria era escolhido na aba
Overlay, aparecia na previa e sumia ao salvar: o `_save` nunca o gravava. E o
"Restaurar padroes", sem pedir confirmacao, zerava o arquivo inteiro, inclusive
a biblioteca de jogos e os perfis de tela, que nem aparecem nesta janela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VANTAGE_NO_FILE_LOG", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

from vantage.config import Settings  # noqa: E402
from vantage.ui.settings import _CAMPOS_DA_JANELA, SettingsDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Fps:
    status = "capturando"
    restarts = 0

    def apps(self):
        return []


class _Lhm:
    def __init__(self, rails):
        self.rails_vistos = list(rails)


class _Ctl:
    """Controlador minimo: o dialogo so' precisa disto, e nada toca o disco."""

    def __init__(self, cfg, rails=()):
        self.settings = cfg
        self.fps = _Fps()
        self.lhm = _Lhm(rails)
        self.aplicou = 0

    def restart_capture(self):
        pass

    def clear_stats(self):
        pass

    def on_settings_changed(self):
        self.aplicou += 1


def _perfil(nome):
    return {"name": nome, "hotkey": "", "topology": "",
            "entries": [{"device": r"\\.\DISPLAY1", "monitor_id": "m1", "name": "TV",
                         "active": True, "primary": True, "position": [0, 0],
                         "mode": None}]}


def test_trilho_escolhido_na_aba_overlay_e_gravado():
    cfg = Settings()
    ctl = _Ctl(cfg, [("Voltage #3", 3.312), ("Voltage #7", 1.352)])
    d = SettingsDialog(ctl, 4)
    d.w_rail.setCurrentIndex(d.w_rail.findData("Voltage #7"))

    d._save()

    assert cfg.mem_volt_rail == "Voltage #7"
    assert ctl.aplicou == 1


def test_trilho_salvo_nao_some_quando_a_placa_ainda_nao_publicou_nada():
    """Logo depois de abrir o app o LHM ainda nao leu a placa; salvar qualquer
    outra opcao nesse instante nao pode apagar a escolha feita antes."""
    cfg = Settings()
    cfg.mem_volt_rail = "Voltage #7"
    d = SettingsDialog(_Ctl(cfg, []), 0)

    d._save()

    assert cfg.mem_volt_rail == "Voltage #7"


def test_restaurar_padroes_nao_apaga_a_biblioteca_nem_os_perfis():
    cfg = Settings()
    cfg.accent = "red"
    cfg.overlay_opacity = 0.5
    cfg.launch_items = [{"name": "Jogo", "path": r"C:\Jogos\jogo.exe", "args": "",
                         "target": "primary:tv", "restore": True}]
    cfg.display_profiles = [_perfil("Sofa")]
    cfg.display_default_profile = "Sofa"
    cfg.display_primary_default = "m1"
    cfg.display_off_by_default = ["tv"]
    cfg.sensor_favorites = ["CPU/Temperature/Package"]
    cfg.gamepad_bindings = {"A": "key_enter"}
    cfg.sanitize()
    ctl = _Ctl(cfg)
    d = SettingsDialog(ctl, 0)

    d._restore_defaults()
    d._save()

    assert cfg.accent == "cyan"
    assert cfg.overlay_opacity == Settings().overlay_opacity
    assert [i["name"] for i in cfg.launch_items] == ["Jogo"]
    assert [p["name"] for p in cfg.display_profiles] == ["Sofa"]
    assert cfg.display_default_profile == "Sofa"
    assert cfg.display_primary_default == "m1"
    assert cfg.display_off_by_default == ["tv"]
    assert cfg.sensor_favorites == ["CPU/Temperature/Package"]
    assert cfg.gamepad_bindings == {"A": "key_enter"}
    assert ctl.aplicou == 1


class _Gravador:
    """Anota cada campo que o dialogo escreve, repassando para o objeto real."""

    def __init__(self, real):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "tocados", set())

    def __getattr__(self, nome):
        return getattr(self._real, nome)

    def __setattr__(self, nome, valor):
        self.tocados.add(nome)
        setattr(self._real, nome, valor)


def test_restaurar_cobre_tudo_o_que_a_janela_grava():
    """Campo novo no `_save` e fora da lista seria opcao que o restaurar esquece."""
    d = SettingsDialog(_Ctl(Settings()), 0)
    gravador = _Gravador(d._cfg)
    d._cfg = gravador

    d._save()

    assert gravador.tocados <= set(_CAMPOS_DA_JANELA), gravador.tocados - set(_CAMPOS_DA_JANELA)
    assert "mem_volt_rail" in gravador.tocados


def test_restaurar_so_preenche_o_formulario_e_cancelar_desfaz():
    """Os padroes vao para a tela; o arquivo so' muda quando a pessoa salva."""
    cfg = Settings()
    cfg.accent = "red"
    cfg.autostart = True
    cfg.alert_cpu_temp = 70
    cfg.sanitize()
    ctl = _Ctl(cfg)
    d = SettingsDialog(ctl, 0)

    d._restore_defaults()

    assert cfg.accent == "red"
    assert cfg.autostart is True
    assert cfg.alert_cpu_temp == 70
    assert ctl.aplicou == 0
    d.reject()
    assert cfg.accent == "red"
    assert ctl.aplicou == 0


def test_restaurar_e_salvar_leva_cada_campo_da_janela_ao_padrao():
    """Campo esquecido no `_preencher` ficaria com o valor antigo depois do Salvar."""
    cfg = Settings()
    for nome, valor in {
            "start_view": "cpu", "update_interval": 1.0, "always_on_top": True,
            "close_to_tray": False, "start_minimized": True, "autostart": True,
            "ping_host": "1.1.1.1", "ping_port": 443, "accent": "red", "ui_scale": 1.25,
            "dash_cards": ["cpu"], "history_window": 300, "smooth_lines": False,
            "fill_area": False, "show_grid": False, "chart_glow": False,
            "fps_window": 30.0, "fps_now_window": 2.0, "fps_only_fullscreen": True,
            "overlay_enabled": False, "overlay_auto_game": False,
            "overlay_corner": "bottom-right", "overlay_opacity": 0.5, "overlay_scale": 1.5,
            "overlay_refresh_hz": 6.0, "overlay_graph_seconds": 120, "overlay_columns": 2,
            "overlay_metrics": ["fps"], "mem_volt_rail": "Voltage #7",
            "alerts_enabled": False, "alert_cpu_temp": 70, "alert_gpu_temp": 70,
            "alert_ram_pct": 80, "alert_vram_pct": 80}.items():
        setattr(cfg, nome, valor)
    cfg.sanitize()
    d = SettingsDialog(_Ctl(cfg, [("Voltage #7", 1.352)]), 0)

    d._restore_defaults()
    d._save()

    padrao = Settings()
    padrao.sanitize()
    diferentes = {nome: getattr(cfg, nome) for nome in _CAMPOS_DA_JANELA
                  if getattr(cfg, nome) != getattr(padrao, nome)}
    assert not diferentes, diferentes
