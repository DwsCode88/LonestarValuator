"""App stylesheet: light, roomy, navy accent."""

QSS = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 10pt; color: #111827; }
QMainWindow, QDialog { background: #F6F7F9; }
QGroupBox { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #4B5563; font-weight: 600; }
QLineEdit, QPlainTextEdit {
    background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 6px; padding: 4px 6px; min-height: 20px; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #2F64A8; }
QLineEdit:disabled { background: #F3F4F6; color: #9CA3AF; }
QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit { min-height: 24px; }
QPushButton { background: #FFFFFF; border: 1px solid #D1D5DB; border-radius: 6px; padding: 5px 12px; }
QPushButton:hover { background: #F3F4F6; }
QPushButton:pressed { background: #E5E7EB; }
QPushButton:disabled { color: #9CA3AF; }
QPushButton#primary { background: #1F3A5F; color: #FFFFFF; border: 1px solid #1F3A5F; font-weight: 600; padding: 6px 16px; }
QPushButton#primary:hover { background: #2A4C7A; }
QPushButton#primary:disabled { background: #93A3B8; border-color: #93A3B8; }
QTableWidget, QListWidget { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px;
    alternate-background-color: #FAFAFB; selection-background-color: #DBEAFE; selection-color: #111827; }
QHeaderView::section { background: #F9FAFB; border: none; border-bottom: 1px solid #E5E7EB; padding: 6px; color: #4B5563; font-weight: 600; }
QListWidget#reports::item { padding: 8px 6px; border-bottom: 1px solid #F1F2F4; }
QListWidget#reports::item:selected { background: #DBEAFE; color: #111827; border-left: 3px solid #1F3A5F; }
QFrame#quickadd { background: #FFFFFF; border: 1px solid #C7D2E3; border-radius: 8px; }
QLabel#h1 { font-size: 14pt; font-weight: 700; color: #1F3A5F; }
QLabel#strong { font-weight: 700; }
QLabel#muted { color: #6B7280; }
QLabel#total { font-size: 15pt; font-weight: 700; color: #1F3A5F; padding: 6px; }
QLabel#banner { background: #FEF3C7; border: 1px solid #F59E0B; border-radius: 6px; padding: 8px 10px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #E5E7EB; border-radius: 6px; background: #FFFFFF; }
QTabBar::tab { padding: 6px 14px; }
QStatusBar { color: #4B5563; }
QMenuBar { background: #FFFFFF; border-bottom: 1px solid #E5E7EB; }
"""
