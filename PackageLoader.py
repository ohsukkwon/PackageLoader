# -*- coding: utf-8 -*-
import sys
import subprocess
import re
import threading

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

g_FONT_FACE = "Malgun Gothic"
g_FONT_SIZE = 10
g_FONT_10_normal_ref = QFont(g_FONT_FACE, g_FONT_SIZE)
g_FONT_10_bold_ref = QFont(g_FONT_FACE, g_FONT_SIZE, QFont.Bold)


class PackageWorker(QThread):
    """패키지 정보를 가져오는 워커 스레드"""
    package_loaded = pyqtSignal(list)
    progress_updated = pyqtSignal(int)
    error_occurred = pyqtSignal(str)

    def __init__(self, device_id):
        super().__init__()
        self.device_id = device_id

    def run(self):
        try:
            # 설치된 패키지 목록 가져오기
            self.progress_updated.emit(30)
            cmd = f"adb -s {self.device_id} shell pm list packages"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                self.error_occurred.emit(f"패키지 목록을 가져올 수 없습니다: {result.stderr}")
                return

            packages = []
            package_lines = result.stdout.strip().split('\n')

            self.progress_updated.emit(60)

            # 시스템 앱 목록 가져오기
            system_cmd = f"adb -s {self.device_id} shell pm list packages -s"
            system_result = subprocess.run(system_cmd, shell=True, capture_output=True, text=True, timeout=30)
            system_packages = set()

            if system_result.returncode == 0:
                for line in system_result.stdout.strip().split('\n'):
                    if line.startswith('package:'):
                        system_packages.add(line.replace('package:', ''))

            self.progress_updated.emit(80)

            # 패키지 정보 구성
            for i, line in enumerate(package_lines):
                if line.startswith('package:'):
                    package_name = line.replace('package:', '')
                    is_system = package_name in system_packages
                    packages.append({
                        'name': package_name,
                        'is_system': is_system,
                        'selected': False
                    })

            packages.sort(key=lambda x: x['name'])

            self.progress_updated.emit(100)
            self.package_loaded.emit(packages)

        except subprocess.TimeoutExpired:
            self.error_occurred.emit("명령 실행 시간이 초과되었습니다.")
        except Exception as e:
            self.error_occurred.emit(f"오류가 발생했습니다: {str(e)}")


class PackageOperationWorker(QThread):
    """패키지 작업을 처리하는 워커 스레드"""
    progress_updated = pyqtSignal(int, str)  # 진행률, 현재 처리중인 패키지명
    operation_completed = pyqtSignal(list)  # 실패한 패키지 목록
    error_occurred = pyqtSignal(str)

    def __init__(self, device_id, packages, operation):
        super().__init__()
        self.device_id = device_id
        self.packages = packages
        self.operation = operation
        self._is_cancelled = False

    def run(self):
        failed_packages = []
        total_packages = len(self.packages)

        for i, package in enumerate(self.packages):
            if self._is_cancelled:
                break

            try:
                # 진행 상황 업데이트
                progress = int((i / total_packages) * 100)
                self.progress_updated.emit(progress, package)

                if self.operation == "uninstall":
                    cmd = f"adb -s {self.device_id} uninstall {package}"
                elif self.operation == "disable":
                    cmd = f"adb -s {self.device_id} shell pm disable-user {package}"
                elif self.operation == "enable":
                    cmd = f"adb -s {self.device_id} shell pm enable {package}"
                elif self.operation == "reset":
                    cmd = f"adb -s {self.device_id} shell pm default-state {package}"

                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

                if result.returncode != 0 or (self.operation == "uninstall" and "Failure" in result.stdout):
                    failed_packages.append(package)

            except Exception as e:
                failed_packages.append(package)

        # 작업 완료
        self.progress_updated.emit(100, "완료")
        self.operation_completed.emit(failed_packages)

    def cancel(self):
        """작업 취소"""
        self._is_cancelled = True


