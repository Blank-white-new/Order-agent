from __future__ import annotations

import argparse
from pathlib import Path

import pythoncom
import win32com.client


WD_EXPORT_FORMAT_PDF = 17
MSO_AUTOMATION_SECURITY_FORCE_DISABLE = 3


def export(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    word.AutomationSecurity = MSO_AUTOMATION_SECURITY_FORCE_DISABLE
    document = None
    try:
        document = word.Documents.Open(
            str(source.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            Revert=False,
            Visible=False,
            OpenAndRepair=False,
            NoEncodingDialog=True,
        )
        document.ExportAsFixedFormat(str(destination.resolve()), WD_EXPORT_FORMAT_PDF)
    finally:
        if document is not None:
            document.Close(False)
        word.Quit()
        pythoncom.CoUninitialize()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    export(args.source, args.destination)
    print(f"exported {args.source} -> {args.destination}")


if __name__ == "__main__":
    main()
