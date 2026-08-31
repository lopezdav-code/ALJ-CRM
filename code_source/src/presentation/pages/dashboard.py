from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QFrame

from domain.models import Member
from infrastructure.sqlite_repository import SqliteRepository

class DashboardPage(QWidget):
    """
    Page d'Accueil / Tableau de bord de l'application ALJ Escalade.
    Affiche des statistiques en temps réel basées sur les adhésions réelles.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.load_real_stats()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(25)

        # En-tête de la page
        header_label = QLabel("Tableau de Bord ALJ Escalade")
        header_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E293B;")
        layout.addWidget(header_label)

        # Grille de KPI
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(15)

        self.kpi_widgets = {}
        kpis = [
            ("Adhérents Actifs", "0", "#163A5F", "active"),
            ("En Attente", "0", "#D97706", "waiting"),
            ("Total Encaissé", "0.00 €", "#16A34A", "amount"),
            ("Emails Envoyés", "0", "#2563EB", "emails")
        ]

        for title, value, color, key in kpis:
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            card.setStyleSheet("""
                QFrame {
                    background-color: #FFFFFF;
                    border: 1px solid #E2E8F0;
                    border-radius: 8px;
                    padding: 15px;
                }
            """)
            card_layout = QVBoxLayout(card)
            
            title_lbl = QLabel(title)
            title_lbl.setStyleSheet("font-size: 13px; color: #64748B;")
            
            val_lbl = QLabel(value)
            val_lbl.setStyleSheet(f"font-size: 20px; font-weight: bold; color: {color}; margin-top: 5px;")
            
            card_layout.addWidget(title_lbl)
            card_layout.addWidget(val_lbl)
            stats_layout.addWidget(card)
            
            self.kpi_widgets[key] = val_lbl

        layout.addLayout(stats_layout)

        # Section d'activité récente
        activity_frame = QFrame()
        activity_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 20px;
            }
        """)
        activity_layout = QVBoxLayout(activity_frame)
        
        act_title = QLabel("Activité Récente")
        act_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #1E293B;")
        activity_layout.addWidget(act_title)
        
        self.act_desc = QLabel("Chargement des dernières activités...")
        self.act_desc.setStyleSheet("color: #64748B; margin-top: 10px; font-size: 13px;")
        activity_layout.addWidget(self.act_desc)
        
        layout.addWidget(activity_frame)
        layout.addStretch()

    def load_real_stats(self):
        """Calcule et affiche les statistiques réelles à partir de la base d'adhérents locale pour la saison active (2026-2027)."""
        try:
            raw_data = SqliteRepository.load_direct_data(season_filter="2026-2027")
            members = [Member.from_dict(row) for row in raw_data]
            
            active_count = len([m for m in members if m.status == "Validated" or m.status == "Terminé"])
            waiting_count = len([m for m in members if "attente" in m.tarif_name.lower() or "cours" in m.status.lower()])
            total_amount = sum([m.amount for m in members if m.status == "Validated" or m.status == "Terminé"])
            sent_emails = len([m for m in members if m.email_sent_date])

            # Mettre à jour les KPI
            self.kpi_widgets["active"].setText(str(active_count))
            self.kpi_widgets["waiting"].setText(str(waiting_count))
            self.kpi_widgets["amount"].setText(f"{total_amount:.2f} €")
            self.kpi_widgets["emails"].setText(str(sent_emails))

            self.act_desc.setText(
                f"✅ Base de données locale SQLite chargée.\n"
                f"📊 Statut : Base synchronisée localement avec {len(members)} membres d'escalade."
            )
        except Exception as e:
            self.act_desc.setText(f"❌ Erreur lors du chargement des statistiques : {e}")
