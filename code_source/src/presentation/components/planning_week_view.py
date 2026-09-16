"""
Vue semaine du planning (graphique Qt) pour l'onglet Créneaux.

Reprend la présentation de l'export Excel (planning_excel_export.py) :
- grille Lundi → Samedi, 9h-22h par pas de 30 minutes, heures affichées à gauche
  ET à droite ;
- hiérarchie des traits : séparateurs de JOURS épais noirs, lignes d'HEURES moyennes,
  demi-heures fines, voies d'un même jour fines ;
- blocs colorés par type de groupe (compétition = vert, perfectionnement = rose,
  cours = bleu lavande, autonome = gris) avec libellé + encadrants (initiales si le
  bloc est court — même heuristique que l'export).
"""
import html

from PySide6.QtWidgets import QGraphicsTextItem, QGraphicsView, QGraphicsScene
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen

from infrastructure.planning_excel_export import (
    DAYS, GRID_START, GRID_END, STEP,
    assign_lanes, clean_group_label, encadrants_text, fill_for_item, parse_horaire,
)

INK = "#1F4E79"


class PlanningWeekView(QGraphicsView):
    """Grille hebdomadaire du planning (scrollable), construite depuis les données BDD."""

    TITLE_H = 30
    DAY_H = 26
    ROW_H = 18          # 30 minutes
    LANE_W = 92         # largeur d'une voie de jour
    TIME_W = 34         # colonnes d'heures (gauche / droite)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setBackgroundBrush(QBrush(QColor("#FFFFFF")))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    # ------------------------------------------------------------------
    def set_planning(self, planning_data, saison: str = ""):
        """(Re)construit la vue depuis les données du planning (format BDD)."""
        self._rebuild(planning_data or [], str(saison or ""))

    # ------------------------------------------------------------------
    def _rebuild(self, planning_data, saison):
        self._scene.clear()
        # Maintien de référence PySide : un QGraphicsTextItem enfant d'un QGraphicsItem
        # est détruit par le GC si aucun wrapper Python ne le référence.
        self._text_items = []
        steps = (GRID_END - GRID_START) // STEP
        grid_h = steps * self.ROW_H
        grid_top = self.TITLE_H + self.DAY_H

        # --- Créneaux valides par jour + répartition en voies ---
        by_day = {day: [] for day in DAYS}
        for item in planning_data:
            span = parse_horaire(item.get("horaires"))
            jour = str(item.get("jour") or "").strip().capitalize()
            if not span or jour not in by_day:
                continue
            start = max(span[0], GRID_START)
            end = min(span[1], GRID_END)
            if end <= start:
                continue
            by_day[jour].append({
                "start": start, "end": end,
                "label": clean_group_label(item.get("groupe")) or "Créneau",
                # fill_for_item renvoie l'hex openpyxl SANS « # » : Qt exige le « # »
                "fill": "#" + fill_for_item(item),
                "encadrants": item.get("encadrants") or [],
            })

        day_lanes = {}
        for day in DAYS:
            assignments, lanes = assign_lanes(by_day[day])
            day_lanes[day] = {"assignments": assignments, "lanes": max(1, lanes)}
        total_lanes = sum(info["lanes"] for info in day_lanes.values())
        grid_w = total_lanes * self.LANE_W
        total_w = self.TIME_W + grid_w + self.TIME_W
        total_h = grid_top + grid_h + 8
        self._scene.setSceneRect(0, 0, total_w, total_h)

        # --- Titre (saison) ---
        title = self._scene.addSimpleText(f"Saison {saison.replace('-', ' - ')}",
                                          QFont("Calibri", 11, QFont.Weight.Bold))
        title.setPos(total_w / 2 - title.boundingRect().width() / 2, 4)

        # --- En-têtes de jours ---
        x = self.TIME_W
        for day in DAYS:
            lanes = day_lanes[day]["lanes"]
            w = lanes * self.LANE_W
            self._scene.addRect(x, self.TITLE_H, w, self.DAY_H,
                                QPen(QColor("#404040"), 2), QBrush(QColor("#D9E1F2")))
            head = self._scene.addSimpleText(day.upper(), QFont("Calibri", 10, QFont.Weight.Bold))
            head.setPos(x + w / 2 - head.boundingRect().width() / 2,
                        self.TITLE_H + (self.DAY_H - head.boundingRect().height()) / 2)
            x += w

        # --- Lignes horizontales (heures = medium, demi-heures = fin) ---
        for i in range(steps + 1):
            y = grid_top + i * self.ROW_H
            pen = QPen(QColor("#404040"), 2) if i % 2 == 0 else QPen(QColor("#BFBFBF"), 1)
            self._scene.addLine(self.TIME_W, y, self.TIME_W + grid_w, y, pen)
            if i < steps:
                label = f"{(GRID_START + i * STEP) // 60}h"
                for lx in (2, self.TIME_W + grid_w + 4):
                    t = self._scene.addSimpleText(label, QFont("Calibri", 9, QFont.Weight.Bold))
                    t.setPos(lx, y)

        # --- Séparateurs verticaux (jours épais, voies fines) ---
        x = self.TIME_W
        for day in DAYS:
            lanes = day_lanes[day]["lanes"]
            self._scene.addLine(x, self.TITLE_H, x, grid_top + grid_h, QPen(QColor("#000000"), 3))
            for lane in range(1, lanes):
                lx = x + lane * self.LANE_W
                self._scene.addLine(lx, grid_top, lx, grid_top + grid_h, QPen(QColor("#595959"), 1))
            x += lanes * self.LANE_W
        self._scene.addLine(x, self.TITLE_H, x, grid_top + grid_h, QPen(QColor("#000000"), 3))

        # --- Blocs de créneaux ---
        # NB : addRect(bx, by, w, h) dessine le rect à (bx, by) mais laisse l'ORIGINE
        # de l'item à (0, 0) — on positionne donc l'item via setPos(bx, by) pour que
        # les textes enfants (positions relatives) tombent dans le bloc.
        x = self.TIME_W
        for day in DAYS:
            info = day_lanes[day]
            for slot, lane in info["assignments"]:
                bx = x + lane * self.LANE_W
                by = grid_top + (slot["start"] - GRID_START) / 30 * self.ROW_H
                bh = (slot["end"] - slot["start"]) / 30 * self.ROW_H
                rows_span = max(1, round(bh / self.ROW_H))
                rect = self._scene.addRect(0, 0, self.LANE_W, bh,
                                           QPen(QColor("#404040"), 2),
                                           QBrush(QColor(slot["fill"])))
                rect.setPos(bx, by)
                rect.setZValue(1)
                enc = encadrants_text(slot["encadrants"], rows_span, slot["label"])
                label_html = f'<div style="color:{INK};"><b>{html.escape(slot["label"])}</b></div>'
                if enc:
                    label_html += f'<div style="color:#111111;">{html.escape(enc)}</div>'
                text = QGraphicsTextItem()
                text.setHtml(label_html)
                text.setTextWidth(self.LANE_W - 6)
                font = QFont("Calibri", 8)
                text.setFont(font)
                text.setParentItem(rect)
                self._text_items.append(text)
                # Centrage vertical si le texte tient dans le bloc
                th = text.boundingRect().height()
                text.setPos(3, max(2, (bh - th) / 2) if th <= bh else 2)
            x += info["lanes"] * self.LANE_W

        self._fit_width()

    def _fit_width(self):
        """Ajuste le zoom pour que la largeur de la grille tienne dans la vue."""
        rect = self.sceneRect()
        if rect.width() > 0 and self.viewport() is not None and self.viewport().width() > 0:
            scale = min(1.0, self.viewport().width() / rect.width())
            from PySide6.QtCore import QPointF
            self.resetTransform()
            self.scale(scale, scale)
            self.centerOn(QPointF(rect.width() / 2, rect.height() / 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_width()