from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

COLORS = {"study": "#5278ED", "exercise": "#19A789", "sleep": "#9473D8"}
ICONS = {
    "today": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "study": '<path d="M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3z"/><path d="M12 6v15"/>',
    "exercise": '<path d="M3 8v8m3-10v12m12-12v12m3-10v8M6 12h12"/>',
    "sleep": '<path d="M20 14A8.5 8.5 0 0 1 10 4a8.5 8.5 0 1 0 10 10Z"/>',
    "records": '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "stats": '<path d="M4 3v17h17M8 15v-4m5 4V6m5 9v-7"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="COLOR"/><circle cx="15" cy="17" r="3" fill="COLOR"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "check": '<path d="m5 12 4 4 10-10"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrow": '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    "bell": '<path d="M5 17h14l-2-3V9a5 5 0 0 0-10 0v5l-2 3ZM10 21h4"/>',
}


def icon(name: str, color="#627089", size=24) -> QIcon:
    paths = ICONS.get(name, ICONS["today"]).replace("COLOR", color)
    data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    QSvgRenderer(QByteArray(data.encode())).render(painter)
    painter.end()
    pix.setDevicePixelRatio(2)
    return QIcon(pix)


def app_pixmap(size=128) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 128, size / 128)
    gradient = QLinearGradient(0, 0, 128, 128)
    gradient.setColorAt(0, QColor("#6D8DF4"))
    gradient.setColorAt(1, QColor("#3E65D6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QRectF(3, 3, 122, 122), 29, 29)
    p.setPen(QPen(QColor("white"), 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(30, 28, 69, 69))
    p.drawLine(48, 62, 61, 75)
    p.drawLine(61, 75, 83, 49)
    p.setPen(Qt.PenStyle.NoPen)
    for x, c in ((49, "#B9D0FF"), (64, "#93E5C8"), (79, "#D1BEFA")):
        p.setBrush(QColor(c))
        p.drawEllipse(QRectF(x - 3, 108, 6, 6))
    p.end()
    return pix


def label(text="", role="", wrap=False) -> QLabel:
    result = QLabel(text)
    if role:
        result.setProperty("role", role)
    result.setWordWrap(wrap)
    return result


def button(text, callback=None, primary=False, name=None, color="#5278ED"):
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(36)
    if primary:
        b.setProperty("role", "primary")
    if name:
        b.setIcon(icon(name, "#FFFFFF" if primary else color))
        b.setIconSize(QSize(18, 18))
    if callback:
        b.clicked.connect(callback)
    return b


def panel() -> QFrame:
    f = QFrame()
    f.setObjectName("panel")
    return f


def duration(minutes: float | None) -> str:
    if minutes is None:
        return "未记录"
    rounded = round(minutes, 1)
    if rounded == 0 and minutes > 0:
        return "不足 0.1 分钟"
    h = int(rounded // 60)
    m = round(rounded - h * 60, 1)
    return f"{h} 小时 {m:g} 分" if h and m else (f"{h} 小时" if h else f"{m:g} 分钟")


class Ring(QWidget):
    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color, self.progress = color, 0.0
        self.setFixedSize(64, 64)

    def set_progress(self, fraction):
        self.progress = min(1, max(0, fraction))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(5, 5, 54, 54)
        p.setPen(QPen(QColor("#EDF0F5"), 5))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(self.color), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90 * 16, -round(self.progress * 360 * 16))
        p.setPen(QColor(self.color))
        p.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{int(self.progress * 100)}%")


class MetricLabel(QLabel):
    """Keep decimal durations fully visible beside the progress ring."""
    def __init__(self):
        super().__init__()
        self.pixel_size = 0
        self.setProperty("role", "metric")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setMinimumHeight(33)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)
        self.fit_font()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_font()

    def fit_font(self):
        width = self.contentsRect().width()
        if width <= 0:
            return
        font = QFont(self.font())
        font.setWeight(QFont.Weight.Bold)
        for size in range(23, 10, -1):
            font.setPixelSize(size)
            if QFontMetrics(font).horizontalAdvance(self.text()) <= width:
                break
        if size != self.pixel_size:
            self.pixel_size = size
            self.setStyleSheet(f"font-size: {size}px; font-weight: 700;")


class GoalCard(QFrame):
    def __init__(self, kind, title, action, callback):
        super().__init__()
        self.setObjectName("panel")
        self.setMinimumWidth(220)
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 18)
        layout.setSpacing(13)
        top = QHBoxLayout()
        mark = QLabel()
        mark.setPixmap(icon(kind, COLORS[kind], 24).pixmap(24, 24))
        top.addWidget(mark)
        top.addWidget(label(title, "cardTitle"))
        top.addStretch()
        self.badge = label("待开始", "badge")
        top.addWidget(self.badge)
        layout.addLayout(top)
        middle = QHBoxLayout()
        values = QVBoxLayout()
        self.amount = MetricLabel()
        self.amount.setText("0 分钟")
        self.goal = label("", "muted")
        values.addWidget(self.amount)
        values.addWidget(self.goal)
        middle.addLayout(values, 1)
        middle.addSpacing(10)
        self.ring = Ring(COLORS[kind])
        middle.addWidget(self.ring)
        layout.addLayout(middle)
        self.detail = label("", "muted", True)
        self.detail.setMinimumHeight(36)
        layout.addWidget(self.detail)
        self.action = button(action, callback, name="arrow", color=COLORS[kind])
        layout.addWidget(self.action)

    def refresh(self, summary):
        actual = summary["totals"][self.kind]
        goal = summary["goals"][self.kind]
        self.amount.setText(duration(actual))
        self.goal.setText(f"今日目标 · {duration(goal)}")
        self.ring.set_progress((actual or 0) / goal)
        achieved = summary["achieved"][self.kind]
        self.badge.setText("已达标" if achieved else ("未记录" if actual is None else "进行中" if actual > 0 else "待开始"))
        backgrounds = {"study": "#EEF3FF", "exercise": "#E8F7F1", "sleep": "#F3EEFC"}
        self.badge.setStyleSheet(f"color: {COLORS[self.kind]}; background: {backgrounds[self.kind]}; padding: 4px 8px; border-radius: 6px;")
        plan = summary["plan"]
        if self.kind == "study":
            self.detail.setText(f"{plan['study_time']} 提醒开始学习\n每一次专注，都会积累下来")
        elif self.kind == "exercise":
            self.detail.setText(f"{plan['exercise_time']} 提醒活动身体\n计时运动，或补记今天的活动")
        else:
            self.detail.setText(f"入睡参考 {plan.get('sleep_bedtime', plan['bedtime'])} · 起床 {plan['wake_time']}\n今晚 {plan['bedtime']} 提醒就寝")


class TrendChart(QWidget):
    def __init__(self):
        super().__init__()
        self.data = []
        self.setMinimumHeight(240)
        self.setMinimumWidth(520)

    def set_data(self, data):
        self.data = data
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(QFont("Microsoft YaHei UI", 9))
        left, top, bottom = 46, 30, self.height() - 34
        width = self.width() - left - 24
        height = bottom - top
        for percent in (0, 50, 100):
            y = bottom - height * percent / 120
            p.setPen(QColor("#E9EDF4"))
            p.drawLine(left, int(y), self.width() - 20, int(y))
            p.setPen(QColor("#8793A6"))
            p.drawText(QRectF(0, y - 10, left - 8, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{percent}%")
        if not self.data:
            return
        spacing = width / max(1, len(self.data) - 1)
        for kind, color in COLORS.items():
            path = QPainterPath()
            connected = False
            points = []
            for i, item in enumerate(self.data):
                value = item["totals"][kind]
                if value is None or not item["has_plan"]:
                    connected = False
                    continue
                ratio = min(1.2, value / item["goals"][kind])
                x, y = left + i * spacing, bottom - height * ratio / 1.2
                if connected:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                connected = True
                points.append((x, y))
            p.setPen(QPen(QColor(color), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            for x, y in points:
                p.drawEllipse(QRectF(x - 3, y - 3, 6, 6))
        p.setPen(QColor("#8793A6"))
        step = 1 if len(self.data) <= 7 else 5
        for i, item in enumerate(self.data):
            if i % step == 0 or i == len(self.data) - 1:
                text = date.fromisoformat(item["day"]).strftime("%m/%d")
                p.drawText(QRectF(left + i * spacing - 26, bottom + 9, 52, 20), Qt.AlignmentFlag.AlignCenter, text)


STYLE = """
* { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif; font-size: 13px; color: #283650; }
QMainWindow, QDialog { background: #F5F7FB; }
QWidget#sidebar { background: #FFFFFF; border-right: 1px solid #E7ECF3; }
QFrame#panel { background: #FFFFFF; border: 1px solid #E5EAF2; border-radius: 14px; }
QLabel { background: transparent; border: none; }
QLabel[role='title'] { font-size: 27px; font-weight: 700; color: #202E49; }
QLabel[role='subtitle'] { font-size: 14px; color: #7F8DA2; }
QLabel[role='section'] { font-size: 17px; font-weight: 600; color: #283650; }
QLabel[role='cardTitle'] { font-size: 15px; font-weight: 600; }
QLabel[role='metric'] { font-size: 23px; font-weight: 700; }
QLabel[role='muted'] { color: #8390A4; font-size: 12px; }
QLabel[role='badge'] { font-size: 11px; }
QLabel[role='brand'] { font-size: 19px; font-weight: 700; }
QLabel[role='timer'] { font-family: 'Segoe UI'; font-size: 72px; font-weight: 300; color: #4169DD; }
QPushButton { background: #FFFFFF; border: 1px solid #E2E8F1; border-radius: 8px; padding: 7px 14px; font-weight: 500; }
QPushButton:hover { background: #F0F4FF; border-color: #C6D4F7; }
QPushButton:pressed { background: #E5ECFC; }
QPushButton:disabled { color: #A6AFBF; background: #F4F6F9; border-color: #E8EDF4; }
QPushButton[role='primary'] { color: #FFFFFF; background: #5278ED; border: 1px solid #5278ED; }
QPushButton[role='primary']:hover { background: #4169DD; border-color: #4169DD; }
QPushButton[role='primary']:disabled { background: #A5B8F2; border-color: #A5B8F2; }
QPushButton[role='nav'] { border: none; background: transparent; text-align: left; color: #758298; padding: 13px 18px; font-size: 14px; }
QPushButton[role='nav']:hover { background: #F6F8FD; }
QPushButton[role='nav']:checked { color: #4169DD; background: #EEF3FF; font-weight: 600; }
QLineEdit, QSpinBox, QDoubleSpinBox, QTimeEdit, QDateEdit, QDateTimeEdit, QComboBox {
    border: 1px solid #DDE4EF; border-radius: 7px; background: #FFFFFF; padding: 7px 9px; min-height: 20px; selection-background-color: #5278ED;
}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QDateEdit:focus, QDateTimeEdit:focus, QComboBox:focus { border-color: #7898F4; }
QComboBox::drop-down { border: none; width: 24px; }
QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button, QDateEdit::up-button, QDateTimeEdit::up-button { width: 20px; }
QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button, QDateEdit::down-button, QDateTimeEdit::down-button { width: 20px; }
QTableWidget { background: #FFFFFF; alternate-background-color: #FAFBFE; border: 1px solid #E5EAF2; border-radius: 10px; gridline-color: #F0F3F8; selection-background-color: #EAF0FF; selection-color: #283650; }
QTableWidget::item { padding: 7px; border-bottom: 1px solid #F0F3F8; }
QHeaderView::section { background: #F7F9FC; color: #7A879C; padding: 10px 6px; border: none; border-bottom: 1px solid #E5EAF2; font-weight: 500; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { padding: 10px 20px; color: #7B899F; background: transparent; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #4169DD; border-bottom: 2px solid #5278ED; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 3px; }
QScrollBar::handle:vertical { background: #CDD6E5; border-radius: 3px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QMenu { background: #FFFFFF; border: 1px solid #E1E7F0; padding: 5px; }
QMenu::item { padding: 8px 25px; border-radius: 5px; }
QMenu::item:selected { background: #EEF3FF; }
QToolTip { color: #FFFFFF; background: #34435E; border: none; padding: 7px; }
"""
