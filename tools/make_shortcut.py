"""'멜야옹 체크기' 바로가기(아이콘 포함)를 프로젝트 폴더와 바탕화면에 만든다.  사용: py tools/make_shortcut.py

- 한글 경로가 깨지지 않도록 PowerShell 명령을 UTF-16 으로 인코딩해서 넘긴다(-EncodedCommand).
- 만든 뒤 실제로 파일이 생겼는지, 아이콘이 들어갔는지 다시 읽어서 확인한다.
- Windows 아이콘 캐시를 새로 고쳐서 바뀐 아이콘이 바로 보이게 한다.
"""
import base64
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "멜야옹 체크기.lnk"


def ps(script: str) -> str:
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-EncodedCommand", enc], capture_output=True)
    if r.returncode:
        raise SystemExit(r.stderr.decode("cp949", "replace"))
    return r.stdout.decode("utf-8", "replace").strip()


def make(lnk: Path):
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    ps(f"""
$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}')
$s.TargetPath = '{pythonw}'
$s.Arguments = '"{ROOT / "main.py"}"'
$s.WorkingDirectory = '{ROOT}'
$s.IconLocation = '{ROOT / "assets" / "icon.ico"},0'
$s.Description = '마비노기 버프·디버프 알림'
$s.Save()
""")
    if not lnk.exists():
        raise SystemExit(f"바로가기가 만들어지지 않았습니다: {lnk}")
    print("만듦:", lnk)


def desktop() -> Path:
    """실제 바탕화면 폴더 (OneDrive 로 옮겨진 경우 포함)."""
    out = ps("[Console]::OutputEncoding=[Text.Encoding]::UTF8; [Environment]::GetFolderPath('Desktop')")
    return Path(out) if out else Path(os.path.expandvars(r"%USERPROFILE%\Desktop"))


if __name__ == "__main__":
    make(ROOT / NAME)
    make(desktop() / NAME)
    subprocess.run(["ie4uinit.exe", "-show"], capture_output=True)      # 아이콘 캐시 새로 고침
