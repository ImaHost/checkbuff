"""관리자 권한으로 실행 (UAC 창은 처음 한 번만).

마비노기가 관리자 권한으로 돌아가서, 게임 안에서 단축키·키 입력을 쓰려면 이 프로그램도 관리자여야 한다.
매번 UAC 창이 뜨지 않도록:
1) 처음 한 번 UAC 로 관리자 권한을 얻으면, 작업 스케줄러에 '가장 높은 권한으로 실행' 작업을 등록한다
   (트리거 없음 = 자동으로 켜지지 않고, 이 프로그램이 부를 때만 실행).
2) 다음부터는 일반 권한으로 켜졌을 때 그 작업을 실행(schtasks /run)하고 스스로 종료 → UAC 창 없이 관리자로 켜짐.
3) exe 를 다른 곳으로 옮기면 작업의 경로가 달라지므로 그때 한 번 다시 UAC 로 등록한다.

PyInstaller 한 파일 exe 가 자기 자신을 다시 켤 때는 PYINSTALLER_RESET_ENVIRONMENT=1 을 줘야
새 임시 폴더로 독립 실행된다 (안 주면 이전 프로세스의 임시 폴더를 이어 써서, 종료 때 '임시 폴더 삭제 실패' 경고).
Qt 를 쓰지 않으므로 앱 시작 전에 부를 수 있다.
"""
import ctypes
import getpass
import os
import re
import subprocess
import sys
import tempfile

FROZEN = getattr(sys, "frozen", False)
NO_WINDOW = 0x08000000


def reset_env_for_child():
    """자기 자신을 다시 켜기 전에 호출 (새 프로세스가 독립된 임시 폴더를 쓰도록)."""
    if FROZEN:
        os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def target() -> tuple[str, list[str], str]:
    """(실행 파일, 인자, 작업 폴더) — exe 면 exe 자신, 소스면 pythonw + main.py"""
    if FROZEN:
        return sys.executable, [], os.path.dirname(sys.executable)
    script = os.path.abspath(sys.argv[0])
    exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(exe):
        exe = sys.executable
    return exe, [script], os.path.dirname(script)


def task_name() -> str:
    user = re.sub(r"[^\w.-]", "_", getpass.getuser())
    return f"MelyaongChecker{'' if FROZEN else '-dev'}_{user}"


def _schtasks(*args, capture=True):
    return subprocess.run(["schtasks", *args], capture_output=capture, creationflags=NO_WINDOW)


def _task_command() -> str | None:
    """등록된 작업의 실행 파일 경로 (없으면 None)."""
    r = _schtasks("/query", "/tn", task_name(), "/xml")
    if r.returncode:
        return None
    xml = r.stdout.decode("utf-16", "replace") if r.stdout[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else r.stdout.decode("utf-8", "replace")
    m = re.search(r"<Command>(.*?)</Command>", xml)
    return m.group(1).strip().strip('"') if m else None


def task_ready() -> bool:
    cmd = _task_command()
    return bool(cmd) and os.path.normcase(cmd) == os.path.normcase(target()[0])


def register_task() -> bool:
    """관리자 권한일 때만 가능. 트리거 없는 '가장 높은 권한' 작업을 등록/갱신."""
    exe, args, cwd = target()
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    arg_str = " ".join(f'"{a}"' for a in [*args, "--no-admin", "--from-task"])
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>멜야옹 체크기를 관리자 권한으로 실행 (UAC 창 없이). 트리거 없음.</Description></RegistrationInfo>
  <Principals>
    <Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>Parallel</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <AllowStartOnDemand>true</AllowStartOnDemand>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{esc(exe)}</Command><Arguments>{esc(arg_str)}</Arguments><WorkingDirectory>{esc(cwd)}</WorkingDirectory></Exec>
  </Actions>
</Task>"""
    fd, path = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-16") as f:
            f.write(xml)
        return _schtasks("/create", "/tn", task_name(), "/xml", path, "/f").returncode == 0
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def remove_task():
    _schtasks("/delete", "/tn", task_name(), "/f")


def run_task() -> bool:
    return _schtasks("/run", "/tn", task_name()).returncode == 0


def relaunch_as_admin_with_uac(extra=("--register-task",)) -> bool:
    exe, args, cwd = target()
    reset_env_for_child()
    params = " ".join(f'"{a}"' for a in [*args, *sys.argv[1:], "--no-admin", *extra])
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, cwd, 1) > 32


def ensure_admin(auto_task: bool = True):
    """앱 시작 맨 앞에서 호출. 관리자가 아니면 (작업 → 없으면 UAC) 로 관리자 인스턴스를 켜고 종료.
    관리자면 필요할 때 작업을 등록/갱신."""
    if os.environ.get("CHECKBUFF_NO_ADMIN"):
        return
    if is_admin():
        if auto_task and ("--register-task" in sys.argv or not task_ready()):
            register_task()
        return
    if "--no-admin" in sys.argv:          # 관리자 인스턴스를 켜려다 사용자가 UAC 를 거절한 경우 등
        return
    try:
        if auto_task and task_ready() and run_task():
            sys.exit(0)                   # UAC 없이 작업으로 관리자 인스턴스가 켜짐
        if relaunch_as_admin_with_uac(("--register-task",) if auto_task else ()):
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass                              # 실패하면 일반 권한으로 그냥 실행
