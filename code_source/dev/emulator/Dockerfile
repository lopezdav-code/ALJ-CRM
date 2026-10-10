# Firebase emulator (Auth + Firestore) for local development — see dev/README.md
# firebase-tools 15 requires Node >= 20 and Java >= 21 (Debian trixie).
FROM node:22-trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g firebase-tools@15.31.0 \
    && npm cache clean --force \
    && mkdir -p /workspace /persist && chown node:node /workspace /persist

# Non-root user (uid 1000): the data exported to dev/.emulator-data
# stays writable by the developer on the host.
USER node
WORKDIR /workspace
# Pre-download the emulator JARs into the image (fast, offline startup)
RUN firebase setup:emulators:firestore && firebase setup:emulators:ui

EXPOSE 4000 8081 9099 9150
# export/: firebase-tools recreates the target folder, which is impossible on the /persist mount point
CMD ["firebase", "emulators:start", "--project", "demo-alj", "--only", "auth,firestore", \
     "--import=/persist/export", "--export-on-exit=/persist/export"]
