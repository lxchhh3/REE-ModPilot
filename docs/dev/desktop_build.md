# Desktop Build & Code Signing

How to ship the Tauri shell as a single-click Windows installer. Moved out of README.md
(2026-08-06) — this is release-time reference, not something you need on every read.

Build invariant: **never** run `cargo build` against `src-tauri/` except for syntax checks —
always go through `pnpm tauri build`. See lesson `#26` for what goes wrong otherwise.

---

## Building the installer

The Tauri shell bundles the FastAPI backend as a pyinstaller-frozen sidecar, so end users get one
`.msi` / `.exe` with no Python install needed.

```bash
# 1. Freeze the backend (run from ModPilot/)
.venv/Scripts/pyinstaller.exe modpilot_backend.spec --clean --noconfirm

# 2. Stage the dist into the Tauri binaries dir
rm -rf frontend/src-tauri/binaries/backend
cp -r dist/modpilot-backend frontend/src-tauri/binaries/backend

# 3. Build the installer (PowerShell, with cargo on PATH)
cd frontend
pnpm tauri build           # produces target/release/bundle/{msi,nsis}/
```

Output: ~25 MB MSI and NSIS installers. On launch the bundled `modpilot.exe` spawns the sidecar on
`:8000`, displays a splash until `/health` returns, then mounts the React UI. On exit (window-close
OR hard-kill via `taskkill /F`) the sidecar dies with the parent — the Windows Job Object binding in
`src-tauri/src/lib.rs` ensures no orphans.

> `src-tauri/target/` is a ~5.7 GB build cache and is gitignored. It was deleted in the 2026-08-06
> cleanup, so the first build after that is a cold one (10-20 min).

---

## Code signing

Without a code-signing cert, Windows SmartScreen warns on first launch ("unrecognized publisher").
End users see a blue dialog and must click "More info → Run anyway".

**The pipeline is ready** — just supply a cert:

```powershell
# Set the cert thumbprint (SHA1 of cert in Cert:\CurrentUser\My)
$env:TAURI_SIGNING_CERT_THUMBPRINT = "abc123..."

# Tauri's bundle pipeline signs modpilot.exe + the installers automatically
# (digestAlgorithm + timestampUrl are already in tauri.conf.json).
pnpm tauri build

# Tauri does NOT sign the bundled sidecar exe — run our wrapper to sign
# everything (parent + sidecar + installers).
.\src-tauri\scripts\sign_bundle.ps1
```

**For local / internal-distribution testing** (signs cleanly on machines that trust your cert, still
SmartScreen-flagged elsewhere):

```powershell
# Generates a self-signed cert, installs it in your cert stores, prints thumbprint
.\src-tauri\scripts\generate_dev_cert.ps1
```

**For production** (no SmartScreen warning): purchase an **EV code-signing cert** from a CA (Sectigo,
DigiCert, GlobalSign — $200-500/yr). Standard OV certs require a 7-day reputation warmup period; EV
certs skip it. Both work with the pipeline above; EV is dispensed on a USB token, so the build
machine needs access to the token at sign time.
