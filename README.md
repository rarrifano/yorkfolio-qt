<p align="center"><img src="yorkfolio_desktop/logo.svg" width="96" alt="YorkFolio"></p>

<h1 align="center">YorkFolio Desktop</h1>

<p align="center">A desktop, holder-style portfolio tracker for B3 investors.<br>
<b>C++ core</b> · <b>Python</b> · <b>Qt (PySide6)</b> · Flatpak</p>

Desktop edition of [YorkFolio](../yorkfolio): the same B3 import, preço médio, returns vs CDI/Ibovespa,
proventos, balanceamento/aporte and IR (DARF, Bens e Direitos), but as a native app with no server,
no login and no browser. Data stays in a local SQLite file. UI in Brazilian Portuguese.

## Architecture

| Layer | Where | What |
| --- | --- | --- |
| **C++20 core** | `core/` | weighted-average-cost position book, monthly IR apuração/DARF, water-filling aporte planner. C ABI (`capi.h`), JSON in/out, [nlohmann/json](https://github.com/nlohmann/json) vendored |
| **Python** | `yorkfolio_desktop/` | B3 .xlsx parsing, ledger building, valuation, history/returns, market data (Yahoo, BCB, Tesouro), SQLite, annual IR report |
| **Qt UI** | `yorkfolio_desktop/ui/` | PySide6 widgets, QPainter charts, background workers |

Python loads the core through `ctypes` (`native.py`), so no Python headers, pybind11 or CMake are needed:
just a C++20 compiler and `make`. The original pure-Python engine is kept in `tests/reference/` and
`tests/test_parity.py` checks the C++ core against it on randomized ledgers.

## Run from source

```bash
make venv     # .venv with PySide6
make core     # builds yorkfolio_desktop/libyorkfolio_core.so (g++ or clang++ with C++20)
make run
```

Try it with synthetic data: `python -m yorkfolio_desktop.demo /tmp/demo.db && .venv/bin/python -m yorkfolio_desktop --db /tmp/demo.db`.

Importing: [investidor.b3.com.br](https://www.investidor.b3.com.br) → Extratos → *Movimentação* and
*Negociação* → Excel. Use **Importar B3…** (Ctrl+O) or drag the files onto the window. Re-importing is safe.
`F5` refreshes quotes. The database lives in `$YORKFOLIO_DATA`, or `~/.local/share/yorkfolio-desktop/portfolio.db`
(`~/.var/app/io.github.rarrifano.YorkFolioDesktop/data/…` in the Flatpak); `--db PATH` overrides it.

## KDE integration

Targets Plasma first: no custom style sheet or palette, so Breeze (or whatever style you use) draws every
widget and the app follows the system color scheme live (*Exibir → Tema de cores* can force light/dark).
Standard menu bar (Arquivo/Exibir/Ajuda), freedesktop theme icons, standard shortcuts (Ctrl+O, F5, Ctrl+Q,
Ctrl+1…6 for tabs), file dialogs through the desktop portal, remembered window geometry, and the desktop-file
name set so Wayland shows the right icon and groups windows in the task manager. Gain/loss colors use Breeze's
positive/negative tones; charts take their colors from the active palette.

## Flatpak

```bash
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.flatpak.Builder org.kde.Sdk//6.10 io.qt.PySide.BaseApp//6.10
make flatpak            # -> io.github.rarrifano.YorkFolioDesktop.flatpak
make flatpak-install    # installs it for your user
flatpak run io.github.rarrifano.YorkFolioDesktop
```

Built on `org.kde.Platform//6.10` + `io.qt.PySide.BaseApp`. Permissions: Wayland/X11, GPU, network
(quotes). No filesystem access: files are picked through the portal.

## Tests

```bash
make test-core   # C++ unit tests (no dependencies)
make test-py     # parity with the reference engine, logic ports, headless UI smoke tests
make test
```

## Notes

- A decision-support tool, not tax advice: double-check IR figures. See the web edition's README for how
  numbers are computed (trade matching, day trade, preço médio, Modified Dietz, IR rules).
- Not done: Windows/macOS packaging (the loader already handles `.dll`/`.dylib`), IR on gains abroad and crypto.

## License

[MIT](LICENSE)
