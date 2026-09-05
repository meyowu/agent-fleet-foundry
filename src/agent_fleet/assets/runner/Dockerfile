FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS python_rootfs
ENV PIP_CONFIG_FILE=/dev/null
COPY requirements.lock /runner-requirements.lock
RUN ["python", "-I", "-m", "pip", "--isolated", "--disable-pip-version-check", "install", "--index-url", "https://pypi.org/simple", "--require-hashes", "--only-binary=:all:", "--no-cache-dir", "--no-compile", "-r", "/runner-requirements.lock"]

FROM scratch
COPY --from=python_rootfs / /
ENV PATH=/usr/local/bin:/usr/bin:/bin \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8
