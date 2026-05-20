"""PyInstaller hook for DrissionPage — collect all submodules, data files, and hidden imports."""
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = collect_all('DrissionPage')

# sub-dependencies
for pkg in ['DataRecorder', 'DownloadKit', 'cssselect']:
    try:
        s_datas, s_binaries, s_hidden = collect_all(pkg)
        datas.extend(s_datas)
        binaries.extend(s_binaries)
        hiddenimports.extend(s_hidden)
    except Exception:
        pass

# include certifi's cacert.pem (SSL cert bundle)
try:
    cert_datas, cert_binaries, cert_hidden = collect_all('certifi')
    datas.extend(cert_datas)
    binaries.extend(cert_binaries)
    hiddenimports.extend(cert_hidden)
except Exception:
    pass
