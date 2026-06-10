# Bundled fonts

Drop these files into this folder. The app registers every `*.ttf` / `*.otf`
here via QFontDatabase at startup and falls back to system fonts
(Bahnschrift/Segoe UI, Consolas) if a file is missing.

| Role | Family | Files to drop in |
|---|---|---|
| Display / key labels | Chakra Petch | `ChakraPetch-Regular.ttf`, `ChakraPetch-Medium.ttf` |
| Body / dialogs | IBM Plex Sans | `IBMPlexSans-Regular.ttf`, `IBMPlexSans-Medium.ttf` (or the variable `IBMPlexSans[wdth,wght].ttf`) |
| Data / mono / PIN | IBM Plex Mono | `IBMPlexMono-Regular.ttf`, `IBMPlexMono-Medium.ttf` |

## Download sources (open license)

All three families are licensed under the **SIL Open Font License 1.1**.

- Chakra Petch — <https://fonts.google.com/specimen/Chakra+Petch>
  (or <https://github.com/google/fonts/tree/main/ofl/chakrapetch>)
- IBM Plex Sans — <https://fonts.google.com/specimen/IBM+Plex+Sans>
  (or <https://github.com/IBM/plex/releases>)
- IBM Plex Mono — <https://fonts.google.com/specimen/IBM+Plex+Mono>
  (or <https://github.com/IBM/plex/releases>)

Keep each family's OFL.txt alongside the files if you redistribute a build.
