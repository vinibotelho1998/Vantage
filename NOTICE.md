# Terceiros

O Vantage é distribuído sob a [licença MIT](LICENSE). Este arquivo lista o que ele
usa e redistribui de terceiros, cada um sob a própria licença.

## Versionado neste repositório

**LibreHardwareMonitor**, em `vendor/lhm/`, sob Mozilla Public License 2.0.
Os binários são redistribuídos sem modificação e só a biblioteca é usada, via
pythonnet. Detalhes em [`vendor/lhm/NOTICE.md`](vendor/lhm/NOTICE.md), licença em
`vendor/lhm/LICENSE` e avisos das dependências dele em
`vendor/lhm/THIRD-PARTY-NOTICES.txt`.

## Dependências

| Biblioteca | Licença | Para quê |
|---|---|---|
| PySide6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only | interface |
| pythonnet | MIT | ponte com o LibreHardwareMonitor |
| psutil | BSD-3-Clause | processos, disco e rede |
| pywin32 | PSF | APIs do Windows |
| WMI | MIT | consulta de hardware |
| nvidia-ml-py | BSD | sensores da GPU NVIDIA |
| Pillow | MIT-CMU | ícone e arte do instalador |

Lido dos metadados dos pacotes instalados, não de memória.

## Qt e PySide6

O PySide6 é usado aqui sob a **LGPL v3**. O Qt entra como biblioteca dinâmica, sem
modificação, e o instalador não impede que você o substitua por outra build
compatível. https://www.qt.io/licensing

## PresentMon

O motor de FPS lê o CSV do **PresentMon**, do projeto
[GameTechDev/PresentMon](https://github.com/GameTechDev/PresentMon) da Intel, sob
licença MIT.

Os binários `tools/presentmon.exe` e `tools/presentmon-1.10-backup.exe` são
redistribuídos sem modificação. Copyright (C) 2017-2024 Intel Corporation, licença
em [`tools/LICENSE.txt`](tools/LICENSE.txt) e detalhes em
[`tools/NOTICE.md`](tools/NOTICE.md). Quando o binário falta, o app baixa a release
oficial.
