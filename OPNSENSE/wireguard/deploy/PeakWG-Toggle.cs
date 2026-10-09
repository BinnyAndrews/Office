// Peak Energy VPN — single EXE for all users; auto-detects peer from
// installed WireGuard tunnel and/or Windows username.
// Build: build-PeakWG-Toggle.cmd  →  PeakEnergyVPN.exe
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.ServiceProcess;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace PeakWG
{
    static class Program
    {
        public const string AppName = "Peak Energy VPN";
        public const string TaskOn = "PEAK-WG-On";
        public const string TaskOff = "PEAK-WG-Off";

        // peer slug → Windows / AzureAD login aliases (normalized: lowercase, no separators)
        // Corporate UPNs: Venugopal.reddy@, Poovarasu.Manickam@, jagadeshwar@, SJ@, binny.andrews@
        public static readonly Dictionary<string, string[]> PeerAliases = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            { "binny.andrews", new[] {
                "binny.andrews", "binnyandrews", "binny", "bandrews",
                "binny.andrews@peakenergy.asia"
            } },
            { "admin", new[] { "admin", "administrator", "peakadmin", "lusrpeakadmin" } },
            { "jagadeshwar", new[] {
                "jagadeshwar", "jagadeeshwar", "jagadesh",
                "jagadeshwar@peakenergy.asia"
            } },
            { "venu.gopal.reddy", new[] {
                "venugopal.reddy", "venugopalreddy", "venugopal", "venu", "gopal",
                "venugopal.reddy@peakenergy.asia"
            } },
            { "poovarasu", new[] {
                "poovarasu.manickam", "poovarasumanickam", "poovarasu", "poova", "manickam",
                "poovarasu.manickam@peakenergy.asia"
            } },
            { "sanoj.james", new[] {
                "sj", "sanoj.james", "sanojjames", "sanoj", "sjames",
                "sj@peakenergy.asia", "sanoj.james@peakenergy.asia"
            } },
        };

        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }

        public static string ServiceName(string tunnel)
        {
            return "WireGuardTunnel$" + tunnel;
        }

        public static string Normalize(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return Regex.Replace(s.ToLowerInvariant(), @"[^a-z0-9]", "");
        }

        public static List<string> ConfSearchDirs()
        {
            var dirs = new List<string>();
            dirs.Add(AppDomain.CurrentDomain.BaseDirectory);
            dirs.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "PeakEnergyVPN"));
            dirs.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PeakEnergyVPN"));
            try
            {
                dirs.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Peak Energy VPN"));
            }
            catch { }
            return dirs;
        }

        public static string FindConf(string tunnel)
        {
            if (string.IsNullOrEmpty(tunnel)) return null;
            string name = tunnel + ".conf";
            foreach (string dir in ConfSearchDirs())
            {
                try
                {
                    string p = Path.Combine(dir, name);
                    if (File.Exists(p)) return p;
                }
                catch { }
            }
            return null;
        }

        public static List<string> InstalledTunnels()
        {
            var list = new List<string>();
            try
            {
                foreach (ServiceController sc in ServiceController.GetServices())
                {
                    if (sc.ServiceName != null &&
                        sc.ServiceName.StartsWith("WireGuardTunnel$", StringComparison.OrdinalIgnoreCase))
                    {
                        list.Add(sc.ServiceName.Substring("WireGuardTunnel$".Length));
                    }
                }
            }
            catch { }
            return list;
        }

        static void AddLoginToken(List<string> tokens, string s)
        {
            if (string.IsNullOrEmpty(s)) return;
            string n = Normalize(s);
            if (n.Length > 0 && !tokens.Contains(n)) tokens.Add(n);
            int slash = s.LastIndexOf('\\');
            if (slash >= 0 && slash < s.Length - 1)
                AddLoginToken(tokens, s.Substring(slash + 1));
            int at = s.IndexOf('@');
            if (at > 0)
                AddLoginToken(tokens, s.Substring(0, at));
        }

        public static List<string> CurrentLoginTokens()
        {
            var tokens = new List<string>();
            AddLoginToken(tokens, Environment.UserName);
            try
            {
                AddLoginToken(tokens, System.Security.Principal.WindowsIdentity.GetCurrent().Name);
            }
            catch { }
            return tokens;
        }

        public static string MatchPeerFromWindowsUser()
        {
            List<string> tokens = CurrentLoginTokens();

            foreach (KeyValuePair<string, string[]> kv in PeerAliases)
            {
                foreach (string alias in kv.Value)
                {
                    string a = Normalize(alias);
                    if (a.Length == 0) continue;
                    foreach (string t in tokens)
                    {
                        if (t == a) return kv.Key;
                        // allow Venugopal.reddy ↔ venugopalreddy style
                        if (t.Length >= 4 && a.Length >= 4 && (t.Contains(a) || a.Contains(t)))
                            return kv.Key;
                    }
                }
                string peerNorm = Normalize(kv.Key);
                foreach (string t in tokens)
                    if (t == peerNorm) return kv.Key;
            }
            return null;
        }

        public static bool TryResolveTunnel(out string tunnel, out string confPath, out string how)
        {
            tunnel = null;
            confPath = null;
            how = "";
            string baseDir = AppDomain.CurrentDomain.BaseDirectory;

            // 1) Explicit override
            string tip = Path.Combine(baseDir, "tunnel.txt");
            if (File.Exists(tip))
            {
                string name = File.ReadAllText(tip).Trim();
                if (!string.IsNullOrEmpty(name))
                {
                    tunnel = name;
                    confPath = FindConf(name);
                    how = "tunnel.txt";
                    return true;
                }
            }

            List<string> installed = InstalledTunnels();
            string userPeer = MatchPeerFromWindowsUser();

            // 2) One installed tunnel → use it
            if (installed.Count == 1)
            {
                tunnel = installed[0];
                confPath = FindConf(tunnel);
                how = "installed service";
                return true;
            }

            // 3) Multiple installed → prefer Windows-user match
            if (installed.Count > 1 && userPeer != null)
            {
                foreach (string t in installed)
                {
                    if (string.Equals(t, userPeer, StringComparison.OrdinalIgnoreCase))
                    {
                        tunnel = t;
                        confPath = FindConf(t);
                        how = "Windows user + service";
                        return true;
                    }
                }
            }

            // 4) Windows username → peer (conf or installable)
            if (userPeer != null)
            {
                tunnel = userPeer;
                confPath = FindConf(userPeer);
                how = "Windows user " + Environment.UserName;
                return true;
            }

            // 5) Any installed tunnel (first)
            if (installed.Count > 0)
            {
                tunnel = installed[0];
                confPath = FindConf(tunnel);
                how = "first WireGuard service";
                return true;
            }

            // 6) Any .conf in search dirs (prefer user match already handled)
            foreach (string dir in ConfSearchDirs())
            {
                try
                {
                    if (!Directory.Exists(dir)) continue;
                    string[] confs = Directory.GetFiles(dir, "*.conf");
                    if (confs.Length == 1)
                    {
                        tunnel = Path.GetFileNameWithoutExtension(confs[0]);
                        confPath = confs[0];
                        how = "config file";
                        return true;
                    }
                }
                catch { }
            }

            return false;
        }
    }

    class MainForm : Form
    {
        readonly Label _status;
        readonly Label _hint;
        readonly Button _btnOn;
        readonly Button _btnOff;
        readonly Timer _timer;
        readonly PictureBox _logo;

        string _tunnel;
        string _confPath;
        string _serviceName;
        string _how;

        public MainForm()
        {
            Text = Program.AppName;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = true;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(400, 310);
            Font = new Font("Segoe UI", 10f);
            BackColor = Color.White;

            try
            {
                string ico = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "PeakEnergyLogo.ico");
                if (File.Exists(ico))
                    Icon = new Icon(ico);
            }
            catch { }

            ResolveTunnel();

            _logo = new PictureBox
            {
                SizeMode = PictureBoxSizeMode.Zoom,
                Location = new Point(125, 12),
                Size = new Size(150, 56),
                BackColor = Color.Transparent
            };
            TryLoadLogo(_logo);
            Controls.Add(_logo);

            _status = new Label
            {
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Font = new Font("Segoe UI", 15f, FontStyle.Bold),
                Location = new Point(20, 78),
                Size = new Size(360, 36)
            };
            Controls.Add(_status);

            _hint = new Label
            {
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                ForeColor = Color.DimGray,
                Location = new Point(16, 118),
                Size = new Size(368, 48),
                Text = HintText()
            };
            Controls.Add(_hint);

            _btnOn = new Button
            {
                Text = "Turn ON",
                Location = new Point(50, 185),
                Size = new Size(140, 48),
                BackColor = Color.FromArgb(46, 125, 50),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnOn.FlatAppearance.BorderSize = 0;
            _btnOn.Click += (s, e) => SetTunnel(true);
            Controls.Add(_btnOn);

            _btnOff = new Button
            {
                Text = "Turn OFF",
                Location = new Point(210, 185),
                Size = new Size(140, 48),
                BackColor = Color.FromArgb(198, 40, 40),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat
            };
            _btnOff.FlatAppearance.BorderSize = 0;
            _btnOff.Click += (s, e) => SetTunnel(false);
            Controls.Add(_btnOff);

            _timer = new Timer { Interval = 1500 };
            _timer.Tick += (s, e) => RefreshStatus();
            _timer.Start();
            RefreshStatus();
        }

        void ResolveTunnel()
        {
            string t, c, how;
            if (Program.TryResolveTunnel(out t, out c, out how))
            {
                _tunnel = t;
                _confPath = c;
                _how = how;
                _serviceName = Program.ServiceName(t);
            }
            else
            {
                _tunnel = null;
                _confPath = null;
                _how = "";
                _serviceName = null;
            }
        }

        string HintText()
        {
            if (!string.IsNullOrEmpty(_tunnel))
            {
                string user = Environment.UserName;
                return "User: " + user + "  →  " + _tunnel +
                       "\nOFF on PETCPL / corp Wi‑Fi · ON when remote";
            }
            return "Could not detect VPN user for Windows login:\n" + Environment.UserName +
                   "\nAsk IT to install WireGuard peer for this PC.";
        }

        static void TryLoadLogo(PictureBox box)
        {
            foreach (string dir in Program.ConfSearchDirs())
            {
                foreach (string name in new[] { "PeakEnergyLogo.png", "PeakEnergyLogo.ico" })
                {
                    string path = Path.Combine(dir, name);
                    try
                    {
                        if (!File.Exists(path)) continue;
                        if (path.EndsWith(".ico", StringComparison.OrdinalIgnoreCase))
                        {
                            using (Icon ico = new Icon(path, 256, 256))
                                box.Image = ico.ToBitmap();
                        }
                        else
                        {
                            using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                                box.Image = Image.FromStream(fs);
                        }
                        return;
                    }
                    catch { }
                }
            }
        }

        bool ServiceExists()
        {
            if (string.IsNullOrEmpty(_serviceName)) return false;
            try
            {
                using (var sc = new ServiceController(_serviceName))
                {
                    var st = sc.Status;
                    return true;
                }
            }
            catch { return false; }
        }

        bool TryGetRunning(out bool running)
        {
            running = false;
            if (string.IsNullOrEmpty(_serviceName)) return false;
            try
            {
                using (var sc = new ServiceController(_serviceName))
                {
                    running = sc.Status == ServiceControllerStatus.Running;
                    return true;
                }
            }
            catch { return false; }
        }

        void RefreshStatus()
        {
            if (string.IsNullOrEmpty(_tunnel) || !ServiceExists())
            {
                ResolveTunnel();
                _hint.Text = HintText();
            }

            bool on;
            if (TryGetRunning(out on))
            {
                _status.Text = on ? "VPN: ON" : "VPN: OFF";
                _status.ForeColor = on ? Color.FromArgb(46, 125, 50) : Color.FromArgb(198, 40, 40);
                _btnOn.Enabled = !on;
                _btnOff.Enabled = on;
            }
            else if (!string.IsNullOrEmpty(_tunnel) && !string.IsNullOrEmpty(_confPath) && File.Exists(_confPath))
            {
                _status.Text = "VPN: READY TO INSTALL";
                _status.ForeColor = Color.DarkOrange;
                _btnOn.Enabled = true;
                _btnOff.Enabled = false;
            }
            else if (!string.IsNullOrEmpty(_tunnel))
            {
                _status.Text = "VPN: NOT INSTALLED";
                _status.ForeColor = Color.DarkOrange;
                _btnOn.Enabled = false;
                _btnOff.Enabled = false;
            }
            else
            {
                _status.Text = "VPN: USER UNKNOWN";
                _status.ForeColor = Color.DarkOrange;
                _btnOn.Enabled = false;
                _btnOff.Enabled = false;
            }
        }

        void SetTunnel(bool turnOn)
        {
            UseWaitCursor = true;
            _btnOn.Enabled = false;
            _btnOff.Enabled = false;
            try
            {
                ResolveTunnel();
                if (string.IsNullOrEmpty(_tunnel))
                {
                    throw new Exception(
                        "Could not auto-detect VPN user.\n\n" +
                        "Windows login: " + Environment.UserName + "\n\n" +
                        "IT: install this user's WireGuard .conf as a tunnel service,\n" +
                        "or place peer .conf under:\n" +
                        @"  C:\ProgramData\PeakEnergyVPN\" + "\n" +
                        "Known peers: binny.andrews, jagadeshwar, venu.gopal.reddy,\n" +
                        "poovarasu, sanoj.james, admin");
                }

                _serviceName = Program.ServiceName(_tunnel);

                if (turnOn && !ServiceExists())
                {
                    if (string.IsNullOrEmpty(_confPath) || !File.Exists(_confPath))
                    {
                        throw new Exception(
                            "Detected user tunnel: " + _tunnel + "\n" +
                            "but WireGuard service is not installed and .conf was not found.\n\n" +
                            "Place " + _tunnel + ".conf in:\n" +
                            @"  C:\ProgramData\PeakEnergyVPN\" + "\n" +
                            "then click Turn ON again (UAC once to install).");
                    }
                    InstallTunnelService(_confPath);
                }

                if (!TryServiceControl(turnOn))
                {
                    if (!TryScheduledTask(turnOn))
                    {
                        throw new Exception(
                            "Access denied starting/stopping VPN.\n\n" +
                            "Ask IT (Admin once on this PC):\n" +
                            "  Install-PeakEnergyVPN.ps1\n" +
                            "which enables no-password toggle for all users.");
                    }
                }

                for (int i = 0; i < 15; i++)
                {
                    System.Threading.Thread.Sleep(400);
                    bool on;
                    if (TryGetRunning(out on) && on == turnOn)
                        break;
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, ex.Message, Program.AppName, MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally
            {
                UseWaitCursor = false;
                RefreshStatus();
            }
        }

        void InstallTunnelService(string conf)
        {
            string wg = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                "WireGuard", "wireguard.exe");
            if (!File.Exists(wg))
                throw new Exception("WireGuard is not installed.\nInstall from https://www.wireguard.com/install/");

            var p = Process.Start(new ProcessStartInfo
            {
                FileName = wg,
                Arguments = "/installtunnelservice \"" + conf + "\"",
                UseShellExecute = true,
                Verb = "runas"
            });
            if (p == null)
                throw new Exception("Could not start wireguard.exe (UAC cancelled?)");
            p.WaitForExit(60000);
            if (p.ExitCode != 0)
                throw new Exception("Failed to install tunnel (exit " + p.ExitCode + ").");
            System.Threading.Thread.Sleep(1000);
            ResolveTunnel();
        }

        bool TryServiceControl(bool turnOn)
        {
            try
            {
                using (var sc = new ServiceController(_serviceName))
                {
                    if (turnOn)
                    {
                        if (sc.Status == ServiceControllerStatus.Running) return true;
                        sc.Start();
                        sc.WaitForStatus(ServiceControllerStatus.Running, TimeSpan.FromSeconds(20));
                    }
                    else
                    {
                        if (sc.Status == ServiceControllerStatus.Stopped) return true;
                        sc.Stop();
                        sc.WaitForStatus(ServiceControllerStatus.Stopped, TimeSpan.FromSeconds(20));
                    }
                    return true;
                }
            }
            catch { return false; }
        }

        bool TryScheduledTask(bool turnOn)
        {
            string task = turnOn ? Program.TaskOn : Program.TaskOff;
            try
            {
                var p = Process.Start(new ProcessStartInfo
                {
                    FileName = "schtasks.exe",
                    Arguments = "/Run /TN \"" + task + "\"",
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                });
                if (p == null) return false;
                p.WaitForExit(15000);
                return p.ExitCode == 0;
            }
            catch { return false; }
        }
    }
}
