# Restoring OPNsense `config.xml`

## Before you restore

1. Fresh OPNsense install completed; you can reach the GUI.
2. Note real NIC names: **Interfaces → Assignments**.
3. Edit `nics.env`:
   ```env
   NIC_WAN=igc0
   NIC_WAN2=igc1
   NIC_LAN=igc2
   ```
   Use your actual names (`igb0`, `em0`, `ix0`, etc.).
4. Rebuild:
   ```powershell
   cd c:\tools\FortigateConfig\peak-opnsense-omada-migration\opnsense
   python build_config_xml.py
   ```
5. Confirm `config.xml` contains your NIC names (search for `igc0` etc.).

## Apply

1. **System → Configuration → Backups**.
2. **Restore** → choose `config.xml`.
3. Reboot when prompted.

## Immediately after restore

1. Connect a laptop to a **VLAN 100** access port on the Omada switch (or temporarily put the LAN NIC and laptop on a simple switch with VLAN 100 if Omada is not ready).
2. Open `https://10.80.100.1:4444`
3. Log in with the password from the installer (or reset via console if locked out).
4. Set a new root password.
5. **Interfaces → opt1 (WAN_JIO)** → enable **WAN** checkbox if needed → Apply.
6. Plug Airtel / Jio when ready; check **System → Gateways**.

## Safety

- Restoring **replaces** the running config. Only do this on a box you are willing to wipe.
- Wrong NIC names = no network. Fix via console: assign interfaces, or rebuild XML and restore again.
- Do not expose port 4444 on WAN.

## If GUI is unreachable after restore

1. Console: `1)` Assign interfaces — map WAN/LAN correctly.  
2. Or factory reset and restore a corrected `config.xml`.
