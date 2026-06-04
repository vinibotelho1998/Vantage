# DBX Stats

Monitor de sistema premium para Windows: um **painel completo** estilo HWMonitor e um **overlay in-game** estilo RivaTuner (RTSS), no mesmo app.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)
![UI](https://img.shields.io/badge/UI-PySide6-41CD52)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/images/panel.png" height="440" alt="Painel DBX Stats">
  &nbsp;&nbsp;&nbsp;
  <img src="docs/images/overlay.png" alt="Overlay in-game" valign="top">
</p>

## Recursos

- **Painel dock** com relógio, CPU, memória, GPU, disco e rede em tempo real, com barras animadas e mini-gráficos (sparklines).
- **Overlay in-game** click-through, sempre no topo: FPS, 1% e 0.1% low, frametime, temperaturas e ping — leve e discreto.
- **Sensores reais** via LibreHardwareMonitor: temperatura, potência (W) e RPM de CPU/GPU/placa, temperatura de NVMe.
- **FPS por jogo** via PresentMon (render ou display), com seleção automática da janela ativa.
- **GPU**: NVIDIA por NVML (com nvidia-smi e estimativa como fallback de potência); AMD/Intel via LHM.
- Estatísticas **mín / méd / máx** por métrica, tema escuro com cor de destaque configurável, multi-monitor e suporte a tela de alta densidade (DPI).

## Requisitos

- Windows 10/11 x64
- [.NET Desktop Runtime](https://dotnet.microsoft.com/download) 6 e 8 (para o LibreHardwareMonitor)
- Visual C++ Redistributable x64
- Executar como administrador para ler temperatura/potência da CPU

O instalador cuida das dependências de runtime automaticamente.

## Uso

Abra o app e o painel aparece num canto da tela.

- **Clique direito** no painel: Configurações, FPS, Estatísticas, Sempre no topo, **Modo Jogo** (liga/desliga o overlay) e Fechar.
- **Arraste** o painel para reposicionar (ou trave a posição nas configurações).
- **Ícone na bandeja**: mostrar/ocultar o painel, abrir configurações, fechar.
- O nome do jogo no painel abre um seletor para fixar qual processo monitorar.

## Desenvolvimento

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

.\.venv\Scripts\pythonw.exe -m dbxstats     # executa o app
.\.venv\Scripts\python.exe scripts\check_env.py   # valida a stack
.\.venv\Scripts\python.exe -m pytest         # testes
.\.venv\Scripts\python.exe -m ruff check src # lint
```

## Arquitetura

A engine de sensores é independente da interface e testável sem display.

```
src/dbxstats/
├── __main__.py          ponto de entrada (eleva admin, sobe engine + UI)
├── app.py               orquestracao: timers, janelas, ciclo de vida
├── config.py            Settings tipado, persistido em %APPDATA%/DBX Stats
├── theme.py             design tokens e cores
├── paths.py · log.py · stats.py
├── platform/
│   ├── win.py           win32: admin, fullscreen multi-monitor, click-through
│   └── autostart.py     inicializacao com o Windows
├── sensors/
│   ├── lhm.py           LibreHardwareMonitor (pythonnet/.NET)
│   ├── gpu.py           NVML + nvidia-smi + estimativa
│   ├── fps.py           PresentMon via named pipe (1%/0.1% low)
│   ├── net.py           ping / perda configuravel
│   └── collector.py     snapshot unificado por ciclo
└── ui/                  main_panel · overlay · settings · tray · widgets · fps_graph · style
```

## Build

```powershell
.\.venv\Scripts\python.exe -m PyInstaller packaging\DBXStats.spec --noconfirm
# instalador (requer Inno Setup 6):
powershell -File packaging\prepare_prereqs.ps1
ISCC packaging\DBXStats_Setup.iss
```

## Tecnologias

[PySide6](https://doc.qt.io/qtforpython/) · [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) · [PresentMon](https://github.com/GameTechDev/PresentMon) · [psutil](https://github.com/giampaolo/psutil) · [pynvml](https://github.com/NVIDIA/nvidia-ml-py) · [pythonnet](https://github.com/pythonnet/pythonnet)

## Licença

[MIT](LICENSE).
