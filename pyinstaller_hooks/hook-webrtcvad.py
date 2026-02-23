from PyInstaller.utils.hooks import collect_dynamic_libs

# webrtcvad-wheels provides module "webrtcvad" without "webrtcvad" distribution metadata.
# The default contrib hook calls copy_metadata("webrtcvad"), which fails in this environment.
binaries = collect_dynamic_libs("webrtcvad")
datas = []
