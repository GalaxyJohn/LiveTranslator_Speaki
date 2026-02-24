# LiveTranslator_Speaki
LiveTranslator_Speaki is a real-time voice translation app that listens to microphone input and shows translated text.

## End-User Requirements
- Windows 10/11 (64-bit)
- Keep `speaki.exe` and the `_internal` folder in the same directory
- Microphone access permission enabled in Windows
- Internet connection (translation providers are API-based)

## GPU / CPU Notes
- CUDA mode:
  - Requires an NVIDIA GPU driver
  - CUDA Toolkit and separate cuDNN install are usually **not** required for this build
- CPU mode:
  - No GPU dependency required
  - Use this mode if CUDA causes compatibility issues

## Translation API Keys
To use cloud translators, configure the corresponding API credentials in app settings:
- OpenAI / Gemini
- DeepL / DeepL Free
- Papago

## FFmpeg / External Tools
You do **not** need to install FFmpeg separately for normal use in this packaged build.

## Quick Start
1. Extract the release zip.
2. Run `speaki.exe` (do not move it out of its folder).
<<<<<<< Updated upstream
3. If CUDA fails, switch STT backend to `CPU` in Settings and restart.
=======
3. If CUDA fails, switch STT backend to `CPU` in Settings and restart.
>>>>>>> Stashed changes
