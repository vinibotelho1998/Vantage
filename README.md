# DBX Stats

Monitor de hardware e desempenho em jogos para Windows. Um app de verdade — feito
para ficar aberto no segundo monitor — com telas dedicadas de CPU, GPU, memória,
disco, rede, sensores e processos, além de uma engine de FPS/frametime nível
CapFrameX. O overlay in-game continua ali, mas agora é um acessório, não o produto.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)
![UI](https://img.shields.io/badge/UI-PySide6-41CD52)
![License](https://img.shields.io/badge/license-MIT-green)

<p align="center">
  <img src="docs/images/panel.png" alt="Painel do DBX Stats">
</p>

<p align="center">
  <img src="docs/images/gaming.png" alt="Tela de jogos com frametime, lows e gargalo">
</p>

## O que ele faz

**Captura de FPS que não desiste.** O motor roda em três camadas independentes —
supervisor, leitor e agregador. O leitor só faz parsing do CSV do PresentMon; toda
a estatística acontece fora do caminho crítico, 4× por segundo. Se a sessão ETW
cair, o jogo fechar o swapchain ou o driver reiniciar, o supervisor detecta e sobe
tudo de novo sozinho, com backoff. Um watchdog ainda vigia o jogo em foco: se ele
está em tela cheia e não sai nenhum frame em 20 s, a captura reinicia sem você
precisar fazer nada.

**Métricas que um entusiasta realmente usa:**

| Métrica | Como é calculada |
| --- | --- |
| FPS atual | média dos frametimes da última janela (0,5 / 1 / 2 s) — não é `1000/último frame`, então o número para de tremer |
| FPS médio | `1000 / média dos frametimes` da janela de análise |
| 1% e 0.1% low | média dos piores 1% / 0.1% frames — o mesmo critério usado em análises de hardware |
| P1 / P0.1 | percentis 99 e 99.9 do frametime, para comparar com ferramentas que usam percentil |
| Stutter | % de frames acima de 1,5× a mediana |
| Engasgos | frames acima de 50 ms ou 3× a mediana |
| Consistência | coeficiente de variação do frametime, normalizado em 0–100 |
| Fluidez | nota composta: consistência + distância do 1% low + penalidade por engasgo |
| Gargalo | compara `CPUBusy` e `GPUBusy` por frame: CPU, GPU, limitado por VSync/cap ou balanceado |
| Latência | render latency e clique → tela (click-to-photon), direto do PresentMon 2 |
| Quadros descartados | frames que nunca chegaram ao display |

**Gráficos que mostram o que aconteceu.** As linhas usam interpolação cúbica
monotona (Fritsch–Carlson): curva lisa que nunca inventa um pico que não existe
nos dados. Quando há mais amostras que pixels, cada coluna desenha a faixa entre
o mínimo e o máximo daquele intervalo — um spike de um frame continua visível com
5 minutos de histórico na tela. A escala vertical se ajusta com transição
amortecida, então o gráfico não pula a cada novo máximo. Passe o mouse para ler
os valores exatos de qualquer ponto.

**Telas:**

- **Painel** — visão geral: KPIs, linha do tempo multi-série, jogo em foco com
  frametime ao vivo e cards de CPU/GPU/RAM/disco/rede.
- **Jogos** — frametime em destaque, FPS ao longo do tempo, histograma de FPS,
  curva de percentis, entrega de quadros, latência, gargalo e estatísticas da sessão.
- **CPU** — uso e temperatura, frequência, potência, grade de núcleos com clock por
  thread, dados do processador e top processos.
- **GPU** — carga, VRAM, clocks, potência, PCIe, encoder/decoder e os motivos de
  throttle relatados pelo driver.
- **Memória & Disco** — RAM, cache, swap, atividade de I/O e um card por unidade
  com temperatura e vida útil.
- **Rede** — throughput, latência, jitter, perda e volume acumulado.
- **Sensores** — a árvore inteira do LibreHardwareMonitor com atual/mín/méd/máx e
  exportação para CSV.
- **Processos** — quem está comendo CPU e memória, com o jogo destacado.
- **Benchmark** — corrida cronometrada, resultado completo, comparação com corridas
  anteriores e exportação dos frametimes.

**Ainda:** overlay in-game click-through configurável, alertas de temperatura e
uso na bandeja, atalhos globais, tema com cor de destaque, escala de interface e
janela sem moldura com redimensionamento e snap nativos do Windows.

<p align="center">
  <img src="docs/images/overlay.png" alt="Overlay in-game" height="170">
  &nbsp;&nbsp;&nbsp;
  <img src="docs/images/settings.png" alt="Configurações" height="170">
</p>

## Atalhos

| Atalho | Ação |
| --- | --- |
| `Ctrl+Alt+R` | zera as estatísticas da sessão |
| `Ctrl+Alt+O` | liga/desliga o overlay |
| `Ctrl+Alt+B` | inicia/para o benchmark |

## Requisitos

- Windows 10/11 x64
- [.NET Desktop Runtime](https://dotnet.microsoft.com/download) 6 e 8 (LibreHardwareMonitor)
- Visual C++ Redistributable x64
- Executar como administrador (sensores de CPU/placa e captura de FPS)

O instalador cuida das dependências de runtime automaticamente.

## Desenvolvimento

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

.\.venv\Scripts\pythonw.exe -m dbxstats            # executa o app
.\.venv\Scripts\python.exe -m pytest               # testes
.\.venv\Scripts\python.exe -m ruff check src tests # lint
.\.venv\Scripts\python.exe scripts\check_env.py    # valida a stack
.\.venv\Scripts\python.exe scripts\smoke_ui.py     # monta e pinta todas as telas
.\.venv\Scripts\python.exe scripts\smoke_fps.py    # motor de FPS contra o PresentMon real
.\.venv\Scripts\python.exe scripts\preview.py      # regenera as imagens do README
```

## Arquitetura

A engine é independente da interface e testável sem display. As views são burras:
recebem um snapshot pronto e desenham — e só a tela visível é atualizada, então
manter o app aberto custa quase nada.

```
src/dbxstats/
├── __main__.py          entrada (eleva admin, sobe engine + UI)
├── app.py               controlador: timers, seleção do jogo, alertas, benchmark
├── config.py            Settings tipado e validado, em %APPDATA%/DBX Stats
├── theme.py             design tokens: paleta, tipografia, escalas de cor
├── core/
│   ├── frames.py        métricas de frame (lows, percentis, stutter, gargalo)
│   ├── series.py        séries temporais, acumulador mín/méd/máx, EMA
│   ├── units.py         formatação de grandezas
│   └── export.py        relatórios CSV
├── sensors/
│   ├── fps.py           PresentMon 2: supervisor + leitor + agregador
│   ├── lhm.py           LibreHardwareMonitor (curado + árvore completa)
│   ├── gpu.py           NVML: clocks, VRAM, PCIe, throttle, potência
│   ├── collector.py     snapshot unificado por ciclo
│   ├── procs.py         monitor de processos
│   └── net.py           latência, jitter e perda
├── platform/            win32: admin, fullscreen, click-through, hotkeys
└── ui/
    ├── main_window.py   chrome próprio, barra lateral, pilha de telas
    ├── charts.py        linhas suaves, envelope mín/máx, gauges, histograma
    ├── components.py    cards, tiles, linhas de métrica, badges
    ├── views/           dashboard · gaming · cpu · gpu · memory · network ·
    │                    sensors · processes · benchmark
    ├── overlay.py       overlay in-game
    ├── settings.py      configurações por abas
    └── tray.py          bandeja do sistema
```

## Build

```powershell
.\.venv\Scripts\python.exe -m PyInstaller packaging\DBXStats.spec --noconfirm
# instalador (requer Inno Setup 6):
powershell -File packaging\prepare_prereqs.ps1
ISCC packaging\DBXStats_Setup.iss
```

## Tecnologias

[PySide6](https://doc.qt.io/qtforpython/) · [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) · [PresentMon](https://github.com/GameTechDev/PresentMon) · [psutil](https://github.com/giampaolo/psutil) · [nvidia-ml-py](https://github.com/NVIDIA/nvidia-ml-py) · [pythonnet](https://github.com/pythonnet/pythonnet)

## Licença

[MIT](LICENSE).
