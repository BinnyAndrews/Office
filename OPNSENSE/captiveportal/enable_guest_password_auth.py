#!/usr/bin/env python3
"""Enable Local Database auth + password policy for Peak guest portal."""
from __future__ import annotations

import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config-PEAK-CORP-FW.xml"


def ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    return el


def set_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = ensure_child(parent, tag)
    el.text = text
    return el


def main() -> None:
    tree = ET.parse(CONFIG)
    root = tree.getroot()
    system = root.find("system")
    assert system is not None

    # --- password policy on Local Database ---
    # Remove prior Local Database authserver entries, then add policy-enabled one.
    for el in list(system.findall("authserver")):
        name = el.findtext("name") or ""
        typ = el.findtext("type") or ""
        if name == "Local Database" or typ == "local":
            system.remove(el)

    auth = ET.Element("authserver")
    # Insert near top of system for readability (after domain-ish settings is fine at end of children)
    system.append(auth)
    set_text(auth, "name", "Local Database")
    set_text(auth, "type", "local")
    set_text(auth, "enable_password_policy_constraints", "1")
    # Duration 0 = do not auto-expire (avoids locking root + shared guest via GUI change flow).
    # Rotate guest password operationally every 90 days instead.
    set_text(auth, "password_policy_duration", "0")
    set_text(auth, "password_policy_length", "12")
    set_text(auth, "password_policy_complexity", "1")
    set_text(auth, "password_policy_compliance", "")

    # --- guest group (no GUI privileges) ---
    guest_gid = "2000"
    guest_group = None
    for g in system.findall("group"):
        if g.findtext("name") == "guestportal":
            guest_group = g
            break
    if guest_group is None:
        guest_group = ET.Element("group", {"uuid": str(uuid.uuid4())})
        # place after admins group
        admins = None
        for i, child in enumerate(list(system)):
            if child.tag == "group" and child.findtext("name") == "admins":
                admins = i
                break
        if admins is not None:
            system.insert(admins + 1, guest_group)
        else:
            system.append(guest_group)
    set_text(guest_group, "gid", guest_gid)
    set_text(guest_group, "name", "guestportal")
    set_text(guest_group, "scope", "user")
    set_text(guest_group, "description", "Captive portal guest Wi-Fi users (no GUI access)")
    # no priv element = no admin pages
    priv = guest_group.find("priv")
    if priv is not None:
        guest_group.remove(priv)
    member = guest_group.find("member")
    if member is None:
        ET.SubElement(guest_group, "member").text = "2000"
    else:
        member.text = "2000"
    set_text(guest_group, "source_networks", "")

    # --- peakguest user (password set in GUI after restore) ---
    guest_user = None
    for u in system.findall("user"):
        if u.findtext("name") == "peakguest":
            guest_user = u
            break
    if guest_user is None:
        guest_user = ET.Element("user", {"uuid": str(uuid.uuid4())})
        root_user_idx = None
        for i, child in enumerate(list(system)):
            if child.tag == "user" and child.findtext("name") == "root":
                root_user_idx = i
                break
        if root_user_idx is not None:
            system.insert(root_user_idx + 1, guest_user)
        else:
            system.append(guest_user)

    set_text(guest_user, "uid", "2000")
    set_text(guest_user, "name", "peakguest")
    set_text(guest_user, "disabled", "0")
    set_text(guest_user, "scope", "user")
    set_text(guest_user, "expires", "")
    set_text(guest_user, "authorizedkeys", "")
    set_text(guest_user, "otp_seed", "")
    set_text(guest_user, "shell", "nologin")
    # Leave / clear password — must be set in System → Access → Users after apply
    pwd = guest_user.find("password")
    if pwd is None:
        ET.SubElement(guest_user, "password").text = ""
    else:
        # Keep existing hash if already set; otherwise empty until GUI set
        if not (pwd.text or "").strip():
            pwd.text = ""
    set_text(guest_user, "landing_page", "")
    set_text(guest_user, "comment", "Shared guest captive-portal account — rotate password every 90 days")
    set_text(guest_user, "email", "")
    set_text(guest_user, "apikeys", "")
    set_text(guest_user, "priv", "")
    set_text(guest_user, "language", "en_US")
    set_text(guest_user, "descr", "Peak Energy Guest Wi-Fi")
    set_text(guest_user, "dashboard", "")
    # group membership
    groups = guest_user.find("group_memberships")
    if groups is None:
        # OPNsense 25 may use <groups> or membership via group.member only
        pass

    # Ensure guest group member list includes uid 2000
    set_text(guest_group, "member", "2000")

    # --- captive portal zone: Local Database ---
    opn = root.find("OPNsense")
    assert opn is not None
    cp = opn.find("captiveportal")
    assert cp is not None
    zones = cp.find("zones")
    assert zones is not None
    for zone in zones.findall("zone"):
        if "Guest" in (zone.findtext("description") or "") or zone.findtext("interfaces") == "opt4":
            set_text(zone, "authservers", "Local Database")
            set_text(zone, "authEnforceGroup", "guestportal")
            set_text(zone, "concurrentlogins", "1")
            set_text(zone, "idletimeout", "60")
            set_text(zone, "hardtimeout", "480")

    rev = root.find("revision")
    if rev is not None:
        set_text(rev, "description", "Guest portal Local Database auth + password policy; peakguest user")
        set_text(rev, "username", "migration@guest-auth")

    tree.write(CONFIG, encoding="utf-8", xml_declaration=True)
    print(f"Updated {CONFIG}")
    print("Auth: Local Database | Policy: min 12 + complexity | User: peakguest (set password in GUI)")
    print("Omada: keep a separate WPA2 PSK on PETCPL-GUEST (do not reuse portal password)")


if __name__ == "__main__":
    main()
