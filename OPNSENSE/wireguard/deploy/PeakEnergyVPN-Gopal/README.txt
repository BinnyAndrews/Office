Peak Energy VPN — Gopal (venu.gopal.reddy)

1) Install WireGuard if missing: https://www.wireguard.com/install/
2) As Admin once (if tunnel not installed yet):
   "C:\Program Files\WireGuard\wireguard.exe" /installtunnelservice "C:\DEV\HOME\venu.gopal.reddy.conf"
   sc.exe config WireGuardTunnel$venu.gopal.reddy start= delayed-auto
3) Optional no-UAC (Admin once):
   powershell -ExecutionPolicy Bypass -File ..\Fix-PeakWG-NoUAC.ps1 -TunnelName venu.gopal.reddy
4) Copy this folder to the laptop Desktop; run PeakEnergyVPN.exe
   Turn OFF on PETCPL · Turn ON when remote.
