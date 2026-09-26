#!/usr/bin/env python3
"""
Build Peak Energy guest captive-portal template and inject zone into
config-PEAK-CORP-FW.xml (WL_GUEST / opt4).
"""
from __future__ import annotations

import base64
import io
import shutil
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "PeakEnergyLogo.png"
DEFAULT = ROOT / "captiveportal" / "htdocs_default"
BUILD = ROOT / "captiveportal" / "peak-guest-template"
ZIP_OUT = ROOT / "captiveportal" / "PeakEnergy-Guest-Portal.zip"
CONFIG = ROOT / "config-PEAK-CORP-FW.xml"

INDEX_HTML = r"""<!doctype html>
<html>
	<head>
	<meta charset="UTF-8">
	<title>Peak Energy Guest Wi-Fi</title>

		<link rel="shortcut icon" href="favicon/favicon.ico" type="image/x-icon">
		<link rel="icon" href="favicon/favicon.ico" type="image/x-icon">
		<link href="css/signin.css" rel="stylesheet">
		<meta name="theme-color" content="#000000">
		<meta http-equiv="X-UA-Compatible" content="IE=edge,chrome=1">
		<meta name="viewport" content="width=device-width, initial-scale=1.0">
		<meta name="description" content="Peak Energy Guest Wi-Fi">
		<script src="js/jquery-3.5.1.min.js"></script>
		<script>
				$( document ).ready(function() {
					let redirurl = (new URL(window.location)).searchParams.get('redirurl');
					$("#signin").click(function (event) {
						event.preventDefault();
						$("#alertMSG").addClass("hidden");
						$.ajax({
							type: "POST",
							url: "/api/captiveportal/access/logon/",
							dataType:"json",
							data:{ user: $("#inputUsername").val(), password: $("#inputPassword").val() }
						}).done(function(data) {
							if (data['clientState'] == 'AUTHORIZED') {
								if (redirurl !== null) {
									window.location = 'http://'+redirurl+'?refresh';
								} else {
									window.location.reload();
								}
							} else {
								$("#inputUsername").val("");
								$("#inputPassword").val("");
								$("#errorMSGtext").html("authentication failed");
								$("#alertMSG").removeClass("hidden");
							}
						}).fail(function(){
							$("#errorMSGtext").html("unable to connect to authentication server");
							$("#alertMSG").removeClass("hidden");
						});
					});

					$("#signin_anon").click(function (event) {
						event.preventDefault();
						$("#alertMSG").addClass("hidden");
						$.ajax({
							type: "POST",
							url: "/api/captiveportal/access/logon/",
							dataType:"json",
							data:{ user: '', password: '' }
						}).done(function(data) {
							if (data['clientState'] == 'AUTHORIZED') {
								if (redirurl !== null) {
									window.location = 'http://'+redirurl+'?refresh';
								} else {
									window.location.reload();
								}
							} else {
								$("#errorMSGtext").html("login failed");
								$("#alertMSG").removeClass("hidden");
							}
						}).fail(function(){
							$("#errorMSGtext").html("unable to connect to authentication server");
							$("#alertMSG").removeClass("hidden");
						});
					});

					$("#logoff").click(function (event) {
						event.preventDefault();
						$("#alertMSG").addClass("hidden");
						$.ajax({
							type: "POST",
							url: "/api/captiveportal/access/logoff/",
							dataType:"json",
							data:{ user: '', password: '' }
						}).done(function(data) {
							window.location.reload();
						}).fail(function(){
							$("#errorMSGtext").html("unable to connect to authentication server");
							$("#alertMSG").removeClass("hidden");
						});
					});

					$("#btnCloseError").click(function(){
						$("#alertMSG").addClass("hidden");
					});

					$.ajax({
						type: "POST",
						url: "/api/captiveportal/access/status/",
						dataType:"json",
						data:{ user: $("#inputUsername").val(), password: $("#inputPassword").val() }
					}).done(function(data) {
						if (data['clientState'] == 'AUTHORIZED') {
						$("#logout_frm").removeClass('hidden');
						} else if (data['authType'] == 'none') {
							$("#login_none").removeClass('hidden');
						} else {
							$("#login_password").removeClass('hidden');
						}
					}).fail(function(){
						$("#errorMSGtext").html("unable to connect to authentication server");
						$("#alertMSG").removeClass("hidden");
					});
				});
		</script>

	</head>
	<body>
		<header>
			<h1><a href="/"><img src="images/PeakEnergyLogo.png" class="maintenance-logo" alt="Peak Energy"></a></h1>
		</header>
		<main>
			<section class="content-row">
				<article class="wrapper">
					<div class="welcome">
						<p class="tagline">Guest Wi-Fi</p>
						<p class="policy">Internet access for visitors. Ask reception for the guest username and password. Corporate systems are not reachable from this network.</p>
					</div>
					<div id="login_password" class="hidden">
						<form class="form-signin">
							<h2 class="form-signin-heading">Sign in to continue</h2>
							<input type="text" id="inputUsername" class="form-control" placeholder="Username" required autofocus autocomplete="username" autocapitalize="none" autocorrect="off">
							<input type="password" autocomplete="current-password" id="inputPassword" class="form-control" placeholder="Password" required>
							<button class="btn" id="signin" type="button">Connect</button>
						</form>
					</div>
					<div id="login_none" class="hidden">
						<form class="form-signin">
							<button class="btn" id="signin_anon" type="button">Connect to Guest Wi-Fi</button>
						</form>
					</div>
					<div id="logout_frm" class="hidden">
						<form class="form-signin">
							<p class="connected">You are connected.</p>
							<button class="btn btn-secondary" id="logoff" type="button">Disconnect</button>
						</form>
					</div>
					<div class="alert alert-danger alert-dismissible hidden" role="alert" id="alertMSG">
						<br/>
						<button type="button" class="btn close" id="btnCloseError" aria-label="Close">
							<span aria-hidden="true">&times;</span>
						</button>
						<span id="errorMSGtext"></span>
					</div>
				</article>
			</section>
		</main>
		<footer>
			<p class="footer-text">Peak Energy</p>
		</footer>
	</body>
</html>
"""

