# syntax=docker/dockerfile:1
# Interactsh OOB collaborator (W3/PR3.1). Sits on osa-oob-net ONLY;
# NEVER reaches docker-socket-proxy (MF6 isolation invariant).
ARG OSA_INTERACTSH_DIGEST=sha256:0000000000000000000000000000000000000000000000000000000000000000
FROM projectdiscovery/interactsh-server@${OSA_INTERACTSH_DIGEST} AS base
EXPOSE 53/udp 53/tcp 80 443 8443
ENTRYPOINT ["interactsh-server", "-listen-addr", "0.0.0.0", "-debug"]
