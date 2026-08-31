import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, 
    QPushButton, QLabel, QCheckBox, QFrame
)
from PySide6.QtCore import QTimer, Qt
from paths import ROOT_DIR

class LogsPage(QWidget):
    """
    Page d'affichage des journaux d'activité (Logs) de l'application (Nouveau !).
    Permet de visualiser les flux stdout/stderr capturés dans app_activity.log en temps réel.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_file_path = os.path.join(ROOT_DIR, "app_activity.log")
        self.init_ui()
        
        # Timer pour rafraîchir automatiquement les logs toutes les 2 secondes
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_logs_auto)
        self.timer.start(2000)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(12)

        # En-tête
        header_layout = QHBoxLayout()
        title = QLabel("📋 Journaux d'activité de l'application (Logs)")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        # Barre d'actions
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(10)

        # Checkbox d'auto-refresh
        self.auto_refresh_cb = QCheckBox("Rafraîchir automatiquement (2s)")
        self.auto_refresh_cb.setChecked(True)
        self.auto_refresh_cb.setStyleSheet("""
            QCheckBox {
                color: #475569;
                font-size: 12px;
                font-weight: 500;
            }
        """)
        self.auto_refresh_cb.toggled.connect(self.toggle_timer)
        actions_bar.addWidget(self.auto_refresh_cb)

        # Checkbox pour bloquer le défilement automatique (pour faciliter la lecture)
        self.pin_to_bottom_cb = QCheckBox("Défilement automatique vers le bas")
        self.pin_to_bottom_cb.setChecked(True)
        self.pin_to_bottom_cb.setStyleSheet("""
            QCheckBox {
                color: #475569;
                font-size: 12px;
                font-weight: 500;
            }
        """)
        actions_bar.addWidget(self.pin_to_bottom_cb)

        actions_bar.addStretch()

        # Bouton Rafraîchir
        refresh_btn = QPushButton("🔄 Rafraîchir")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                color: #475569;
            }
            QPushButton:hover {
                background-color: #F8FAFC;
                border-color: #94A3B8;
            }
        """)
        refresh_btn.clicked.connect(self.load_logs_manual)
        actions_bar.addWidget(refresh_btn)

        # Bouton Copier dans le presse-papier (Nouveau !)
        copy_btn = QPushButton("📋 Copier")
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #F0FDF4;
                border: 1px solid #BBF7D0;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                color: #16A34A;
            }
            QPushButton:hover {
                background-color: #DCFCE7;
                border-color: #86EFAC;
            }
        """)
        copy_btn.clicked.connect(self.copy_logs_to_clipboard)
        actions_bar.addWidget(copy_btn)

        # Bouton Nettoyer
        clear_btn = QPushButton("🗑️ Effacer le fichier log")
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #FEF2F2;
                border: 1px solid #FCA5A5;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-weight: 500;
                color: #EF4444;
            }
            QPushButton:hover {
                background-color: #FEE2E2;
                border-color: #F87171;
            }
        """)
        clear_btn.clicked.connect(self.clear_log_file)
        actions_bar.addWidget(clear_btn)

        layout.addLayout(actions_bar)

        # Zone d'affichage des logs
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setPlaceholderText("Les journaux d'activité s'afficheront ici en temps réel...")
        self.log_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #38BDF8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        layout.addWidget(self.log_text_edit)

        # Premier chargement immédiat des logs
        self.load_logs()

    def toggle_timer(self, checked):
        if checked:
            self.timer.start(2000)
        else:
            self.timer.stop()

    def load_logs_auto(self):
        # N'actualise que si le widget est actif/visible à l'écran
        if self.isVisible():
            self.load_logs()

    def load_logs_manual(self):
        self.load_logs()

    def load_logs(self):
        if not os.path.exists(self.log_file_path):
            self.log_text_edit.setPlainText("ℹ️ Aucun journal d'activité 'app_activity.log' trouvé pour le moment.")
            return

        try:
            # Lire les logs de manière sécurisée en limitant la taille lue (ex: les 1500 dernières lignes)
            with open(self.log_file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            
            last_lines = lines[-1500:] if len(lines) > 1500 else lines
            log_content = "".join(last_lines)
            
            # Mettre à jour la zone de texte
            self.log_text_edit.setPlainText(log_content)
            
            # Faire défiler vers le bas si la case est cochée
            if self.pin_to_bottom_cb.isChecked():
                self.scroll_to_bottom()
        except Exception as e:
            self.log_text_edit.setPlainText(f"❌ Impossible de charger les logs : {e}")

    def scroll_to_bottom(self):
        scroll_bar = self.log_text_edit.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def copy_logs_to_clipboard(self):
        """Copie le texte des journaux affichés dans le presse-papier de l'utilisateur."""
        from PySide6.QtGui import QGuiApplication
        try:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(self.log_text_edit.toPlainText())
            
            # Message de confirmation rapide (boîte d'information)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, 
                "Copie réussie", 
                "Le journal d'activité a été copié avec succès dans votre presse-papier !"
            )
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Erreur", f"Impossible de copier les logs : {e}")

    def clear_log_file(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Effacer le journal d'activité",
            "Êtes-vous sûr de vouloir vider intégralement le fichier log 'app_activity.log' ?\nCette action est irréversible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with open(self.log_file_path, "w", encoding="utf-8") as f:
                    f.write(f"--- Journal d'activité réinitialisé par l'utilisateur ---\n")
                self.load_logs()
            except Exception as e:
                QMessageBox.warning(self, "Erreur", f"Impossible d'effacer le fichier log : {e}")