SIGNIN_CSS = r"""html,
body {
  padding: 0;
  margin: 0;
}

body {
  background: #000000;
  color: #e8f4fc;
  font-family: "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 18px;
  font-weight: 300;
  text-align: center;
}

header {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 160px;
  padding: 28px 16px 8px;
}

header h1,
header a {
  display: inline-block;
  line-height: 1;
  margin: 0;
}

header img {
  display: block;
  width: min(320px, 80vw);
  height: auto;
}

footer {
  padding: 24px 16px 32px;
}

.footer-text {
  margin: 0;
  color: #55c5f1;
  font-size: 14px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.content-row {
  min-height: calc(100vh - 280px);
  display: flex;
  align-items: center;
  padding: 24px 0 48px;
}

.wrapper {
  width: 100%;
  max-width: 480px;
  margin: 0 auto;
  padding: 0 20px;
}

.welcome {
  margin-bottom: 28px;
}

.tagline {
  margin: 0 0 10px;
  color: #55c5f1;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.policy {
  margin: 0;
  color: #9bb8cc;
  font-size: 15px;
  line-height: 1.45;
}

.connected {
  color: #55c5f1;
  margin: 0 0 16px;
}

.form-signin {
  margin: 0 auto;
}

.form-signin-heading {
  color: #e8f4fc;
  font-size: 20px;
  margin: 0 0 18px;
}

.form-control {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin: 0 0 12px;
  padding: 12px 14px;
  border: 1px solid #1a4f73;
  border-radius: 6px;
  background: #0a1620;
  color: #e8f4fc;
  font-size: 16px;
}

.btn {
  display: inline-block;
  width: 100%;
  margin-top: 8px;
  padding: 14px 18px;
  border: 0;
  border-radius: 6px;
  background: linear-gradient(180deg, #55c5f1 0%, #3aa9e4 100%);
  color: #00355f;
  font-size: 17px;
  font-weight: 600;
  cursor: pointer;
}

.btn:hover {
  filter: brightness(1.05);
}

.btn-secondary {
  background: transparent;
  border: 1px solid #3aa9e4;
  color: #55c5f1;
}

.alert {
  margin-top: 18px;
  padding: 12px 14px;
  border-radius: 6px;
  background: #3a1010;
  border: 1px solid #a94442;
  color: #f2dede;
  position: relative;
}

.hidden {
  display: none !important;
}

.close {
  position: absolute;
  right: 8px;
  top: 4px;
  width: auto;
  padding: 4px 8px;
  background: transparent;
  color: #f2dede;
  border: 0;
}
"""


