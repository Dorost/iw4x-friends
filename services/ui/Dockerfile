# Web UI + IW4x dedicated server under Wine, for Linux hosts (see docker-compose.yml)
FROM debian:bookworm-slim

# iw4x.exe is a 32-bit Windows program: wine32 from the i386 architecture.
# xvfb: the dedicated server opens a console window, which needs an X display.
RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends wine wine32 xvfb ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /bin/uv

# WINEDEBUG=-all: Wine's debug logging costs CPU on every call, turn it off.
# A 32-bit prefix is all iw4x.exe needs and starts faster than a 64-bit one.
ENV WINEPREFIX=/wine WINEARCH=win32 WINEDEBUG=-all \
    WINEDLLOVERRIDES="mscoree,mshtml,winemenubuilder.exe=" \
    UV_PYTHON_INSTALL_DIR=/opt/python DISPLAY=:99

# Build the prefix now so the first start is fast. No crash dialog: a crashed
# server should exit (and be restartable from the UI), not wait on an invisible window.
RUN wineboot -i \
 && wine reg add "HKCU\\Software\\Wine\\WineDbg" /v ShowCrashDialog /t REG_DWORD /d 0 /f \
 && wineserver -w

WORKDIR /app
COPY app.py index.html lobby.gsc ./
RUN uv sync --script app.py

CMD ["sh", "-c", "Xvfb :99 -nolisten tcp & exec uv run app.py"]
