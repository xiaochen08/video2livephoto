"""PyInstaller entry point for the bundled Python IPC worker."""

from desktop.ipc_server import main


if __name__ == "__main__":
    raise SystemExit(main())