def zip_template(src: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(src).as_posix())
    return buf.getvalue()


def set_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = text
    return el


def main() -> None:
    if not LOGO.exists():
        raise SystemExit(f"Missing logo: {LOGO}")
    if not DEFAULT.exists():
        raise SystemExit(f"Missing default template: {DEFAULT}")
    if not CONFIG.exists():
        raise SystemExit(f"Missing config: {CONFIG}")

    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(DEFAULT, BUILD)

    # Brand assets
    shutil.copy2(LOGO, BUILD / "images" / "PeakEnergyLogo.png")
    (BUILD / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (BUILD / "css" / "signin.css").write_text(SIGNIN_CSS, encoding="utf-8")

    zip_bytes = zip_template(BUILD)
    ZIP_OUT.write_bytes(zip_bytes)
    content_b64 = base64.b64encode(zip_bytes).decode("ascii")
    print(f"Wrote {ZIP_OUT} ({len(zip_bytes)} bytes)")

    tree = ET.parse(CONFIG)
    root = tree.getroot()
    opn = root.find("OPNsense")
    assert opn is not None
    cp = opn.find("captiveportal")
    assert cp is not None

    zones = cp.find("zones")
    templates = cp.find("templates")
    if zones is None:
        zones = ET.SubElement(cp, "zones")
    else:
        for z in list(zones):
            zones.remove(z)
    if templates is None:
        templates = ET.SubElement(cp, "templates")
    else:
        for t in list(templates):
            templates.remove(t)

    template_uuid = str(uuid.uuid4())
    fileid = uuid.uuid4().hex[:12]
    zone_uuid = str(uuid.uuid4())

    tmpl = ET.SubElement(templates, "template", {"uuid": template_uuid})
    ET.SubElement(tmpl, "fileid").text = fileid
    ET.SubElement(tmpl, "name").text = "PeakEnergy-Guest"
    ET.SubElement(tmpl, "content").text = content_b64

    zone = ET.SubElement(zones, "zone", {"uuid": zone_uuid})
    fields = {
        "enabled": "1",
        "zoneid": "0",
        "interfaces": "opt4",
        "disableRules": "0",
        "authservers": "Local Database",
        "roaming": "1",
        "alwaysSendAccountingReqs": "0",
        "authEnforceGroup": "guestportal",
        "idletimeout": "60",
        "hardtimeout": "480",
        "concurrentlogins": "1",
        "certificate": "",
        "servername": "",
        "allowedAddresses": "",
        "allowedMACAddresses": "",
        "extendedPreAuthData": "0",
        "template": template_uuid,
        "description": "Peak Energy Guest Wi-Fi (VLAN 102)",
    }
    for k, v in fields.items():
        ET.SubElement(zone, k).text = v

    # revision note
    rev = root.find("revision")
    if rev is not None:
        set_text(rev, "description", "Added Peak Energy guest captive portal (opt4 / WL_GUEST)")
        set_text(rev, "username", "migration@captiveportal")

    tree.write(CONFIG, encoding="utf-8", xml_declaration=True)
    print(f"Updated {CONFIG}")
    print("Zone: Peak Energy Guest Wi-Fi on opt4 (WL_GUEST), click-through (no auth), branded template")


if __name__ == "__main__":
    main()
