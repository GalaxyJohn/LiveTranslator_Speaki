# SpeaKI Deployment Checklist

## 1) Environment prep
1. Install Python 3.11 or 3.12 (64-bit recommended).
2. Install C++ runtime (Visual C++ Redistributable) on Windows.
3. Ensure microphone permission is enabled in OS privacy settings.

## 2) Dependency install
1. `python -m pip install -r requirements.txt`
2. `python -m pip install -r requirements-build.txt` (for EXE build only)
3. Or use `install.bat` to set up `.venv` automatically.

## 3) Configuration
1. Copy `settings.sample.json` to `settings.json`.
2. Fill keys you need:
   - `llm.api_key` for OpenAI/Gemini
   - `deepl.api_key` or `deepl_free.api_key`
   - `papago.client_id` and `papago.client_secret`
3. Choose STT backend in app settings:
   - `cuda` for GPU speed
   - `cpu` for compatibility

## 4) Preflight
1. Run `powershell -ExecutionPolicy Bypass -File scripts/preflight.ps1`
2. Confirm all checks pass before build/release.

## 5) Runtime smoke test
1. Launch app and click `Start`.
2. Confirm status flow: `idle -> preparing -> running`.
3. Speak multiple short sentences quickly and verify UI remains responsive.
4. Click `Clear` and verify:
   - text areas reset
   - new translations start from new segment
5. Click `Stop` and restart once to verify clean shutdown/startup cycle.

## 6) Build EXE
1. Run `powershell -ExecutionPolicy Bypass -File scripts/build_exe.ps1 -Clean`
2. Or run `build_exe.bat`
3. Deliver `dist/speaki/` folder (one-folder build).

## 7) Release package contents
1. `dist/speaki/` output
2. `settings.sample.json`
3. Short user guide with API key setup and backend choice
4. Known limitations list (provider quotas/network dependency)
