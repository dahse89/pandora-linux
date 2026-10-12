FROM registry.fedoraproject.org/fedora:44@sha256:1660054c93ea9c99c39cfcfbd7240f8020219f31bf5d43f35bc17972d557896e

RUN dnf install --assumeyes --setopt=install_weak_deps=False --setopt=gpgcheck=True \
        lorax xorriso isomd5sum pykickstart ShellCheck make python3 curl \
        gnupg2 mtools dnf5 dnf5-plugins sudo shadow-utils util-linux-core \
        qt6-qtdeclarative-devel \
    && dnf clean all

ARG BUILD_UID=1000
ARG BUILD_GID=1000
RUN test "$BUILD_UID" -gt 0 && test "$BUILD_GID" -gt 0 \
    && (getent group "$BUILD_GID" || groupadd --gid "$BUILD_GID" builder) \
    && useradd --create-home --uid "$BUILD_UID" --gid "$BUILD_GID" builder \
    && printf 'builder ALL=(root) NOPASSWD: /usr/bin/mkksiso, /usr/bin/chown\n' \
        > /etc/sudoers.d/pandora-build \
    && chmod 0440 /etc/sudoers.d/pandora-build \
    && visudo --check --file=/etc/sudoers.d/pandora-build

ENV HOME=/home/builder PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
USER builder
CMD ["make", "iso"]