class ProgressDialog(QDialog):
    """패키지 작업 진행 상황을 표시하는 다이얼로그"""
    cancel_requested = pyqtSignal()

    def __init__(self, operation, total_packages, parent=None):
        super().__init__(parent)
        self.operation = operation
        self.total_packages = total_packages
        self.init_ui()

    def init_ui(self):
        operation_names = {
            "uninstall": "삭제",
            "disable": "비활성화",
            "enable": "활성화",
            "reset": "재설정"
        }

        self.setWindowTitle(f"패키지 {operation_names.get(self.operation, '처리')}")
        self.setModal(True)
        self.setFixedSize(500, 300)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # 제목
        title_label = QLabel(f"📦 패키지 {operation_names.get(self.operation, '처리')} 진행 중")
        title_label.setFont(g_FONT_10_bold_ref)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #2c3e50; margin-bottom: 10px;")
        layout.addWidget(title_label)

        # 현재 처리중인 패키지
        self.current_package_label = QLabel("준비 중...")
        self.current_package_label.setFont(g_FONT_10_normal_ref)
        self.current_package_label.setAlignment(Qt.AlignCenter)
        self.current_package_label.setStyleSheet("""
            color: #34495e; 
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 8px;
            margin: 5px;
        """)
        layout.addWidget(self.current_package_label)

        # 진행률 표시
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #bdc3c7;
                border-radius: 8px;
                text-align: center;
                font-weight: bold;
                background-color: #ecf0f1;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2980b9);
                border-radius: 7px;
            }
        """)
        layout.addWidget(self.progress_bar)

        # 진행 상태 라벨
        self.status_label = QLabel(f"0 / {self.total_packages} 완료")
        self.status_label.setFont(g_FONT_10_normal_ref)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #7f8c8d;")
        layout.addWidget(self.status_label)

        # 취소 버튼
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("취소")
        self.cancel_button.setFont(g_FONT_10_bold_ref)
        self.cancel_button.setFixedSize(100, 35)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """)
        self.cancel_button.clicked.connect(self.on_cancel_clicked)
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch()
        layout.addLayout(button_layout)

        self.setLayout(layout)

    @pyqtSlot(int, str)
    def update_progress(self, progress, current_package):
        """진행 상황 업데이트"""
        self.progress_bar.setValue(progress)

        if current_package == "완료":
            self.current_package_label.setText("✅ 작업이 완료되었습니다!")
            self.current_package_label.setStyleSheet("""
                color: #27ae60; 
                background-color: #d5f4e6;
                border: 1px solid #27ae60;
                border-radius: 4px;
                padding: 8px;
                margin: 5px;
                font-weight: bold;
            """)
            self.cancel_button.setText("✅ 완료")
            self.cancel_button.setStyleSheet("""
                QPushButton {
                    background-color: #27ae60;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                }
                QPushButton:hover {
                    background-color: #229954;
                }
            """)
        else:
            self.current_package_label.setText(f"처리 중: {current_package}")

        # 완료된 패키지 수 계산
        completed = int((progress / 100) * self.total_packages)
        self.status_label.setText(f"{completed} / {self.total_packages} 완료")

    def on_cancel_clicked(self):
        """취소 버튼 클릭"""
        if self.cancel_button.text() == "✅ 완료":
            self.accept()
        else:
            reply = QMessageBox.question(self, "확인",
                                         "작업을 취소하시겠습니까?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.cancel_requested.emit()
                self.reject()

    def closeEvent(self, event):
        """윈도우 닫기 이벤트"""
        if self.cancel_button.text() != "✅ 완료":
            reply = QMessageBox.question(self, "확인",
                                         "작업을 취소하시겠습니까?",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.cancel_requested.emit()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


class PackageDetailDialog(QDialog):
    """패키지 상세 정보를 표시하는 서브 윈도우 (이쁘게 구성)"""

    def __init__(self, device_id, package_name, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.package_name = package_name
        self.package_info = {}
        self.enable_states = {
            0: "ENABLED_STATE_DEFAULT",
            1: "ENABLED_STATE_ENABLED",
            2: "ENABLED_STATE_DISABLED",
            3: "ENABLED_STATE_DISABLED_USER",
            4: "ENABLED_STATE_DISABLED_UNTIL_USED"
        }
        self.init_ui()
        self.load_package_detail()

    def init_ui(self):
        self.setWindowTitle(f"패키지 상세 정보 - {self.package_name}")
        self.setModal(True)
        self.resize(1000, 850)
        # "?" 아이콘 제거
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        # 메인 레이아웃
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 제목 영역
        title_frame = QFrame()
        title_frame.setFrameStyle(QFrame.StyledPanel)
        title_frame.setStyleSheet("""
            QFrame {
                background-color: #f0f8ff;
                border: 2px solid #4682b4;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        title_layout = QVBoxLayout(title_frame)

        title_label = QLabel("📦 패키지 상세 정보")
        title_label.setFont(g_FONT_10_bold_ref)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: #2c3e50; background: transparent; border: none;")
        title_layout.addWidget(title_label)

        package_label = QLabel(f"Package: {self.package_name}")
        package_label.setFont(g_FONT_10_normal_ref)
        package_label.setAlignment(Qt.AlignCenter)
        package_label.setStyleSheet("color: #34495e; background: transparent; border: none; margin-top: 5px;")
        title_layout.addWidget(package_label)

        main_layout.addWidget(title_frame)

        # 스크롤 영역
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameStyle(QFrame.NoFrame)

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        # 정보 영역
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.StyledPanel)
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #bdc3c7;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)

        # 로딩 라벨
        self.loading_label = QLabel("📥 패키지 정보를 로드")
        self.loading_label.setFont(g_FONT_10_normal_ref)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("color: #3498db; padding: 20px;")
        info_layout.addWidget(self.loading_label)

        # 정보 입력 폼 (초기에는 숨김)
        self.form_widget = QWidget()
        form_layout = QFormLayout(self.form_widget)
        form_layout.setSpacing(15)
        form_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # 스타일 설정을 위한 함수
        def create_info_field(label_text, icon=""):
            label = QLabel(f"{icon} {label_text}")
            label.setFont(g_FONT_10_bold_ref)
            label.setStyleSheet("color: #2c3e50; min-width: 150px;")

            edit = QLineEdit()
            edit.setReadOnly(True)
            edit.setFont(g_FONT_10_normal_ref)
            edit.setStyleSheet("""
                QLineEdit {
                    background-color: #f8f9fa;
                    border: 1px solid #dee2e6;
                    border-radius: 4px;
                    padding: 8px;
                    color: #495057;
                }
                QLineEdit:focus {
                    border-color: #80bdff;
                    background-color: #ffffff;
                }
            """)
            return label, edit

        # 각 필드 생성
        label, self.appid_edit = create_info_field("App ID:", "🆔")
        form_layout.addRow(label, self.appid_edit)

        label, self.enable_state_edit = create_info_field("Enable State:", "⚡")
        form_layout.addRow(label, self.enable_state_edit)

        label, self.version_name_edit = create_info_field("Version Name:", "📌")
        form_layout.addRow(label, self.version_name_edit)

        label, self.version_code_edit = create_info_field("Version Code:", "🔢")
        form_layout.addRow(label, self.version_code_edit)

        label, self.installer_edit = create_info_field("Installer Package:", "📦")
        form_layout.addRow(label, self.installer_edit)

        label, self.timestamp_edit = create_info_field("Time Stamp:", "⏰")
        form_layout.addRow(label, self.timestamp_edit)

        label, self.last_update_edit = create_info_field("Last Update Time:", "🔄")
        form_layout.addRow(label, self.last_update_edit)

        self.form_widget.setVisible(False)
        info_layout.addWidget(self.form_widget)

        scroll_layout.addWidget(info_frame)
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)

        # 버튼 영역
        button_frame = QFrame()
        button_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border-top: 1px solid #dee2e6;
                border-radius: 0px;
            }
        """)
        button_layout = QHBoxLayout(button_frame)
        button_layout.setContentsMargins(15, 15, 15, 15)

        # 복사 버튼
        self.copy_button = QPushButton("📋 복사")
        self.copy_button.setFont(g_FONT_10_bold_ref)
        self.copy_button.setFixedSize(100, 35)
        self.copy_button.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:pressed {
                background-color: #1e7e34;
            }
            QPushButton:disabled {
                background-color: #6c757d;
                color: #ffffff;
            }
        """)
        self.copy_button.clicked.connect(self.copy_package_info)
        self.copy_button.setEnabled(False)  # 초기에는 비활성화
        button_layout.addWidget(self.copy_button)

        button_layout.addStretch()

        # 닫기 버튼
        close_button = QPushButton("❌ 닫기")
        close_button.setFont(g_FONT_10_bold_ref)
        close_button.setFixedSize(100, 35)
        close_button.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
            QPushButton:pressed {
                background-color: #545b62;
            }
        """)
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)

        main_layout.addWidget(button_frame)
        self.setLayout(main_layout)

    def load_package_detail(self):
        """패키지 상세 정보 로드"""
        # 백그라운드에서 정보 로드
        self.worker = QThread()
        self.worker.run = self.get_package_detail
        self.worker.start()

    def get_package_detail(self):
        """패키지 상세 정보 가져오기"""
        try:
            cmd = f"adb -s {self.device_id} shell dumpsys package {self.package_name}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                info = self.parse_package_info(result.stdout)
                QMetaObject.invokeMethod(self, "update_package_detail",
                                         Qt.QueuedConnection,
                                         Q_ARG(dict, info))
            else:
                QMetaObject.invokeMethod(self, "update_error",
                                         Qt.QueuedConnection,
                                         Q_ARG(str, "패키지 정보를 가져올 수 없습니다."))
        except Exception as e:
            QMetaObject.invokeMethod(self, "update_error",
                                     Qt.QueuedConnection,
                                     Q_ARG(str, str(e)))

    def parse_package_info(self, dumpsys_output):
        """dumpsys 출력에서 필요한 정보 파싱"""
        info = {
            'appId': '',
            'enabled': '',
            'version_name': '',
            'version_code': '',
            'installer': '',
            'timestamp': '',
            'last_update': ''
        }

        lines = dumpsys_output.split('\n')

        for line in lines:
            line = line.strip()

            if line.startswith('appId='):
                info['appId'] = line.split('=')[1] if '=' in line else ''
            elif line.startswith('User 0: '):
                enabled_value = line.split(' enabled=')[1][0]
                try:
                    state_code = int(enabled_value)
                    info['enabled'] = f"{state_code} ({self.enable_states.get(state_code, 'UNKNOWN')})"
                except:
                    info['enabled'] = enabled_value
            elif line.startswith('versionName='):
                info['version_name'] = line.split('=')[1] if '=' in line else ''
            elif line.startswith('versionCode='):
                version_code = line.split('=')[1] if '=' in line else ''
                info['version_code'] = version_code.split(' ')[0] if ' ' in version_code else version_code
            elif line.startswith('installerPackageName='):
                info['installer'] = line.split('=')[1] if '=' in line else ''
            elif line.startswith('timeStamp='):
                info['timestamp'] = line.split('=')[1] if '=' in line else ''
            elif line.startswith('lastUpdateTime='):
                info['last_update'] = line.split('=')[1] if '=' in line else ''

        return info

    @pyqtSlot(dict)
    def update_package_detail(self, info):
        """패키지 상세 정보 업데이트"""
        self.package_info = info

        self.appid_edit.setText(info.get('appId', 'N/A'))
        self.enable_state_edit.setText(info.get('enabled', 'N/A'))
        self.version_name_edit.setText(info.get('version_name', 'N/A'))
        self.version_code_edit.setText(info.get('version_code', 'N/A'))
        self.installer_edit.setText(info.get('installer', 'N/A'))
        self.timestamp_edit.setText(info.get('timestamp', 'N/A'))
        self.last_update_edit.setText(info.get('last_update', 'N/A'))

        # 로딩 라벨 숨기고 폼 표시
        self.loading_label.setVisible(False)
        self.form_widget.setVisible(True)
        self.copy_button.setEnabled(True)  # 복사 버튼 활성화

    @pyqtSlot(str)
    def update_error(self, error_message):
        """에러 메시지 업데이트"""
        self.loading_label.setText(f"❌ 오류: {error_message}")
        self.loading_label.setStyleSheet("color: #e74c3c; padding: 20px;")

    def copy_package_info(self):
        """패키지 정보 복사 (App ID부터 Last Update Time까지)"""
        if not self.package_info:
            QMessageBox.warning(self, "경고", "복사할 정보가 없습니다.")
            return

        # 복사할 텍스트 구성
        copy_text = f"""Package: {self.package_name}
App ID: {self.package_info.get('appId', 'N/A')}
Enable State: {self.package_info.get('enabled', 'N/A')}
Version Name: {self.package_info.get('version_name', 'N/A')}
Version Code: {self.package_info.get('version_code', 'N/A')}
Installer Package Name: {self.package_info.get('installer', 'N/A')}
Time Stamp: {self.package_info.get('timestamp', 'N/A')}
Last Update Time: {self.package_info.get('last_update', 'N/A')}"""

        # 클립보드에 복사
        clipboard = QApplication.clipboard()
        clipboard.setText(copy_text)

        # 성공 메시지 표시
        self.show_copy_success_message()

    def show_copy_success_message(self):
        """복사 성공 메시지 표시 (임시 툴팁 스타일)"""
        msg = QMessageBox(self)
        msg.setWindowTitle("복사 완료")
        msg.setText("📋 패키지 상세 정보가 클립보드에 복사되었습니다!")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #f8f9fa;
            }
            QMessageBox QLabel {
                color: #2c3e50;
                font-size: 11px;
            }
        """)

        # 자동으로 1.5초 후에 닫기
        QTimer.singleShot(1500, msg.accept)
        msg.exec_()


class PackageInfoDialog(QDialog):
    """패키지 정보를 표시하는 모달 대화상자"""

    def __init__(self, device_id, package_name, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.package_name = package_name
        self.init_ui()
        self.load_package_info()

    def init_ui(self):
        self.setWindowTitle(f"패키지 정보 - {self.package_name}")
        self.setModal(True)
        self.resize(1000, 800)
        # "?" 아이콘 제거
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()

        # 패키지명 라벨
        title_label = QLabel(f"패키지: {self.package_name}")
        title_label.setFont(g_FONT_10_bold_ref)
        layout.addWidget(title_label)

        # 텍스트 에디터 (읽기 전용)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(g_FONT_10_normal_ref)

        # 스크롤바 항상 표시
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        layout.addWidget(self.text_edit)

        # 버튼 레이아웃
        button_layout = QHBoxLayout()

        copy_button = QPushButton("복사")
        copy_button.clicked.connect(self.copy_text)
        button_layout.addWidget(copy_button)

        button_layout.addStretch()

        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def load_package_info(self):
        """패키지 정보 로드"""
        self.text_edit.setText("패키지 정보를 로드")

        # 백그라운드에서 정보 로드
        self.worker = QThread()
        self.worker.run = self.get_package_info
        self.worker.start()

    def get_package_info(self):
        """패키지 정보 가져오기 (백그라운드 스레드에서 실행)"""
        try:
            cmd = f"adb -s {self.device_id} shell dumpsys package {self.package_name}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                # 메인 스레드에서 UI 업데이트
                QMetaObject.invokeMethod(self, "update_package_info",
                                         Qt.QueuedConnection,
                                         Q_ARG(str, result.stdout))
            else:
                QMetaObject.invokeMethod(self, "update_package_info",
                                         Qt.QueuedConnection,
                                         Q_ARG(str, f"패키지 정보를 가져올 수 없습니다: {result.stderr}"))
        except Exception as e:
            QMetaObject.invokeMethod(self, "update_package_info",
                                     Qt.QueuedConnection,
                                     Q_ARG(str, f"오류 발생: {str(e)}"))

    @pyqtSlot(str)
    def update_package_info(self, info_text):
        """패키지 정보 업데이트 (메인 스레드에서 실행)"""
        self.text_edit.setText(info_text)

    def copy_text(self):
        """텍스트 복사"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_edit.toPlainText())
        QMessageBox.information(self, "복사 완료", "패키지 정보가 클립보드에 복사되었습니다.")


