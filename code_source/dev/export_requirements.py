"""Régénère (ou vérifie) les requirements*.txt à partir de uv.lock.

uv.lock est la source de vérité. Les requirements*.txt restent versionnés car le client
lourd les consomme avec pip (runtime Python embarqué du paquet portable, updater, install.bat).

    python dev/export_requirements.py            # réécrit les fichiers
    python dev/export_requirements.py --check    # échoue si un fichier est périmé (CI)
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # code_source/

# fichier -> arguments de `uv export` (la sortie est toujours sans hash : parité avec l'existant,
# pip passerait sinon en mode strict --require-hashes)
TARGETS = {
    "requirements.txt": ["--no-dev", "--group", "desktop"],
    "requirements-docker.txt": ["--no-dev", "--group", "web"],
    "requirements-dev.txt": ["--only-dev"],
}
COMMON = ["--frozen", "--no-hashes", "--no-emit-project"]


def export(extra_args):
    result = subprocess.run(
        ["uv", "export", *COMMON, *extra_args],
        cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8").replace("\r\n", "\n")


def significant(text):
    """Lignes hors commentaires : le bandeau et les « # via » varient selon la version de uv."""
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def main(argv):
    check = "--check" in argv
    stale = []
    for name, args in TARGETS.items():
        path = os.path.join(ROOT, name)
        expected = export(args)
        if check:
            current = ""
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    current = f.read().replace("\r\n", "\n")
            if significant(current) != significant(expected):
                stale.append(name)
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(expected)
            print(f"écrit : {name}")
    if stale:
        print("Fichiers périmés par rapport à uv.lock : " + ", ".join(stale), file=sys.stderr)
        print("Lancer : python dev/export_requirements.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
