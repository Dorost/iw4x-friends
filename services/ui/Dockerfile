# Web UI + IW4x dedicated server under Wine, for Linux hosts (see docker-compose.yml)
FROM debian:bookworm-slim

# WINEDEBUG=-all: Wine's debug logging costs CPU on every call, turn it off.
# A 32-bit prefix is all iw4x.exe needs and starts faster than a 64-bit one.
ENV WINEPREFIX=/wine WINEARCH=win32 WINEDEBUG=-all \
    WINEDLLOVERRIDES="mscoree,mshtml,winemenubuilder.exe=" \
    UV_PYTHON_INSTALL_DIR=/opt/python DISPLAY=:99

# iw4x.exe is a 32-bit Windows program: wine32 from the i386 architecture.
# xvfb: the dedicated server opens a console window, which needs an X display.
# Build the prefix now so the first start is fast. No crash dialog: a crashed
# server should exit (and be restartable from the UI), not wait on an invisible window.
# wineboot copies Wine's own DLLs into the prefix: in the same layer as Wine they become
# hard links to the originals, so the image (and every server's pull) holds them once.
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends wine wine32 xvfb ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && wineboot -i \
 && wine reg add "HKCU\\Software\\Wine\\WineDbg" /v ShowCrashDialog /t REG_DWORD /d 0 /f \
 && wineserver -w \
 && pe=/usr/lib/i386-linux-gnu/wine/i386-windows \
 && for f in "$WINEPREFIX"/drive_c/windows/system32/*; do \
      o="$pe/$(basename "$f")"; \
      if [ -f "$f" ] && [ -f "$o" ] && cmp -s "$f" "$o"; then ln -f "$o" "$f"; fi; \
    done \
 && n=$(find "$WINEPREFIX" -type f -links +1 | wc -l) && echo "$n hard links into $pe" && [ "$n" -gt 0 ]

COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /bin/uv

WORKDIR /app
# Python and the dependencies (135 MB) first: a change to only the pages or game
# scripts then rebuilds and pulls a few kB instead.
COPY app.py ./
RUN uv sync --script app.py
COPY index.html login.html tg.html lobby.gsc weapons.gsc players.gsc sdfun.gsc vote.gsc bots.txt ./

CMD ["sh", "-c", "Xvfb :99 -nolisten tcp & exec uv run app.py"]
