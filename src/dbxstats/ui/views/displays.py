"""Tela de gerenciamento de monitores: modo, ligar e desligar, primaria e perfis.

Fala direto com `platform.displays`, que usa API nativa do Windows. Duas decisoes
desta tela vieram de problema real e valem registro:

Desligar aqui e' desanexar do desktop. Nunca desabilitar o dispositivo no
Gerenciador de Dispositivos: aquilo mantem a saida de video viva com o no de
monitor em erro, e o app de Configuracoes do Windows para de abrir.

A lista de modos vem do driver, nao do EDID. Algumas TVs declaram menos blocos de
extensao do que realmente possuem, e o Windows para de ler antes das taxas altas.
E' por isso que 4K 144 aparece aqui mesmo quando some das Configuracoes.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from ... import theme
from ...platform import ccd
from ...platform import displays as D
from ..components import Badge, Card, KpiStrip, PillButton, divider, label
from .base import View, scroll_page

_KPIS = [
    ("total", "Telas", ""), ("on", "Ligadas", ""),
    ("primary", "Primária", ""), ("pixels", "Área total", "px"),
]


def _combo(items: list[tuple[str, object]], current=None) -> QComboBox:
    box = QComboBox()
    for text, value in items:
        box.addItem(text, value)
    if current is not None:
        idx = box.findData(current)
        if idx >= 0:
            box.setCurrentIndex(idx)
    return box


class _DisplayCard(Card):
    """Um cartao por tela fisica, com os controles dela."""

    changed = Signal()

    def __init__(self, disp: D.Display, view: DisplaysView) -> None:
        color = theme.GPU if disp.active else theme.FAINT
        super().__init__(disp.name or disp.device, color)
        self.view = view
        self.disp = disp

        self.badge = Badge("", theme.MUTE)
        self.add_header_widget(self.badge)

        info = QHBoxLayout()
        info.setSpacing(theme.scaled(14))
        nativa = f"{disp.native[0]} x {disp.native[1]}" if disp.native else "?"
        for caption, value in (("Nativa", nativa), ("Atual", disp.summary),
                               ("Saída", disp.device.replace("\\\\.\\", ""))):
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(label(caption.upper(), 7.5, color=theme.FAINT))
            cell.addWidget(label(value, 9.5, color=theme.TXT))
            info.addLayout(cell)
        info.addStretch(1)
        self.add_layout(info)
        self.add(divider())

        self.res_box = _combo(self._resolutions())
        self.hz_box = _combo([])
        self.res_box.currentIndexChanged.connect(self._fill_rates)
        self._fill_rates()

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        row.addWidget(label("Resolução", 8.5, color=theme.MUTE))
        row.addWidget(self.res_box, 2)
        row.addWidget(label("Taxa", 8.5, color=theme.MUTE))
        row.addWidget(self.hz_box, 1)
        self.add_layout(row)

        actions = QHBoxLayout()
        actions.setSpacing(theme.scaled(8))
        self.btn_apply = PillButton("Aplicar", theme.FPS, filled=True)
        self.btn_apply.clicked.connect(self._apply_mode)
        self.btn_primary = PillButton("Tornar primária", theme.RAM)
        self.btn_primary.clicked.connect(self._make_primary)
        self.btn_power = PillButton("", theme.MUTE)
        self.btn_power.clicked.connect(self._toggle_power)
        actions.addWidget(self.btn_apply)
        actions.addWidget(self.btn_primary)
        actions.addWidget(self.btn_power)
        actions.addStretch(1)
        self.add_layout(actions)

        self._sync_state()

    # ── dados ────────────────────────────────────────────────────────────────
    def _resolutions(self) -> list[tuple[str, object]]:
        seen: dict[tuple[int, int], bool] = {}
        for mode in self.disp.modes:
            key = (mode.width, mode.height)
            if key not in seen:
                seen[key] = self.disp.is_upscaled(mode)
        items = []
        for (w, h), upscaled in sorted(seen.items(), key=lambda kv: kv[0][0] * kv[0][1],
                                       reverse=True):
            suffix = ""
            if self.disp.native and (w, h) == tuple(self.disp.native):
                suffix = "   nativa"
            elif upscaled:
                suffix = "   escalonada"
            items.append((f"{w} x {h}{suffix}", (w, h)))
        return items

    def _fill_rates(self) -> None:
        key = self.res_box.currentData()
        self.hz_box.clear()
        if not key:
            return
        rates = sorted({m.refresh for m in self.disp.modes
                        if (m.width, m.height) == key}, reverse=True)
        for hz in rates:
            self.hz_box.addItem(f"{hz} Hz", hz)

    def _selected(self) -> D.Mode | None:
        size = self.res_box.currentData()
        hz = self.hz_box.currentData()
        if not size or not hz:
            return None
        return D.Mode(size[0], size[1], hz)

    def _sync_state(self) -> None:
        if self.disp.primary:
            self.badge.update_badge("PRIMÁRIA", theme.RAM)
        elif self.disp.active:
            self.badge.update_badge("ligada", theme.OK)
        else:
            self.badge.update_badge("desligada", theme.FAINT)
        self.btn_power.setText("Desligar" if self.disp.active else "Ligar")
        self.btn_power.set_color(theme.BAD if self.disp.active else theme.OK)
        self.btn_primary.setVisible(self.disp.active and not self.disp.primary)
        self.btn_apply.setVisible(self.disp.active)
        self.res_box.setEnabled(self.disp.active)
        self.hz_box.setEnabled(self.disp.active)

        if self.disp.active and self.disp.mode:
            idx = self.res_box.findData((self.disp.mode.width, self.disp.mode.height))
            if idx >= 0 and idx != self.res_box.currentIndex():
                self.res_box.setCurrentIndex(idx)
                self._fill_rates()
            idx = self.hz_box.findData(self.disp.mode.refresh)
            if idx >= 0:
                self.hz_box.setCurrentIndex(idx)

    # ── acoes ────────────────────────────────────────────────────────────────
    def _apply_mode(self) -> None:
        mode = self._selected()
        if mode is None:
            return
        previous = self.disp.mode
        ok, err = D.set_mode(self.disp.device, mode)
        if not ok:
            self.view.notify(f"{self.disp.name}: {err}", theme.BAD)
            return
        self.view.confirm_or_revert(self.disp.device, previous,
                                    f"{self.disp.name} em {mode.label}")

    def _make_primary(self) -> None:
        ok, err = D.set_primary(self.disp.device)
        self.view.notify(f"{self.disp.name} agora é a primária" if ok
                         else f"{self.disp.name}: {err}", theme.OK if ok else theme.BAD)
        self.view.reload()

    def _toggle_power(self) -> None:
        target = not self.disp.active
        ok, err = D.set_enabled(self.disp.device, target)
        if not ok:
            self.view.notify(f"{self.disp.name}: {err}", theme.BAD)
        else:
            self.view.notify(f"{self.disp.name} {'ligada' if target else 'desligada'}",
                             theme.OK)
        self.view.reload()


class DisplaysView(View):
    key = "displays"
    title = "Telas"
    glyph = "▣"
    subtitle = "monitores, modos e perfis"

    def __init__(self, app) -> None:
        super().__init__(app)
        self._cards: list[_DisplayCard] = []
        self._pending_revert: QTimer | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.scaled(theme.GAP))

        self.kpi = KpiStrip(_KPIS, columns=5)
        root.addWidget(self.kpi)

        self.status = label("", 9, color=theme.MUTE)
        self.status.setVisible(False)
        root.addWidget(self.status)

        page, self.lay = scroll_page()
        root.addWidget(page, 1)

        self.cards_holder = QWidget()
        self.cards_lay = QVBoxLayout(self.cards_holder)
        self.cards_lay.setContentsMargins(0, 0, 0, 0)
        self.cards_lay.setSpacing(theme.scaled(theme.GAP))
        self.lay.addWidget(self.cards_holder)

        self.lay.addWidget(self._build_topology())
        self.lay.addWidget(self._build_profiles())
        self.lay.addStretch(0)

        self.reload()

    # ── perfis ───────────────────────────────────────────────────────────────
    def _build_profiles(self) -> Card:
        card = Card("Perfis", theme.DISK, "guarda quais telas ficam ligadas e em que modo")
        self.profiles_box = QVBoxLayout()
        self.profiles_box.setSpacing(theme.scaled(6))
        card.add_layout(self.profiles_box)
        card.add(divider())

        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("nome do perfil, ex: Jogo na TV")
        btn = PillButton("Salvar estado atual", theme.DISK, filled=True)
        btn.clicked.connect(self._save_profile)
        seed = PillButton("Recriar prontos", theme.MUTE)
        seed.clicked.connect(self._seed_profiles)
        row.addWidget(self.profile_name, 1)
        row.addWidget(btn)
        row.addWidget(seed)
        card.add_layout(row)
        return card

    def _build_topology(self) -> Card:
        card = Card("Modos rápidos", theme.CPU, "o mesmo que o Win+P faz")
        row = QHBoxLayout()
        row.setSpacing(theme.scaled(8))
        for text, mode, color in (("Estender", "extend", theme.OK),
                                  ("Clonar", "clone", theme.FPS),
                                  ("Só a principal", "internal", theme.MUTE),
                                  ("Só as externas", "external", theme.MUTE)):
            btn = PillButton(text, color)
            btn.clicked.connect(lambda m=mode, t=text: self._topology(m, t))
            row.addWidget(btn)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _topology(self, mode: str, label_text: str) -> None:
        ok, err = ccd.set_topology_mode(mode)
        self.notify(f"{label_text} aplicado" if ok else f"{label_text}: {err}",
                    theme.OK if ok else theme.BAD)
        self.reload()

    def _seed_profiles(self) -> None:
        seeded = D.suggested_profiles()
        if not seeded:
            self.notify("nenhuma tela encontrada para montar perfis", theme.WARN)
            return
        existing = {p["name"] for p in self.cfg.display_profiles}
        novos = [p for p in seeded if p["name"] not in existing]
        self.cfg.display_profiles = self.cfg.display_profiles + novos
        self.cfg.save()
        self._refresh_profiles()
        self.notify(f"{len(novos)} perfil(is) criado(s)" if novos
                    else "os perfis prontos já existem", theme.OK)

    def _refresh_profiles(self) -> None:
        while self.profiles_box.count():
            item = self.profiles_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                _clear_layout(item.layout())
        profiles = self.cfg.display_profiles
        if not profiles:
            self.profiles_box.addWidget(
                label("nenhum perfil salvo ainda", 9, color=theme.FAINT))
            return
        for index, profile in enumerate(profiles):
            row = QHBoxLayout()
            row.setSpacing(theme.scaled(8))
            ligadas = [e for e in profile["entries"] if e.get("active")]
            resumo = ", ".join(e.get("name") or e.get("device", "") for e in ligadas)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(profile["name"], 10, color=theme.TXT))
            col.addWidget(label(resumo, 8, color=theme.FAINT))
            row.addLayout(col, 1)
            apply_btn = PillButton("Aplicar", theme.OK, filled=True)
            apply_btn.clicked.connect(lambda i=index: self._apply_profile(i))
            del_btn = PillButton("Excluir", theme.BAD)
            del_btn.clicked.connect(lambda i=index: self._delete_profile(i))
            row.addWidget(apply_btn)
            row.addWidget(del_btn)
            self.profiles_box.addLayout(row)

    def _save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            self.notify("dê um nome ao perfil antes de salvar", theme.WARN)
            return
        entries = D.snapshot()
        profiles = [p for p in self.cfg.display_profiles if p["name"] != name]
        profiles.append({"name": name[:40], "hotkey": "", "entries": entries})
        self.cfg.display_profiles = profiles
        self.cfg.save()
        self.profile_name.clear()
        self._refresh_profiles()
        self.notify(f"perfil '{name}' salvo", theme.OK)

    def _apply_profile(self, index: int) -> None:
        try:
            profile = self.cfg.display_profiles[index]
        except IndexError:
            return
        ok, err = D.apply_profile(profile["entries"])
        self.notify(f"perfil '{profile['name']}' aplicado" if ok else err,
                    theme.OK if ok else theme.BAD)
        self.reload()

    def _delete_profile(self, index: int) -> None:
        try:
            removed = self.cfg.display_profiles.pop(index)
        except IndexError:
            return
        self.cfg.save()
        self._refresh_profiles()
        self.notify(f"perfil '{removed['name']}' excluído", theme.MUTE)

    # ── ciclo ────────────────────────────────────────────────────────────────
    def reload(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        found = D.list_displays()
        for disp in found:
            card = _DisplayCard(disp, self)
            self.cards_lay.addWidget(card)
            self._cards.append(card)

        active = [d for d in found if d.active]
        primary = next((d for d in found if d.primary), None)
        pixels = sum(d.mode.width * d.mode.height for d in active if d.mode)
        self.kpi.set("total", str(len(found)), theme.TXT)
        self.kpi.set("on", str(len(active)), theme.OK if active else theme.BAD)
        self.kpi.set("primary", primary.name.split(" ")[0] if primary else "—", theme.RAM)
        self.kpi.set("pixels", f"{pixels / 1_000_000:.1f}M", theme.FPS)

        # Primeira abertura ja' vem com perfis utilizaveis. Tela vazia com um
        # botao "salvar" nao ensina nada sobre o que a funcao faz.
        if not self.cfg.display_profiles:
            seeded = D.suggested_profiles()
            if seeded:
                self.cfg.display_profiles = seeded
                self.cfg.save()

        self._refresh_profiles()

    def on_activate(self) -> None:
        self.reload()

    def notify(self, text: str, color: str = theme.MUTE) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")
        self.status.setVisible(True)
        QTimer.singleShot(6000, lambda: self.status.setVisible(False))

    def confirm_or_revert(self, device: str, previous: D.Mode | None, description: str) -> None:
        """Volta sozinho ao modo anterior se ninguem confirmar a tempo.

        Modo invalido em TV costuma dar tela preta, e sem imagem nao ha' como
        clicar em nada. O relogio corre e desfaz por conta propria.
        """
        seconds = int(self.cfg.display_confirm_seconds or 0)
        self.reload()
        if seconds <= 0 or previous is None:
            self.notify(description, theme.OK)
            return

        remaining = {"n": seconds}
        timer = QTimer(self)
        self._pending_revert = timer

        def keep() -> None:
            timer.stop()
            self._pending_revert = None
            self.status.setVisible(False)
            self.notify(f"{description} mantido", theme.OK)

        def tick() -> None:
            remaining["n"] -= 1
            if remaining["n"] <= 0:
                timer.stop()
                self._pending_revert = None
                D.set_mode(device, previous)
                self.reload()
                self.notify("sem confirmação, voltei ao modo anterior", theme.WARN)
                return
            self.notify(f"{description}. Clique em Telas de novo para manter. "
                        f"Desfaço em {remaining['n']}s", theme.WARN)

        timer.timeout.connect(tick)
        timer.start(1000)
        self._keep_callback = keep


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())
