%global srcname crypto_dashboard

Name:           crypto-dashboard
Version:        1.0
Release:        1%{?dist}
Summary:        Real-time cryptocurrency dashboard with candlestick charts

License:        GPL-3.0-or-later
URL:            https://github.com/michwill/crypto-dashboard
# hatchling sdist from `uv build --sdist` (the crypto_dashboard-VERSION tarball)
Source0:        %{srcname}-%{version}.tar.gz

# Pure Python and arch-independent: the compiled bits (PyQt6, numpy) come from
# the distro's own python3-* packages, declared as Requires below.
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  desktop-file-utils

# Every runtime dependency ships in Fedora, so there is nothing to vendor (the
# whole reason qeth's spec is complicated). PyQt6 is deliberately NOT a
# pyproject dependency — it's expected from the system so the app matches the
# desktop Qt theme — so it is named here explicitly. The chart uses an OpenGL
# viewport (pyqtgraph useOpenGL=True), which reaches QtOpenGLWidgets, so the
# full python3-pyqt6 (not python3-pyqt6-base) is required.
Requires:       python3-pyqt6
Requires:       python3-pyqtgraph
Requires:       python3-numpy
Requires:       python3-requests
Requires:       python3-websocket-client
Requires:       python3-platformdirs

%description
Crypto Dashboard is a Qt (PyQt6) desktop app showing real-time cryptocurrency
prices with candlestick and volume charts, streaming live trades from Binance
over a websocket. It uses the system PyQt6 so the app matches your desktop's
Qt theme.

%prep
%autosetup -n %{srcname}-%{version}

%generate_buildrequires
# PyQt6 is a runtime-only system dependency (not in [project.dependencies]), so
# it is not pulled in here.
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
# Capture the module, its .dist-info, and the /usr/bin/crypto-dashboard entry
# point generated from [project.gui-scripts].
%pyproject_save_files %{srcname}

# Desktop entry + themed icon into system paths (NOT into site-packages).
desktop-file-install --dir=%{buildroot}%{_datadir}/applications \
    data/crypto-dashboard.desktop
install -Dm0644 data/icons/hicolor/scalable/apps/crypto-dashboard.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/crypto-dashboard.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/crypto-dashboard.desktop

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
# The gui-scripts entry point is not auto-captured, so list it explicitly.
%{_bindir}/crypto-dashboard
%{_datadir}/applications/crypto-dashboard.desktop
%{_datadir}/icons/hicolor/scalable/apps/crypto-dashboard.svg

%changelog
* Thu Jul 23 2026 Michael Egorov <michwill@yieldbasis.com> - 1.0-1
- Initial Fedora package.
