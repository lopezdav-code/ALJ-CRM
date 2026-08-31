import sys
import os
import threading
import socket

# S'assurer que le répertoire src est dans le chemin d'import
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from PySide6.QtWidgets import QApplication
from presentation.main_window import MainWindow

def find_free_port(start_port=8000, max_port=8099):
    """Trouve un port local disponible en testant dynamiquement l'occupation."""
    for port in range(start_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                # Tenter de lier le port. Si succès, le port est libre.
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return 8000 # Fallback par défaut

def start_backend_server(port):
    """Démarre le serveur FastAPI local (server.py) dans un thread en arrière-plan."""
    try:
        import uvicorn
        from server import fastapi_app_imported
    except ImportError:
        # Essayer d'importer l'application FastAPI depuis server.py
        try:
            from server import app as fastapi_app_imported
        except Exception as e:
            print(f"⚠️ [SYSTEM] Erreur lors de l'import du serveur FastAPI : {e}")
            return
    
    try:
        import uvicorn
        print(f"🌐 [SYSTEM] Démarrage du serveur API local (FastAPI) sur http://127.0.0.1:{port}...")
        # Lancer uvicorn sans reload pour que cela tourne de manière stable dans un thread
        uvicorn.run(fastapi_app_imported, host="127.0.0.1", port=port, log_level="warning")
    except Exception as e:
        print(f"⚠️ [SYSTEM] Impossible de démarrer le serveur API local : {e}")

def main():
    # Phase 10 - Logging structure : stdout -> INFO, stderr -> ERROR,
    # fichier rotatif app_activity.log (historique conserve) + console.
    from logger import PrintToLogInterceptor
    sys.stdout = PrintToLogInterceptor(level=20)   # logging.INFO
    sys.stderr = PrintToLogInterceptor(level=40)   # logging.ERROR

    # 1. Trouver un port reseau disponible
    port = find_free_port()
    # 2. Stocker le port dans l'environnement pour que l'IHM puisse construire le bon lien URL
    os.environ["FASTAPI_PORT"] = str(port)

    # 3. Lancer le serveur FastAPI en tache de fond (daemon=True) sur le port trouve
    server_thread = threading.Thread(target=start_backend_server, args=(port,), daemon=True)
    server_thread.start()

    import datetime
    print("\n================================================================================")
    print("🎬 [STARTUP] ALJ ESCALADE MANAGER - DEMARRAGE DE L'APPLICATION (PySide6)")
    print("================================================================================")
    print(f"📂 Repertoire : {os.getcwd()}")
    print(f"💻 Systeme   : {sys.platform}")
    print(f"⏳ Lancement : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🚀 Initialisation et chargement de l'interface graphique (IHM)...")

    app = QApplication(sys.argv)

    # Appliquer une police systeme propre par defaut
    font = app.font()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow()
    window.showMaximized()
    print("✅ [SYSTEM] Interface graphique affichee avec succes et prete.")

    exit_code = app.exec()

    # Fermeture propre : l'historique d'activite est conserve (fichier rotatif).
    import logging
    logging.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
