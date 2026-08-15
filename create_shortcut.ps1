# 创建桌面快捷方式: 音频自动闪避助手 (双击启动, 无控制台)
$ErrorActionPreference = "Stop"
$project = $PSScriptRoot
$pythonw = Join-Path $project ".venv\Scripts\pythonw.exe"
$icon = Join-Path $project "icon.ico"
$aumid = "AudioDuck.AudioDuckingAssistant.1"

if (-not (Test-Path $pythonw)) {
    Write-Host "未找到运行环境 (.venv)，请先双击 run.bat 完成初始化。"
    Read-Host "按回车退出"
    exit 1
}
if (-not (Test-Path $icon)) {
    Write-Host "未找到图标文件 icon.ico。"
    Read-Host "按回车退出"
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "音频自动闪避助手.lnk"
$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = $pythonw
$lnk.Arguments = "main.py"
$lnk.WorkingDirectory = $project
$lnk.IconLocation = $icon + ",0"
$lnk.Description = "音频自动闪避助手 - 直播/语音聊天自动压低背景声音"
$lnk.Save()

# 给快捷方式写入 AppUserModelID, 保证任务栏显示自定义图标
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class AumidHelper {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SHGetPropertyStoreFromParsingName(string pszPath, IntPtr pbc, int flags, ref Guid riid, out IntPtr ppv);

    [ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IPropertyStore {
        int GetCount(out uint cProps);
        int GetAt(uint iProp, out PKEY key);
        int GetValue(ref PKEY key, out PROPVARIANT pv);
        int SetValue(ref PKEY key, ref PROPVARIANT pv);
        int Commit();
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PKEY { public Guid fmtid; public uint pid; }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROPVARIANT {
        public ushort vt;
        public ushort wReserved1;
        public ushort wReserved2;
        public ushort wReserved3;
        public IntPtr pValue;
    }

    public static void Set(string lnkPath, string aumid) {
        Guid fmtid = new Guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"); // PKEY_AppUserModel_ID
        Guid iid = new Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99");
        IntPtr ppv;
        int hr = SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, 2, ref iid, out ppv);
        if (hr != 0) throw new COMException("SHGetPropertyStoreFromParsingName: " + hr);
        IPropertyStore store = (IPropertyStore)Marshal.GetObjectForIUnknown(ppv);
        PKEY key = new PKEY { fmtid = fmtid, pid = 5 };
        PROPVARIANT pv = new PROPVARIANT { vt = 31, pValue = Marshal.StringToCoTaskMemUni(aumid) }; // VT_LPWSTR
        try {
            store.SetValue(ref key, ref pv);
            store.Commit();
        } finally {
            Marshal.FreeCoTaskMem(pv.pValue);
            Marshal.ReleaseComObject(store);
        }
    }
}
"@
try {
    [AumidHelper]::Set($lnkPath, $aumid)
    Write-Host "已写入 AppUserModelID: $aumid"
} catch {
    Write-Host ("AppUserModelID 写入失败(不影响快捷方式): " + $_.Exception.Message)
}

Write-Host ("已创建桌面快捷方式: " + $lnkPath)