class CheckBoxTableWidget(QTableWidget):
    """체크박스가 포함된 테이블 위젯"""

    def __init__(self):
        super().__init__()
        self.setSortingEnabled(False)  # 기본으로는 비활성화

    def keyPressEvent(self, event):
        """키보드 이벤트 처리"""
        if event.key() == Qt.Key_Space:
            # Space 키 처리: 선택된 모든 행의 체크박스 토글 (포커스된 행 제외 조건 추가)
            selected_rows = set()

            # 현재 선택된 행들을 가져오기
            selected_indexes = self.selectionModel().selectedIndexes()
            for index in selected_indexes:
                selected_rows.add(index.row())

            current_row = self.currentRow()

            # 포커스된 행이 선택되어 있지 않으면 포커스 행은 제외
            if current_row >= 0:
                if current_row in selected_rows:
                    # 포커스 행이 선택된 상태이므로 선택된 모든 행을 토글
                    pass  # selected_rows를 그대로 사용
                else:
                    # 포커스 행이 선택되지 않은 상태이므로 포커스 행을 제외하고 선택된 행만 토글
                    if current_row in selected_rows:
                        selected_rows.remove(current_row)

            if selected_rows:
                # 첫 번째 선택된 행의 체크박스 상태를 기준으로 설정
                first_row = min(selected_rows)
                first_checkbox_widget = self.cellWidget(first_row, 1)
                if first_checkbox_widget:
                    first_checkbox = first_checkbox_widget.findChild(QCheckBox)
                    if first_checkbox:
                        # 첫 번째 체크박스의 반대 상태로 모든 선택된 행을 설정
                        new_state = not first_checkbox.isChecked()

                        # 이벤트 연결을 임시로 해제하고 일괄 업데이트
                        self.batch_update_checkboxes(selected_rows, new_state)
            return
        elif event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            # Ctrl+C 처리: 선택된 모든 행의 패키지 이름 복사
            selected_rows = set()

            # 현재 선택된 행들을 가져오기
            selected_indexes = self.selectionModel().selectedIndexes()
            for index in selected_indexes:
                selected_rows.add(index.row())

            # 현재 포커스된 행도 포함
            current_row = self.currentRow()
            if current_row >= 0:
                selected_rows.add(current_row)

            if selected_rows:
                # 선택된 모든 행의 패키지 이름 수집
                package_names = []
                for row in sorted(selected_rows):
                    package_name_item = self.item(row, 2)  # Package Name 컬럼
                    if package_name_item:
                        package_names.append(package_name_item.text())

                if package_names:
                    # 패키지 이름들을 \n으로 구분하여 클립보드에 복사
                    clipboard = QApplication.clipboard()
                    clipboard.setText('\n'.join(package_names))

                    # 복사 완료 메시지를 툴팁으로 표시
                    count = len(package_names)
                    self.setToolTip(f"{count}개 패키지 이름이 복사되었습니다")
                    QTimer.singleShot(2000, lambda: self.setToolTip(""))  # 2초 후 툴팁 제거
            return

        super().keyPressEvent(event)

    def batch_update_checkboxes(self, row_indices, new_state):
        """여러 체크박스를 일괄 업데이트하는 최적화된 메서드"""
        # 부모 위젯에서 일괄 업데이트 시작 알림
        parent_widget = self.parent()
        while parent_widget:
            if hasattr(parent_widget, 'start_batch_update'):
                parent_widget.start_batch_update()
                break
            parent_widget = parent_widget.parent()

        try:
            # 체크박스 상태를 빠르게 업데이트
            for row in row_indices:
                checkbox_widget = self.cellWidget(row, 1)
                if checkbox_widget:
                    checkbox = checkbox_widget.findChild(QCheckBox)
                    if checkbox:
                        # 이벤트 차단하고 상태만 변경
                        checkbox.blockSignals(True)
                        checkbox.setChecked(new_state)
                        checkbox.blockSignals(False)

        finally:
            # 일괄 업데이트 완료 알림
            parent_widget = self.parent()
            while parent_widget:
                if hasattr(parent_widget, 'end_batch_update'):
                    parent_widget.end_batch_update(row_indices, new_state)
                    break
                parent_widget = parent_widget.parent()

    def sort(self, column, order):
        """정렬 - Package Name 컬럼(2)만 허용하고 패키지 이름으로만 정렬"""
        if column == 2:  # Package Name 컬럼만 정렬 허용
            # 현재 아이템들을 가져와서 패키지 이름으로 정렬
            items = []
            for row in range(self.rowCount()):
                # 각 행의 데이터를 보존
                row_data = {
                    'index': self.item(row, 0).text() if self.item(row, 0) else "",
                    'checkbox': self.cellWidget(row, 1),
                    'package_name': self.item(row, 2).text() if self.item(row, 2) else "",
                    'is_system': self.item(row, 2).foreground().color() == QColor('gray') if self.item(row, 2) else False
                }
                items.append(row_data)

            # 패키지 이름으로만 정렬
            reverse_order = (order == Qt.DescendingOrder)
            items.sort(key=lambda x: x['package_name'], reverse=reverse_order)

            # 정렬된 데이터로 테이블 업데이트
            for row, item_data in enumerate(items):
                # Index 업데이트 (새 순서로)
                index_item = QTableWidgetItem(str(row + 1))
                index_item.setFlags(index_item.flags() & ~Qt.ItemIsEditable)
                index_item.setTextAlignment(Qt.AlignCenter)
                self.setItem(row, 0, index_item)

                # 체크박스는 기존 것을 그대로 사용
                self.setCellWidget(row, 1, item_data['checkbox'])

                # Package Name
                name_item = QTableWidgetItem(item_data['package_name'])
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                if item_data['is_system']:
                    name_item.setForeground(QColor('gray'))
                else:
                    name_item.setForeground(QColor('black'))
                name_item.setBackground(QColor(255, 255, 255))
                self.setItem(row, 2, name_item)


