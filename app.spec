# PyInstaller spec for VST Sampling Factory.
# Build:  pyinstaller app.spec
# Output: dist/VSTSamplingFactory/VSTSamplingFactory.exe

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('settings.json', '.'),
        ('reaper/scripts/render_job.lua', 'reaper/scripts'),
        ('reaper/scripts/list_presets.lua', 'reaper/scripts'),
    ],
    hiddenimports=[
        'soundfile',
        'scipy.signal',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['matplotlib.tests', 'scipy.spatial.cKDTree'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VSTSamplingFactory',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='VSTSamplingFactory',
)
