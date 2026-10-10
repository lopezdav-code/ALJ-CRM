# Émulateur Firebase (Auth + Firestore) pour le développement local — voir dev/README.md
# firebase-tools 15 exige Node >= 20 et Java >= 21 (Debian trixie).
FROM node:22-trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g firebase-tools@15.31.0 \
    && npm cache clean --force \
    && mkdir -p /workspace /persist && chown node:node /workspace /persist

# Utilisateur non-root (uid 1000) : les données exportées dans dev/.emulator-data
# restent modifiables par le développeur sur l'hôte.
USER node
WORKDIR /workspace
# Pré-téléchargement des JAR des émulateurs dans l'image (démarrage hors ligne et rapide)
RUN firebase setup:emulators:firestore && firebase setup:emulators:ui

EXPOSE 4000 8081 9099 9150
# export/ : firebase-tools recrée le dossier cible, impossible sur le point de montage /persist
CMD ["firebase", "emulators:start", "--project", "demo-alj", "--only", "auth,firestore", \
     "--import=/persist/export", "--export-on-exit=/persist/export"]
