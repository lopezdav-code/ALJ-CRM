from PySide6.QtCharts import QChart, QChartView, QPieSeries, QPieSlice, QBarSeries, QBarSet, QBarCategoryAxis, QValueAxis
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt, QMargins
from PySide6.QtWidgets import QWidget, QVBoxLayout

class AgePieChartWidget(QWidget):
    """
    Graphique en camembert (Pie Chart) interactif Qt pour la répartition démographique des adhérents.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Création du graphique
        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.SeriesAnimations)
        self.chart.setTheme(QChart.ChartThemeLight)
        
        # Supprimer le fond et les marges par défaut de Qt pour s'intégrer harmonieusement
        self.chart.setBackgroundBrush(Qt.transparent)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        
        # Configuration de la police du titre
        font = QFont("Segoe UI", 10, QFont.Bold)
        self.chart.setTitleFont(font)
        self.chart.setTitleBrush(QColor("#1E293B"))
        self.chart.legend().setVisible(True)
        self.chart.legend().setAlignment(Qt.AlignBottom)
        self.chart.legend().setFont(QFont("Segoe UI", 8))

        # Viewport du graphique
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setStyleSheet("background: transparent;")
        
        layout.addWidget(self.chart_view)

    def set_data(self, age_groups: dict):
        """Peuple le camembert avec les tranches d'âges d'adhérents."""
        self.chart.removeAllSeries()
        
        series = QPieSeries()
        series.setHoleSize(0.35) # Crée un effet Donut moderne et élégant !

        # Définition d'un jeu de couleurs coordonnées (Palette ALJ Escalade + tons modernes)
        colors = [
            QColor("#2563EB"), # Bleu Action
            QColor("#10B981"), # Vert ALJ
            QColor("#F59E0B"), # Ambre
            QColor("#EF4444"), # Rouge Erreur
            QColor("#8B5CF6")  # Violet
        ]

        total = sum(age_groups.values())
        if total == 0:
            return

        for idx, (group_name, count) in enumerate(age_groups.items()):
            if count > 0:
                percentage = (count / total) * 100
                slice_label = f"{group_name} : {count} ({percentage:.1f}%)"
                slice_obj = QPieSlice(slice_label, count)
                
                # Appliquer la couleur correspondante de notre palette
                color_idx = idx % len(colors)
                slice_obj.setBrush(colors[color_idx])
                slice_obj.setPen(QColor("#FFFFFF")) # Bordure blanche élégante
                
                # Effets de survol interactifs
                def on_hovered(state, sl=slice_obj):
                    sl.setExploded(state)
                    sl.setLabelVisible(state)
                    
                slice_obj.hovered.connect(on_hovered)
                series.append(slice_obj)

        self.chart.addSeries(series)


class MonthlyRevenueChartWidget(QWidget):
    """
    Graphique en barres (Bar Chart) Qt pour le suivi financier des recettes mensuelles récoltées.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.SeriesAnimations)
        self.chart.setBackgroundBrush(Qt.transparent)
        
        # Configuration des polices et légendes
        self.chart.setTitleFont(QFont("Segoe UI", 10, QFont.Bold))
        self.chart.setTitleBrush(QColor("#1E293B"))
        self.chart.legend().setVisible(False) # Pas de légende nécessaire car barre unique

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setStyleSheet("background: transparent;")
        
        layout.addWidget(self.chart_view)

    def set_data(self, monthly_revenue: dict):
        """Met à jour le graphique financier avec les revenus mensuels."""
        self.chart.removeAllSeries()
        
        # Supprimer les anciens axes s'ils existent
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        # Trier les mois chronologiquement d'après leur rang dans l'année civile
        month_order = {
            "Janvier": 1, "Février": 2, "Mars": 3, "Avril": 4, "Mai": 5, "Juin": 6,
            "Juillet": 7, "Août": 8, "Septembre": 9, "Octobre": 10, "Novembre": 11, "Décembre": 12
        }
        
        sorted_months = sorted(
            [m for m in monthly_revenue.keys() if m in month_order],
            key=lambda m: month_order[m]
        )

        # Création du jeu de données (BarSet)
        bar_set = QBarSet("Recettes")
        bar_set.setBrush(QColor("#16A34A")) # Vert Succès pour l'argent !
        bar_set.setBorderColor(QColor("#FFFFFF"))

        categories = []
        max_val = 0.0
        
        for m_name in sorted_months:
            rev = monthly_revenue[m_name]
            bar_set.append(rev)
            categories.append(m_name[:4] + ".") # Version courte du mois (ex: Sept.)
            if rev > max_val:
                max_val = rev

        series = QBarSeries()
        series.append(bar_set)
        
        # Afficher la valeur au survol d'une barre
        def on_bar_hovered(status, index, b_set=bar_set):
            if status:
                val = b_set.at(index)
                self.chart.setTitle(f"📊 Volume des Recettes Mensuelles : {val:.2f} €")
            else:
                self.chart.setTitle("📊 Volume des Recettes Mensuelles (HelloAsso)")
                
        series.hovered.connect(on_bar_hovered)
        self.chart.addSeries(series)

        # Axe X : Catégories (Mois)
        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_x.setLabelsFont(QFont("Segoe UI", 8))
        axis_x.setLabelsBrush(QColor("#64748B"))
        self.chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        # Axe Y : Montant en €
        axis_y = QValueAxis()
        axis_y.setRange(0, max_val * 1.15 if max_val > 0 else 100)
        axis_y.setLabelFormat("%.0f €")
        axis_y.setLabelsFont(QFont("Segoe UI", 8))
        axis_y.setLabelsBrush(QColor("#64748B"))
        # Dessiner des lignes de grille horizontales légères
        axis_y.setLinePenColor(QColor("#E2E8F0"))
        axis_y.setGridLineColor(QColor("#F1F5F9"))
        
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)


