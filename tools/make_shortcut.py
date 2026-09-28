"""'버프체크기' 바로가기(아이콘 포함)를 프로젝트 폴더와 바탕화면에 만든다.  사용: py tools/make_shortcut.py"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def make(lnk: Path):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    ps = f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}')
$s.TargetPath = '{pythonw}'
$s.Arguments = '"{ROOT / "main.py"}"'
$s.WorkingDirectory = '{ROOT}'
$s.IconLocation = '{ROOT / "assets" / "icon.ico"},0'
$s.Description = '마비노기 버프 남은 시간 감시'
$s.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    print("만듦:", lnk)


if __name__ == "__main__":
    make(ROOT / "버프체크기.lnk")
    desktop = Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))
    onedrive = Path(os.path.expandvars(r"%OneDrive%\Desktop")) if os.environ.get("OneDrive") else None
    for d in (desktop, onedrive):
        if d and d.is_dir():
            make(d / "버프체크기.lnk")
            break
