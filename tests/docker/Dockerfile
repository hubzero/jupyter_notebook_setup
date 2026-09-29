# file: tests/docker/Dockerfile
#
# Stock Rocky Linux 10 plus exactly the host prerequisites listed at the top of jpkg.  The list is
# passed in by run-docker-test.sh, which reads it out of jpkg, so the image can't drift from what the
# comment tells people to install.  Octave comes from EPEL (with CRB), as the comment says, so the
# octave-kernel detection is tested against a real octave rather than a stand-in.
#
# The Docker Hub library image (rockylinux:N) stops at 9; Rocky 10 is published as
# rockylinux/rockylinux:10.

ARG BASE_IMAGE=rockylinux/rockylinux:10
FROM ${BASE_IMAGE}

ARG PREREQS
RUN test -n "${PREREQS}" \
    && dnf -y --setopt=install_weak_deps=False install ${PREREQS} \
    && dnf clean all \
    && rm -rf /var/cache/dnf

RUN dnf -y install epel-release \
    && crb enable \
    && dnf -y --setopt=install_weak_deps=False install octave \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# The launchers refuse to run as root, and `ps auxwwe` only shows the environment of the caller's own
# processes, so the tests run as an ordinary user the way hub users would.
RUN useradd --create-home --shell /bin/bash jupytest

ENTRYPOINT ["sleep", "infinity"]