class PackageListWidget(QWidget):
    """패키지 목록을 표시하는 위젯"""

    def __init__(self):
        super().__init__()
        self.packages = []
        self.filtered_packages = []
        self.search_results = []
        self.current_search_index = -1
        self.current_device_id = None
        # 성능 향상을 위한 패키지 딕셔너리 (이름을 키로 사용)
        self.package_dict = {}
        # 일괄 업데이트 상태
        self.is_batch_updating = False
        # 진행 상황 다이얼로그
        self.progress_dialog = None
        self.operation_worker = None
        # 스크롤바 위치 및 선택된 항목 저장
        self.saved_scroll_position = 0
        self.saved_selected_packages = []
        self.saved_current_row = -1
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # 검색 영역
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("패키지 이름 검색 (정규표현식 지원)")
        self.search_button = QPushButton("검색")
        self.search_button.clicked.connect(self.search_packages)

        # Reset 버튼 추가
        self.reset_search_button = QPushButton("Reset")
        self.reset_search_button.clicked.connect(self.reset_search)

        # 검색 결과 라벨 추가
        self.search_result_label = QLabel("")

        self.search_edit.returnPressed.connect(self.search_packages)

        search_layout.addWidget(QLabel("검색:"))
        search_layout.addWidget(self.search_edit)
        search_layout.addWidget(self.search_button)
        search_layout.addWidget(self.reset_search_button)
        search_layout.addWidget(self.search_result_label)

        layout.addLayout(search_layout)

        # 전체 패키지 갯수 표시 라벨
        self.package_count_label = QLabel("전체 package 갯수 [0]")
        self.package_count_label.setFont(g_FONT_10_bold_ref)
        layout.addWidget(self.package_count_label)

        # 패키지 테이블 (체크박스 테이블 사용) - 인덱스 컬럼 추가
        self.package_table = CheckBoxTableWidget()
        self.package_table.setColumnCount(3)  # index, checkbox, package name
        self.package_table.setHorizontalHeaderLabels(["Index", "선택", "Package Name"])

        # Package Name 컬럼만 정렬 가능하도록 설정
        header = self.package_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)  # Index 컬럼
        header.setSectionResizeMode(1, QHeaderView.Interactive)  # 체크박스 컬럼
        header.setSectionResizeMode(2, QHeaderView.Interactive)  # Package Name 컬럼
        header.setSortIndicatorShown(True)  # 정렬 표시 활성화
        # 수정된 부분: 메서드 존재 여부를 확인하고 연결
        if hasattr(self, 'on_sort_indicator_changed'):
            header.sortIndicatorChanged.connect(self.on_sort_indicator_changed)
        self.package_table.setSortingEnabled(True)

        # 마우스 이벤트 연결 (더블클릭)
        self.package_table.itemDoubleClicked.connect(self.on_package_double_clicked)

        # 마우스 우클릭 더블클릭 이벤트 처리를 위한 이벤트 필터
        self.package_table.viewport().installEventFilter(self)

        # 스크롤바 항상 표시
        self.package_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.package_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)

        # 테이블 스타일 설정
        self.package_table.setStyleSheet("""
            QTableWidget {
                background-color: #f8f9fa;
                color: black;
                gridline-color: #dee2e6;
                selection-background-color: #add8e6;
                selection-color: black;
            }
            QTableWidget::item {
                background-color: #ffffff;
                color: black;
                border-bottom: 1px solid #dee2e6;
                padding: 5px;
            }
            QTableWidget::item:selected {
                background-color: #add8e6;
                color: black;
            }
            QHeaderView::section {
                background-color: #e9ecef;
                color: black;
                padding: 8px;
                border: 1px solid #dee2e6;
                font-weight: bold;
            }
        """)

        # 테이블 설정
        self.package_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.package_table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # 다중 선택 허용
        self.package_table.setAlternatingRowColors(True)
        self.package_table.verticalHeader().setVisible(False)

        # 포커스 정책 설정
        self.package_table.setFocusPolicy(Qt.StrongFocus)

        # 컬럼 너비 설정 (마우스로 조절 가능)
        self.package_table.setColumnWidth(0, 80)  # Index 컬럼 초기 너비
        self.package_table.setColumnWidth(1, 80)  # 체크박스 컬럼 초기 너비
        self.package_table.setColumnWidth(2, 400)  # Package Name 초기 너비

        layout.addWidget(self.package_table)

        # 새로운 체크박스 제어 버튼 레이아웃
        checkbox_control_layout = QHBoxLayout()

        # CheckOn 버튼 추가
        self.check_on_button = QPushButton("Check On")
        self.check_on_button.clicked.connect(self.check_on_selected)
        self.check_on_button.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        checkbox_control_layout.addWidget(self.check_on_button)

        # CheckOff 버튼 추가
        self.check_off_button = QPushButton("Check Off")
        self.check_off_button.clicked.connect(self.check_off_selected)
        self.check_off_button.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
        """)
        checkbox_control_layout.addWidget(self.check_off_button)

        # Toggle 버튼 추가
        self.toggle_button = QPushButton("Toggle")
        self.toggle_button.clicked.connect(self.toggle_selected)
        self.toggle_button.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
        """)
        checkbox_control_layout.addWidget(self.toggle_button)

        checkbox_control_layout.addStretch()
        layout.addLayout(checkbox_control_layout)

        # 기존 버튼 레이아웃
        button_layout = QHBoxLayout()

        # Uninstall 버튼
        self.uninstall_button = QPushButton("Uninstall")
        self.uninstall_button.clicked.connect(self.uninstall_selected)
        button_layout.addWidget(self.uninstall_button)

        # Disable 버튼
        self.disable_button = QPushButton("Disable")
        self.disable_button.clicked.connect(self.disable_selected)
        button_layout.addWidget(self.disable_button)

        # Enable 버튼
        self.enable_button = QPushButton("Enable")
        self.enable_button.clicked.connect(self.enable_selected)
        button_layout.addWidget(self.enable_button)

        # Reset 버튼 (Default로 변경)
        self.reset_button = QPushButton("Default")
        self.reset_button.clicked.connect(self.reset_selected)
        button_layout.addWidget(self.reset_button)

        button_layout.addStretch()

        layout.addLayout(button_layout)

        # 진행률 표시
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def on_sort_indicator_changed(self, logical_index, order):
        """정렬 표시기 변경 시 호출 - Package Name 컬럼만 허용"""
        if logical_index != 2:  # Package Name 컬럼(2)이 아니면
            # Package Name 컬럼으로 정렬 변경
            header = self.package_table.horizontalHeader()
            header.setSortIndicator(2, Qt.AscendingOrder)

    def save_scroll_position(self):
        """현재 스크롤바 위치를 저장"""
        scroll_bar = self.package_table.verticalScrollBar()
        self.saved_scroll_position = scroll_bar.value()

    def restore_scroll_position(self):
        """저장된 스크롤바 위치로 복원"""
        scroll_bar = self.package_table.verticalScrollBar()
        scroll_bar.setValue(self.saved_scroll_position)

    def save_selected_items(self):
        """현재 선택된 항목들과 포커스 행을 저장"""
        # 현재 선택된 패키지 이름들 저장
        self.saved_selected_packages = []
        selected_indexes = self.package_table.selectionModel().selectedIndexes()
        selected_rows = set()

        for index in selected_indexes:
            selected_rows.add(index.row())

        for row in selected_rows:
            package_name_item = self.package_table.item(row, 2)
            if package_name_item:
                self.saved_selected_packages.append(package_name_item.text())

        # 현재 포커스된 행의 패키지 이름 저장
        current_row = self.package_table.currentRow()
        if current_row >= 0:
            package_name_item = self.package_table.item(current_row, 2)
            if package_name_item:
                self.saved_current_row = package_name_item.text()
            else:
                self.saved_current_row = None
        else:
            self.saved_current_row = None

    def restore_selected_items(self):
        """저장된 선택 항목들과 포커스 행을 복원"""
        if not self.saved_selected_packages and self.saved_current_row is None:
            return

        # 패키지 이름으로 행 찾기를 위한 딕셔너리 생성
        package_to_row = {}
        for row in range(self.package_table.rowCount()):
            package_name_item = self.package_table.item(row, 2)
            if package_name_item:
                package_to_row[package_name_item.text()] = row

        # 선택 상태를 클리어하고 새로 설정
        self.package_table.clearSelection()

        # 저장된 선택 항목들을 복원
        for package_name in self.saved_selected_packages:
            if package_name in package_to_row:
                row = package_to_row[package_name]
                self.package_table.selectRow(row)

        # 저장된 포커스 행을 복원
        if self.saved_current_row and self.saved_current_row in package_to_row:
            row = package_to_row[self.saved_current_row]
            self.package_table.setCurrentCell(row, 2)

    def check_on_selected(self):
        """선택된 패키지들의 체크박스를 모두 CheckOn"""
        selected_rows = self.get_selected_rows()
        if not selected_rows:
            QMessageBox.information(self, "알림", "CheckOn할 패키지를 선택해주세요.")
            return

        self.batch_update_selected_checkboxes(selected_rows, True)

    def check_off_selected(self):
        """선택된 패키지들의 체크박스를 모두 CheckOff"""
        selected_rows = self.get_selected_rows()
        if not selected_rows:
            QMessageBox.information(self, "알림", "CheckOff할 패키지를 선택해주세요.")
            return

        self.batch_update_selected_checkboxes(selected_rows, False)

    def toggle_selected(self):
        """선택된 패키지들의 체크박스를 토글"""
        selected_rows = self.get_selected_rows()
        if not selected_rows:
            QMessageBox.information(self, "알림", "토글할 패키지를 선택해주세요.")
            return

        # 첫 번째 선택된 행의 체크박스 상태를 기준으로 토글
        first_row = min(selected_rows)
        first_checkbox_widget = self.package_table.cellWidget(first_row, 1)
        if first_checkbox_widget:
            first_checkbox = first_checkbox_widget.findChild(QCheckBox)
            if first_checkbox:
                # 첫 번째 체크박스의 반대 상태로 모든 선택된 행을 설정
                new_state = not first_checkbox.isChecked()
                self.batch_update_selected_checkboxes(selected_rows, new_state)

    def get_selected_rows(self):
        """선택된 행들의 인덱스 리스트 반환"""
        selected_rows = set()
        selected_indexes = self.package_table.selectionModel().selectedIndexes()
        for index in selected_indexes:
            selected_rows.add(index.row())
        return sorted(list(selected_rows))

    def batch_update_selected_checkboxes(self, row_indices, new_state):
        """선택된 행들의 체크박스를 일괄 업데이트"""
        self.start_batch_update()
        try:
            for row in row_indices:
                checkbox_widget = self.package_table.cellWidget(row, 1)
                if checkbox_widget:
                    checkbox = checkbox_widget.findChild(QCheckBox)
                    if checkbox:
                        checkbox.blockSignals(True)
                        checkbox.setChecked(new_state)
                        checkbox.blockSignals(False)
        finally:
            self.end_batch_update(row_indices, new_state)

    def start_batch_update(self):
        """일괄 업데이트 시작"""
        self.is_batch_updating = True

    def end_batch_update(self, row_indices, new_state):
        """일괄 업데이트 완료 - 패키지 데이터 업데이트"""
        try:
            # 효율적으로 패키지 데이터 업데이트
            for row in row_indices:
                package_name_item = self.package_table.item(row, 2)
                if package_name_item:
                    package_name = package_name_item.text()
                    # 딕셔너리를 사용한 빠른 검색
                    if package_name in self.package_dict:
                        self.package_dict[package_name]['selected'] = new_state
        finally:
            self.is_batch_updating = False

    def on_checkbox_changed(self, state):
        """개별 체크박스 상태 변경 - 최적화됨"""
        # 일괄 업데이트 중이면 개별 처리 건너뛰기
        if self.is_batch_updating:
            return

        checkbox = self.sender()
        row = -1

        # 체크박스가 위치한 행 찾기
        for i in range(self.package_table.rowCount()):
            checkbox_widget = self.package_table.cellWidget(i, 1)
            if checkbox_widget and checkbox_widget.findChild(QCheckBox) == checkbox:
                row = i
                break

        if row != -1:
            # 패키지 데이터 업데이트
            package_name_item = self.package_table.item(row, 2)
            if package_name_item:
                package_name = package_name_item.text()
                # 딕셔너리를 사용한 빠른 업데이트
                if package_name in self.package_dict:
                    package = self.package_dict[package_name]
                    package['selected'] = (state == Qt.Checked)

                    # 체크박스 상태에 따라 작업 수행
                    if state == Qt.Checked:
                        self.install_or_enable_package(package_name, package['is_system'])

    def install_or_enable_package(self, package_name, is_system):
        """패키지 설치 또는 활성화"""
        if not self.current_device_id:
            return

        try:
            if is_system:
                # 시스템 앱은 활성화
                cmd = f"adb -s {self.current_device_id} shell pm enable {package_name}"
            else:
                # 일반 앱은 설치 (이미 설치된 경우 활성화)
                cmd = f"adb -s {self.current_device_id} shell pm enable {package_name}"

            subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        except Exception as e:
            print(f"패키지 활성화 실패: {package_name}, 오류: {str(e)}")

    def eventFilter(self, obj, event):
        """이벤트 필터 - 마우스 우클릭 더블클릭 감지"""
        if obj == self.package_table.viewport():
            if event.type() == QEvent.MouseButtonDblClick:
                if event.button() == Qt.RightButton:
                    item = self.package_table.itemAt(event.pos())
                    if item:
                        self.on_package_right_double_clicked(item)
                    return True
        return super().eventFilter(obj, event)

    def on_package_double_clicked(self, item):
        """패키지 더블클릭 이벤트 (왼쪽 버튼)"""
        if not self.current_device_id:
            QMessageBox.warning(self, "경고", "선택된 디바이스가 없습니다.")
            return

        if item.column() <= 1:  # Index나 체크박스 컬럼이면 무시
            return

        row = item.row()
        package_name_item = self.package_table.item(row, 2)  # Package Name 컬럼
        if package_name_item:
            package_name = package_name_item.text()
            dialog = PackageInfoDialog(self.current_device_id, package_name, self)
            dialog.exec_()

    def on_package_right_double_clicked(self, item):
        """패키지 마우스 우클릭 더블클릭 이벤트"""
        if not self.current_device_id:
            QMessageBox.warning(self, "경고", "선택된 디바이스가 없습니다.")
            return

        if item.column() <= 1:  # Index나 체크박스 컬럼이면 무시
            return

        row = item.row()
        package_name_item = self.package_table.item(row, 2)  # Package Name 컬럼
        if package_name_item:
            package_name = package_name_item.text()
            dialog = PackageDetailDialog(self.current_device_id, package_name, self)
            dialog.exec_()

    def keyPressEvent(self, event):
        """키보드 이벤트 처리"""
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ControlModifier:
            # Ctrl+F 처리: 검색 Edit로 포커스 설정
            self.search_edit.setFocus()
            self.search_edit.selectAll()
            return
        elif event.key() == Qt.Key_F3:
            if self.search_edit.hasFocus() and self.search_edit.text().strip():
                # 검색 Edit 창에 포커스가 있고 문자가 있을 때
                self.search_packages()
            elif self.package_table.hasFocus() and self.search_results:
                # 패키지 리스트에 포커스가 있을 때 이전 검색 결과로 이동
                self.find_previous()
        elif event.key() == Qt.Key_F4:
            if self.search_edit.hasFocus() and self.search_edit.text().strip():
                # 검색 Edit 창에 포커스가 있고 문자가 있을 때
                self.search_packages()
            elif self.package_table.hasFocus() and self.search_results:
                # 패키지 리스트에 포커스가 있을 때 다음 검색 결과로 이동
                self.find_next()
        else:
            super().keyPressEvent(event)

    def reset_search(self):
        """검색 리셋"""
        self.search_edit.clear()
        self.search_result_label.setText("")
        self.clear_search_highlights()
        self.search_results = []
        self.current_search_index = -1

    def search_packages(self):
        """패키지 검색"""
        search_text = self.search_edit.text().strip()
        if not search_text:
            QMessageBox.warning(self, "경고", "검색할 문자를 입력해주세요.")
            return

        try:
            pattern = re.compile(search_text, re.IGNORECASE)
            self.search_results = []

            # 먼저 모든 하이라이트 제거
            self.clear_search_highlights()

            for row in range(self.package_table.rowCount()):
                package_name_item = self.package_table.item(row, 2)  # Package Name 컬럼
                if package_name_item and pattern.search(package_name_item.text()):
                    self.search_results.append(row)

            # 검색 결과 갯수 표시
            self.search_result_label.setText(f"검색[{len(self.search_results)}]")

            # 검색 결과 하이라이트
            self.highlight_search_results()

            # 패키지 테이블로 포커스 이동
            self.package_table.setFocus()

            # 첫 번째 검색 결과로 이동
            self.current_search_index = -1
            if self.search_results:
                self.find_next()

        except re.error as e:
            QMessageBox.warning(self, "정규표현식 오류", f"잘못된 정규표현식입니다: {str(e)}")

    def highlight_search_results(self):
        """검색 결과 하이라이트 - Package Name 컬럼을 노란색 배경"""
        for row in self.search_results:
            # Package Name 컬럼만 연한 노란색 배경으로 변경
            name_item = self.package_table.item(row, 2)
            if name_item:
                name_item.setBackground(QColor(255, 255, 224))  # 연한 노란색

    def clear_search_highlights(self):
        """검색 하이라이트 제거"""
        for row in range(self.package_table.rowCount()):
            # Package Name 컬럼의 배경색 초기화
            name_item = self.package_table.item(row, 2)
            if name_item:
                # 원래 배경색으로 복원
                name_item.setBackground(QColor(255, 255, 255))  # 흰색 배경

    def find_next(self):
        """다음 검색 결과로 이동 - 경계값 확인 후 이동"""
        if not self.search_results:
            return

        # 현재 포커스된 행 가져오기
        current_row = self.package_table.currentRow()

        # 현재 포커스 행보다 큰 검색 결과 중 가장 가까운 것 찾기
        next_rows = [row for row in self.search_results if row > current_row]

        if next_rows:
            # 가장 가까운 다음 결과로 이동
            next_row = min(next_rows)
            self.current_search_index = self.search_results.index(next_row)
        else:
            # 현재 포커스가 마지막 검색 결과보다 크거나 같으면 현재 위치 유지
            max_search_row = max(self.search_results) if self.search_results else -1
            if current_row >= max_search_row:
                return  # 현재 위치에 머물기
            else:
                # 첫 번째 검색 결과로 순환
                next_row = self.search_results[0]
                self.current_search_index = 0

        self.package_table.selectRow(next_row)
        self.package_table.scrollToItem(self.package_table.item(next_row, 2))

    def find_previous(self):
        """이전 검색 결과로 이동 - 경계값 확인 후 이동"""
        if not self.search_results:
            return

        # 현재 포커스된 행 가져오기
        current_row = self.package_table.currentRow()

        # 현재 포커스 행보다 작은 검색 결과 중 가장 가까운 것 찾기
        prev_rows = [row for row in self.search_results if row < current_row]

        if prev_rows:
            # 가장 가까운 이전 결과로 이동
            prev_row = max(prev_rows)
            self.current_search_index = self.search_results.index(prev_row)
        else:
            # 현재 포커스가 첫 번째 검색 결과보다 작거나 같으면 현재 위치 유지
            min_search_row = min(self.search_results) if self.search_results else float('inf')
            if current_row <= min_search_row:
                return  # 현재 위치에 머물기
            else:
                # 마지막 검색 결과로 순환
                prev_row = self.search_results[-1]
                self.current_search_index = len(self.search_results) - 1

        self.package_table.selectRow(prev_row)
        self.package_table.scrollToItem(self.package_table.item(prev_row, 2))

    def load_packages(self, device_id):
        """패키지 목록 로드"""
        self.current_device_id = device_id
        self.clear_packages()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.worker = PackageWorker(device_id)
        self.worker.package_loaded.connect(self.on_packages_loaded)
        self.worker.progress_updated.connect(self.progress_bar.setValue)
        self.worker.error_occurred.connect(self.on_error)
        self.worker.start()

    @pyqtSlot(list)
    def on_packages_loaded(self, packages):
        """패키지 로드 완료 - 최적화됨"""
        self.packages = packages
        self.filtered_packages = packages.copy()

        # 패키지 딕셔너리 생성 (빠른 검색을 위해)
        self.package_dict = {pkg['name']: pkg for pkg in packages}

        self.display_packages()
        self.progress_bar.setVisible(False)

        # 패키지 목록 로드 후 선택된 항목들 복원
        QTimer.singleShot(100, self.restore_selected_items)

    @pyqtSlot(str)
    def on_error(self, error_message):
        """오류 처리"""
        QMessageBox.critical(self, "오류", error_message)
        self.progress_bar.setVisible(False)

    def display_packages(self):
        """패키지 목록 표시 - 최적화됨"""
        self.package_table.setRowCount(len(self.filtered_packages))

        # 전체 패키지 갯수 표시 업데이트
        self.package_count_label.setText(f"전체 package 갯수 [{len(self.filtered_packages)}]")

        # 업데이트 시작을 알림
        self.package_table.setUpdatesEnabled(False)  # UI 업데이트 임시 중단

        try:
            for row, package in enumerate(self.filtered_packages):
                # Index 컬럼 (정렬 불가)
                index_item = QTableWidgetItem(str(row + 1))
                index_item.setFlags(index_item.flags() & ~Qt.ItemIsEditable)
                index_item.setTextAlignment(Qt.AlignCenter)
                self.package_table.setItem(row, 0, index_item)

                # 체크박스
                checkbox = QCheckBox()
                checkbox.setChecked(package.get('selected', False))
                checkbox.stateChanged.connect(self.on_checkbox_changed)
                # 시스템 앱은 회색으로 표시
                if package['is_system']:
                    checkbox.setStyleSheet("color: gray;")

                # 체크박스를 가운데 정렬
                checkbox_widget = QWidget()
                checkbox_layout = QHBoxLayout(checkbox_widget)
                checkbox_layout.addWidget(checkbox)
                checkbox_layout.setAlignment(Qt.AlignCenter)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)

                self.package_table.setCellWidget(row, 1, checkbox_widget)

                # Package Name
                name_item = QTableWidgetItem(package['name'])
                name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
                if package['is_system']:
                    name_item.setForeground(QColor('gray'))
                else:
                    name_item.setForeground(QColor('black'))
                # 배경색을 명시적으로 설정
                name_item.setBackground(QColor(255, 255, 255))  # 흰색 배경
                self.package_table.setItem(row, 2, name_item)

        finally:
            self.package_table.setUpdatesEnabled(True)  # UI 업데이트 재개

    def get_selected_packages(self):
        """선택된 패키지 목록 반환"""
        selected_packages = []

        for row in range(self.package_table.rowCount()):
            checkbox_widget = self.package_table.cellWidget(row, 1)
            if checkbox_widget:
                checkbox = checkbox_widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    package_name_item = self.package_table.item(row, 2)
                    if package_name_item:
                        selected_packages.append(package_name_item.text())

        return selected_packages

    def uninstall_selected(self):
        """선택된 패키지 삭제"""
        selected_packages = self.get_selected_packages()

        if not selected_packages:
            QMessageBox.information(self, "알림", "삭제할 패키지를 선택해주세요.")
            return

        reply = QMessageBox.question(self, "확인",
                                     f"{len(selected_packages)}개의 패키지를 삭제하시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 스크롤 위치 저장 (uninstall은 스크롤바만 저장)
            self.save_scroll_position()
            self.perform_package_operation(selected_packages, "uninstall")

    def disable_selected(self):
        """선택된 패키지 비활성화"""
        selected_packages = self.get_selected_packages()

        if not selected_packages:
            QMessageBox.information(self, "알림", "비활성화할 패키지를 선택해주세요.")
            return

        reply = QMessageBox.question(self, "확인",
                                     f"{len(selected_packages)}개의 패키지를 비활성화하시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 스크롤 위치 및 선택 항목 저장
            self.save_scroll_position()
            self.save_selected_items()
            self.perform_package_operation(selected_packages, "disable")

    def enable_selected(self):
        """선택된 패키지 활성화"""
        selected_packages = self.get_selected_packages()

        if not selected_packages:
            QMessageBox.information(self, "알림", "활성화할 패키지를 선택해주세요.")
            return

        reply = QMessageBox.question(self, "확인",
                                     f"{len(selected_packages)}개의 패키지를 활성화하시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 스크롤 위치 및 선택 항목 저장
            self.save_scroll_position()
            self.save_selected_items()
            self.perform_package_operation(selected_packages, "enable")

    def reset_selected(self):
        """선택된 패키지 재설정"""
        selected_packages = self.get_selected_packages()

        if not selected_packages:
            QMessageBox.information(self, "알림", "재설정할 패키지를 선택해주세요.")
            return

        reply = QMessageBox.question(self, "확인",
                                     f"{len(selected_packages)}개의 패키지를 기본 상태로 재설정하시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 스크롤 위치 및 선택 항목 저장
            self.save_scroll_position()
            self.save_selected_items()
            self.perform_package_operation(selected_packages, "reset")

    def perform_package_operation(self, packages, operation):
        """패키지 작업 실행 - 진행 다이얼로그와 함께"""
        if not self.current_device_id:
            QMessageBox.warning(self, "경고", "선택된 디바이스가 없습니다.")
            return

        # 진행 다이얼로그 생성
        self.progress_dialog = ProgressDialog(operation, len(packages), self)

        # 워커 스레드 생성
        self.operation_worker = PackageOperationWorker(self.current_device_id, packages, operation)

        # 시그널 연결
        self.operation_worker.progress_updated.connect(self.progress_dialog.update_progress)
        self.operation_worker.operation_completed.connect(self.on_operation_completed)
        self.operation_worker.error_occurred.connect(self.on_operation_error)
        self.progress_dialog.cancel_requested.connect(self.operation_worker.cancel)

        # 워커 스레드 시작
        self.operation_worker.start()

        # 진행 다이얼로그 표시
        self.progress_dialog.exec_()

    @pyqtSlot(list)
    def on_operation_completed(self, failed_packages):
        """패키지 작업 완료"""
        operation_names = {
            "uninstall": "삭제",
            "disable": "비활성화",
            "enable": "활성화",
            "reset": "재설정"
        }

        # 결과 메시지 표시
        if failed_packages:
            operation_name = operation_names.get(self.operation_worker.operation, "처리")
            QMessageBox.warning(self, "경고",
                                f"다음 패키지 {operation_name}에 실패했습니다:\n" + "\n".join(failed_packages))

        # 패키지 목록 새로고침
        self.load_packages(self.current_device_id)

        # 작업 완료 후 복원 처리
        if self.operation_worker.operation == "uninstall":
            # uninstall의 경우 스크롤 위치만 복원
            QTimer.singleShot(1000, self.restore_scroll_position)
        else:
            # enable/disable/default의 경우 스크롤 위치와 선택 항목 모두 복원
            QTimer.singleShot(1000, self.restore_scroll_position)
            # 선택 항목 복원은 패키지 로드 완료 후에 처리됨 (on_packages_loaded에서)

        # 정리
        self.operation_worker = None
        self.progress_dialog = None

    @pyqtSlot(str)
    def on_operation_error(self, error_message):
        """패키지 작업 오류"""
        if self.progress_dialog:
            self.progress_dialog.accept()

        QMessageBox.critical(self, "오류", f"작업 중 오류가 발생했습니다: {error_message}")

        # 정리
        self.operation_worker = None
        self.progress_dialog = None

    def clear_packages(self):
        """패키지 목록 초기화"""
        self.package_table.setRowCount(0)
        self.packages = []
        self.filtered_packages = []
        self.package_dict = {}  # 딕셔너리도 초기화
        self.search_results = []
        self.current_search_index = -1
        self.search_edit.clear()
        self.search_result_label.setText("")
        self.package_count_label.setText("전체 package 갯수 [0]")
        self.clear_search_highlights()


class AndroidPackageManager(QMainWindow):
    """메인 애플리케이션 클래스"""

    def __init__(self):
        super().__init__()
        self.init_ui()
        self.load_devices()

    def init_ui(self):
        self.setWindowTitle("Android Package Manager")

        # 최대화면 시작
        # self.showMaximized()
        self.setWindowState(Qt.WindowMaximized)

        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 메인 레이아웃
        layout = QVBoxLayout()

        # 스플리터 생성
        splitter = QSplitter(Qt.Vertical)

        # 상단: 디바이스 목록
        device_frame = QFrame()
        device_layout = QVBoxLayout()
        device_layout.addWidget(QLabel("연결된 디바이스 목록 (더블클릭으로 선택 / F5로 연결된 단말 갱신)"))

        self.device_list = QListWidget()
        self.device_list.itemDoubleClicked.connect(self.on_device_selected)
        device_layout.addWidget(self.device_list)
        device_frame.setLayout(device_layout)

        # 하단: 패키지 목록
        self.package_widget = PackageListWidget()

        # 스플리터에 위젯 추가
        splitter.addWidget(device_frame)
        splitter.addWidget(self.package_widget)

        # 초기 크기 비율 설정 (상단:하단)
        splitter.setSizes([50, 750])

        layout.addWidget(splitter)
        central_widget.setLayout(layout)

        # 상태바
        self.statusBar().showMessage("준비")

        # 패키지 위젯이 포커스를 받을 수 있도록 설정
        self.package_widget.setFocusPolicy(Qt.StrongFocus)

    def load_devices(self):
        """연결된 디바이스 목록 로드"""
        try:
            result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
            devices = []

            for line in result.stdout.split('\n')[1:]:
                if line.strip() and '\tdevice' in line:
                    device_id = line.split('\t')[0]
                    devices.append(device_id)

            # 디바이스 목록 정렬
            devices.sort()

            self.device_list.clear()
            for device in devices:
                self.device_list.addItem(device)

            self.statusBar().showMessage(f"{len(devices)}개의 디바이스가 연결됨")

        except Exception as e:
            QMessageBox.critical(self, "오류", f"디바이스 목록을 가져올 수 없습니다: {str(e)}")

    def on_device_selected(self, item):
        """디바이스 선택 시 패키지 목록 로드"""
        device_id = item.text()
        self.statusBar().showMessage(f"디바이스 {device_id}의 패키지 로드")

        # 패키지 목록 로드
        self.package_widget.load_packages(device_id)

        # 패키지 위젯에 포커스 설정 (키보드 이벤트를 받기 위해)
        self.package_widget.setFocus()

    def keyPressEvent(self, event):
        """메인 윈도우 키 이벤트"""
        if event.key() == Qt.Key_F and event.modifiers() == Qt.ControlModifier:
            # Ctrl+F 처리: 패키지 위젯의 검색 Edit로 포커스 설정
            self.package_widget.search_edit.setFocus()
            self.package_widget.search_edit.selectAll()
        elif event.key() == Qt.Key_F5:
            # F5로 디바이스 목록 새로고침
            self.load_devices()
        else:
            super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)

    # ADB가 설치되어 있는지 확인
    try:
        subprocess.run("adb version", shell=True, capture_output=True, check=True)
    except subprocess.CalledProcessError:
        QMessageBox.critical(None, "오류", "ADB가 설치되어 있지 않거나 PATH에 등록되어 있지 않습니다.")
        sys.exit(1)

    window = AndroidPackageManager()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()