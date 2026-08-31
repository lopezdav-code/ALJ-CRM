import datetime
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QFont

class RegistrationChartWidget(QWidget):
    """
    Graphique vectoriel dessiné nativement via QPainter (sans dépendance externe).
    Affiche les inscriptions par semaine (en barres vertes) et le total cumulé (courbe orange).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.weekly_data = []  # Liste de tuples (semaine_str, inscrits_semaine, total_cumule)
        self.setMinimumHeight(240)
        self.setStyleSheet("background-color: #FFFFFF;")

    def set_data(self, weekly_data):
        """Met à jour les données et force le rafraîchissement graphique."""
        self.weekly_data = weekly_data
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Dimensions du widget
        w = self.width()
        h = self.height()

        # Marges pour les axes et légendes
        margin_left = 50
        margin_right = 50
        margin_top = 30
        margin_bottom = 40

        chart_w = w - margin_left - margin_right
        chart_h = h - margin_top - margin_bottom

        # Fond blanc pur de la zone de graphique
        painter.fillRect(0, 0, w, h, QBrush(QColor("#FFFFFF")))

        if not self.weekly_data:
            # Message si aucune donnée
            painter.setPen(QColor("#64748B"))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(self.rect(), Qt.AlignCenter, "Aucune donnée chronologique disponible.")
            return

        # Calculer les valeurs maximales pour l'échelle des deux axes Y
        max_weekly = max(item[1] for item in self.weekly_data) if self.weekly_data else 1
        max_cumulative = max(item[2] for item in self.weekly_data) if self.weekly_data else 1

        # Assurer des minimums décents pour l'échelle
        if max_weekly < 5: max_weekly = 5
        if max_cumulative < 10: max_cumulative = 10

        num_points = len(self.weekly_data)
        col_w = chart_w / max(num_points, 1)

        # ----------------------------------------------------
        # DESSINER LE QUADRILLAGE ET LES AXES Y
        # ----------------------------------------------------
        grid_pen = QPen(QColor("#F1F5F9"), 1, Qt.DashLine)
        axis_pen = QPen(QColor("#CBD5E1"), 1)
        text_font = QFont("Segoe UI", 8)
        painter.setFont(text_font)

        # Dessiner 4 lignes horizontales de repère
        for i in range(5):
            ratio = i / 4.0
            y = margin_top + chart_h - (ratio * chart_h)
            
            # Grille horizontale
            painter.setPen(grid_pen)
            painter.drawLine(margin_left, y, margin_left + chart_w, y)
            
            # Échelle Axe Y Gauche (Inscriptions hebdomadaires)
            val_weekly = int(ratio * max_weekly)
            painter.setPen(QColor("#475569"))
            painter.drawText(5, y + 4, f"{val_weekly}")

            # Échelle Axe Y Droit (Total cumulé)
            val_cumulative = int(ratio * max_cumulative)
            painter.setPen(QColor("#EA580C"))
            painter.drawText(w - margin_right + 8, y + 4, f"{val_cumulative}")

        # Ligne de l'axe X de base
        painter.setPen(axis_pen)
        painter.drawLine(margin_left, margin_top + chart_h, margin_left + chart_w, margin_top + chart_h)

        # ----------------------------------------------------
        # DESSINER LES BARRES (Nombre d'inscrits par semaine)
        # ----------------------------------------------------
        bar_brush = QBrush(QColor("#10B981"))  # Vert ALJ
        for idx, (week_label, count, _) in enumerate(self.weekly_data):
            x = margin_left + (idx * col_w) + (col_w * 0.15)
            bar_width = col_w * 0.7
            
            ratio_h = count / max_weekly
            bar_height = ratio_h * chart_h
            y = margin_top + chart_h - bar_height
            
            # Dessiner la barre
            painter.fillRect(x, y, bar_width, bar_height, bar_brush)

            # Dessiner le label de semaine sur l'axe X (toutes les 1 ou 2 semaines si trop denses)
            if num_points < 10 or idx % 2 == 0:
                painter.setPen(QColor("#64748B"))
                painter.drawText(x - 5, margin_top + chart_h + 18, f"S{week_label}")

        # ----------------------------------------------------
        # DESSINER LA COURBE CUMULÉE (Ligne orange épaisse)
        # ----------------------------------------------------
        curve_pen = QPen(QColor("#EA580C"), 2.5, Qt.SolidLine)
        curve_brush = QBrush(QColor("#FFFFFF"))
        painter.setPen(curve_pen)

        points = []
        for idx, (_, _, cumulative) in enumerate(self.weekly_data):
            x = margin_left + (idx * col_w) + (col_w / 2.0)
            ratio_h = cumulative / max_cumulative
            y = margin_top + chart_h - (ratio_h * chart_h)
            points.append(QPointF(x, y))

        # Relier les points de la courbe
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i+1])

        # Dessiner des ronds blancs cerclés d'orange sur chaque point cumulé
        painter.setPen(curve_pen)
        for pt in points:
            painter.setBrush(curve_brush)
            painter.drawEllipse(pt, 4, 4)
            
        # ----------------------------------------------------
        # DESSINER LA LÉGENDE DU GRAPHIQUE
        # ----------------------------------------------------
        legend_font = QFont("Segoe UI", 8, QFont.Bold)
        painter.setFont(legend_font)

        # Carré Vert pour "Inscriptions"
        painter.fillRect(margin_left + 10, 5, 12, 12, QBrush(QColor("#10B981")))
        painter.setPen(QColor("#1E293B"))
        painter.drawText(margin_left + 28, 15, "Inscriptions de la semaine (barres)")

        # Ligne Orange pour "Cumulé"
        painter.setPen(QPen(QColor("#EA580C"), 2.5))
        painter.drawLine(margin_left + 230, 11, margin_left + 250, 11)
        painter.setPen(QColor("#1E293B"))
        painter.drawText(margin_left + 258, 15, "Progression cumulée (courbe)")
