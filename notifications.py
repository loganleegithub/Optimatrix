"""Best-effort local desktop alerts; never interpret delivery as guaranteed."""
import subprocess
import sys


def notify_desktop(reason):
    if sys.platform != 'darwin':
        return {'status':'unavailable', 'detail':'当前系统未配置桌面通知；请查看页面告警'}
    script = 'on run argv\n display notification (item 1 of argv) with title "Optimatrix Testnet"\nend run'
    try:
        result = subprocess.run(['osascript','-e',script,str(reason)[:240]],
                                capture_output=True, timeout=2, check=False)
        if result.returncode == 0:
            return {'status':'requested_unconfirmed', 'detail':'已请求系统通知；系统勿扰或权限可能阻止显示，未确认送达'}
    except (OSError,subprocess.SubprocessError):
        pass
    return {'status':'failed', 'detail':'本机桌面通知请求失败；页面与持久化告警仍保留'}
