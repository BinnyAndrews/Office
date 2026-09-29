# Peak Energy Biometrics

Separate copy of the Peak Energy Hikvision attendance app. The original project in `PEAK ENERGY BIOMETRICS` is unchanged.

Entry and exit readers stay `10.80.100.11` and `10.80.100.12`. Punches stay in `master.dbo.atteninfo` for Keka.

## Run

```powershell
cd c:\DEV\OFFICE\PeakEnergyBiometrics
py -3 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
copy appsettings.example.json appsettings.json
.\start-ui.cmd
```

On first launch set the SQL password, then **Create / Repair database**. That adds helper tables only and does not wipe `atteninfo`.

## Install with Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

Startup uses the same shortcut and task names as the original app (`Peak Energy Biometrics`, `Peak-Energy-Biometrics-Collector`). Install this copy only on a PC that should run this folder.

## Build

```bat
build-exe.cmd
```

Output: `dist\PeakEnergyBiometrics.exe`
