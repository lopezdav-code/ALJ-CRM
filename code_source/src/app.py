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
from paths import ROOT_DIR

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
    # Configurer le logging unifié dans app_activity.log
    import datetime
    log_file_path = os.path.join(ROOT_DIR, "app_activity.log")
    
    class LoggerRedirector(object):
        def __init__(self, original_stream, log_file, prefix="INFO"):
            self.original_stream = original_stream
            self.log_file = log_file
            self.prefix = prefix

        def write(self, str_val):
            # Écrire sur le flux console d'origine
            self.original_stream.write(str_val)
            self.original_stream.flush()
            # Écrire dans le fichier de log
            if str_val.strip():
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                try:
                    self.log_file.write(f"{now_str} [{self.prefix}] - {str_val.strip()}\n")
                    self.log_file.flush()
                except Exception:
                    pass

        def flush(self):
            self.original_stream.flush()
            try:
                self.log_file.flush()
            except Exception:
                pass

        def __getattr__(self, name):
            return getattr(self.original_stream, name)

    try:
        log_file = open(log_file_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = LoggerRedirector(sys.stdout, log_file, "INFO")
        sys.stderr = LoggerRedirector(sys.stderr, log_file, "ERROR")
    except Exception as e:
        print(f"⚠️ [SYSTEM] Impossible d'initialiser le fichier de log unifié : {e}")

    # 1. Trouver un port réseau disponible
    port = find_free_port()
    # 2. Stocker le port dans l'environnement pour que l'IHM puisse construire le bon lien URL
    os.environ["FASTAPI_PORT"] = str(port)

    # 3. Lancer le serveur FastAPI en tâche de fond (daemon=True) sur le port trouvé
    server_thread = threading.Thread(target=start_backend_server, args=(port,), daemon=True)
    server_thread.start()

    print("\n================================================================================")
    print("🎬 [STARTUP] ALJ ESCALADE MANAGER — DÉMARRAGE DE L'APPLICATION (PySide6)")
    print("================================================================================")
    print(f"📂 Répertoire : {os.getcwd()}")
    print(f"💻 Système   : {sys.platform}")
    print(f"⏳ Lancement : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🚀 Initialisation et chargement de l'interface graphique (IHM)...")
    
    app = QApplication(sys.argv)
    
    # Appliquer une police système propre par défaut
    font = app.font()
    font.setFamily("Segoe UI")
    font.setPointSize(10)
    app.setFont(font)
    
    window = MainWindow()
    window.showMaximized()
    print("✅ [SYSTEM] Interface graphique affichée avec succès et prête.")
    
    exit_code = app.exec()
    
    # Phase 7 — Fermeture propre : l'historique d'activité est conservé
    # (plus de truncate à chaque fermeture, qui faisait perdre tout historique).
    try:
        # Restaurer les flux standards d'origine
        if hasattr(sys.stdout, "original_stream") and sys.stdout.original_stream:
            sys.stdout = sys.stdout.original_stream
        if hasattr(sys.stderr, "original_stream") and sys.stderr.original_stream:
            sys.stderr = sys.stderr.original_stream
            
        # Fermer le fichier de log s'il est ouvert
        if 'log_file' in locals() and log_file and not log_file.closed:
            log_file.close()
    except Exception:
        pass
        
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