class CourseFillingChartWidget(QWidget):
    """
    Graphique en barres verticales (Bar Chart) pour la répartition des effectifs par cours/tarifs.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.SeriesAnimations)
        self.chart.setBackgroundBrush(Qt.transparent)
        
        self.chart.setTitleFont(QFont("Segoe UI", 10, QFont.Bold))
        self.chart.setTitleBrush(QColor("#1E293B"))
        self.chart.legend().setVisible(False)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setStyleSheet("background: transparent;")
        
        layout.addWidget(self.chart_view)

    def set_data(self, course_counts: list):
        """Met à jour le graphique d'effectifs avec la liste des (nom_cours, effectif)."""
        self.chart.removeAllSeries()
        
        for axis in list(self.chart.axes()):
            self.chart.removeAxis(axis)

        if not course_counts:
            return

        # Limiter aux 6 cours les plus denses pour une parfaite lisibilité
        top_courses = course_counts[:6]

        bar_set = QBarSet("Effectif")
        bar_set.setBrush(QColor("#163A5F")) # Bleu profond ALJ
        bar_set.setBorderColor(QColor("#FFFFFF"))

        categories = []
        max_val = 0
        
        for c_name, count in top_courses:
            bar_set.append(count)
            # Raccourcir le nom du cours s'il est trop long pour l'axe X
            short_name = c_name
            if len(short_name) > 18:
                short_name = short_name[:15] + "..."
            categories.append(short_name)
            if count > max_val:
                max_val = count

        series = QBarSeries()
        series.append(bar_set)
        
        def on_bar_hovered(status, index, b_set=bar_set):
            if status:
                val = int(b_set.at(index))
                cours_full_name = top_courses[index][0]
                self.chart.setTitle(f"👥 {cours_full_name} : {val} licencié(s)")
            else:
                self.chart.setTitle("👥 Inscriptions par Cours / Tarifs (Top 6)")
                
        series.hovered.connect(on_bar_hovered)
        self.chart.addSeries(series)

        # Axe X
        axis_x = QBarCategoryAxis()
        axis_x.append(categories)
        axis_x.setLabelsFont(QFont("Segoe UI", 8))
        axis_x.setLabelsBrush(QColor("#64748B"))
        self.chart.addAxis(axis_x, Qt.AlignBottom)
        series.attachAxis(axis_x)

        # Axe Y
        axis_y = QValueAxis()
        axis_y.setRange(0, max_val + 2 if max_val > 0 else 10)
        axis_y.setLabelFormat("%d")
        axis_y.setLabelsFont(QFont("Segoe UI", 8))
        axis_y.setLabelsBrush(QColor("#64748B"))
        axis_y.setLinePenColor(QColor("#E2E8F0"))
        axis_y.setGridLineColor(QColor("#F1F5F9"))
        
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        series.attachAxis(axis_y)
