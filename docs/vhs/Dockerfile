# Recording environment for the demo tapes in docs/.
#
# VHS needs ttyd and ffmpeg; the upstream image already carries both, plus the
# JetBrains Mono family the tapes ask for. All this layer adds is the Python
# side, pinned so a re-record years from now produces the same frames — and
# pinned to the same pandas major the README's example output was taken from,
# since pandas 3 reports text columns as `str` where pandas 2 said `object`.
FROM ghcr.io/charmbracelet/vhs:v0.11.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-venv \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/demo \
 && /opt/demo/bin/pip install --no-cache-dir "pandas==3.0.5"

# Ahead of /usr/bin, so the recorded `python demo.py` is this interpreter.
ENV PATH="/opt/demo/bin:$PATH"

# The repository is mounted at /vhs; profile the working tree, not an install.
ENV PYTHONPATH=/vhs/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /vhs
